#!/usr/bin/env python3
r"""Read Last War chat (world / national / alliance / DM) out of the game's Lua VM.

Why this exists
---------------
The live chat broadcast (world / national / alliance firehose) does NOT ride the
plain-TCP game leg on :17935 -- it flows over a dedicated TLS WebSocket
(``lastwar-chat-wss-*``) and is therefore NOT passively decodable without a TLS
keylog / MITM (ruled out by project policy). See ``docs/research/chat.md``.

Passive ``tools/chat_monitor.py`` only ever sees the TCP control leg (DM
send/ack, room registry, map-object shares). It can never see world/alliance
broadcast text.

This tool takes the other route that project policy DOES allow: read the messages
*after* the client has decrypted them, from inside the game's own Lua state via
the warm xLua daemon (see ``docs/research/game-launch-and-scene-control.md`` and
the ``project_xlua_dostring_live`` memory). Every incoming ``ChatMessage`` (class
``ChatMessage`` in the client) is intercepted at the Lua ingress and copied into a
ring buffer that this script polls, hex-decodes (to survive Player.log's mangling
of non-ASCII) and emits as one JSON line per message.

Requirements / caveats
----------------------
* The warm Lua daemon must be running (``tools/lua_daemon.py``) and the game
  alive. Run under the Windows Python so it can reach the daemon:
      C:\Python312\python.exe -u tools\chat_reader.py --seconds 300
* The chat window does NOT need to be open. The hook sits on the class-level
  ``ChatMessage:onParseServerData``, which the client runs for every parsed
  message whether or not the chat UI is up, so capture is always-on.
* Capture is LIVE-forward from the moment the hook is installed: it sees new
  messages, not pre-existing backlog.
* Non-ASCII text is carried as hex and decoded here, so Cyrillic/CJK survive.

Output: one JSON record per message to stdout and, if given, appended to --out.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import lua_client  # noqa: E402

MARKER = "ACT"

# ---------------------------------------------------------------------------
# Lua side: install idempotent hooks that copy each incoming ChatMessage into
# the global ring buffer _G.__CR_BUF. Fields are hex-encoded so non-ASCII text
# reaches Python intact (LogError mangles raw UTF-8 in Player.log).
# ---------------------------------------------------------------------------
_INSTALL_LUA = r"""
local function L(s) CS.UnityEngine.Debug.LogError("ACT "..tostring(s)) end
_G.__CR_BUF = _G.__CR_BUF or {}
local function hex(s)
  if type(s) ~= "string" then return "" end
  return (s:gsub('.', function(c) return string.format('%02x', c:byte()) end))
end
local function record(a)
  local rec = {}
  local function pg(k) local ok, v = pcall(function() return a[k] end) if ok then return v end end
  local function mg(n) local ok, v = pcall(function() return a[n](a) end) if ok then return v end end
  rec.roomId = tostring(pg("roomId"))
  rec.seqId  = tostring(pg("seqId"))
  rec.st     = tostring(pg("serverTime"))
  rec.post   = tostring(pg("post"))
  rec.mtype  = tostring(pg("type"))
  rec.uid    = tostring(pg("senderUid"))
  -- getMsg() is the base text. getMessageWithExtra() renders attachment/interactive
  -- posts (coord shares, etc.) whose base text is just a "?" placeholder into a full
  -- string ("[ALLY] Name (BZ #100 X:.. Y:..)"). Emit both; Python picks the display.
  rec.msg    = hex(tostring(mg("getMsg")))
  rec.we     = hex(tostring(mg("getMessageWithExtra")))
  rec.ismy   = tostring(mg("isMySendChat"))
  rec.sender = hex(mg("getSenderName"))
  local si = mg("getSenderInfo")
  if type(si) == "table" then
    rec.alliance = hex(tostring(si.allianceSimpleName or ""))
    rec.lang     = tostring(si.lang)
    rec.gm       = tostring(si.gmFlag)
    rec.srv      = tostring(si.serverId)
    -- The sender's avatar. `headPic` is the head-frame id; `headPicVer` is the
    -- version that keys the on-disk copy the client caches under ChatPhotos
    -- (md5(f"{uid}_{headPicVer}").jpg -- same scheme as a chat photo). The panel
    -- resolves it with no game call; a built-in head with no cached file just
    -- renders nickname-only.
    rec.hp       = tostring(si.headPic)
    rec.hpv      = tostring(si.headPicVer)
  end
  local cap = _G.__CR_BUF
  cap[#cap + 1] = rec
  if #cap > 500 then table.remove(cap, 1) end
end

-- Single class-level ingress hook. ChatMessage:onParseServerData fires exactly
-- once for every parsed message regardless of room / UI routing (world / national
-- / alliance / DM). Bind the class table directly from package.loaded so it works
-- on a fresh session with no captured instance yet -- and, crucially, WITHOUT the
-- chat window open (the client parses the stream whether or not the UI is up).
--
-- We deliberately do NOT also hook the UI-routing handlers
-- (ChatViewTipBubbleDataManager:OnGetNewChatMsg / UpdateOnNewMessage): they fire
-- in addition to onParseServerData for the same message, producing duplicates, and
-- only work while the chat view is open. The single class hook is both sufficient
-- and duplicate-free. Older revisions of this tool DID hook those handlers
-- (originals stashed in _G.__CR_H); if a stale set is still wrapped in this long
-- running game session, restore it so it stops double-recording.
if type(_G.__CR_H) == "table" then
  local mgr = DataCenter.ChatViewTipBubbleDataManager
  for m, orig in pairs(_G.__CR_H) do pcall(function() mgr[m] = orig end) end
  _G.__CR_H = nil
  L("legacy UI hooks restored")
end

local CM = package.loaded["Chat.Model.ChatMessage"]
if type(CM) == "table" and type(CM.onParseServerData) == "function" then
  -- Save the pristine method exactly once, then always rebuild the wrapper from
  -- it. This keeps re-install idempotent AND lets an updated record() take effect
  -- without a game restart, with no ever-growing wrapper chain.
  _G.__CR_ORIG = _G.__CR_ORIG or CM.onParseServerData
  local orig = _G.__CR_ORIG
  CM.onParseServerData = function(self, ...)
    local r = {orig(self, ...)}
    pcall(record, self)
    return table.unpack(r)
  end
  _G.__CR_CLASS_HOOKED = true
  L("class-hook on")
else
  L("class-hook FAIL: Chat.Model.ChatMessage type="..type(CM))
end
L("chat_reader hooks installed; buf="..#_G.__CR_BUF)
"""

_DRAIN_LUA = r"""
local function L(s) CS.UnityEngine.Debug.LogError("ACT "..tostring(s)) end
local cap = _G.__CR_BUF or {}
L("N="..#cap)
local function f(v) return tostring(v == nil and "" or v) end   -- nil-safe field
for i, r in ipairs(cap) do
  -- Each line is emitted under its own pcall: a single malformed record must
  -- never abort the whole drain loop (that would silently drop every message).
  pcall(function()
    L("R roomId="..f(r.roomId).." seqId="..f(r.seqId).." st="..f(r.st).." post="..f(r.post)
      .." type="..f(r.mtype).." uid="..f(r.uid).." lang="..f(r.lang)
      .." gm="..f(r.gm).." srv="..f(r.srv).." hp="..f(r.hp).." hpv="..f(r.hpv)
      .." ismy="..f(r.ismy).." alliance="..f(r.alliance)
      .." sender="..f(r.sender).." msg="..f(r.msg).." we="..f(r.we))
  end)
end
_G.__CR_BUF = {}   -- drained; keep buffer small
"""


def _hexdec(h: str) -> str:
    try:
        return bytes.fromhex(h).decode("utf-8", "replace")
    except Exception:
        return ""


def classify_room(room_id: str) -> str:
    if not room_id or room_id == "nil":
        return "other"
    if room_id.startswith("country_"):
        return "world"
    if room_id.startswith("custom_lang_"):
        return "national"
    if room_id.startswith("alliance_"):
        return "alliance"
    if room_id.endswith("_v2"):
        return "dm"
    return "other"


# The game's "local" emoji are Private Use Area glyphs (U+E000..U+F8FF) sitting
# inline in the message text; a terminal / JSON consumer renders them as broken
# boxes ("локальные смайлы выводятся неверно"). Replace each with a readable
# [e:XXXX] token. Rich inline objects arrive as <lwSticker:N:> / <lwPhoto:N:> /
# <lwEmoji:N:> ... markers; normalise them all to a readable [kind:N].
_PUA_RE = re.compile("[\ue000-\uf8ff]")
_LW_RE = re.compile(r"<lw([A-Za-z]+):(\d+)(?::[^>]*)?>")
_PLACEHOLDER = {"", "?", "nil"}


def _render_text(s: str) -> str:
    """Make chat text human-readable: name inline objects and PUA emoji explicitly."""
    s = _LW_RE.sub(lambda m: f"[{m.group(1).lower()}:{m.group(2)}]", s)
    s = _PUA_RE.sub(lambda m: f"[e:{ord(m.group()):04X}]", s)
    return s


def _parse_record_line(line: str) -> dict | None:
    """Parse one 'ACT R k=v k=v ...' drain line into a decoded chat record."""
    body = line
    if body.startswith("ACT "):
        body = body[4:]
    if not body.startswith("R "):
        return None
    body = body[2:]
    # Fields are space-separated key=value; the trailing hex fields hold no spaces
    # (hex) and the plain fields (roomId/uid/...) hold no spaces either.
    fields: dict[str, str] = {}
    for tok in body.split(" "):
        if "=" in tok:
            k, v = tok.split("=", 1)
            fields[k] = v
    room_id = fields.get("roomId", "")
    base = _hexdec(fields.get("msg", ""))          # getMsg()
    with_extra = _hexdec(fields.get("we", ""))     # getMessageWithExtra()
    # Attachment / interactive posts (coord shares, invites, ...) leave getMsg() as
    # a bare "?" placeholder; getMessageWithExtra() renders the real content
    # ("[ALLY] Name (BZ #100 X:.. Y:..)"). Prefer it only when the base is empty.
    display = with_extra if (base.strip() in _PLACEHOLDER and with_extra) else base
    # Timestamp the record with the message's own serverTime (epoch ms), NOT the
    # parse time: when the user scrolls up, the client re-parses old history through
    # the hook "now", so a parse-time ts would sort ancient messages to the bottom.
    server_time = fields.get("st", "")
    try:
        ts = int(server_time) / 1000.0
    except (TypeError, ValueError):
        ts = time.time()
    rec = {
        "ts": ts,
        "room_id": room_id,
        "chat_type": classify_room(room_id),
        "seq_id": fields.get("seqId", ""),
        "server_time": server_time,
        "post": fields.get("post", ""),
        "type": fields.get("type", ""),
        "sender_uid": fields.get("uid", ""),
        "server_id": fields.get("srv", ""),
        # Avatar: head-frame id + the version that keys its cached JPG on disk.
        "head_pic": fields.get("hp", ""),
        "head_pic_ver": fields.get("hpv", ""),
        "lang": fields.get("lang", ""),
        "gm": fields.get("gm", ""),
        "is_mine": fields.get("ismy", "") == "true",
        "alliance": _hexdec(fields.get("alliance", "")),
        "sender_name": _hexdec(fields.get("sender", "")),
        "msg": _render_text(display),
    }
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--seconds", type=float, default=120,
                    help="how long to capture (0 = until Ctrl+C)")
    ap.add_argument("--interval", type=float, default=5,
                    help="seconds between buffer drains")
    ap.add_argument("--out", metavar="PATH", help="append JSONL here as well as stdout")
    ap.add_argument("--no-open", action="store_true",
                    help="deprecated no-op (the chat window no longer needs to be open)")
    args = ap.parse_args()

    # Chat text is UTF-8 (Cyrillic / Arabic / CJK / emoji). The Windows console
    # defaults to a legacy codepage (e.g. cp1251), so a raw print() of a foreign
    # message raises UnicodeEncodeError and kills the whole capture mid-stream --
    # the classic "nothing shows up" symptom. Force UTF-8 on both streams.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    ev = lua_client.get_evaluator()

    # Install the single class-level hook (idempotent). No need to open the chat
    # window -- onParseServerData fires regardless of UI state.
    ev.run(_INSTALL_LUA, marker=MARKER, settle=1.5)

    print(f"# chat_reader: capturing for {args.seconds or '∞'}s",
          file=sys.stderr, flush=True)

    seen: set[tuple] = set()
    out_fh = open(args.out, "a", encoding="utf-8") if args.out else None
    total = 0
    deadline = time.time() + args.seconds if args.seconds > 0 else None
    try:
        while deadline is None or time.time() < deadline:
            time.sleep(args.interval)
            lines = ev.run(_DRAIN_LUA, marker=MARKER, settle=1.2)
            for ln in (lines or []):
                rec = _parse_record_line(ln)
                if rec is None:
                    continue
                # A ChatMessage always carries a roomId; a record without one is
                # not a routable message -- skip it rather than emit an empty line.
                if not rec["room_id"] or rec["room_id"] == "nil":
                    continue
                # Your own outgoing message is parsed twice: an optimistic local
                # echo with no server seqId yet, and ~1s later the server-confirmed
                # copy (real seqId). Every genuine broadcast carries a positive
                # seqId, so dropping the seqId-less copy removes the duplicate
                # without losing anything -- the confirmed copy still comes through.
                # (isMySendChat() is unreliable here: it read false on some echoes.)
                seq = rec["seq_id"]
                if not (seq.isdigit() and int(seq) > 0):
                    continue
                key = (rec["room_id"], rec["seq_id"], rec["sender_uid"], rec["msg"])
                if key in seen:
                    continue
                seen.add(key)
                total += 1
                out = json.dumps(rec, ensure_ascii=False)
                print(out, flush=True)
                if out_fh:
                    out_fh.write(out + "\n")
                    out_fh.flush()
    except KeyboardInterrupt:
        pass
    finally:
        if out_fh:
            out_fh.close()
    print(f"# chat_reader: {total} messages captured", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

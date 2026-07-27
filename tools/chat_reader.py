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
* The in-game **chat window must be open** -- the client only processes the chat
  stream while the chat UI is up. This script opens it for you
  (``GoToUtil.OpenChatView()``); leave it open while capturing.
* Capture is LIVE from the moment the hook is installed. Pre-existing backlog is
  only replayed by the client on the *first* chat-open of a game session
  (``TryInitAllRoomData``); a fresh open mid-session shows only new messages.
* Non-ASCII text is carried as hex and decoded here, so Cyrillic/CJK survive.

Output: one JSON record per message to stdout and, if given, appended to --out.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import lua_client  # noqa: E402

MARKER = "ACT"

# ---------------------------------------------------------------------------
# Lua side: install idempotent hooks that copy each incoming ChatMessage into
# the global ring buffer _G.__CHATREAD. Fields are hex-encoded so non-ASCII text
# reaches Python intact (LogError mangles raw UTF-8 in Player.log).
# ---------------------------------------------------------------------------
_INSTALL_LUA = r"""
local function L(s) CS.UnityEngine.Debug.LogError("ACT "..tostring(s)) end
_G.__CHATREAD = _G.__CHATREAD or {}
local function hex(s)
  if type(s) ~= "string" then return "" end
  return (s:gsub('.', function(c) return string.format('%02x', c:byte()) end))
end
local function cname(t)
  if type(t) ~= "table" then return nil end
  local ok, cn = pcall(function()
    local mt = getmetatable(t); local idx = mt and rawget(mt, "__index")
    return (rawget(t, "_class_type") and t._class_type.__cname) or (idx and idx.__cname)
  end)
  return ok and cn or nil
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
  rec.msg    = hex(pg("msg"))
  rec.att    = hex(pg("attachmentMsg"))
  rec.sender = hex(mg("getSenderName"))
  local si = mg("getSenderInfo")
  if type(si) == "table" then
    rec.alliance = hex(tostring(si.allianceSimpleName or ""))
    rec.lang     = tostring(si.lang)
    rec.gm       = tostring(si.gmFlag)
  end
  local cap = _G.__CHATREAD
  cap[#cap + 1] = rec
  if #cap > 500 then table.remove(cap, 1) end
end
local function scanargs(...)
  for i = 1, select("#", ...) do
    local a = select(i, ...)
    if cname(a) == "ChatMessage" then record(a) end
  end
end

-- 1) UI-routing handlers: selected room -> OnGetNewChatMsg, other rooms -> UpdateOnNewMessage.
local mgr = DataCenter.ChatViewTipBubbleDataManager
_G.__CR_H = _G.__CR_H or {}
local function hook_mgr(m)
  if _G.__CR_H[m] then mgr[m] = _G.__CR_H[m] end            -- restore before re-wrapping
  local orig = mgr[m]
  if type(orig) ~= "function" then return end
  _G.__CR_H[m] = orig
  mgr[m] = function(self, ...) pcall(scanargs, ...) return orig(self, ...) end
end
hook_mgr("OnGetNewChatMsg")
hook_mgr("UpdateOnNewMessage")

-- 2) Class-level ingress: ChatMessage:onParseServerData fires for every parsed
--    message regardless of room/UI routing. Needs a live ChatMessage instance to
--    reach the class table; grab one lazily from a captured message if present.
if not _G.__CR_CLASS_HOOKED then
  local CM = nil
  if type(_G.__LASTCHAT) == "table" then
    CM = rawget(_G.__LASTCHAT, "_class_type")
    if not CM then local mt = getmetatable(_G.__LASTCHAT); CM = mt and rawget(mt, "__index") end
  end
  if type(CM) == "table" and type(CM.onParseServerData) == "function" then
    local orig = CM.onParseServerData
    CM.onParseServerData = function(self, ...)
      local r = {orig(self, ...)}
      pcall(record, self)
      return table.unpack(r)
    end
    _G.__CR_CLASS_HOOKED = true
    L("class-hook on")
  end
end
L("chat_reader hooks installed; buf="..#_G.__CHATREAD)
"""

_OPEN_LUA = (
    'pcall(function() GoToUtil.OpenChatView() end) '
    'CS.UnityEngine.Debug.LogError("ACT chat window opened")'
)

_DRAIN_LUA = r"""
local function L(s) CS.UnityEngine.Debug.LogError("ACT "..tostring(s)) end
local cap = _G.__CHATREAD or {}
L("N="..#cap)
for i, r in ipairs(cap) do
  L("R roomId="..r.roomId.." seqId="..r.seqId.." st="..r.st.." post="..r.post
    .." type="..(r.mtype or "").." uid="..r.uid.." lang="..tostring(r.lang)
    .." gm="..tostring(r.gm).." alliance="..(r.alliance or "").." sender="..(r.sender or "")
    .." msg="..(r.msg or "").." att="..(r.att or ""))
end
_G.__CHATREAD = {}   -- drained; keep buffer small
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
    rec = {
        "ts": time.time(),
        "room_id": room_id,
        "chat_type": classify_room(room_id),
        "seq_id": fields.get("seqId", ""),
        "server_time": fields.get("st", ""),
        "post": fields.get("post", ""),
        "type": fields.get("type", ""),
        "sender_uid": fields.get("uid", ""),
        "lang": fields.get("lang", ""),
        "gm": fields.get("gm", ""),
        "alliance": _hexdec(fields.get("alliance", "")),
        "sender_name": _hexdec(fields.get("sender", "")),
        "msg": _hexdec(fields.get("msg", "")),
        "attachment_msg": _hexdec(fields.get("att", "")),
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
                    help="do not auto-open the chat window (assume it is already open)")
    args = ap.parse_args()

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    ev = lua_client.get_evaluator()

    # Install hooks (idempotent) and open the chat window.
    ev.run(_INSTALL_LUA, marker=MARKER, settle=1.5)
    if not args.no_open:
        ev.run(_OPEN_LUA, marker=MARKER, settle=2.0)
    # Second install pass: now that a ChatMessage may exist (__LASTCHAT), the
    # class-level hook can bind.
    ev.run(_INSTALL_LUA, marker=MARKER, settle=1.2)

    print(f"# chat_reader: capturing for {args.seconds or '∞'}s "
          f"(chat window must stay open)", file=sys.stderr, flush=True)

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

r"""One chat message, as the game's Lua VM hands it over — recorded and decoded.

Why this module exists
----------------------
There are now TWO readers of the same thing and they must not drift apart:

* ``tools/chat_reader.py`` — the long-running LISTENER. It wraps
  ``ChatMessage:onParseServerData`` so every message the client parses is copied
  into a ring buffer, and drains that buffer as it fills. It hears what ARRIVES.
* the ``READ_CHAT`` statement (``src/lastwar_bot/script_engine.py``) — the one-off
  BACKLOG read. The client already holds the last few dozen messages of every room
  it is in (``ChatInterface.getRoomMgr().roomDatas[<room>].msgs``), and reading them
  is what fills a chat tab that has only just been switched on. It reads what is
  ALREADY THERE.

The two differ only in WHERE the message comes from. The recording (what a
``ChatMessage`` is asked for), the wire it travels on (hex over the daemon's log
channel) and the decoding back into a record are identical, so they live here once.
A second copy of :func:`parse_record_line` is the bug this module exists to prevent:
the reader's records and the backlog's records land in the same store under the same
identity, and a field spelled differently in one of them is a duplicate row nobody
can see is a duplicate.

Nothing here talks to the game. The Lua is text; the callers run it.

Hex, and why
------------
``CS.UnityEngine.Debug.LogError`` is the read-back channel, and it mangles raw UTF-8
in ``Player.log``. Chat is Cyrillic, Arabic, CJK and emoji, so every string field is
hex-encoded in Lua and decoded here (:func:`hexdec`). Numbers and ids travel plain.
"""
from __future__ import annotations

import re
import time

#: The marker every line of ours carries, so the daemon's log reader can pick them out.
MARKER = "ACT"

#: How many messages the LISTENER's ring buffer keeps before it starts dropping the
#: oldest. A drain runs every few seconds and a busy world room does not manage this
#: many in between; the backlog read raises it for its own buffer instead of sharing.
LIVE_CAP = 500

# ---------------------------------------------------------------------------
# Lua: the recorder both readers install.
# ---------------------------------------------------------------------------
#: Defines ``_G.__CR_REC(message, sink)`` — copy one ``ChatMessage`` into ``sink``
#: (a plain Lua array), hex-encoding every string field on the way.
#:
#: Rebuilt from source on every install rather than guarded by an `if`: that is what
#: lets an updated recorder take effect in a game session that has been up for days,
#: which is the whole reason the reader can be improved without a client restart.
#:
#: Every field is read under its own `pcall`. A ``ChatMessage`` is a live object whose
#: getters reach into the client's own managers, and a message whose sender has left
#: the room raises rather than answering nil — one unguarded read there loses the
#: whole batch, not one field.
RECORD_LUA = r"""
_G.__CR_BUF = _G.__CR_BUF or {}
_G.__CR_CAP = _G.__CR_CAP or __CAP__
local function hex(s)
  if type(s) ~= "string" then return "" end
  return (s:gsub('.', function(c) return string.format('%02x', c:byte()) end))
end
_G.__CR_REC = function(a, sink)
  sink = sink or _G.__CR_BUF
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
  -- posts (coord shares, invites, …) whose base text is just a "?" placeholder into a
  -- full string. Emit both; Python picks which one to display.
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
    -- The sender's avatar: `headPic` is the head-frame id, `headPicVer` the version
    -- that keys the JPG the client caches under ChatPhotos. The panel resolves it
    -- with no game call at all.
    rec.hp       = tostring(si.headPic)
    rec.hpv      = tostring(si.headPicVer)
  end
  sink[#sink + 1] = rec
  local cap = _G.__CR_CAP or __CAP__
  while #sink > cap do table.remove(sink, 1) end
end
"""


def record_lua(cap: int = LIVE_CAP) -> str:
    """The recorder, with the ring-buffer cap filled in."""
    return RECORD_LUA.replace("__CAP__", str(int(cap)))


#: Emit every record sitting in one buffer, one log line each, then empty it.
#:
#: One `pcall` PER LINE, not one around the loop: a single malformed record must never
#: abort the drain, because an aborted drain silently loses every message behind it.
DRAIN_LUA = r"""
local function L(s) CS.UnityEngine.Debug.LogError("__MARK__ "..tostring(s)) end
local cap = _G.__SINK__ or {}
L("N="..#cap)
local function f(v) return tostring(v == nil and "" or v) end   -- nil-safe field
for i, r in ipairs(cap) do
  pcall(function()
    L("R roomId="..f(r.roomId).." seqId="..f(r.seqId).." st="..f(r.st).." post="..f(r.post)
      .." type="..f(r.mtype).." uid="..f(r.uid).." lang="..f(r.lang)
      .." gm="..f(r.gm).." srv="..f(r.srv).." hp="..f(r.hp).." hpv="..f(r.hpv)
      .." ismy="..f(r.ismy).." alliance="..f(r.alliance)
      .." sender="..f(r.sender).." msg="..f(r.msg).." we="..f(r.we))
  end)
end
_G.__SINK__ = {}   -- drained; keep the buffer small
"""


def drain_lua(sink: str = "__CR_BUF", marker: str = MARKER) -> str:
    """Drain one named global buffer. ``sink`` is a global NAME, not a value."""
    return DRAIN_LUA.replace("__SINK__", sink).replace("__MARK__", marker)


#: The buffer the BACKLOG read fills. Deliberately not the listener's: the reader child
#: drains `__CR_BUF` on its own clock, so a backlog seeded into it would be carried off
#: by whichever of the two asked first and the other would see nothing.
HISTORY_SINK = "__CR_HIST"


#: Seed :data:`HISTORY_SINK` with the messages the CLIENT IS ALREADY HOLDING.
#:
#: `ChatInterface.getRoomMgr().roomDatas` is the client's own per-room state, and each
#: room's `msgs` is its message list — about forty per room a client has been sitting
#: in, filled by the same parse the listener hooks. Reading it asks the SERVER nothing:
#: it is the copy the client made when the messages arrived, which is exactly what
#: «read once, then listen» wants a first read to be.
#:
#: `historyState` / `ChatController.ChatRoomRequestHistoryMsg` would fetch DEEPER than
#: what is held — that is a request to the server, and it is deliberately not made here.
#:
#: A room with an empty `msgs` (every private conversation the player has not opened in
#: this session) is skipped rather than counted: it is not «no history», it is history
#: the client has not asked for, and saying «0 messages» about it would be a lie.
BACKLOG_LUA = r"""
local function L(s) CS.UnityEngine.Debug.LogError("__MARK__ "..tostring(s)) end
_G.__SINK__ = {}
_G.__CR_CAP = __CAP__
local I = package.loaded["Chat.ChatInterface"]
if type(I) ~= "table" then L("SEED err=no-chat-interface") return end
local ok, mgr = pcall(function() return I.getRoomMgr() end)
if not ok or type(mgr) ~= "table" then L("SEED err=no-room-manager") return end
local rooms, seeded = 0, 0
for _, rd in pairs(mgr.roomDatas or {}) do
  if type(rd) == "table" and type(rd.msgs) == "table" and #rd.msgs > 0 then
    rooms = rooms + 1
    local msgs = rd.msgs
    local from = #msgs - __LIMIT__ + 1
    if from < 1 then from = 1 end
    for i = from, #msgs do
      if pcall(_G.__CR_REC, msgs[i], _G.__SINK__) then seeded = seeded + 1 end
    end
  end
end
_G.__CR_CAP = __LIVECAP__
L("SEED rooms="..rooms.." n="..seeded)
"""


def backlog_lua(limit: int = 40, marker: str = MARKER,
                sink: str = HISTORY_SINK, cap: int = 4000) -> str:
    """Seed the history buffer from what the client holds. Needs :func:`record_lua` first.

    ``limit`` is per ROOM — the newest that many of each. ``cap`` bounds the buffer
    against a client that has been up for a week with a hundred rooms open; the live
    cap is restored on the way out so the listener's own buffer keeps its own bound.
    """
    return (BACKLOG_LUA
            .replace("__SINK__", sink)
            .replace("__MARK__", marker)
            .replace("__LIMIT__", str(max(1, int(limit))))
            .replace("__CAP__", str(int(cap)))
            .replace("__LIVECAP__", str(int(LIVE_CAP))))


# ---------------------------------------------------------------------------
# Python: decoding one drained line back into a record.
# ---------------------------------------------------------------------------
def hexdec(h: str) -> str:
    try:
        return bytes.fromhex(h).decode("utf-8", "replace")
    except Exception:       # noqa: BLE001 — a mangled field is not a lost message
        return ""


def classify_room(room_id: str) -> str:
    """Which tab a room belongs to. Kept in step with `panel/chat_history.py`."""
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


# The game's "local" emoji are Private Use Area glyphs (U+E000..U+F8FF) sitting inline
# in the message text; a terminal or a JSON consumer renders them as broken boxes.
# Replace each with a readable [e:XXXX] token. Rich inline objects arrive as
# <lwSticker:N:> / <lwPhoto:N:> / <lwEmoji:N:> markers; normalise them to [kind:N].
_PUA_RE = re.compile("[\ue000-\uf8ff]")
_LW_RE = re.compile(r"<lw([A-Za-z]+):(\d+)(?::[^>]*)?>")
_PLACEHOLDER = {"", "?", "nil"}


def render_text(s: str) -> str:
    """Make chat text human-readable: name inline objects and PUA emoji explicitly."""
    s = _LW_RE.sub(lambda m: f"[{m.group(1).lower()}:{m.group(2)}]", s)
    s = _PUA_RE.sub(lambda m: f"[e:{ord(m.group()):04X}]", s)
    return s


def parse_record_line(line: str, marker: str = MARKER) -> "dict | None":
    """Parse one ``ACT R k=v k=v …`` drain line into a decoded chat record.

    ``None`` for anything that is not one of our record lines.
    """
    body = line
    head = marker + " "
    if body.startswith(head):
        body = body[len(head):]
    if not body.startswith("R "):
        return None
    body = body[2:]
    # Fields are space-separated key=value; the hex fields hold no spaces (hex) and the
    # plain ones (roomId / uid / …) hold none either.
    fields: dict = {}
    for tok in body.split(" "):
        if "=" in tok:
            k, v = tok.split("=", 1)
            fields[k] = v
    room_id = fields.get("roomId", "")
    base = hexdec(fields.get("msg", ""))          # getMsg()
    with_extra = hexdec(fields.get("we", ""))     # getMessageWithExtra()
    # Attachment / interactive posts (coord shares, invites, …) leave getMsg() as a bare
    # "?" placeholder; getMessageWithExtra() renders the real content. Prefer it only
    # when the base is empty — otherwise a plain message would gain a rendered prefix.
    display = with_extra if (base.strip() in _PLACEHOLDER and with_extra) else base
    # Timestamp the record with the message's own serverTime (epoch ms), NEVER the parse
    # time: history read out of the client is parsed «now», so a parse-time stamp would
    # sort every ancient message to the bottom of the tab.
    server_time = fields.get("st", "")
    try:
        ts = int(server_time) / 1000.0
    except (TypeError, ValueError):
        ts = time.time()
    return {
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
        "alliance": hexdec(fields.get("alliance", "")),
        "sender_name": hexdec(fields.get("sender", "")),
        "msg": render_text(display),
    }


def usable(record: "dict | None") -> bool:
    """Whether a decoded record is a routable, non-duplicate message.

    Two rules, both learnt live and both cheap to get wrong:

    * a ``ChatMessage`` always carries a ``roomId`` — one without is not routable;
    * an outgoing message is parsed TWICE, an optimistic local copy with no ``seqId``
      yet and, about a second later, the server-confirmed copy with a real one. Every
      genuine message carries a positive ``seqId``, so dropping the one without it
      removes the duplicate and loses nothing. (``isMySendChat()`` is NOT the test —
      it read false on some of the sender's own echoes.)
    """
    if not record:
        return False
    room = str(record.get("room_id") or "")
    if not room or room == "nil":
        return False
    seq = str(record.get("seq_id") or "")
    return seq.isdigit() and int(seq) > 0


def identity(record: dict) -> tuple:
    """What makes two decoded records the same message."""
    return (record.get("room_id", ""), record.get("seq_id", ""),
            record.get("sender_uid", ""), record.get("msg", ""))

r"""Share map coordinates into chat — the importable half of `tools/chat_send.py`.

Import this from any script that needs to put a coordinate in front of a player;
`tools/chat_send.py` is only the CLI wrapper around it. Everything runs inside the
game's own Lua VM through the warm daemon: no pixels, no foreground input, no raw
wire crafting.

Quick start
-----------
```python
import sys, os
sys.path.insert(0, os.path.join("tools", "lib"))
import chat_share, lua_client

ev = lua_client.get_evaluator()
me = chat_share.self_profile(ev)                       # uid / srv / x / y / name / abbr
room = chat_share.dm_room("1000000000014972", me["uid"])

# a bare pin
chat_share.share_point(ev, room, chat_share.point_attachment(615, 493, 935),
                       peer_uid="1000000000014972")

# your own base, exactly like the in-game "share my position" button
chat_share.share_point(ev, room, chat_share.base_attachment(me),
                       peer_uid="1000000000014972")
```

Model (full write-up: docs/research/chat-coord-share.md)
-------------------------------------------------------
A shared coordinate is **not** text. It is a `ChatMessage` with `post = 13`
(`PostType.Text_PointShare`), `msg = "?"` (a placeholder) and an `attachmentId`
JSON blob that the receiving client renders into the bubble. It does **not** go
through the text choke point `ChatManager2:__sendToRoom` — that rebuilds `extra`
and silently drops the attachment. The working path is the share command class,
dispatched on the chat connection:

    ChatManager2:GetInstance().Net:SendSFSMessage(<cmd>, param)

`chat_share_cmd()` in `lua_actions` picks `<cmd>` from the room id (DM
`chat.room.send`, world/national `chat.country`, alliance `al.msg`). Only the DM
command is verified live.

Attachment kinds
----------------
Every blob carries `x`, `y`, `sid`, `worldId`, `worldType`. What follows depends on
the object; `pos_type` (`posType`) is the discriminator:

| helper | posType | extra fields |
|---|---|---|
| `base_attachment()` | *absent* | `oname = "[TAG] Name"` |
| `point_attachment()` | 0 | `uid` = the sharer (only this kind has one) |
| `point_attachment(..., pos_type=1)` | 1 | `olv`, `oname` = template id |
| `point_attachment(..., pos_type=6)` | 6 | `olv`, `oname`, `uname` = "Добытчик: …" |
| `task_attachment()` | 22 | `uuid`, `cfgId`, `uname`, `abbr`, `dispatch = 1` |

Pass anything else through the `extra` mapping. `uuid` values exceed 2^53 — keep
them as Python ints / JSON integers and never round-trip them through a float.
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import lua_actions  # noqa: E402

MARKER = "ACT"

# The label the client itself puts on a shared secret task.
SECRET_TASK_LABEL = "Секретное задание"


def _hexdec(h: str) -> str:
    """Decode a hex field emitted by the Lua side (Player.log mangles raw UTF-8)."""
    try:
        return bytes.fromhex(h).decode("utf-8", "replace")
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

def dm_room(peer_uid: str, self_uid: str) -> str:
    """DM room id: `custom_<peerUid>_<selfUid>_v2` (peer first, self second)."""
    return "custom_%s_%s_v2" % (peer_uid, self_uid)


def peer_of(room_id: str):
    """The peer uid encoded in a DM room id, or None for a broadcast room."""
    parts = room_id.split("_")
    if len(parts) >= 4 and parts[0] == "custom" and room_id.endswith("_v2"):
        return parts[1]
    return None


_SELF_LUA = r'''
local function hex(s) return (tostring(s):gsub('.', function(c) return string.format('%02x', c:byte()) end)) end
pcall(function()
  local uid = ChatInterface.getPlayerUid()
  local srv = ChatInterface.getSelfServerId()
  local p = ChatInterface.getPlayer()
  local ud = ChatInterface.getUserData(uid)
  local x, y = "", ""
  pcall(function()
    local tp = SceneUtils.IndexToTilePos(p.world_main_pos)
    x, y = tp.x, tp.y
  end)
  CS.UnityEngine.Debug.LogError("ACT self uid="..tostring(uid).." srv="..tostring(srv)
    .." x="..tostring(x).." y="..tostring(y)
    .." name="..hex(tostring(ud and ud.userName or (p and p.name) or ""))
    .." abbr="..hex(tostring(ud and ud.allianceSimpleName or "")))
end)
'''


def self_profile(ev) -> dict:
    """`{uid, srv, x, y, name, abbr}` for the logged-in player, read live.

    `x`/`y` are the own base tile (`world_main_pos` -> `SceneUtils.IndexToTilePos`).
    An empty dict means the game is not alive / not logged in.
    """
    out = {}
    for ln in ev.run(_SELF_LUA, MARKER, 1.2):
        if " self " not in ln:
            continue
        for tok in ln.split(" self ", 1)[1].split(" "):
            key, sep, value = tok.partition("=")
            if not sep:
                continue
            out[key] = _hexdec(value) if key in ("name", "abbr") else value
    return out


def self_label(profile: dict) -> str:
    """`"[TAG] Name"` — the label the game puts on a shared own base."""
    name = profile.get("name", "")
    abbr = profile.get("abbr")
    return "[%s] %s" % (abbr, name) if abbr else name


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

def point_attachment(x, y, server, pos_type: int = 0, label=None, uid=None,
                     extra=None) -> str:
    """`attachmentId` JSON for a map object at (x, y) on `server`.

    `uid` is written only for `pos_type == 0` (the bare pin, where it identifies the
    sharer); every richer kind describes the object instead and the game's own shares
    carry no `uid`. `extra` merges last, so it can override anything.
    """
    att = {"x": int(x), "y": int(y), "sid": int(server), "worldId": 0, "worldType": 0,
           "posType": int(pos_type)}
    if label:
        att["oname"] = label
    if uid and int(pos_type) == 0:
        att["uid"] = str(uid)
    if extra:
        att.update(extra)
    return json.dumps(att, ensure_ascii=False, separators=(",", ":"))


def base_attachment(profile: dict, label=None) -> str:
    """`attachmentId` for "share my position" — no `posType`, labelled by `oname`."""
    att = {"x": int(profile["x"]), "y": int(profile["y"]), "sid": int(profile["srv"]),
           "worldId": 0, "worldType": 0, "oname": label or self_label(profile)}
    return json.dumps(att, ensure_ascii=False, separators=(",", ":"))


def task_attachment(task: dict, label: str = SECRET_TASK_LABEL) -> str:
    """`attachmentId` for a secret task, from a `tools/dispatch_tasks.py` record.

    The record needs `x`, `y`, `srv`, `uuid`, `cfgId` and (for the label line) the
    owner's `name` / `abbr`.
    """
    return point_attachment(
        task["x"], task["y"], task["srv"], pos_type=22, label=label,
        extra={"uuid": int(task["uuid"]), "cfgId": int(task["cfgId"]),
               "uname": task.get("name", ""), "abbr": task.get("abbr", ""),
               "dispatch": 1},
    )


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def share_point(ev, room_id: str, attachment: str, peer_uid=None, lang: str = "ru") -> bool:
    """Send `attachment` into `room_id`. True when the game confirmed the send.

    `peer_uid` is only needed for a DM and is derived from the room id when omitted.
    Outgoing chat cannot be unsent — build and eyeball the attachment first.
    """
    cmd = lua_actions.chat_share_cmd(room_id)
    lang_room = room_id.split("_")[2] if room_id.startswith("custom_lang_") else None
    if cmd == lua_actions.CMD_SHARE_DM and not peer_uid:
        peer_uid = peer_of(room_id)
    chunk = lua_actions.chat_share_point(
        room_id, attachment, lang=lang,
        to_user=peer_uid if cmd == lua_actions.CMD_SHARE_DM else None,
        lang_room=lang_room,
    )
    return any("chat_point_sent" in ln for ln in ev.run(chunk, MARKER, 1.4))

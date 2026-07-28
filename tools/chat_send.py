r"""Send a chat message (DM / world / national / alliance) from inside the game.

Reverse-engineered live from PM traces to the player "EleNita": plain text,
inline emoji and stickers (task #1085), then map coordinates (task #1089).
Everything runs inside the game's own Lua VM through the warm daemon
(tools/lua_daemon.py) -- no screen reading, no foreground input, no raw wire
crafting.

Why this route
--------------
Chat broadcast/DM text rides a TLS WebSocket that project policy does not MITM,
so we drive the client's own send path instead. Every chat send funnels through a
single choke point:

    ChatManager2:__sendToRoom(roomId, msg, extra, reply, isProxy, post)

which builds and fires BOTH wire commands (`lw.user.push.chat.msg` + the
`chat.stat` telemetry twin). Stickers ride their own manager entry
`ChatEmojiTemplateManager:TrySendSticker(roomId, stickerId)`. The confirmed API
and the reverse-engineering are written up in docs/research/chat-send.md.

Room ids (docs/research/chat.md §2)
-----------------------------------
    DM        custom_<peerUid>_<selfUid>_v2     (built for you from --to)
    World     country_<server>
    National  custom_lang_<lang>_<server>
    Alliance  alliance_<serverId>_<allianceId>

Emoji
-----
Inline emoji are Private Use Area glyphs living *inside* the text. Reference them
in --text with `{e:<id>}` tokens (e.g. "hi {e:101}!"); this resolves the id to its
PUA char live via the game config before sending. `--list-emoji` prints ids.

Coordinates
-----------
A shared map coordinate is not text: it is `post = 13` plus an `attachmentId` JSON
blob, sent as its own command (see docs/research/chat-coord-share.md). `--coords`
sends a bare map pin, `--my-base` shares the player's own base the way the chat
"share my position" button does. The recipient gets the normal tappable bubble.
Richer map objects (secret task, resource node, ...) add `--coord-type <posType>`
plus their own fields through `--coord-extra`; `tools/dispatch_tasks.py
--share-args` prints those for a live secret task.

Usage (run under the Windows Python so it can reach the daemon)
--------------------------------------------------------------
    C:\Python312\python.exe tools\chat_send.py --to 1697234600000972 --text "Тест"
    C:\Python312\python.exe tools\chat_send.py --to <uid> --text "hi {e:101}{e:106}"
    C:\Python312\python.exe tools\chat_send.py --to <uid> --sticker 35
    C:\Python312\python.exe tools\chat_send.py --to <uid> --coords "567,471"
    C:\Python312\python.exe tools\chat_send.py --to <uid> --coords "X:567 Y:471" --coord-server 972
    C:\Python312\python.exe tools\chat_send.py --to <uid> --coords "500,500" --coord-label "Сбор тут"
    C:\Python312\python.exe tools\chat_send.py --to <uid> --my-base
    C:\Python312\python.exe tools\chat_send.py --to <uid> --coords "615,493" --coord-type 22 \
        --coord-label "Секретное задание" --coord-extra '{"uuid":…,"cfgId":…,"uname":…,"abbr":…,"dispatch":1}'
    C:\Python312\python.exe tools\chat_send.py --room country_935 --text "hello world"
    C:\Python312\python.exe tools\chat_send.py --to <uid> --text "hi" --dry-run
    C:\Python312\python.exe tools\chat_send.py --list-emoji
    C:\Python312\python.exe tools\chat_send.py --list-sticker

Sending to a DM room needs the peer's uid (--to). A raw --room targets any
channel directly. Outgoing messages cannot be unsent -- use --dry-run to preview
the resolved room id and payload first.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import coords as coords_fmt  # noqa: E402
import lua_actions  # noqa: E402
import lua_client  # noqa: E402

MARKER = "ACT"
_EMOJI_TOKEN = re.compile(r"\{e:(\d+)\}")


def _log(msg: str) -> None:
    print(msg, flush=True)


def _hexdec(h: str) -> str:
    """Decode a hex field emitted by the Lua side (Player.log mangles raw UTF-8)."""
    try:
        return bytes.fromhex(h).decode("utf-8", "replace")
    except ValueError:
        return ""


def resolve_self_uid(ev) -> str:
    """The logged-in player's uid (needed to build a DM room id)."""
    chunk = (
        'CS.UnityEngine.Debug.LogError("ACT selfuid="..'
        'tostring(select(2, pcall(function() return ChatInterface.getPlayerUid() end))))'
    )
    for ln in ev.run(chunk, MARKER, 0.8):
        if "selfuid=" in ln:
            return ln.split("selfuid=", 1)[1].strip()
    return ""


def resolve_self_profile(ev) -> dict:
    """Live self profile used to label a coordinate share.

    `world_main_pos` on the player record is the own base's tile index; the tile x/y
    come from `SceneUtils.IndexToTilePos`. The display label the game itself puts on a
    "share my position" message is `"[<allianceSimpleName>] <userName>"`.
    """
    chunk = r'''
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
    out = {}
    for ln in ev.run(chunk, MARKER, 1.2):
        if " self " not in ln:
            continue
        for tok in ln.split(" self ", 1)[1].split(" "):
            key, sep, value = tok.partition("=")
            if not sep:
                continue
            out[key] = _hexdec(value) if key in ("name", "abbr") else value
    return out


def dm_room(peer_uid: str, self_uid: str) -> str:
    """DM room id: custom_<peerUid>_<selfUid>_v2 (peer first, self second)."""
    return "custom_%s_%s_v2" % (peer_uid, self_uid)


def resolve_emoji_pua(ev, ids) -> dict:
    """Map each emoji id -> its inline PUA character, live from the game config.

    `GetEmojiDataById(id).name` is a PUA hex stem (e.g. 101 -> "e006" -> U+E006).
    """
    if not ids:
        return {}
    id_list = ",".join(str(int(i)) for i in ids)
    chunk = (
        'local em=DataCenter.ChatEmojiTemplateManager '
        'for _,id in ipairs({%s}) do '
        'local d=em:GetEmojiDataById(id) '
        'CS.UnityEngine.Debug.LogError("ACT emojipua "..id.."="..'
        'tostring(d and d.name or "")) end' % id_list
    )
    out = {}
    for ln in ev.run(chunk, MARKER, 1.0):
        if "emojipua " in ln:
            body = ln.split("emojipua ", 1)[1].strip()
            if "=" in body:
                sid, name = body.split("=", 1)
                name = name.strip()
                if name and name != "nil":
                    try:
                        out[int(sid)] = chr(int(name, 16))
                    except ValueError:
                        pass
    return out


def assemble_text(ev, text: str) -> str:
    """Replace `{e:<id>}` tokens in `text` with their live PUA emoji characters."""
    ids = [int(m) for m in _EMOJI_TOKEN.findall(text)]
    if not ids:
        return text
    pua = resolve_emoji_pua(ev, ids)
    missing = [i for i in ids if i not in pua]
    if missing:
        _log("WARN: unknown emoji id(s): %s (left as literal token)"
             % ", ".join(map(str, missing)))

    def sub(m):
        return pua.get(int(m.group(1)), m.group(0))

    return _EMOJI_TOKEN.sub(sub, text)


def list_emoji(ev) -> None:
    chunk = (
        'local em=DataCenter.ChatEmojiTemplateManager '
        'for _,e in ipairs(em:GetShowEmojiList()) do '
        'local id = type(e)=="table" and (e.id or e.cfgId) or e '
        'local d=em:GetEmojiDataById(id) '
        'CS.UnityEngine.Debug.LogError("ACT emoji "..tostring(id).." "..'
        'tostring(d and d.name or "")) end'
    )
    for ln in ev.run(chunk, MARKER, 1.2):
        if "ACT emoji " in ln:
            _log(ln.split("ACT emoji ", 1)[1].strip())


def list_sticker(ev) -> None:
    chunk = (
        'local em=DataCenter.ChatEmojiTemplateManager '
        'for _,s in ipairs(em:GetShowStickerList()) do '
        'local id = type(s)=="table" and (s.id or s.cfgId) or s '
        'local d=em:GetStickerDataById(id) '
        'CS.UnityEngine.Debug.LogError("ACT sticker "..tostring(id).." "..'
        'tostring(d and d.name or "")) end'
    )
    for ln in ev.run(chunk, MARKER, 1.2):
        if "ACT sticker " in ln:
            _log(ln.split("ACT sticker ", 1)[1].strip())


def send(ev, room: str, text=None, sticker=None, dry=False) -> int:
    if sticker is not None:
        _log("room=%s  sticker=%d" % (room, sticker))
        if dry:
            _log("[dry-run] not sent")
            return 0
        for ln in ev.run(lua_actions.chat_send_sticker(room, sticker), MARKER, 1.4):
            if "chat_sticker_sent" in ln:
                _log("sent (sticker %d)" % sticker)
                return 0
        _log("WARN: no send confirmation from the game")
        return 1

    msg = assemble_text(ev, text)
    # Show a readable preview (PUA glyphs won't render in most terminals).
    preview = _EMOJI_TOKEN.sub(lambda m: "[e:%s]" % m.group(1), text)
    _log("room=%s  msg=%r  (%d bytes utf-8)" % (room, preview, len(msg.encode("utf-8"))))
    if dry:
        _log("[dry-run] not sent")
        return 0
    for ln in ev.run(lua_actions.chat_send_text(room, msg), MARKER, 1.4):
        if "chat_sent" in ln:
            _log("sent")
            return 0
    _log("WARN: no send confirmation from the game")
    return 1


def parse_coords(text: str):
    """(x, y, server|None) from any coordinate spelling the project accepts.

    Delegates to tools/lib/coords.py (the canonical parser: "X:567 Y:471",
    "@[567,471|935]", "(567,471)", "567/471", ...) and additionally accepts the plain
    "567,471" pair, which the shared parser deliberately ignores in prose.
    """
    hits = coords_fmt.parse(text)
    if hits:
        _, _, x, y, server = hits[0]
        return x, y, server
    m = re.fullmatch(r"\s*(\d{1,4})\s*[,; ]\s*(\d{1,4})\s*(?:[|@]\s*(\d{1,5})\s*)?", text)
    if m:
        return int(m.group(1)), int(m.group(2)), (int(m.group(3)) if m.group(3) else None)
    raise ValueError("cannot read a coordinate out of %r" % text)


def build_point_attachment(x: int, y: int, server: int, pos_type=0, label=None,
                           uid=None, extra=None) -> str:
    """The `attachmentId` blob for a shared map point.

    Shape confirmed live against the game's own shares (docs/research/chat-coord-share.md):
    the "share my base" button omits `posType` and labels the bubble through `oname`
    ("[TAG] Name"); a bare pin is `posType 0` plus the sharer's `uid`. Richer objects
    (`posType` 1 / 6 / 22 …) carry no `uid` but kind-specific fields instead — pass
    those through `extra` (e.g. a secret task's `uuid`, `cfgId`, `uname`, `abbr`,
    `dispatch`); `tools/dispatch_tasks.py --share-args` prints a ready blob.
    """
    att = {"x": int(x), "y": int(y), "sid": int(server), "worldId": 0, "worldType": 0}
    if pos_type is None:
        att["oname"] = label or ""
    else:
        att["posType"] = int(pos_type)
        if label:
            att["oname"] = label
        # Only the bare pin identifies the sharer; every richer kind describes the
        # object itself instead.
        if uid and int(pos_type) == 0:
            att["uid"] = str(uid)
    if extra:
        att.update(extra)
    return json.dumps(att, ensure_ascii=False, separators=(",", ":"))


def send_point(ev, room: str, attachment: str, peer_uid=None, lang: str = "ru",
               dry: bool = False) -> int:
    """Send a coordinate share; `attachment` is the finished attachmentId JSON."""
    cmd = lua_actions.chat_share_cmd(room)
    lang_room = room.split("_")[2] if room.startswith("custom_lang_") else None
    if cmd == lua_actions.CMD_SHARE_DM and not peer_uid:
        # A raw --room DM still needs the peer uid: it is the first id in
        # custom_<peerUid>_<selfUid>_v2.
        parts = room.split("_")
        peer_uid = parts[1] if len(parts) >= 4 and parts[0] == "custom" else None
    _log("room=%s  cmd=%s  attachmentId=%s" % (room, cmd, attachment))
    if dry:
        _log("[dry-run] not sent")
        return 0
    chunk = lua_actions.chat_share_point(
        room, attachment, lang=lang,
        to_user=peer_uid if cmd == lua_actions.CMD_SHARE_DM else None,
        lang_room=lang_room,
    )
    for ln in ev.run(chunk, MARKER, 1.4):
        if "chat_point_sent" in ln:
            _log("sent (coordinates)")
            return 0
    _log("WARN: no send confirmation from the game")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Send a chat message from inside the game.")
    ap.add_argument("--to", help="peer uid -> DM room custom_<peer>_<self>_v2")
    ap.add_argument("--room", help="raw room id (world/national/alliance/DM)")
    ap.add_argument("--text", help="message text; supports {e:<id>} emoji tokens")
    ap.add_argument("--sticker", type=int, help="sticker id to send (see --list-sticker)")
    ap.add_argument("--coords", metavar="X,Y",
                    help='share a map pin; accepts "567,471", "X:567 Y:471", "@[567,471|935]"')
    ap.add_argument("--coord-server", type=int,
                    help="server id for --coords (default: the coordinate's own, else self server)")
    ap.add_argument("--coord-label", help="text shown on the shared pin (attachment `oname`)")
    ap.add_argument("--coord-type", type=int, default=0,
                    help="attachment posType: 0 bare pin (default), 1 resource node, "
                         "6 node being gathered, 22 secret task")
    ap.add_argument("--coord-extra", metavar="JSON",
                    help="extra attachment fields for a richer object, e.g. a secret "
                         "task's {\"uuid\":…,\"cfgId\":…,\"uname\":…,\"abbr\":…,\"dispatch\":1} "
                         "(tools/dispatch_tasks.py --share-args prints it)")
    ap.add_argument("--my-base", action="store_true",
                    help='share own base coordinates, like the chat "share my position" button')
    ap.add_argument("--lang", default="ru", help="sender language tag on a share (default ru)")
    ap.add_argument("--dry-run", action="store_true", help="preview room + payload, do not send")
    ap.add_argument("--list-emoji", action="store_true", help="list available emoji ids")
    ap.add_argument("--list-sticker", action="store_true", help="list available sticker ids")
    args = ap.parse_args()

    ev = lua_client.get_evaluator()

    if args.list_emoji:
        list_emoji(ev)
        return 0
    if args.list_sticker:
        list_sticker(ev)
        return 0

    if args.text is None and args.sticker is None and not args.coords and not args.my_base:
        ap.error("nothing to send: pass --text / --sticker / --coords / --my-base "
                 "(or a --list-* flag)")
    if not args.room and not args.to:
        ap.error("no target: pass --to <peerUid> (DM) or --room <roomId>")

    # The self profile is needed for a DM room id and to label a coordinate share.
    profile = {}
    if not args.room or args.coords or args.my_base:
        profile = resolve_self_profile(ev)
        if not profile.get("uid"):
            _log("ERROR: could not resolve self profile (is the game alive?)")
            return 1

    room = args.room or dm_room(args.to, profile["uid"])

    rc = 0
    if args.text is not None:
        rc |= send(ev, room, text=args.text, dry=args.dry_run)
    if args.sticker is not None:
        rc |= send(ev, room, sticker=args.sticker, dry=args.dry_run)

    if args.my_base:
        if not profile.get("x"):
            _log("ERROR: could not read the own base tile (world_main_pos)")
            return rc | 1
        label = args.coord_label or (
            "[%s] %s" % (profile.get("abbr"), profile.get("name"))
            if profile.get("abbr") else profile.get("name", ""))
        att = build_point_attachment(profile["x"], profile["y"],
                                     args.coord_server or profile["srv"],
                                     pos_type=None, label=label)
        rc |= send_point(ev, room, att, peer_uid=args.to, lang=args.lang, dry=args.dry_run)

    if args.coords:
        try:
            x, y, server = parse_coords(args.coords)
        except ValueError as exc:
            ap.error(str(exc))
        server = args.coord_server or server or int(profile.get("srv") or 0)
        if not server:
            ap.error("no server for the coordinate: pass --coord-server")
        extra = None
        if args.coord_extra:
            try:
                extra = json.loads(args.coord_extra)
            except ValueError as exc:
                ap.error("--coord-extra is not valid JSON: %s" % exc)
            if not isinstance(extra, dict):
                ap.error("--coord-extra must be a JSON object")
        att = build_point_attachment(x, y, server, pos_type=args.coord_type,
                                     label=args.coord_label, uid=profile.get("uid"),
                                     extra=extra)
        _log("coords %s" % coords_fmt.fmt(x, y, server))
        rc |= send_point(ev, room, att, peer_uid=args.to, lang=args.lang, dry=args.dry_run)

    return rc


if __name__ == "__main__":
    raise SystemExit(main())

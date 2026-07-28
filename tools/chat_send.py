r"""Send a chat message (DM / world / national / alliance) from inside the game.

Reverse-engineered live from a PM trace to the player "EleNita" (task #1085):
plain text, inline emoji and stickers. Everything runs inside the game's own Lua
VM through the warm daemon (tools/lua_daemon.py) -- no screen reading, no
foreground input, no raw wire crafting.

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

Usage (run under the Windows Python so it can reach the daemon)
--------------------------------------------------------------
    C:\Python312\python.exe tools\chat_send.py --to 1697234600000972 --text "Тест"
    C:\Python312\python.exe tools\chat_send.py --to <uid> --text "hi {e:101}{e:106}"
    C:\Python312\python.exe tools\chat_send.py --to <uid> --sticker 35
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
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "lib"))
import lua_actions  # noqa: E402
import lua_client  # noqa: E402

MARKER = "ACT"
_EMOJI_TOKEN = re.compile(r"\{e:(\d+)\}")


def _log(msg: str) -> None:
    print(msg, flush=True)


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


def main() -> int:
    ap = argparse.ArgumentParser(description="Send a chat message from inside the game.")
    ap.add_argument("--to", help="peer uid -> DM room custom_<peer>_<self>_v2")
    ap.add_argument("--room", help="raw room id (world/national/alliance/DM)")
    ap.add_argument("--text", help="message text; supports {e:<id>} emoji tokens")
    ap.add_argument("--sticker", type=int, help="sticker id to send (see --list-sticker)")
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

    if args.text is None and args.sticker is None:
        ap.error("nothing to send: pass --text and/or --sticker (or a --list-* flag)")
    if not args.room and not args.to:
        ap.error("no target: pass --to <peerUid> (DM) or --room <roomId>")

    if args.room:
        room = args.room
    else:
        self_uid = resolve_self_uid(ev)
        if not self_uid:
            _log("ERROR: could not resolve self uid (is the game alive?)")
            return 1
        room = dm_room(args.to, self_uid)

    rc = 0
    if args.text is not None:
        rc |= send(ev, room, text=args.text, dry=args.dry_run)
    if args.sticker is not None:
        rc |= send(ev, room, sticker=args.sticker, dry=args.dry_run)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

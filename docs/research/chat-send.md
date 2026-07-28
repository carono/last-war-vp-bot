# Sending chat messages (text, emoji, sticker)

Reverse-engineered live for task #1085 from a PM trace to the player **EleNita**
(`results/traces/20260728_220208_чат_EleNita_trace.log`). This is the write side of
[`chat.md`](chat.md) (rooms/wire) and [`chat-lua-readout.md`](chat-lua-readout.md)
(the read side).

## Why the wire trace was empty

The recorded `*_traffic.jsonl` held only keepalives and `push.world.march.*`. Chat
broadcast/DM text rides a TLS WebSocket that project policy does not MITM, and the
`lw.user.push.chat.msg` control frames live on the `:17935` leg — which the capture
missed (stale port, see the `env_read_wgb_blocked` memory). So the send was
reconstructed from the **Lua trace** plus live introspection through the warm
daemon, not from the pcap.

> **Coordinates are the exception.** A shared map point is not text and does
> **not** go through `__sendToRoom` (it drops the attachment). See
> [`chat-coord-share.md`](chat-coord-share.md).

## The one choke point

Every chat send — world, national, alliance, DM, text, emoji — funnels through a
single client method:

```
ChatManager2:__sendToRoom(roomId, msg, extra, reply, isProxy, post)
```
(`Assets/Main/LuaScripts/Chat/ChatManager2.lua:243`, param names confirmed by a
read-only `debug.sethook` "call" probe.)

| Param | Text send (from trace) | Meaning |
|---|---|---|
| `roomId` | `custom_1697234600000972_1522777203000972_v2` | target room (see below) |
| `msg` | `123123` | the text; **inline emoji are PUA chars inside this string** |
| `extra` | a table | optional `msgExtra` (srcLang, post, atUids, senderLevel, …) |
| `reply` | `nil` | reply-to message |
| `isProxy` | `0` | proxy flag |
| `post` | `nil` | post-type payload |

`__sendToRoom` builds and fires **both** wire commands acked together — the
`lw.user.push.chat.msg` (`{uid=peer, msg, roomId}`) and its `chat.stat` telemetry
twin (see `chat.md §3.1`).

`extra` is read entirely defensively: a `call`-hook probe that fed an empty-proxy
table watched the client read `timeline, seqId, post, senderLevel, allianceId,
reportUid, detectReportUid, equipId, teamUuid, lotteryInfo, attachmentId,
shamoInfo, media, isNormalMsg, extraJson, picJson, atPlayers` — every one nil —
and still reach `SFSNetwork.SendMessage` without error. **So `extra = {}` sends a
clean plain message.** The high-level UI path (`ChatManager2:SyncMessageToServer`
→ `SendChatMsg` → `__sendToRoom`) only exists to populate `extra` and echo the
message locally; it needs the lazily-loaded `LWUserPushChatMsgMessage` class,
which `__sendToRoom` does not.

Full call chain observed in the trace for the text `123123`:
`ChatInterface.CheckMessage` → `ChatManager2.CheckRoomSend` →
`SyncMessageToServer` → `SFSBaseMessage.__init(self, false, peerUid, "123123", roomId)`
→ `SendChatMsg` → `__sendToRoom(roomId, "123123", extra, nil, 0, nil)` →
`IsStrEmoji("123123")` → `IsSticker(0)`.

## Room ids

Same as `chat.md §2`. The tool builds a DM room from the peer uid:

```
DM        custom_<peerUid>_<selfUid>_v2      peer FIRST, self SECOND
World     country_<server>
National  custom_lang_<lang>_<server>
Alliance  alliance_<serverId>_<allianceId>
```

`selfUid` comes live from `ChatInterface.getPlayerUid()` (here 1522777203000972,
server 935). EleNita's uid is 1697234600000972.

## Emoji — inline PUA glyphs

Emoji are **not** a separate field; they are Private Use Area characters
(U+E000–U+F8FF) sitting inside `msg`. The picker inserts one PUA glyph per emoji.

`DataCenter.ChatEmojiTemplateManager:GetEmojiDataById(id)` returns
`{id, name, path, sort, category}` where **`name` is the PUA hex stem**:

```
101 -> e006   (U+E006)     104 -> e008     107 -> e00d
102 -> e01c                105 -> e007     108 -> e033
103 -> e01e                106 -> e036
```

So emoji id `101` → `chr(0xE006)`. `tools/chat_send.py` resolves `{e:<id>}` tokens
in `--text` to these chars live before sending. `GetShowEmojiList()` enumerates the
available ids.

## Stickers — their own manager entry

Stickers are **not** text. They ride:

```
ChatEmojiTemplateManager:TrySendSticker(roomId, stickerId)
```
(`.../DataCenter/ChatEmojiManager/ChatEmojiTemplateManager.lua:409`; param order
confirmed by the same hook probe.)

`GetStickerDataById(id)` returns `{id, name, type, para1, para2, frame_rate,
unlock_goods, link_decoration_id, sticker_name, sort}`; `GetShowStickerList()`
enumerates ids (e.g. `5 dice`, `6 sticker/map_like`, `35
sticker/zyf_shengdanjie_biaoqing_icon`).

## Headless mode — confirmed

Sending does **not** need the chat UI. `ChatManager2` is an always-loaded
singleton and `__sendToRoom` fires the wire commands directly, with no dependency
on the `UIChatNew_v2` window. Verified live against EleNita
(`custom_1697234600000972_1522777203000972_v2`):

| Send | Chat window | Result (via `tools/chat_reader.py`) |
|---|---|---|
| `тест`  | open   | echoed back `is_mine=true`, `seq_id=123` |
| `тест2` | **closed** (`UIManager:IsWindowOpen("UIChatNew_v2") == false`) | echoed back `is_mine=true`, `seq_id=124` |

The monotonic `seq_id` bump (123 → 124) proves each was a real server send, not a
local echo. So the tool works fully headless — closed dialog, no focus, no pixels.

## Tooling

- `tools/lib/lua_actions.py` — `chat_send_text(room, msg)` / `chat_send_sticker(room, id)`
  recipes (msg rebuilt byte-for-byte via `string.char`, so Cyrillic/CJK/PUA survive
  the daemon hop and xLua compile).
- `tools/chat_send.py` — CLI: `--to <peerUid>` (DM) or `--room <id>`, `--text`
  (with `{e:<id>}` tokens), `--sticker <id>`, `--coords` / `--my-base`
  (see [`chat-coord-share.md`](chat-coord-share.md)), `--dry-run`,
  `--list-emoji`, `--list-sticker`. Runs through the warm daemon; no pixels, no
  foreground input.

Outgoing chat cannot be unsent — `--dry-run` previews the resolved room id and
payload first.

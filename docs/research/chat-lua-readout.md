# Reading world / national / alliance chat from the game's Lua VM

Companion to [`chat.md`](chat.md). That document proves the **transport** split;
this one covers how to actually **read the broadcast messages** that `chat.md`
showed are unreachable by passive capture.

## The problem restated

- The live broadcast firehose (world / national / alliance) rides a dedicated
  **TLS WebSocket** (`lastwar-chat-wss-*`), not the plain-TCP `:17935` game leg.
- Passive capture (`tools/lastwar_proto.py`, `tools/chat_monitor.py`) therefore
  only ever sees chat **control** on `:17935` (DM send/ack, room registry,
  map-object shares). It can never see broadcast message text.
- A TLS keylog / MITM against the WSS is out of project policy.

So the earlier worker who said "broadcast chat is TLS WSS, passively unreadable"
was **correct**. The premise that "chat is multiplexed over the single game TCP
connection" is the *old, overturned* claim (see `chat.md` §1 correction).

## The route that works: read after the client decrypts

The client is xLua-driven and we already own a live-Lua channel (the warm daemon,
`tools/lua_daemon.py`; see `project_xlua_dostring_live` and
`game-launch-and-scene-control.md`). The WSS payload is decrypted **inside the
game** and materialised as Lua `ChatMessage` objects. We read them there — no
MITM, no keylog.

### Chat data model (verified live 2026-07-27)

Every message is an instance of the Lua class **`ChatMessage`**.

Data fields (raw):

| field | meaning |
|---|---|
| `msg` | message text (plain messages). For special post types the text is in `attachmentMsg`. |
| `attachmentMsg` | attachment / rich payload text |
| `roomId` | room (see `chat.md` §2 for the `country_` / `custom_lang_` / `alliance_` / `_v2` shapes) — property via getter |
| `senderUid` | sender uid (string) |
| `seqId` | per-room monotonic sequence id |
| `serverTime` | server send time (epoch ms) |
| `post`, `type` | message/post-type discriminators (e.g. `post=611` = an attachment/interactive message) |

Getter methods (call `m:getX()`):

`getSenderName`, `getSenderInfo`, `getSenderNameWithAlliance`, `getMessageParam`,
`getServerTime`, `getCreateTime`, `getExtra`, `getMediaInfo`, `getSeqId`,
`getEmojiList`, `isMySendChat`, `GetTranslateState`, …

`getSenderInfo()` returns a profile table with, among others:
`allianceSimpleName`, `allianceId`, `allianceRank`, `serverId`, `lang`,
`gmFlag`, `headPic`, `headPicVer`, `title`, `titleSkinId`, `name`.

**Non-ASCII caveat.** `CS.UnityEngine.Debug.LogError` (our daemon read-back
channel) mangles raw UTF-8 in `Player.log`. Hex-encode any string in Lua before
logging it (`s:gsub('.', fn)` → `%02x`) and decode in Python — this survives
Cyrillic/CJK intact. `CS.System.Convert.ToBase64String(...)` did **not** work
through the daemon; the manual hex path does.

### Where the messages flow (the hook points)

There is **no persistent per-room message store in `DataCenter`** — a depth-5
scan of all 531 managers found zero `ChatMessage` tables. The current backlog
lives in the C# chat-view scroll (userdata, not Lua-reachable). What *is*
observable from Lua is the **ingress**, while the chat window is open:

- `DataCenter.ChatViewTipBubbleDataManager:OnGetNewChatMsg(...)` — new message in
  the **currently-selected** room (render path).
- `DataCenter.ChatViewTipBubbleDataManager:UpdateOnNewMessage(chatMessage)` — new
  message in a **non-selected** room (tip-bubble path). **Proven**: captured 11
  live alliance `ChatMessage`s here on chat-open (roomId `alliance_935_…`,
  `alliance=TLou`, `lang=en`, real `seqId`/`serverTime`/`senderUid`).
- `ChatMessage:onParseServerData(...)` — class-level parse; fires for every
  message regardless of UI routing (broadest hook; bind it off any live
  `ChatMessage` instance's `_class_type`).

Hooking is non-destructive: wrap the method, `pcall` the recorder, always call the
original.

### Hard constraints

1. **The chat window must be open.** The client only subscribes to / processes
   the WSS stream while the chat UI is up. With it closed, none of the hooks fire
   and nothing arrives. `tools/chat_reader.py` opens it via
   `GoToUtil.OpenChatView()`.
2. **Live-forward only.** Capture starts when the hook is installed. The client
   replays recent backlog through the hooks only on the **first** chat-open of a
   game session (`TryInitAllRoomData`); a mid-session re-open, room re-select, or
   a forced `TryInitAllRoomData()` does **not** re-emit cached messages (it pulls
   fresh server data instead). So a monitor sees new messages, not old ones.

## Tool

`tools/chat_reader.py` (run under the Windows Python, warm daemon + game alive,
chat window kept open):

```bat
C:\Python312\python.exe -u tools\chat_reader.py --seconds 300 --out results\chat.jsonl
```

It installs the three hooks above, opens the chat window, then polls a Lua ring
buffer every few seconds and emits one decoded JSON record per message
(`room_id`, `chat_type`, `seq_id`, `server_time`, `sender_uid`, `sender_name`,
`alliance`, `lang`, `msg`, `attachment_msg`, …). It de-dupes by
`(room_id, seq_id, sender_uid, msg)`.

## Open follow-ups

- **On-demand backlog.** Reading the full on-screen history without waiting for
  live traffic needs the C#-side ChatView scroll data source, or a hook on the
  message-**cell** bind (re-binds as you scroll). Neither was reached from Lua in
  this pass — the cell-bind hook is the recommended next step.
- **`getMessageParam`** takes an argument we didn't supply (returned nil bare);
  worth mapping for rich-message rendering.
- **`post` / `type` catalogue** — only `post=611` (attachment) sampled so far.

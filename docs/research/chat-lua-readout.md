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
lives in the C# chat-view scroll (userdata, not Lua-reachable). The reliable
ingress is the **class-level parse**, and that is the only hook the tool uses:

- **`ChatMessage:onParseServerData(...)`** — class-level parse; fires **exactly
  once** for every message regardless of room / UI routing (world / national /
  alliance / DM), and **whether or not the chat window is open** (the client
  parses the stream either way). Bind the class table **directly from
  `package.loaded["Chat.Model.ChatMessage"]`** — always loaded, so the hook
  installs on a fresh session with no captured instance yet. This single hook is
  sufficient and duplicate-free.

The two UI-routing handlers
(`DataCenter.ChatViewTipBubbleDataManager:OnGetNewChatMsg` / `UpdateOnNewMessage`)
were an earlier approach. **Do not use them**: they only fire while the chat view
is open, DMs route through `ChatPrivateDataManager` instead so they never see
"личка", and they fire *in addition* to `onParseServerData` for the same message
→ duplicates. An even earlier bug reached the class off a live instance's
`_class_type` via a never-set `_G.__LASTCHAT` global, so the class hook never
bound at all.

Hooking is non-destructive: save the pristine method once, rebuild the wrapper
from it on each install (idempotent, no growing wrapper chain), `pcall` the
recorder, always call the original.

### Reading the text — getters, not raw fields

- **`getMsg()`** is the base text. For attachment / interactive posts (coord
  shares `post=404`/`13`, invites, …) it is just a `"?"` placeholder. **Use
  `getMessageWithExtra()`** as the fallback there — it renders the full string,
  e.g. `[<ALLY>] <Player3> (BZ #100 X:602 Y:404)` — author, alliance and
  coordinates already formatted. (There is no `attachmentMsg` data field; the old
  code read it and always got empty.)
- **Local emoji** are Private Use Area glyphs (U+E000–U+F8FF) sitting inline in
  the text; they show as broken boxes. Replace with a readable token (`[e:E001]`).
- **Rich inline objects** arrive as `<lwSticker:N:>` / `<lwPhoto:N:>` /
  `<lwEmoji:N:>` markers → normalise to `[sticker:N]` / `[photo:N]` / …
- **`isMySendChat()` is unreliable** — it read `false` on some of the sender's own
  echoes. Don't dedup on it (see below).

### Hard constraints

1. **Timestamp from `serverTime`, not parse time.** Tag each record with the
   message's own `serverTime` (epoch ms), never `time.time()`: scrolling up
   re-parses old history through the hook "now", so a parse-time stamp sorts
   ancient messages to the bottom.
2. **Drop the optimistic echo.** Your own outgoing message is parsed twice — an
   optimistic local copy with **no `seqId`** yet, then ~1 s later the
   server-confirmed copy with a real `seqId`. Every genuine broadcast carries a
   positive `seqId`, so dropping the `seqId`-less copy removes the duplicate with
   no loss.
3. **The LISTENER is live-forward only** — the hook starts hearing when it is
   installed, so it sees new messages and not the backlog. **The BACKLOG is a
   separate read and it exists (#2064):** this file used to say the client keeps no
   persistent store of messages, and that is wrong. The client holds its own per-room
   copy in `Chat.ChatInterface.getRoomMgr().roomDatas[<room>].msgs`, filled by the very
   parse the hook wraps — measured live on one account: **7 rooms, 291 messages held**,
   every one of them with a `uid`, a `seqId` and its own `serverTime`; 254 had plain
   text and the rest were attachment posts, which read through `getMessageWithExtra`.
   `READ_CHAT` (docs/dsl.md) and `actions/read_chat_history.md` read that copy, once, on
   a press. It asks the SERVER nothing. `ChatController.ChatRoomRequestHistoryMsg` would
   fetch DEEPER than what is held and `Chat.Controller.ChatDBManager`
   (`QueryLatestChat` / `QueryChatByTime`) is the client's own on-disk base — neither is
   touched, on purpose: the first is a background question to the server, and the second
   has not been needed while the held copy answers.
4. **UTF-8 stdout.** Chat is UTF-8 (Cyrillic / Arabic / CJK / emoji). The Windows
   console the reader runs under defaults to a legacy codepage (cp1251), so a raw
   `print()` of a foreign message raises `UnicodeEncodeError` and kills the whole
   capture mid-stream — the classic "nothing shows up" symptom. `chat_reader.py`
   forces `sys.stdout/stderr` to UTF-8; keep that if you refactor.
5. **nil-safe drain.** The Lua→Python read-back line concatenates record fields;
   guard every field against `nil` and wrap each line in `pcall`, or one
   malformed record aborts the whole drain loop and silently drops every message.

## Tool

`tools/chat_reader.py` (run under the Windows Python, warm daemon + game alive —
the chat window does **not** need to be open):

```bat
C:\Python312\python.exe -u tools\chat_reader.py --seconds 300 --out results\chat.jsonl
```

It installs the single class hook, then polls a Lua ring buffer every few seconds
and emits one decoded JSON record per message (`ts` from serverTime, `room_id`,
`chat_type`, `seq_id`, `server_time`, `sender_uid`, `server_id`, `sender_name`,
`alliance`, `lang`, `is_mine`, `msg`, …). It drops seqId-less optimistic echoes
and de-dupes by `(room_id, seq_id, sender_uid, msg)`.

## Rendering emoji / stickers / photos in the panel

`chat_reader.py` normalises rich objects to tokens (`[e:E006]`, `[sticker:35]`,
`[photo:429]`). The panel turns those back into inline images via
`tools/chat_assets.py` (token → local PNG) rendered in a `tk.Text` widget.

Asset sources (discovered live from `DataCenter.ChatEmojiTemplateManager`):

- **Local emoji** — the config lists 81 emoji whose sprite stem *is* the PUA
  codepoint (`e006` == U+E006 == `[e:E006]`). The individual PNGs
  (`Assets/Main/Sprites/UI/LWChatEmoji/Default`) sit in a bundle that only
  downloads when the in-game emoji picker opens, so instead we crop them from the
  **`lwEmoji` TMP sprite atlas** — always cached (chat renders emoji from it). The
  TMP MonoBehaviour carries `m_SpriteCharacterTable` (unicode→name) +
  `m_SpriteGlyphTable` (glyph→atlas rect); crop the `lwEmoji` Texture2D by each
  rect (flip Y: Unity is bottom-left). `tools/extract_chat_assets.py` does this.
- **Stickers** — `GetStickerDataById(id)` gives `name` (resource stem, e.g. 35 →
  `zyf_shengdanjie_biaoqing_icon`), plus `para1`/`para2`. The textures under
  `Assets/Main/TextureEx/UIStickerDynamic` are animation **spritesheets** (grids
  of 128×128 cells — dice 512×512 = 4×4, S3_1 512×1024 = 4×8); scaling the whole
  sheet is unreadable, so crop the first cell `(0,0,128,128)` as a static
  thumbnail. The map-emote stickers (`map_like`, …) have no standalone sprite:
  `para1` names a shared MapSticker atlas and `para2` is the frame index into its
  128×128 grid — crop that cell. Both handled by `extract_chat_assets.py`; the
  full id→stem/para map is dumped to `tools/data/chat_assets_map.json`. A few
  stickers whose bundle is uncached fall back to the `[sticker:N]` token.
- **Photos** (`[photo:N]`, `N` = `picVer`) — user-uploaded images. The URL builder
  `Chat.ChatInterface.getCustomPicUrl` delegates to a native `GetCustomPicUrl`
  (needs the runtime `device` global; not callable statically from Lua) — but that
  is **not needed**: the client caches every chat photo on disk, keyed
  deterministically (verified live against `SendPhoto.SetUILoadedSuccessShow`,
  which is handed `<uid[-6:]>/<hash>.jpg`):

      <LocalLow>/FunFly/Last War-Survival Game/ChatPhotos/<uid[-6:]>/<md5(f"{uid}_{picVer}")>.jpg

  (`..._big.jpg` = the full-size copy, present only once opened fullscreen). So
  `chat_assets.photo_path(uid, picVer)` resolves the real JPG with no game call —
  the panel renders it inline. Only photos the client hasn't downloaded yet fall
  back to a `🖼 фото` placeholder.

Run once to populate `results/chat_assets/{emoji,sticker}/`:

```bat
C:\Python312\python.exe tools\extract_chat_assets.py
```

- **Avatars** — the sender's avatar is cached under the *same* ChatPhotos scheme
  as a message photo, keyed by `md5(f"{uid}_{headPicVer}").jpg`. `chat_reader.py`
  now emits `head_pic` (head-frame id) and `head_pic_ver` (the version) from
  `getSenderInfo()`, and `chat_assets.avatar_path(uid, headPicVer)` resolves the
  JPG with no game call. The panel draws it inline (20 px) before the nickname; a
  built-in head frame with no uploaded avatar has no cached file and simply renders
  nickname-only.

### Panel history & lazy-load

The panel persists chat to a **per-character** SQLite store,
`<profile>/chat_history_<uid>.db` (`panel/chat_history.py`): history belongs to the
character, not the account — one account can hold several characters with different
uids and their chats must not mix. The current character's uid is read live from
the game (`ChatInterface.getPlayerUid()` via `chat_share.self_profile`) when the
chat monitor starts, and the matching file is opened then; if the uid cannot be
read (game not alive) the tabs stay empty until it can. Every message the monitor
sees is written to that file as it arrives — table `messages(id, ts, uid, name,
text, room, chat_type, raw_json)`, idempotent on `(room, uid, ts, text)`. The raw
`<profile>/chat_log.jsonl` the reader still writes (`chat_reader --out`) is kept as
the account-wide raw capture log; it is **not** auto-imported into a per-character
store (it cannot be split by character reliably), so per-character history builds
forward from first use.

Lazy-load reads out of the store, never the whole log: on startup each tab loads
only its newest **page** (`CHAT_PAGE = 100`) into memory and renders it; a scroll
to the top — or a click on the "↑ show earlier messages" header — pages the
previous chunk in *from the store*, prepended and top-anchored so the reader stays
put. A live message only appends (and is written straight to the store); the view
auto-scrolls to the newest line only when the reader is already at the bottom. The
in-memory list is capped (`CHAT_MSGS_MAX`) — overflow is dropped from memory but
stays in the store, reachable again by scrolling up.

The sender avatar is drawn inline (20 px) before the nickname, resolved from the
ChatPhotos cache (see above); a sender with no cached avatar gets a neutral
head-and-shoulders placeholder rather than a blank.

The **DM tab is a contact list beside one conversation**. The list has one entry
per DM peer, built from the store (`dm_contacts`): avatar, name, last message and
its time, newest conversation on top. The peer of a room `custom_<a>_<b>_v2` is the
uid that is not ours (`dm_peer_uid`); the name/avatar come from the peer's own most
recent message. Clicking a contact opens **only** that peer's thread — the
conversation view is filtered to that room and pages just that room on scroll-up
(`recent_room` / `older_room`). A live DM always refreshes the contact list; it is
appended to the conversation only when it belongs to the peer currently open, and
otherwise bumps that contact's unread count. This is DM-only — world/alliance/
national rooms are still one stream per tab.

### The phone draws the same history as a conversation

The web front-end does not list the chat — it **draws** it (#2064). The tab's screen
says `map: {kind: "chat"}`, the same door the world map goes through, and
`panel/web/app/src/views/ChatView.tsx` paints a pane that reads oldest-at-the-top with
the box to answer in underneath: «интерфейс чата как в телеграм». The channel cards are
still sent and are marked `drawn`, so a front-end that does not know the kind still
shows the newest messages as an ordinary list.

Every page comes off `/api/screen/data?kind=page` — `web_data` in `panel/tabs/chat.py`,
answered from **this profile's own SQLite store on an HTTP worker thread**, forty rows at
a time with `more` saying whether anything is above. Nothing on that path touches the
game, so a thumb flicking upwards cannot become a stream of questions to the server; when
the store runs out the page says so, and only THEN is the server asked (below). The
scroll is held in place across a prepend — the pane's
height is measured before the rows go in and the same distance is added back to
`scrollTop` — and a new message pulls the view down only when the reader was already at
the bottom, exactly as the window's own view behaves.

Whose history is being paged is the tab's own `chat_uid`, read live from the game and remembered in its saved block. A freshly started panel has neither, and asking the game who is logged in is exactly what a page of history must not cost — so where the profile holds exactly ONE `chat_history_<uid>.db` that file names its own character and is opened read-only. Two or more is left unanswered: a chat drawn under the wrong character's name is worse than an empty page.

A bubble carries the message's own `serverTime` as its stamp, and only «which day is
this» is judged against now (`tools/lib/game_clock.py`); an un-synced clock names the
date outright rather than guessing «вчера». Coordinates in the words are links, marked
server-side by `panel/web/coordlinks.py` so `tools/lib/coords.py` stays the one parser.
Photographs ride `/api/chatsprite?photo=<uid>&ver=<n>`; a tap opens the full-size copy in
the panel's one modal.

### Asking the SERVER for history older than the client holds

Everything above reads a copy that already exists. When a person keeps scrolling past
the end of both — the panel's store and the client's own per-room list — the words they
are looking for are on the server, and that is the one reading in the chat that costs a
round trip. The person asked for it in these words: «Опрос сервера при прокрутке тоже
сделай, если у нас нет сообщений» (#2064).

**The call.** `ChatManager2.Instance.Ctrl:ChatRoomRequestHistoryMsg(roomId, sort)` —
`Chat.Controller.ChatController`, reached through `package.loaded` (there is no global
`ChatController`, and `Chat.ChatInterface` is a loaded module too). `debug.getlocal`
names the parameters `self, roomId, sort`; the source is `ChatController.lua:528-541`.

| what | measured live, 2026-08-29, on the world room |
|---|---|
| `sort = 0` | the BACKWARDS direction — 100 messages per call: the room held 47, then 148, then 248, `GetFirstMsgServerTime()` walking back 1787963199672 → 1787949750850 |
| `sort = 1` | brings nothing at all — the forward direction with the client already at «now» |
| the cursor | belongs to the CLIENT: every call means «what lies before the oldest I hold», so a second call fetches the slice before the first and never the same one twice |
| the end | `roomData:GetIsChatHistoryEnd()` — the server's «that is all there was», remembered by the client per room. It answers with NO VALUE rather than `false` while the end has not been reached, so read it into a local before doing anything with it |

**The recipe** is `src/lastwar_bot/actions/fetch_chat_history.md`: it reads how many the
client holds, asks (only if the end does not already stand), waits, reads the count and
the end flag back, and finishes with the ordinary `READ_CHAT` — so what the server sent
travels home through the one decoder everything else uses and lands in the same store
under the same identity. `limit` is 400 rather than the backlog's 40 for a reason:
`READ_CHAT` answers with the newest `limit` of each room, and a smaller number would
fetch the slice and then leave it unread.

**The rules the person set for it** are kept in `panel/tabs/chat.py::_ask_server_for_older`
rather than in the front-end, because that is where they cannot be forgotten: the store
is always read first (the phone reaches this only once a page has said `more: false`),
the ask rides a person's SCROLL and never a clock, `_deep_busy` holds the room for the
length of the round trip so one scroll makes one request, and `_history_end` is the
panel's copy of the game's per-room end — once it stands the page stops offering the
reading at all. The phone shows both states: a button that says it is asking and is
disabled while it does, and a line saying the history has ended when there is nothing
left to press.

Measured end to end through the phone's own door (`POST /api/screen/press`,
`action: older`): **8.7 s** for the first ask, `got: 92`, then 100, 100, 61 on the ones
after it — each one further back, none of them the same slice. The world history the
store could page went from 46 messages to 400 across ten pages, back to the previous
afternoon.

### Emoji / sticker picker

The send box has an emoji/sticker picker (the "😊" button). It is drawn entirely
from the sprites `tools/extract_chat_assets.py` already extracts — no game call to
open it: `chat_assets.emoji_catalogue()` and `sticker_catalogue()` list the emoji
(id + PUA hex + png) and stickers (id + png) that have a sprite on disk. Picking an
**emoji** drops a `{e:<id>}` token into the message box at the caret; `chat_send`
resolves it to the inline PUA glyph on send. Picking a **sticker** sends it as its
own message (`chat_send --sticker <id>` → `ChatEmojiTemplateManager:TrySendSticker`)
— the game does not let a sticker ride alongside text, so it is one sticker per
message, not an `attachmentId` on a text post.

## Open follow-ups

- ~~**On-demand backlog.**~~ Answered twice over (#2064): `READ_CHAT` reads the copy
  the client holds, and `fetch_chat_history` asks the server for what lies before it.
  Neither needed the C#-side scroll data source or a cell-bind hook.
- **`getMessageParam`** takes an argument we didn't supply (returned nil bare);
  worth mapping for rich-message rendering.
- **`post` / `type` catalogue** — only `post=611` (attachment) sampled so far.

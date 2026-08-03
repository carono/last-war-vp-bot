# Last War chat system — protocol notes

Derived by passive capture only (no injection, no MITM). Reference decoder:
`tools/lastwar_proto.py`. This file focuses on chat, system broadcasts and the
social feed; it complements the wire spec in [`protocol.md`](protocol.md).

```bash
python tools/lastwar_proto.py capture.pcapng --grep chat        # chat frames only
python tools/lastwar_proto.py capture.pcapng --timeline         # every frame, timestamped
python tools/lastwar_proto.py capture.pcapng --json out.json    # full transcript
```

## 1. Transport — chat is SPLIT across two connections

> **Correction (active capture, 2026-07-22).** An earlier passive-only pass
> concluded "chat is not a separate connection." A live investigation — driving
> the running client, enumerating every TCP socket of `LastWar.exe`, and
> capturing all of them — proved that is only half true. Chat is **split**: a
> plain-TCP part on the game gateway and a **dedicated TLS WebSocket** for the
> live broadcast stream. Details below; raw evidence in
> [`chat-active-capture.md`](chat-active-capture.md).

The client keeps **two** chat-carrying sockets alive at once:

**A. Game gateway — `…:17935`, plain TCP, the `lastwar_proto.py` binary protocol.**
The accelerator IP varies per session (`<server-ip>`, `<server-ip4>`, … —
dialled bare, no DNS). This connection carries chat **control and low-rate**
traffic only:
- `common.chat.room.id` — the room registry (returns `country_<server>`,
  `custom_lang_<lang>_<server>`),
- `lw.user.push.chat.msg` + `chat.stat` — **direct-message** send and its ack,
- `chat.get.system.mails`, alliance-social RPCs (`al.show.help`,
  `alliance.notice.*`, `get.alliance.share.mission.list`),
- game notifications (`push.all.notice`, `push.new.news`, `push.al.help.*`) and
  occasional chat events (a chat **gift** was seen here as `push.chat`).

**B. Chat WebSocket — `lastwar-chat-wss-us-{aws,gcp,ali}-ali.lastwargame.com:443`,
TLS (WSS).** A **separate, dedicated, multi-cloud** endpoint established at
login and held open persistently. This is where the **live broadcast firehose**
(world / national / alliance message stream) flows. Because it is TLS it does
**not** passively decode — but the SNI names it outright, and the split is
proven by elimination (see below).

**The decisive evidence:** during ~3 min with the world-chat ticker visibly
scrolling fast, the `:17935` stream carried **zero** broadcast `push.chat`
frames — only the DM send/ack and room registry. Meanwhile the WSS
(`<server-ip6>:443`, `…-gcp-ali`) was established at login and streamed
steadily the whole time (a ~55 KB burst when chat tabs were opened = history
load, then a continuous ~2–4 KB / 15 s live trickle). The client was clearly
receiving world chat, and it was **not** arriving on `:17935` → it arrives on
the WSS.

**Why it "drops while the game runs":** the WSS is multi-cloud and the client
**fails over** between providers. In the capture the Alibaba endpoint
(`<server-ip7>`, `…-us-ali`) was dropped after ~17 s and the client settled on
the GCP one — a chat socket dying independently of the game socket is exactly
the behaviour the task premise described. The old note blaming only a
"translation service" was wrong; the real separate connection is the chat WSS.

Other genuinely separate endpoints seen in the same capture (none carry the
in-band binary protocol, all TLS):

| SNI | Role |
|---|---|
| `lastwar-chat-wss-us-{aws,gcp,ali}-ali.lastwargame.com:443` | **Live chat WebSocket** (broadcast stream), multi-cloud failover |
| `lastwar-serverlist-us-{aws,gcp}-ali.lastwargame.com:443` | Server/gateway list (shares IPs with the chat WSS) |
| `lastwar-fight-report.akamaized.net:443` | Battle-report / news images CDN (Akamai) |
| `lw-c-log.lastwarapp.net:443` | Client log/telemetry upload (Cloudflare) |
| `te-receiver.lastwar.com:443` | Telemetry event receiver (ThinkingData-style) |
| `<server-ip11>` / `129.226.x` on `:10012` / `:443` / `:80` | Tencent Cloud SDK stubs — connect at login, then idle (~300 B); **not** chat |

## 2. Rooms and chat types

There is no per-type endpoint — every chat type is just a **`roomId` string** on
the same commands. Room ids are handed to the client by `common.chat.room.id`
at login (and by `open.red.packet` for the alliance room). The four types the
game UI exposes map to id shapes as follows:

| UI chat type | `roomId` shape | Example |
|---|---|---|
| **World / cross-server** | `country_<server>` | `country_100` |
| **National / language** | `custom_lang_<lang>_<server>` | `custom_lang_ru_100` |
| **Alliance (clan)** | `alliance_<serverId>_<allianceId>` | `alliance_935_3d4b9dee…` |
| **Personal (DM)** | `custom_<peerUid>_<selfUid>_v2` | `custom_1640…_1595…_v2` |

`chat.stat` also carries a numeric `type` field that mirrors the channel, but
the authoritative discriminator is the `roomId` prefix above.

## 3. Message shapes

Three distinct frame families carry actual chat text; which one you see depends
on direction and channel.

### 3.1 Sending a message — two commands fired together

A send is **two commands acked by `_id`**:

| Command | Key fields |
|---|---|
| `lw.user.push.chat.msg` | `uid` (the **peer**, not the sender), `msg`, `roomId` |
| `chat.stat` | telemetry twin — `sendTime`, `type`, `roomId`, `msg`, `msgExtra` |

`msgExtra` holds `srcLang`, `senderLevel`, `post`, `atUids`, `atPlayers`,
`isSendEmoji`. The ack echoes the request and adds `_mt` (server send time) and
`_time`. Note `msgExtra.atUids` sometimes arrives as the literal string
`"table: 00000003588EF170"` — a Lua table stringified by mistake in the client,
which incidentally confirms the game logic is Lua.

A DM sent *by* the captured client only shows as the request plus its ack; the
broadcast goes to the recipient's client, so we never see our own outgoing DM as
a `push.chat`.

### 3.2 Receiving a broadcast — `push.chat`

Unsolicited server push carrying an incoming message or a chat-embedded event.
Fields: `msg`, `senderUid`, `senderName`, `senderPic`, `senderPicVer`, `type`,
`post`, `gmFlag`, `standardMsg`, `time`, `seqId`, `customJsonParam`.

`customJsonParam` is a nested JSON string with the full sender/target profile
(uid, name, country, alliance id/name/abbr, head skin). A `senderUid` of
`"system"` with `gmFlag: 1` marks a system/GM message rather than a player one.

Observed variant — a **chat gift** (`type: 0`, `senderUid: "system"`): the
`customJsonParam` describes the gift (`itemId`, `giftExtraItemId`, `num`,
`chatGiftUuid`), the giver (`senderInfo`), the recipient (`targetInfo`), and a
free-text `context` — the message the sender typed alongside the gift.

### 3.3 Sharing a map object into chat — `chat.room.send`

A player can attach a map object; the attachment is a **JSON string** inside
`attachmentId` — the cleanest object description the protocol offers, since the
client has already resolved what the object is.

| Command | `posType` | Object |
|---|---|---|
| `chat.room.send` | 2 | monster |
| `chat.room.send` | 5 | resource mine |
| `chat.room.send` | 6 | mine with an active gatherer (`uname` = `"Collector: [TAG]name"`) |
| `hero.dispatch.share.chat` | 22 | secret task / hero dispatch |

Common fields: `x`, `y`, `sid` (server), `olv`, `oname`, `worldId`, `worldType`.
`hero.dispatch.share.chat` adds `cfgId`, `uuid`, `dispatch`. `oname` is not one
type — an integer template id for a mine, a `"LLVV"` string for a monster, a
localised name for a task; any consumer must tolerate all three. See
[`protocol.md`](protocol.md#chat) for the tile-coordinate caveat.

> **The client-side view of the same feature** — how a shared coordinate is
> modelled (`post = 13`, `msg = "?"`, the `attachmentId` blob), which `posType`
> values were observed live, and how to *send* one — is written up in
> [`chat-coord-share.md`](chat-coord-share.md). Note the send does **not** go
> through the text choke point `ChatManager2:__sendToRoom`.

## 4. System broadcasts and the social feed

These are game notifications that surface in or beside chat. All arrive on the
same connection as unsolicited pushes.

| Push / command | Dir | What it is |
|---|---|---|
| `push.all.notice` | ← | Server-wide banner. `id` = localisation template, `params` = fill-ins. |
| `push.new.news` | ← | World battle-report feed item (`bigType`, `smallType`, `dataObj` with atk/def sides, powers, ranks). |
| `get.world.news.info` | → | Client pulls the news list (`_id` cursor) → `newsInfo`, `areaInfo`. |
| `push.al.help.new` / `.update` | ← | Alliance help request (`helpId`, `senderId`, `itemId`, `level`, `nowcount`/`maxcount`, `queueType`). |
| `push.alliance.reward.new` | ← | Alliance gift / mail red-point (`giftInfo`, `allianceNewMail`, `redPoint`). |
| `push.lw.alliance.alert.info.create` / `.remove` | ← | Alliance map-alert markers (`info`, `uuid`). High volume — 120 removes in one 3-minute trace. |

### `push.all.notice` templates seen

`id` indexes a client-side localisation string; `params` are substituted in.

| `id` | Meaning | `params` |
|---|---|---|
| `15502` | King appointed a player to a throne position | `kingName`, `targetName`, `positionId`, `kingPositionId` |
| `31103` | Kill-streak announcement | `name`, `killNum`, `uid`, `pointId`, `serverId`, `allianceInfo{…}` |

The numeric `id` set is open-ended — treat unknown ids as "system notice, text
resolved client-side" rather than failing to parse.

## 5. Capturing chat

1. **Capture ALL of the client's sockets, not just `:17935`** — chat is split
   (§1). Enumerate them first with `netstat -ano | findstr <LastWar-pid>` (or
   `tools/find_lastwar_connections.ps1`), then `dumpcap` broadly and post-filter.
   The `:17935` leg decodes; the WSS leg is TLS and only shows as SNI + volume.
   Full worked example: [`chat-active-capture.md`](chat-active-capture.md).
2. `python tools/lastwar_proto.py <cap>.pcapng --grep chat` for the plain-TCP
   chat control frames, or `--timeline` and grep `chat|notice|news|help|share`.
   Extract the game leg first: `tshark -r cap.pcapng -Y "tcp.port==17935" -w game.pcapng`.
3. Name the TLS legs by SNI:
   `tshark -r cap.pcapng -Y "tls.handshake.type==1" -T fields -e ip.dst -e tls.handshake.extensions_server_name` —
   look for `lastwar-chat-wss-*` (the live broadcast socket).
4. To see all four chat types you must actually visit each tab in-game during
   the capture (`tools/_chat_recon.py` drives focus/click/screenshot). Room ids
   are only announced (`common.chat.room.id`) around login and when a room is
   first opened; a capture that starts mid-session shows messages but not the
   handshake.

## 6. Open questions

- **WSS wire format** — the `lastwar-chat-wss-*` broadcast leg is TLS, so its
  payload (WebSocket JSON? protobuf? same TLV as `:17935`?) is not passively
  decodable. Would need a TLS keylog / MITM, which project policy rules out.
- **Outgoing world/alliance send path** — only a DM send was captured on
  `:17935`; whether a world/alliance send goes out on `:17935`, the WSS, or both
  is unconfirmed (posting to those rooms is visible to other players).
- **`chat.stat.type` numeric values** — not yet mapped to the four room types;
  `roomId` prefix is the reliable discriminator meanwhile.
- **Full `push.all.notice` id catalogue** — only a few templates seen; the rest
  need a longer capture or the client string table.

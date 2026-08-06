# Last War wire protocol — specification

Derived by passive capture only (no injection, no MITM, no cert tampering).
Reference decoder: `tools/lastwar_proto.py`. Validated against
three saved captures plus several hours of live decoding: **every frame of
every reassembled game stream parses — 100% of bytes consumed in both
directions, zero unknown tags.** The command vocabulary stands at **220**, and
live observation kept extending it long after the saved captures stopped
yielding anything new.

```bash
pip install scapy zstandard
python tools/lastwar_proto.py capture.pcapng                  # survey + summary
python tools/lastwar_proto.py capture.pcapng --survey-only    # just the flow map
python tools/lastwar_proto.py capture.pcapng --timeline       # every message, timestamped
python tools/lastwar_proto.py capture.pcapng --grep chat      # filter by command
python tools/lastwar_proto.py capture.pcapng --json out.json  # full transcript
```

## 1. Transport and endpoint map

Custom binary over **plain TCP — no TLS**. Observed endpoint
`<server-ip>:17935` (AWS Global Accelerator). The client dials the accelerator
IP directly with **no preceding DNS lookup**, so SNI/DNS filters will not find
it — filter by frame shape or port instead.

**And the port moves between builds** (#1053): `:17935` when this file was first
written, **`:10012` on the current client**. A capture pinned to the number
written down here hears *nothing*, which on screen is indistinguishable from an
idle account — the most expensive false lead this repository has produced. So the
port is **read off the running client**: `map_capture.detect_game_ports()` returns
the ports of its server conversations, and `LW_GAME_PORT` / `game_paths.game_port()`
answers only when there is no client to ask. Every capture tool does this by
default; `--port N` pins one and `--all-tcp` drops the filter entirely.

**Which of the client's conversations is the game is NOT decided here** — it is
`game_link`'s rule and there is one copy of it (`docs/research/server-link-status.md`).
The client talks to more than one server: the game on its own port, the chat /
control channel on another, plus a loopback pair to itself. They live and die
separately, and «this process has a live socket» says nothing about which.

### A wrong reading of this, twice in one night — recorded so it is not re-derived

Both were measured, both looked solid, and **both are wrong**:

* ❌ **«the port moved back to `:17935`»** (#1053, 2026-08-07 03:30). A client held
  six sockets on `:10012` and one on `:17935`; 25 s of capture on each found
  `:10012` delivering **0 packets with payload** and the lone `:17935` socket
  carrying nine alliance pushes. Read as «the gateway moved back».
  **Disproved 00:45 the same night**, by the same client's socket table: the six
  `:10012` sockets were **CLOSE_WAIT**, not established, and `game_link.probe()`
  said `link='lost', dead=6`. The live `:17935` socket was the **control channel**
  of a stranded client — precisely the state #1266 was bought with. When the client
  reconnected, `:10012` came back established and a 20 s capture on it carried
  alliance marches and alerts. **The game port is `:10012`.**
* ❌ **«the busiest port wins»** — the tie-break the first reading suggested. The
  busier port was the one carrying nothing, because those six sockets were the
  half-closed *losers of the gateway race*. Counting sockets measures how many the
  client has opened, never which one is answering.

What survives from the same measurements, and is used in the code:

* a capture filters on **every** conversation, including one whose sockets are all
  half-closed — that is where the client will come back after a reconnect, and a
  filter term that matches nothing costs nothing;
* anything that must point at exactly ONE socket (`steal_via_socket`) takes the
  conversation carrying the half-closed race losers — the game's signature — and
  refuses to answer at all when that conversation has no established socket. On a
  stranded client the honest answer is «there is nothing to send down», not the
  control channel's port.

Gameplay, alliance events and map queries all multiplex over this **single
connection**. Chat is only **partly** here: the game gateway carries chat
control (room registry, DM send/ack, system mails, notifications), but the
**live broadcast chat stream rides a separate, dedicated TLS WebSocket**,
`lastwar-chat-wss-us-{aws,gcp,ali}-ali.lastwargame.com:443` (multi-cloud, fails
over between providers, can drop independently of the game socket). Proven by
active capture — see [`chat.md`](chat.md) and
[`chat-active-capture.md`](chat-active-capture.md). Other auxiliary TLS services:
asset/battle-report CDNs, telemetry (`lw-c-log`, `te-receiver`) and a chat
**translation** service — none carry gameplay.

Two captures were analysed: capture A (173 s) and capture B (60 s, with
cross-server travel). The first showed no DNS at all for the game; the second
resolved three `lastwar` domains, so DNS is worth collecting even though the
main connection still dials a bare IP.

| Flow | Volume | What it is |
|---|---|---|
| **TCP `<server-ip>:17935`** | 23 KB up / 388 KB down | **The game.** Everything below decodes from this one connection. |
| TCP `<server-ip10>:80` | 14 KB up, 0 down | Tencent Cloud. Custom framing on port 80, not HTTP. Telemetry/SDK — undecoded, and it never gets a reply. |
| UDP `129.226.1.x:8081` | ~7 KB | Tencent Cloud SDK. High-entropy, undecoded. |
| UDP `<server-ip10>:137`, `<server-ip11>:137` | ~1.6 KB | NetBIOS-shaped `CKAAAA…` wildcard queries — SDK NAT-type probing. |
| UDP `<server-ip3>:50080` | 21 892 pkts, 10.9 MB | **Not the game.** Header `48000001` + counter + max-entropy body, 1444 B MTU cap — reads as a VPN/tunnel. See open questions. |
| UDP `192.168.1.x` | ~450 KB | LAN traffic, not the game. Their first byte is `0x80` by coincidence, which is why `classify()` refuses to call UDP "GAME". |
| TCP `lastwar-cdn.lastwarapp.net:443`, `lastwar-cdn.akamaized.net:443` | 55 KB / 53 KB down (B) | Asset CDN. TLS, not decoded, no gameplay. |
| TCP `lastwar-us-translate.lastwargame.com:443` | 4.5 KB (B) | **Chat translation** service. TLS. The only game-adjacent endpoint that is genuinely separate. |

Everything else in the capture is ordinary desktop TLS noise (IMAP, CDNs,
JetBrains, …).

## 2. Frame layout

Every frame starts with a 3-byte header. Frames are packed back-to-back in the
TCP stream and freely split across segments, so **reassembly is mandatory**.

```
+--------+------------------+---------------------------+
| flags  | uint16 BE length | body                      |
| 1 byte | 2 bytes          | `length` bytes            |
+--------+------------------+---------------------------+
```

The flag byte is a bitfield: **`0x20` = compressed**, **`0x10` = zstd** (clear
means zlib), high bits = direction.

Three flag bits describe the body; the remaining bits are the direction
(`0x80` server, `0xc4` client):

| Bit | Meaning |
|---|---|
| `0x20` | body is compressed |
| `0x10` | compression is zstd (with a 4-byte raw-size prefix), else raw zlib |
| `0x08` | length field is **uint32** instead of uint16 (large frames) |

| flags | Direction | Body |
|---|---|---|
| `0x80` | server → client | plaintext TLV |
| `0xb0` | server → client | zstd-compressed TLV |
| `0xb8` | server → client | zstd, uint32 length — used for the 340 KB `init` dump |
| `0xc4` | client → server | XOR-masked TLV |
| `0xe4` | client → server | XOR-masked, then **zlib**-compressed TLV |

Do not enumerate valid flag bytes — test them: `byte & ~0x38 == 0x80` for
server frames, `== 0xc4` for client frames.

The uint16 length sits at `pos+1`; with `0x08` set it is a uint32 at the same
offset, so the header grows from 3 to 5 bytes before any size prefix.

**The two directions compress differently.** Server frames use zstd and prefix
the body with a **4-byte big-endian uncompressed size**, then a raw zstd frame
(magic `28 b5 2f fd`); the header `length` counts the zstd bytes *excluding*
that prefix, so the full frame is `3 + 4 + length`. Client frames use raw zlib
(`78 da`) with **no size prefix** — and since client headers carry no length
either, the zlib stream's own end is what delimits the frame.

Order matters on the client path: the body is **masked first, compressed
second**, so a reader must unmask before inflating.

### Client frames

Client headers are 5 bytes and carry **no length field** — the TLV tree is
self-delimiting and defines the frame boundary:

```
c4  <uint16 serverId>  K2  K1   <masked TLV body>
```

Bytes 1–2 are the **serverId** (observed `0x03a7` = 100), not a length. `K1`
and `K2` are the XOR mask key bytes, transmitted in the clear.

### The XOR mask

Applied to the client body only, indexed from the body start:

```
body[j] ^= K1   where j % 4 == 0
body[j] ^= K2   where j % 4 == 1
body[j] unchanged where j % 4 == 2 or 3
```

Both key bytes ship in the same header, so the mask is self-defeating —
obfuscation, not encryption. Sanity check: `body[0] ^ K1 == 0x12` (the map tag)
held for 113/113 client frames.

Worked example: masked `wo\x80ld.\x95et.\x90loc\x99` with `K1 = 0xf2` decodes to
`world.get.block`.

### Writing a client frame

`tools/lastwar_encode.py` is the mirror of the decoder. Encoding order is
**deflate, then mask** — the decoder unmasks before inflating, so the mask is
the outermost layer on the wire. (The sentence above, "masked first, compressed
second", describes the client's internal order and reads backwards as a wire
description; the encoder follows the decoder, which is what round-trips.)

The writer is verified against real traffic: `--verify` re-encodes every client
frame of a capture and diffs the bytes — **603/603 byte-exact** across both
saved captures, including the 4 zlib frames (compared by re-decoding, since
zlib output is compressor-dependent). That check needs the *tags*, which
`read_value()` throws away by collapsing four integer widths onto `int` and
decoding strings lossily, so the module carries its own tag-preserving reader.

`K1`/`K2` are free: 30 distinct pairs across 113 frames, so the client picks
them per frame and they carry no state. The header's `serverId` stayed 100 in
every frame of both captures — it is the account's **home** server, not the
server being acted on; a cross-server action puts its target in the params.

## 3. TLV value encoding

The body is one self-describing typed tree. A value is a 1-byte type tag
followed by a type-specific payload. All integers are **big-endian, signed**.

| Tag | Type | Payload |
|---|---|---|
| `0x01` | bool | 1 byte |
| `0x02` | int8 | 1 byte |
| `0x03` | int16 | 2 bytes |
| `0x04` | int32 | 4 bytes |
| `0x05` | int64 | 8 bytes |
| `0x06` | float | 4 bytes IEEE-754 |
| `0x07` | double | 8 bytes IEEE-754 |
| `0x08` | string | `uint16` length + UTF-8 bytes |
| `0x0a` | blob | `uint32` length + bytes (**contains protobuf**) |
| `0x0c` | int32[] | `uint16` count + count×4 bytes |
| `0x0d` | int64[] | `uint16` count + count×8 bytes |
| `0x10` | string[] | `uint16` count + count× (`uint16` length + UTF-8 bytes) |
| `0x11` | list | `uint16` count + count× self-typed values |
| `0x12` | map | `uint16` count + count× (`uint16` keylen, key, value) |

Tags `0x06`/`0x07` are inferred from the numeric progression and have not been
seen carrying a distinguishing value yet — treat as provisional. Every other
tag is confirmed: across all three captures the decoder consumes **100% of the
bytes of every reassembled game stream with zero unknown tags**.

> **Do not trust the "unknown TLV tags" block in a live summary as evidence
> that the protocol changed.** `unknown_tags` is a module-global counter bumped
> at the `raise BadTag` site in `read_value()`. `iter_frames()` catches that
> `BadTag`, discards the frame and resyncs to the next magic byte — but the
> counter has already been incremented. So every misaligned frame the decoder
> *rejects* still lands in the report, labelled as a format gap. `is_game()`
> already guards against exactly this (it saves and restores the counter around
> its probe); the resync path in `iter_frames()` does not.
>
> This is not hypothetical. `results/live_5min_run2.log` closed with ~20 tags
> each at almost exactly ×4 — that suspicious uniformity is the resync scan, not
> the game. The same tags reproduce from pure garbage:
>
> ```python
> # a valid server header pointing at a body whose first byte is a bogus tag
> frame = lambda b: bytes([0x80]) + len(b).to_bytes(2, "big") + b
> stream = b"".join(frame(bytes([t]) + b"\x00" * 6) for t in (0x28, 0xB5, 0x82, 0xF7))
> list(iter_frames(stream, "down"))   # -> [] : every frame dropped
> unknown_tags                        # -> {40: 1, 181: 1, 130: 1, 247: 1}
> ```
>
> Zero frames reached the caller, yet all four tags were reported as gaps. The
> clean 5-minute capture C — 260 real frames — printed **no unknown-tag block at
> all**, which is the actual signal. Before documenting a new tag, confirm it
> appears in a frame that *decoded*.

## 4. Envelope

Every body is a map with short single-letter keys:

```json
{"c": 1, "a": 13, "p": {"c": "world.get.block", "r": -1, "p": { …params… }}}
```

| Key | Meaning |
|---|---|
| `c` (outer) | channel / frame class — `1` for RPC, `0` for the keepalive |
| `a` | opcode group; `13` for RPC, `29` for the keepalive |
| `p` (outer) | envelope |
| `c` (inner) | **command name** (absent on keepalives) |
| `r` | request id, `-1` (`ffffffff`) when unused |
| `p` (inner) | command parameters / response payload |

Common payload keys: `_id` is a monotonic client sequence number, `_time` and
`timeStamp` are epoch milliseconds.

The keepalive carries `clientTime` / `serverTime` and no command name; it fires
roughly every 4 s in both directions.

## 5. Command vocabulary

Union of three captures — 42 distinct client commands. Still not exhaustive:
capture B added 29 commands that capture A never showed, and capture C added
another 9, so each new activity surfaces more. Responses echo the request's
command name.

**Capture C** — a 5-minute unattended live session
(`results/live_5min_run3.log`, 301 s, 7395 packets / 260 frames across 145
half-streams, one game endpoint `<server-ip>:17935`). Worth contrasting with
the map-panning capture in `results/live_5min.log`: with the map idle, traffic
collapses to keepalives and alliance pushes — 18 `world.get.block` in 5 minutes
against 453 in under 2 minutes while scrolling. What an unattended capture
surfaces is therefore whatever the *account* is doing (dailies firing, alliance
events), not what the map is doing. Drive the client deliberately if you want
map vocabulary.

### Client → server

**World / map**

| Command | Parameters |
|---|---|
| `world.get.block` | `bigMap`, `x`, `y`, `serverId`, `worldId`, `type`, `viewLvl`, `blockSize`, `index[]`, `leftBottom`, `rightTop` |
| `world.get.march.infos` | `x`, `y`, `needCross` → `marchInfos` |
| `world.flag.get.can.effect` | `worldId` → `flags` |
| `lw.req.world.occupy.info` | `serverId` → `content` |

`world.get.block` is a **rectangular map-region query** — the exact primitive
the bot currently reconstructs by screenshotting and OCR'ing the map. It fires
continuously while the map scrolls (99 requests in 60 s in capture B).

**Cross-server travel**

| Command | Parameters |
|---|---|
| `user.leave.world` | `worldId`, `serverId` → `success` |
| `meteorite.enter.world` | `targetServerId` → `success` |
| `go.to.world` | — → `success` |
| `get.server.state` / `get.other.server.info` | `serverId` / `server` |
| `get.player.cross.server.list` | → `list` |
| `get.cross.server.king.info` | `serverIds` → `serverInfo`, `serverKing` |

**Alliance**

| Command | Parameters |
|---|---|
| `get.al.points` | `serverId` → `alMemberPointsArr` |
| `al.help.all` | `allianceId`, `cmdBaseTime`, `accPoint` |
| `alliance.notice.list.info` / `.pinned.list.info` | `start`, `end` → `notices` |
| `get.alliance.share.mission.list` | `allianceId` → `shareMissionArr` |
| `top.message.get` | → `info` |

**Other**

| Command | Parameters |
|---|---|
| `get.user.info.multi` | `uids`, `allservers` → `uids[]` player profiles — see below |
| `mail.read.status.betch` | `uids` (long comma-separated list; this is the one client message big enough to be zlib-compressed) |
| `train.list` | `isRefresh`, `pageIndex`, `pageSize` → `trainServers`, `allianceTrainList` |
| `train.march.get.pos` | `point`, `serverId`, `uuid`, `positionId` |
| `hero.dispatch.list` | → `todayAssistNum`, `todayStealNum` |
| `get.king.info` | `serverId` → `kingInfo`, `occupyAllianceId`, `declaration` |
| `get.in.battle.city.stronghold` | `serverId` → `inBattleIds` |
| `get.all.server.trade` | `serverId` → `worldCityTradeArr` |
| `city.war.get.info` | `serverId` → `cityInfoList`, `noOpenList` |
| `lw.season.rq.info` | `serverId` → `serverSeasonInfo` |
| `get.world.news.info` | `allservers` → `newsInfo`, `areaInfo` |
| `champion.duel.result.show.rank.list` | `serverId`, `num` → `rank`, `endTime` |
| `zwl.get.target.act.info`, `view.blood.night.act`, `center.throne.activity.info`, `bloody.queen.s1.rest.gain.city.occupation.rank.first.info` | event/activity status probes, mostly `serverId` |
| *(keepalive)* | `clientTime` |

**Added by capture C** (see below) — dailies, alliance training and social actions,
none of which the earlier captures exercised:

| Command | Parameters |
|---|---|
| `daily.quest.reward` | `stage` (`-1` = claim all) → `reward[]`, `rewardRate`, `rewardNum`, `stageArr[]` |
| `daily.task.reward` | `taskId` → `reward[]`, `taskInfo[]` |
| `gather.collect.reward` | `uuidArr[]` → `reward[]`, `collect_reward[]` |
| `detect.event.get.card.box.list` | — → `cardBoxList[]`, `dailyDropTimes` |
| `get.new.user.info` | `uid` → `serverId`, `uid`, `level`, `allianceId` (+51 fields — the fullest player record seen on the wire) |
| `open.red.packet` | `serverId`, `uuid`, `cfgId` → `roomId` (`alliance_<serverId>_<allianceId>`) |
| `thumbs.up` | `type` (61 observed) |
| `train.batch.reward` | — → claims pending alliance-training rewards |
| `train.record.batch.detail` | `info` (`"<uuid>;<serverId>"`) → `detailInfo[]` |

**City visitors** — the queue of characters that walk up to the base (`DataCenter.CityVisitorManager`).
A visitor's `data.eventType` indexes the global `VisitorType` enum (`RECRUITMENT=3`,
`MERCHANT=1`, `GIFT=2`, `WORKER_LOTTERY=5`, `ALLIANCE_INVITE_MOVE_CITY=8`, …); the
neighbouring `data.visitorId` looks like a kind but is a per-arrival counter. See
`docs/research/city-visitor-recruit.md`.

| Command | Parameters |
|---|---|
| `visitor.operate` | `uid` (Long), `operate` (Int; `1` = accept/recruit) — accept a queued visitor; recruits a waiting survivor when its `eventType == RECRUITMENT`, collects the gifts when it is `GIFT` |
| `finish.visitor` | `uid` — dismiss/finish a visitor |
| `visitor.receive.reward` | claim a visitor's reward |
| `visitor.fresh` | refresh the visitor queue |
| `survivor.visitor.receive.free` / `.score` / `.bubble` / `.info` | the survivor-rating mini-game |

### Server → client

Responses echo the request's command name. Pushes are unsolicited:

| Push | Payload highlights |
|---|---|
| `push.chat` | `msg`, `senderUid`, `senderName`, `type`, `post`, `gmFlag`, `customJsonParam` (nested JSON with sender/target profile, alliance, country) |
| `push.world.march.new` | `uuid`, `ownerUid`, `teamUuid`, `armyWeight`, `targetServer`, `_proto` (protobuf blob) |
| `push.world.march.world.get.new` | `serverMarchArr` → `marchInfos[]` with `startPos`, `targetPos`, `arriveTime`, `type`, `monsterId` |
| `push.lw.alliance.alert.info.create` / `.remove` | `info`, `uuid` |
| `push.al.help.new` / `.update` | `helpId`, `senderId`, `nowCount`, `maxCount`, `itemId`, `level` |
| `push.alliance.reward.new` | `giftInfo`, `allianceNewMail`, `redPoint` |
| `push.all.notice` | `id`, `params` |
| `push.new.news` | `uuid`, `bigType`, `smallType`, `dataObj`, `createTime`, `overTime` |
| `push.running.boss.del` | `uuid` |
| `push.world.march.del` | `uuid`, `ownerUid`, `isBattleFail`, `_proto` |
| `push.battle.finish` | `result`, `uuid`, `leaderUuid` |
| `push.army.return` | `army_formation[]` with per-squad `soldiers[]`, `chipEquipGroup` |
| `push.resource.item.update` | `resource_items[]` |
| `push.batch.effect.change` | `reasons` |
| `push.al.sign` | `signNum`, `allianceWageNum` |
| `push.user.visitor.change` | fires when the city-visitor queue changes (a visitor arrives or is removed after `visitor.operate`) |
| `push.alliance.march.refresh` | `worldId`, `uuid`, `type` (+30 fields) — full restate of an allied march, not a delta |
| `push.alliance.march.remove` | `teamUuid`, `isCancel` (distinguishes a recall from an arrival) |
| `push.al.zombieRushPoint.change` | `allianceId` (+1) — fires in bursts during a Zombie Rush event |
| `push.month.card.card.privilege` | *(no fields observed)* — bare notification |

### Rankings

A ranking screen sends one command when you open it and the whole board comes
back in a single reply — a list of dicts, one per player, each carrying at
least a `uid` and a `name`. No paging was seen: `al.rank` returned all 99
members and `champion.duel.result.show.rank.list` all 32 duellists in one
frame. Nothing pushes a board; it crosses the wire only when the screen is
opened, which is why `tools/scan_leaderboard.py` cannot make one arrive.

| Command | Request | List | Per entry |
|---|---|---|---|
| `al.rank` | `allianceId` | `list[]` | `uid`, `name`, `power`, `armyKill`, `weeklyProgress`, `todayProgress`, `rank`, `mainCityLv`, `serverId`, `online`, `offLineTime` (offline members only, epoch-ms last-seen), `joinTime`, `donateTime` |
| `champion.duel.result.show.rank.list` | `serverId`, `num` | `rank[]` | `uid`, `name`, `server`, `rank`, `allianceName`, `group5`, `rank5`, `skin[]` |
| `rank.get` | `serverId`, `type`, `global` | `allianceRanking[]` | `uid` (**alliance id**), `alliancename`, `abbr`, `fightpower`, `armyKill`, `leader`, `leaderUid`, `curMember`, `maxMember`, `nums`, `country`, `icon`, `srcServer` |

**`rank.get` is multiplexed by `type`** — `type: 2` is the alliance ranking,
and the reply echoes both `type` and `serverId`, plus `selfRanking` (your own
alliance's place). A decoder must key the board on the type as well as the
command, or two different rankings dedup into each other.

Its rows are **alliances, not players**: `uid` is an alliance id and the name
is under `alliancename`, with `leader`/`leaderUid` naming the R5 as a separate
field. Any shape test that demands a `name` walks straight past this board.

It carries **no rank field at all** — the 44 entries came back strictly sorted
by `fightpower` descending, so the reply order *is* the ranking. That is the
opposite of `al.rank` above, which is why "is the list sorted" has to be
established per board rather than assumed either way.

Note the inconsistent typing: `fightpower` arrived as a JSON number and
`armyKill` as a string **in the same entry** (and `al.search` sent
`fightpower` as a string). All are past 2^32, so a server-side encoder is
likely widening the ones that would lose precision as doubles — a decoder has
to accept both spellings.

Not a ranking, despite the shape: **`al.search`** (`page`, `searchType`,
`recommend` → `list[]` of 39 alliances) is the recruitment browser reached
from the same part of the UI. It carries `alliancename` and `fightpower` like
a board, but its list is in no fightpower order (24.4G, 15.0G, 9.5G, 3.1G,
197M, then back up), which is what tells the two apart.

**The field called `rank` is not always the position.** This is the one trap,
and it is not theoretical:

* in `champion.duel.result.show.rank.list` it *is* the placement — the 32
  entries carried exactly 1..32, in order;
* in `al.rank` it is the alliance **role** (R1..R5). The 99 entries carried
  `{3: 86, 4: 10, 1: 2, 5: 1}`, and the list arrives in no sorted order at all
  — not by `power`, not by `weeklyProgress`, not by `todayProgress`. That
  board is really the roster; the client sorts it locally by whichever column
  you picked, so **the position you see on that screen was never on the wire**
  and cannot be recovered from the frame.

So a decoder must verify a candidate field really is `1..N` in order before
reading it as a placement, and report no position otherwise rather than
inferring one from the order of the list. `lastwar_proto.is_position_sequence`
is that check. Where a board states no number but the server *did* sort the
list (`rank.get`), the index is the placement — recorded with its provenance
(`position_source`) so "the board said so" and "the order implies it" stay
distinguishable.

Boards not in the table are recognised by shape: a list of ≥3 dicts each with
a `uid`, a name (under `name` *or* `alliancename`), and a rank or score
column. Replayed over all three captures that test finds exactly the real
boards and no false positives — but only because the lists that are *not*
rankings are excluded by name (`lastwar_proto.NOT_LEADERBOARDS`): a march's
`plunderRecord`, `get.user.info.multi`, `train.list`,
`get.alliance.world.mark.info`, `al.search`, and the
`dragon.assign.player.info` / `quarantine.act.player.list` sign-up sheets all
otherwise pass it.

### Alliance-member presence (online / "last seen")

All the presence a bot can read off the wire lives on exactly one command, and
it fully backs the UI's *"онлайн"* / *"был N минут назад"* line:

* **`al.rank` is the only frame that carries per-member presence.** Each roster
  entry has `online` (a plain boolean; capture: 100 members, 6 `true` / 94
  `false`), and every *offline* member additionally carries **`offLineTime`** —
  the epoch-**ms** timestamp of when they last went offline. Online members omit
  `offLineTime` (there is nothing to show but "онлайн"). A walk over the whole
  session found `online` / `offLineTime` in `al.rank` and nowhere else.

* **`offLineTime` is the backing value for "был N минут назад".** The UI renders
  `now − offLineTime`: in the capture the 94 offline members spread from ~0 min
  to ~15 h ago, exactly the roster's relative-time column. So the last-seen time
  *is* on the wire — it just rides the roster response, keyed per member, not a
  standalone command. (My first pass on #996 wrongly reported no last-seen field;
  it was hidden because online members omit `offLineTime` and the field is
  camel-cased `offLineTime`, not `offlineTime`.)

* **It is tied to the alliance-list screen — there is no background feed.**
  `al.rank` crossed the wire once (one `up` request, one `down` reply) and only
  when the alliance ranking/roster screen was opened. No `push.*` carries
  `online`/`offLineTime`; presence is never streamed unsolicited. So a bot cannot
  observe presence passively — it must open the roster (or inject the `al.rank`
  request) to sample it, and the snapshot is stale the moment it lands. The
  profile commands the client fetches for other players (`get.new.user.info`,
  `get.user.info.multi`, `user.remark.list`) carry no presence, and
  `social.status.view` (`otherUid` → `socialStatus`) returns an empty object.

* **The local player's own presence** is in the `init` blob at login —
  `lastOffLineTime`, `offLineTime`, `todayLoginTimes`, `loginDays`, `regTime`,
  `lastTime` — describing *you*, never a teammate.

Net: `al.rank` gives both who is online now (`online`) and when each offline
member was last seen (`offLineTime`, epoch-ms) — the complete "онлайн / был N
минут назад" data — but only on demand when the roster is opened; nothing pushes
it in the background.

## 6. Login sequence

The client races **three gateways on port 17935 in parallel** and keeps the
fastest; the losers get one handshake and are dropped. Observed in capture C:

| Gateway | Provider | Role |
|---|---|---|
| `<server-ip4>:17935` | AWS Global Accelerator | winner — carried the whole session |
| `<server-ip2>:17935` | Cloudflare | probed, 1 frame, dropped |
| `<server-ip5>:17935` | Google Cloud | probed, 1 frame, dropped |

**The game IP is not stable.** Capture A used `<server-ip>`, capture C used
`<server-ip4>`, and in C the old address served plain TLS instead. Never
hard-code it — match on the frame shape.

The opening frame is the keepalive envelope carrying a device fingerprint:
`appVersion`, `deviceId`, `androidDid`, `uuid`, `packageSign`, `resVersion`,
`CoreV`, `SecurityCode`, `afuid`, `simOp`. `login.ext` then uploads hardware
details (`deviceName`, `deviceModel`, `os_version`, `graphicsDeviceName`,
`processorType`) plus an `add` token built from the account uid.

> These frames are **credential material**. A capture and any transcript
> derived from it identify the account and machine — keep both out of the
> repository.

Ordering (t+ from the first frame):

```
0.00  --> handshake / device fingerprint      (all three gateways)
0.51  <-- init                                 445 KB, 243 top-level keys
0.68  <-- push.formation.preset, push.utc.time, push.off.season.skip.cd
0.86  --> check.device.change
1.36  --> common.chat.room.id                  -> country_100, custom_lang_ru_100
1.49  --> login.other {alliance}               -> full alliance record
      # NOT the session kick, twice looked for here: docs/research/session-kick.md
1.58  --> login.ext   {hardware fingerprint}   -> {success: true}
1.49-2.5 ~90 parallel UI-population calls (activities, shops, heroes, season…)
2.64  --> meteorite.enter.world                 enter the world map
```

`init` is the whole account state in one frame — 243 top-level keys covering
items, heroes, vip, science, shops, settings and more. It is the reason the
`0x08` uint32-length flag exists.


### Chat

> Full chat write-up — room types, message shapes, system broadcasts and the
> "separate connection" question — is in [`chat.md`](chat.md).

Rooms come from `common.chat.room.id`: public rooms are `country_<server>` and
`custom_lang_<lang>_<server>`; a direct message uses
`custom_<peerUid>_<selfUid>_v2`.

Sending is **two commands fired together**, both acked by `_id`:

| | |
|---|---|
| `lw.user.push.chat.msg` | the message itself — `uid` (the **peer**, not the sender), `msg`, `roomId` |
| `chat.stat` | telemetry twin — `sendTime`, `type`, `roomId`, `msg`, and `msgExtra` with `srcLang`, `senderLevel`, `post`, `atUids`, `atPlayers`, `isSendEmoji` |

The ack echoes the request and adds `_mt` (server send time) and `_time`.

Note `msgExtra.atUids` arrives as the literal string `"table: 00000003588EF170"`
— a Lua table stringified by mistake in the client, which incidentally confirms
the game logic is Lua.

Two different shapes carry chat: `push.chat` (broadcast, seen in capture A with
`senderUid`, `senderName`, `customJsonParam`) and `lw.user.push.chat.msg`
(direct message). A DM sent *by* the captured client only ever shows as the
request plus its ack — the broadcast goes to the recipient's client, not ours.

#### Sharing a map object — `attachmentId`

A player can attach a map object to a message. The attachment is a **JSON
string** inside `attachmentId`, and it is the cleanest description of a map
object the protocol offers — the client already resolved what the object is.

Three commands send one, depending on what is being shared:

| Command | `posType` | Object |
|---|---|---|
| `chat.room.send` | 2 | monster |
| `chat.room.send` | 5 | resource mine |
| `chat.room.send` | 6 | mine with an active gatherer (`uname` reads `"Collector: [TAG]name"`) |
| `hero.dispatch.share.chat` | 22 | secret task / hero dispatch |

Common fields: `x`, `y`, `sid` (server), `olv` (object level), `oname`,
`worldId`, `worldType`. `hero.dispatch.share.chat` adds `cfgId`, `uuid`,
`dispatch` and repeats `uuid` / `targetServer` / `type` on the envelope.

```json
// monster, level 6
{"posType":2, "oname":"300602", "olv":6, "x":636, "y":547, "sid":100}

// gold mine, level 4
{"posType":5, "oname":129027, "olv":4, "x":189, "y":597, "sid":1038}

// secret task
{"posType":22, "cfgId":60000701, "oname":"Секретное задание", "dispatch":1,
 "uuid":1394584916020422441, "x":470, "y":652, "sid":999}
```

**`oname` is not one type.** For a mine it is an integer template id (`129027`
for gold — the same value regardless of level). For a monster it is a *string*
holding the `LLVV` template (`"300602"` = level 6, variant 2). For a secret
task it is the localised display name. Any consumer must tolerate all three.

`cfgId` in a task attachment is the same field as `f10.f2` on an `f2=17` tile —
`50000704` and `60000701` both appear in captured tiles — which confirms the
`LLVV` level reading from a second, independent direction. The command name
`hero.dispatch.share.chat` also states outright what tile analysis had only
inferred: an `f2=17` tile *is* a hero dispatch.

Shared coordinates can be off by one from the tile: a mine shared as
`x=189,y=597` matched the tile at `(190,597)`, with no tile at 189 on that row.
Whether the link carries the click point or the indexing differs by one is
unresolved — it matters for anything that navigates by coordinates from chat.

### Switching servers

A cross-server jump completes in about **1.6 s** and arrives in three waves,
all on the same connection — no reconnect, no separate endpoint:

```
+0.22  --> lw.season.rq.info, train.march.get.pos, get.server.state
+0.88  --> get.in.battle.city.stronghold, get.all.server.trade,
           get.king.info, get.cross.server.king.info, go.to.world
+1.25  --> ~25 requests in one burst: user.leave.world,
           meteorite.enter.world, world.get.block, city.war.get.info,
           zwl.get.target.act.info, center.throne.activity.info,
           lw.req.world.occupy.info, bloody.queen…rank.first.info
+1.40  <-- every response returns as one batch
```

The burst is **not limited to the destination**. Jumping to 959 also queried
992, 1038 and 8120, and `world.get.block` fires for several `serverId` values.
A reader that assumes one server per jump will mis-attribute tiles; the
`serverId` inside each `serverPointArr` block is authoritative, not the jump
target.

`meteorite.enter.world` is the exception, and an earlier revision of this
section wrongly lumped it in with the rest. Re-checked across every capture on
disk it names **one** server per jump — 100×3, 1003×2 (the same value sent
twice), 1035×1, never two different ones — and that server is the one every
following `world.get.block` request then asks for. The off-target ids in the
burst ride on `center.throne.activity.info`, `get.all.server.trade` and
`get.in.battle.city.stronghold` instead (8120 on all three), which is what the
original claim had confused it with.

That makes it the one **advance** notice of a move. Everything else is
evidence after the fact, and after-the-fact evidence needs the map to keep
talking: a drag re-requests blocks every frame, so weight of traffic follows
it within a second. A **minimap click does not** — the viewport lands on
ground the client already has, it may request no blocks at all, and a reader
weighing traffic will sit on the old server indefinitely. `secret_task_capture.py`
therefore treats `targetServerId` as a statement of intent that overrules the
tally outright, clearing the votes and holding the election shut for ~5 s so
in-flight responses from the server being left cannot take the screen back.

Five commands first appeared during such a jump and are season/train scoped:
`get.server.state`, `lw.season.rq.info`, `train.march.get.pos`,
`train.refresh`, `zwl.get.target.act.info`.

## 7. World map semantics (`world.get.block`, plus the march stream)

Two streams describe the map, and only the first is made of tiles.
`world.get.block` carries everything that stands still — bases, secret tasks,
strongholds — and is what the rest of this section is about. Everything that
*moves* rides the march stream instead (`push.world.march.*`,
`world.get.march.infos`), which is a separate shape entirely and is covered
under "Trucks" at the end of this section. A scan built on map blocks alone
finds no trucks, and that is why: they were never tiles.

### Zoom

> **Measured against the camera's height in #1265** (docs/research/map-sweep-zoom.md §8).
> `viewLvl` is the camera's LOD band, and the three levels below map onto it exactly:
>
> | camera height | LOD | `viewLvl` | what comes back |
> |---|---|---|---|
> | ≤ 600 | 1–4 | **0** | every tile kind, secret tasks and ghost recon included |
> | 601 – 1199 | 5 | **1** | bases, mines, cities, strongholds — no tasks, no ghost |
> | ≥ 1200 | 6+ | **2** | **nothing**: whole-server squares, zero points |
>
> Within a band the height changes only the SIZE of the region asked for (`index[]` goes
> from 12–16 block ids at height 105 to a flat 132 at 600, both `viewLvl 0`), which is
> what an earlier revision of this note mistook for "`viewLvl` is not the height": it
> sampled two heights that were both inside band 0. Beware the tween — a jump that also
> changes the zoom fires its first request at the OLD band.

`viewLvl` is the zoom level, and `blockSize` moves with it. Two levels were
observed:

| viewLvl | blockSize | Viewport | `serverPointArr` |
|---|---|---|---|
| 0 (zoomed in) | 10 | 50 × 50 tiles | 1 block |
| 1 (zoomed out) | 20 | 160 × 120 tiles | 1 block |
| 2 (whole world) | 1000 | one server square | **9 blocks** (3 × 3 servers) |

`viewLvl=2` was only seen live, not in any saved capture. At that level the
client walks **other servers** — one request per server id — and each response
carries nine blocks instead of one, i.e. a 3 × 3 grid of server squares.
Observed ids in a single pan: 976, 8125, 940, 1032.

`index[]` lists the block ids actually requested, so a small pan re-fetches
only the newly exposed blocks (observed lengths 3–160).

The request's `timeStamp` is **a sync token, not a clock** — it is a
monotonically rising counter, and the server answers with only what changed
since it. Panning inside an already-loaded region returns 3–40 points; entering
a fresh district returned 1490. Any consumer that assumes a response describes
the whole viewport will be wrong.

The client does not debounce: dragging the map emits a request per frame, and
the same `x`/`y` was seen sent five or six times in a row before any response
arrived.

### Coordinates — two different packings

This is the easiest thing to get wrong: **request and response do not use the
same coordinate space.**

- **Request** `leftBottom` / `rightTop` are packed **`y * 3000 + x`** in
  *world* space, matching the `x` / `y` fields (which are the viewport centre).
- **Response** block `leftBottom` and every tile's `f1` are packed
  **`y * maxAreaSize + x`** (`maxAreaSize` = 1000) in **server-local** space.

**Most consumers want server-local coordinates and no lift at all.** They are
what the game shows on screen, they are what `pointId` in `hero.dispatch.*`
carries, and they need only an unpack:

```python
x, y = f1 % A, f1 // A                    # A = maxAreaSize, 0..A-1
```

Verified three ways on the saved captures: every tile lands in `0..999`, every
tile lands inside its own block's box (854/854), and for the 48 tasks that also
appear as a `hero.dispatch.*` record, `pointId` unpacks to exactly the same
pair (48/48).

To lift a tile to *world* space instead, add the server's origin — the corner
**of the request**, rounded down to the local grid:

```python
ox, oy = (gx // A) * A, (gy // A) * A     # gx, gy = REQUEST leftBottom unpacked
world_x, world_y = ox + (f1 % A), oy + (f1 // A)
```

Verified: **6373/6373 tiles land inside their requested box** under this model.

> **Trap.** `gx, gy` above must come from the **request**. A decoder iterating
> responses has the *block's* `leftBottom` closest to hand, and that one is
> already server-local — feeding it through the world-space unpack (`% 3000`)
> invents an origin of 1000 or 2000 whenever `leftBottom % 3000 > A`. The
> failure is quiet: coordinates stay plausible, just shifted by a whole server
> square, and only show up as x values above 1000 on a 1000×1000 server. This
> bug shipped in `secret_tasks()` and was caught by a reader noticing the
> out-of-range x, not by any test.

### Object types (`f2` on each tile)

| `f2` | Count | What it is | Key fields |
|---|---|---|---|
| 7 | 1710 | **Resource mine** | `f6.f1` = `family*100 + level`, `f6.f8` = occupier uid, `f6.f9` serverId, `f6.f10` allianceId |
| 6 | 1116 | **Player base** | `f3.f14` name, `f3.f15` alliance abbr, `f3.f4` HQ level (4–35), `f3.f27` country, `f3.f1` uid, `f3.f7` allianceId |
| 17 | 224 | **Secret task / hero dispatch** — see below | `f10.f2` cfgId, `f10.f1` owner, `f10.f4` stealers, `f10.f8` expiry |
| 11 | 34 | Stronghold / fortress (fixed 100-tile grid) | `f101.f3` level (1/5/7), `f101.f8` reward, `f101.f1` template |
| 29 | 28 | **Ghost-recon squad — "Операция Призрак"** — see below (task #1010) | `f14.f2` cfgId (fam 4/5/6), `f14.f1` owner, `f14.f6` targetServer, `f14.f5` members, `f14.f9` state, `f14.f8` uuid (hex) |
| 25 | 17 | Named facility held by a player | `f101.f5` player name, `f101.f10` alliance name |
| 35 | 3 | Named facility on a fixed grid | `f101.f4` player name, `f101.f11` alliance name, `f101.f6` level, `f101.f12` serverId |
| 21 | 4 | Alliance HQ | `f11.f12` alliance name, `f11.f6` abbr, `f11.f7` member uid list |

### Player profiles (`get.user.info.multi`)

Clicking a base on the map makes the client ask `get.user.info.multi` for that
one uid. The reply is **plain JSON, not protobuf**, and carries the numbers no
map tile does:

| Field | What it is |
|---|---|
| `power` | total power |
| `armyPower` | army power |
| `armyKill` | lifetime army kills |
| `svipLevel` | SVIP level |
| `mainBuildingLevel`, `level` | HQ level — agreed on all 95 profiles seen |
| `serverId`, `currentServer`, `srcServer` | current server, current server, origin server |
| `uid`, `name`, `country`, `allianceId`, `allianceAbbrName` | same values the `f2=6` tile carries |

Each entry names its own `uid`, so a reply needs no correlating back to the
request via `_id`. Present on all 95 profiles in the saved captures: `uid`,
`power`, `armyPower`, `armyKill`, `svipLevel`, `level`, `mainBuildingLevel`,
`serverId`, `name`, `country`, `allianceId`, `allianceAbbrName`.

The same command also arrives **batched** — 46 and 43 uids in the captures, an
alliance roster fetched at login. Same entry shape; only the reason the client
asked differs. Note the request's own `uids` is a list of bare uid *strings*
while the reply's is a list of objects, so a decoder must not assume either.

Where a player appeared as both a map tile and a profile (59 uids), the two
sources agreed **59/59** on level, server, name, `allianceId` and
`allianceAbbrName` — so a profile merges onto a tile's record by
`(serverId, uid)` with neither contradicting the other. `tools/scan_players.py`
does exactly this.

### Player notes (`user.remark.list`)

The private note the client lets you write on another player is stored
**server-side**, not locally. `user.remark.list` returns the whole list,
paginated — the client asks `{"pageSize": 500, "page": N}` once at login, and
in the saved capture two pages held 869 notes.

| Field | What it is |
|---|---|
| `uid` | the author — you; identical on every entry |
| `targetUid` | the player the note is about |
| `remark` | the note text |
| `lastUpdateTime` | last edited, epoch ms |

A note is **not** on the `f2 = 6` tile and not on the player's profile. Tested
rather than assumed:

* the literal note text appears nowhere else in the capture;
* of 1094 base tiles, no field is present on the 276 belonging to noted
  players and absent from the other 818;
* no field *value* is common to >90% of noted players and absent from all
  others.

The alliance fields (`f3.f7`, `f3.f11`, `f3.f15`, `f3.f26`) do differ between
the two groups — 12% of noted players carry `f7` against 68% of the rest — but
in the opposite direction to a marker. Noted players are mostly *outside* an
alliance, which says what this account marks (farms), not that the tile
carries a flag.

The command that **writes** a note has never been captured: every note in the
capture was last edited 17 hours before it started, and no client frame in it
mentions one. To find it, run a scan with `--dump` while setting a note and
grep the transcript for up-frames.

`tools/scan_players.py` merges these into its records as `remark`, keyed by
`targetUid`. Because the list only arrives at login, the scan has to be
started **before** logging in.

### Resource mines (`f2 = 7`)

`f6.f1` encodes both the resource and its level as `family * 100 + level`,
with levels running 1–10 (12 during a season, per the maintainer):

| Family | `f6.f1` | Resource |
|---|---|---|
| 0 | 1–10 | bread |
| 1 | 101–110 | iron |
| 2 | 201–210 | gold |

The `family * 100 + level` structure is derived from the wire data — a full
area load showed all three families populated across levels 1–10. The mapping
of family to resource name was **confirmed by the maintainer against the game
screen**, not derived from the protocol; nothing on the wire names them.

A free mine carries only `f6.f1` and `f6.f2`. Occupation adds `f6.f8` (the
gathering player's uid), `f6.f9` (their server) `f6.f10` (their alliance) and
`f6.f3` (an activity uuid) — so "free or taken" is readable without any OCR.

### Monsters are not on the wire

Map monsters (levels well above the 1–10 mine range: 12, 17, 21, 23, 26, 28
were all visible on screen) **never appear in any observed message**. This was
checked against:

* incremental deltas from panning the camera (141 new tiles: bases, mines,
  tasks — no monsters);
* a **full load of a previously unvisited district** (1490 tiles, 1029 mines,
  every family at every level 1–10 — still no monsters);
* `push.world.point.update`, which carries the same tile encoding
  (`create` / `change` / `remove` / `foldUp`) — no monsters;
* a scan of every field of every message for values matching the observed
  monster levels — no matches;
* a **re-login**, including the 443 KB `init` — no monsters, and the sync
  token does not reset across logout, so there is no "full snapshot" request;
* a **switch to a server not visited that day** (959), watched end to end —
  five commands appeared that were not in the 199-command vocabulary, all of
  them season/train related, none about monsters.

Across roughly 2000 unique tiles from every one of those paths, **zero**
objects carried a level above the 1–10 mine range, while levels 12–28 were
visible on screen throughout.

The conclusion is that **monster placement is computed client-side** from map
configuration and never crosses the wire. The server does know monsters exist
and tracks outcomes — `init` carries `find_monster_max_level` (35 for this
account) alongside `daily_kill_boss`, `daily_auto_kill_boss`,
`attack_behemoth_boss_time` and `kill_lock_hart_boss` — and it accepts a chat
share referencing a monster by `oname` and coordinate. So the server validates
and scores monster interactions; it just never announces where they are.

Practical consequence: monsters stay a vision problem. Mines, bases, tasks,
strongholds and marches come off the wire as exact numbers.

**Player bases and secret tasks both arrive inside `world.get.block`** — there
is no separate command for either. A single 60 s session yielded 1116 named
bases and 224 tasks.

Secret tasks get their own breakdown below.


### Secret tasks / hero dispatch (`f2 = 17`)

636 unique tiles across all captures. Every one has the same field set, and
each maps **1:1 onto a record in `hero.dispatch.alliance.list`** — verified on
all 48 tiles whose uuid appeared in both (`ownerId`, `cfgId`, `actEndTime` and
the stealer list matched exactly).

| Tile field | Meaning | Dispatch equivalent |
|---|---|---|
| `f1` | coordinate, `y*1000+x` server-local | `pointId` |
| `f100` | task uuid | `uuid` |
| `f10.f1` | owner uid | `ownerId` |
| `f10.f2` | config id — encodes the level | `cfgId` |
| `f10.f3` | completion time (ms) | `completionTime` |
| `f10.f4` | **uids that already stole from it** (absent = 0, max 3) | `stealInfoList[].uid` |
| `f10.f6` | 18 B: two packed int64 uuids | — |
| `f10.f8` | expiry (ms) | `actEndTime` |
| `f10.f9` | allianceId | `allianceId` |
| `f10.f10` | family flag, `1` or `3` | — (redundant, see below) |
| `f102` / `f103` | serverId | `targetServer` |

**Level** is not a field of its own — it is the *trailing* two digit pairs of
`cfgId`, read as `LLVV` (level, variant), with everything before them a family
prefix. The prefix is not a fixed width, so read from the right:

```python
family, level, variant = str(cfg)[:-4], int(str(cfg)[-4:-2]), int(str(cfg)[-2:])
# 50000704 -> ("5000", 7, 4)     400602 -> ("40", 6, 2)
```

Four families appear: `30`, `40`, `5000`, `6000`. Observed levels 1, 3, 4, 5,
6, 7 — plus a `6000 99xx` group (128 tiles) that does not fit the reading. That
group is one-per-player with a distinct template range, so it is probably a
different task class rather than "level 99".

**The reading is verified against the game, not just against itself.** A task
shared into chat carried `cfgId 60000701`, and the maintainer read its level as
**7** off the game UI — `LL = 07`, matching. That check is independent of the
wire: the level came from the screen, the cfgId from the packet, and nothing in
the decoder connects them. A second, weaker check comes from the shape of the
data — level 4 does occur (four tiles on server 999: `50000404`, `400404`,
`400401` ×2), and across 271 live tiles the distribution reads as a plausible
game population (`4`×4, `5`×52, `6`×88, `7`×90) rather than the noise a
misaligned digit window would produce.

One tile broke the four-family pattern: `cfgId 5000302` is seven digits, which
splits as family `500`, level 3, variant 2. A single occurrence — noted rather
than concluded, but a reader hitting a fifth family should not be surprised.

**`f10.f10` is fully determined by the cfgId family** — `30`/`40` → 1,
`5000`/`6000` → 3, on 766/766 tiles. It therefore carries no information the
cfgId does not already have. The obvious reading, "number of loot slots", is
**wrong**: a family-`40` tile (`400602`, flag 1) was captured with two entries
in `f10.f4`, and its blob was re-decoded by hand to rule out a parser artefact.

**Robbery count** is the length of `f10.f4`: absent → 0, then 1, 2 or 3.
**The maximum is 3** — no tile or dispatch record in 636 tiles / 144 records
exceeded it. Verified directly: for the 48 tasks whose uuid appeared both as a
tile and as a `hero.dispatch.*` record, `len(f10.f4)` equalled
`len(stealInfoList)` **48/48**, and the cfgIds matched. So free loot slots are
readable off the map with no OCR and no panel opening.

#### The star — family `6000`, excluding the `99` class

Some task markers are drawn with a star, and those are the ones worth raiding.
**No field distinguishes them.** Every captured tile carries the identical
field set, so the star must be derived client-side from `cfgId` — the same
place the level hides.

The maintainer's ruling is **family `6000`**, on this evidence:

* **Positive, confirmed by eye.** The task shared into chat from server 999 at
  (470, 652) was starred, and its attachment named `cfgId 60000701` — family
  `6000`. The maintainer confirmed the star at the moment of sharing.
* **Negative, unreproduced.** An unstarred task at (469, 659) matched a tile
  with `cfgId 50000704` — family `5000`. From a dataset outside this
  repository; no server-999 tile appears in `results/`, so it was not
  re-derived here.
* **Consistency.** Across 271 live tiles nothing contradicted the reading.

Two caveats, so the strength of this is not overstated later:

* "Nothing contradicted it" is weaker than it sounds. No tile's star was ever
  checked by eye except the shared one, so a contradiction had no route to
  surface. The 271 tiles are *consistent with* the rule, not a test of it.
* ~~One observation still does not fit.~~ **Resolved.** The maintainer had
  reported a starred **level-4** task at (574, 624) on server 999 and noted
  family `6000` held no level-4 tile in any capture. The 2026-07-19 run
  captured `cfgId 60000401` — family `6000`, level 4 — so the family does span
  level 4. The note stood only because no such tile had been seen.

The `99` class is **excluded from the star**, and since 2026-07-19 that is a
sighting rather than an inference. This section used to argue that level `99`
tiles are "internal one-per-player tasks the UI does not draw, so they cannot
be the starred markers a player sees". **The premise is wrong.** The maintainer
watched a family-`6000` tile with `cfgId 60009902` — level 99 by the cfgId —
render on screen as a seasonal oil-barrel task, displayed at **level 6** in the
UI and carrying **no star**. The UI does draw these; it draws them unstarred,
under a level of its own that the cfgId contradicts.

The conclusion outlived its premise, and family alone demonstrably over-reports:
in that day's captures **113 of 189 starred lines — 60% — were level 99**, none
ever confirmed by eye, while both by-eye confirmations on record (`60000701`
level 7, `60000401` level 4) sit outside the class. Excluding it costs no
confirmed star.

Two things this does not settle:

* whether *every* `99` tile is unstarred or only this seasonal type — one
  sighting cannot separate those;
* what the UI level means when it disagrees with the cfgId (6 vs 99). Until
  that is understood, `level` on a `99` task is the wire's number, not the
  player's.

The rule lives in `STAR_TASK_FAMILIES` plus `SecretTask.starred` (which applies
the `99` exclusion) in `tools/lastwar_proto.py`. To re-test it, run
`tools/live_tshark.py --tasks --families` and compare the tally with the stars
actually drawn on that patch of map.

**Daily limits** live on the player, not the tile: `hero.dispatch.list` returns
`todayAssistNum` and `todayStealNum`.

**Expiry is a daily reset** — 597 of 636 tiles shared one timestamp
(01:59:59 UTC), the rest fell on adjacent days.

#### Rewards

The map tile carries **no reward data at all**. Rewards appear only in
`hero.dispatch.alliance.list` → `ls[].stealInfoList[].reward`, and only
*retrospectively* — they record what a past thief received, not what a
prospective one would get:

```json
"reward": [
  {"type": 7,  "value": {"id": "710005", "num": 7}},
  {"type": 7,  "value": {"id": "500104", "num": 56}},
  {"type": 27, "value": {"id": "8001",   "num": 529400}}
]
```

`type` 7 is an item and 27 a resource; `id` indexes a client-side config table
that is not on the wire.

**Partly answered — the prospective reward.** The panel request was found (see
below): tapping another player's task marker fires **`world.get.detail.new`**,
not anything in the `hero.dispatch.*` family. Its *response* has still not been
captured — the 2026-07-19 trap recorded both requests and missed both replies —
so whether the payout is quoted there or comes from client-side config remains
open. Re-run the trap with `--match world.get.detail` to close it.

#### Stealing — `hero.dispatch.steal`

> The client side of this — which Lua call sends it, what gates it, and how a
> coordinate is turned into the `uuid` it wants — is
> [`secret-task-steal.md`](secret-task-steal.md). Robbing is automated there
> (`tools/steal_secret_task.py`, `actions/steal_secret_task.md`).

Captured live on 2026-07-19 by `tools/trap_command.py` while the maintainer
robbed a task by hand. The command is **`hero.dispatch.steal`** — no command
containing "rob" exists. The exchange is four messages:

```
--> world.get.detail.new  {worldId, pointType: 17, point, previewAssistance: 10,
                           serverId, uid: ""}      open the marker's panel
--> hero.dispatch.steal   {targetServer, uuid, _id}          the steal itself
<-- push.hero.dispatch.mission.steal {pointId, serverId, worldId, playerInfo}
<-- hero.dispatch.steal   {reward[], ownerInfo, target_uid, target_alliance_id,
                           config_id, uuid, recordUuid, color,
                           todayStealNum, todayAssistNum}
```

**The request has three fields and none of them is a coordinate.** A steal is
keyed by the task `uuid` (tile field `f100`), so a caller holding only `x`/`y`
must first resolve the uuid from a map scan — `world.get.block` carries it.

**The request carries no credential of any kind** — no uid, no signature, no
`SecurityCode`, nothing from the login handshake. Authority comes entirely from
*which connection the frame arrives on*. `_id` is the same per-connection
monotonic counter every other request uses (9159 here). Any plan to send this
frame therefore has to become an authenticated connection first; there is no
token to lift out of a capture and attach to a lone request. See §10.

`push.hero.dispatch.mission.steal` is a **broadcast**, and it carries the
thief's `playerInfo` — uid, name, alliance abbr, country. Stealing is not
quiet: the owner and their alliance are told who did it.

The response is the first **prospective-side** reward record on the wire, and
its shape is richer than the retrospective one above — `value` carries
`itemId`, `addNum`/`add`, the resulting `number`, and for items `rewardAdd`,
`count`, `para1`, `use`:

```json
{"type": 7,  "value": {"itemId": "710005", "count": 36, "rewardAdd": 18, "para1": "108500004"}}
{"type": 27, "value": {"itemId": 8001, "add": 1588100, "number": 5510811779}}
```

`todayStealNum` / `todayAssistNum` come back on every steal, so the daily
counter is readable without a separate `hero.dispatch.list`. **The cap itself
is still not on the wire** — a bot must discover it by hitting it.

Afterwards the client fires `hero.dispatch.share.chat` on its own to post the
task into alliance chat. That is a client-side courtesy, not part of the steal.

One coordinate note, consistent with the off-by-one already recorded above:
the steal was at `point 509552` → `(552, 200)` server-local, while the chat
attachment the client generated for the same task said `x: 551, y: 200`.

#### Shared secret missions — `alliance.share.mission.*`

A secret task (`f2 = 17`, above) is a map tile: you only learn of one by
panning `world.get.block` onto it. When a player presses **share** on a mission
worth raiding, the server broadcasts it to the whole alliance as a push — so an
alliance member learns of it without looking at that patch of map at all. This
is the "секретная миссия" side of the same feature, distinct from the tile
scan; there is **no** separate `secret.mission.*` / `world.secret.mission.*`
command family (searched across every capture — none exists). The only
game class carrying the word is `HeroDispatchMissionPointInfo`, i.e. hero
dispatch is the mission.

Two commands carry them (captured 2026-07-19 in `results/rob_trap.jsonl`):

```
<-- push.alliance.share.mission.add {missionCfgId, missionUuid,
        missionCurrentServerId, shareUid, shareAllianceId, missionPlayerServerId}
--> get.alliance.share.mission.list {allianceId}
<-- get.alliance.share.mission.list {allianceId, shareMissionArr[]}
```

| Field | Meaning | Same as a tile's |
|---|---|---|
| `missionCfgId` | config id — encodes level + star | `f10.f2` / `cfgId` |
| `missionUuid` | the mission/task uuid | `f100` / `uuid` |
| `missionCurrentServerId` | server the tile sits on now | `f102` |
| `missionPlayerServerId` | the owner's home server | — |
| `shareUid` | who shared it | — |
| `shareAllianceId` | the alliance it was shared to | `f10.f9` |

The one captured `add` was `missionCfgId 60000701` — family `6000`, level 7, a
**starred** mission, which is exactly the kind a player shares. Level and the
star are read off `missionCfgId` exactly as `SecretTask` reads them off `cfgId`
(`split_cfg_id`, `STAR_TASK_FAMILIES`). The push carries **no** dispatch/loot
state (no completion time, no stealer list), so it says "a mission became
available", not "raidable right now" — cross-check the uuid against a
`secret_task_capture` scan for that. `shareMissionArr[]` was **empty** in every
capture, so its element field names are inferred from the `add` push, not
observed; the decoder tolerates a missing key. `hero.dispatch.share.chat` also
carries the same mission inside `extraShareInfo` (adds `missionUid`, `num`,
`shareServerId`), but without a `missionCfgId` — so the `add` push is the richer
source. Decoded by `lastwar_proto.share_missions`.

#### Secret missions — "Операция Призрак" / ghost recon (`ghost.recon.*`)

The in-game **секретная миссия** is neither of the two above. It is the
**Secret Command Post** ("Секретный командный пункт"), its "Операция Призрак"
tab — a helmet icon in the world-screen bottom-left cluster. Confirmed live
2026-07-23, a **Thursday**: the feature is weekly, so captures taken any other
day hold none of it (searched — zero `ghost.*` / `secret.mission.*` frames until
that day). It is a co-op dispatch: an ally sends a squad against a target
server, teammates join to help ("Команда союзников"), everyone loots when the
squad returns.

Two client commands fetch them when the panel opens; both wrap the rows in
`taskList` with the same shape:

```
--> ghost.recon.get.task.list            (open the panel)
<-- ghost.recon.get.task.list   {dispatchBeginTime, dispatchEndTime, openTime,
                                 autoStart, taskList[]}
--> ghost.recon.get.alliance.task.list   ("Команда союзников" — the help list)
<-- ghost.recon.get.alliance.task.list  {taskList[]}
```

Per task (all fields observed in `results/task1004/ghost_recon_task_list.json`,
6 tasks):

| Field | Meaning |
|---|---|
| `uuid` | mission id |
| `cfgId` | rarity/type/level — family `4`/`5`/`6` is the rarity tier the UI colours (SSR / UR★); read like a task cfgId, but the UI level ("ур.5") did **not** match the digits ("03"), the same cfgId-vs-UI caveat as the level-99 class |
| `state` | `0` empty slot · `2` running (squad out) · `3` done — lootable, helpers can claim |
| `pointId` | target coordinate `y*1000+x` (0 while `state` 0) |
| `targetServer` | server the mission targets |
| `ownerId` / `ownerServer` / `allianceId` | who launched it |
| `allianceShow` | `1` visible to the alliance (joinable), `0` private |
| `memberList[]` | squads — leader + helpers, each `heroList` (`heroId`/`level`/`rank`/`awakenLv`) + `memberInfo` + `canReward`/`rewarded`/`helpRewarded` |
| `stealList[]` | who looted it — `{uid, name, abbr, reward[], time}`; the UI caps "Награбленные награды" at 5 |
| `teamStartTime` / `completionTime` / `taskExpireTime` / `actEndTime` | epoch-ms timers |

Decoded by `lastwar_proto.ghost_recon_missions` / `GhostReconMission`; streamed
live by `tools/dev/secret_mission_capture.py` (its `--discover` mode is what found
`ghost.recon.*` in the first place, and re-finds a renamed family when the
seasonal feature shifts).

**A ghost-recon dispatch is also a map tile (`f2 = 29`) — task #1010.** An
earlier note here claimed ghost recon "never rides `world.get.block`". Wrong: a
ghost squad is drawn on the map under a tile type we had been discarding as an
unknown. Established by data 2026-07-23 (`results/task1010/tiles.jsonl` +
`results/ghost1005/session.pcapng`), no guessing:

- 28+43 `f2 = 29` tiles across two captures, **every one** with a cfgId of
  family 4/5/6 (the ghost rarity tiers), `state = 3`, and one shared `actEndTime`
  (the weekly window). No other tile kind carries that shape.
- the `f2 = 29` cfgId set (`40307`, `50302`, `50304`, `50307`, …) **shares exact
  values with the confirmed `ghost.recon.*` poll/push missions** (`results/task1004`)
  and is **disjoint** from the `f2 = 17` secret-task cfgIds (6–8 digit,
  families 30/40/500/…). This is what pins the tile type to ghost recon.

**Open caveat (uuid not yet matched).** We have not yet caught the *same mission
instance* in both the poll/push and as a tile — in both captures the two sets of
uuids were disjoint (`tools/_ghost_uuid_crosscheck.py`). That is expected, not
contradictory: the poll/push lists **your own alliance's** missions, while the
map shows **other players'** squads wherever you pan, so they coincide only if
you pan over your alliance's own squad with the panel open. Closing this is a
one-run job: `tools/dev/ghost_recon_tile_dump.py` already matches tile↔mission by
uuid live — open the panel, pan over a known mission, and the uuid link prints.

The tile carries the same mission the poll does, in protobuf field numbers under
`f14`:

| tile field | poll field |
|---|---|
| `f14.f1` | `ownerId` |
| `f14.f2` | `cfgId` (family 4/5/6) |
| `f14.f3` | `teamStartTime` |
| `f14.f5[]` | `memberList` (leader + helpers) |
| `f14.f6` | `targetServer` |
| `f14.f7` | `actEndTime` (shared across the week) |
| `f14.f8` | mission uuid, 32-hex form |
| `f14.f9` | `state` (`3` = done / lootable) |
| `f14.f11` | `completionTime` |
| `f100` | mission uuid (numeric) · `f1` = server-local `pointId` |

`f102`/`f103` is the tile's own server (where the squad is drawn); the server it
attacks is `f14.f6`, a different id. Decoded by `lastwar_proto.ghost_recon_tiles`
(the tile analogue of `secret_tasks`), so ghost recon can now be found by a
**tile scan** — panning the map, exactly like a secret task — not only through
the `ghost.recon.*` poll. `tools/dev/ghost_recon_tile_dump.py` dumps every tile kind
and labels `f2 = 29`.

### Trucks (march type 37)

A truck is not a tile and never appears in `world.get.block`. It rides the
march stream as an ordinary march whose `_proto._protobuf.f11` is **37**,
carrying an extra `train` object beside the march. Four commands are involved:

| Command | Where the march sits |
|---|---|
| `push.world.march.world.get.new` | `.serverMarchArr[].marchInfos[]` |
| `world.get.march.infos` | `.marchInfos[]` |
| `push.world.march.new` | the payload *is* one march |
| `push.world.march.del` | `{ownerUid, uuid, isBattleFail}` — the march is over |

`train.type` separates two things that share the shape. **1** is a player's own
truck, the robbable one; **2** is the alliance train, which has no owner and a
`carriageList` where a truck has an escort squad. Of the 158 in the saved
captures, 157 are type 1 and one is type 2.

The march protobuf carries the geometry and the `train` object the cargo:

```
f9 / f10    current leg, packed y * 1000 + x, server-local
f13 / f14   when that leg started / ends, epoch ms
f26         serverId

train.uid / .name / .country      owner
train.allianceId / .abbr          alliance
train.cfgId                       tier + level, see below
train.startPos                    where it set out (the owner's city)
train.arriveTime                  when the run ends and it leaves the map
train.baseGoods.full              the cargo it set out with
train.marchInfo.robTimes          how many times it has been robbed
train.marchInfo.plunderRecord     who did it, with their power
train.marchInfo.power / .heroInfo escort power and squad
```

**`startPos` is not the current position and `arriveTime` is not the leg's
end.** A truck hops station to station and only the hop it is on right now is
described, which is why neither matched across all 177 truck marches on disk
(0/177 against each). Position has to be interpolated along `f9`→`f10` over
`f13`..`f14`; `Truck.position` does it.

`completeness` is exactly `1 - 0.25 * robTimes` on all 158 trucks (110 at
0/1.0, 46 at 1/0.75, 2 at 2/0.5), so **four robberies empty one**. Three and
four were never observed, so the ceiling is arithmetic rather than a sighting.

#### `cfgId` — tier and level

Two schemes, chosen by magnitude. Both were checked against the `level` the
server sends alongside: **156 of 156 decode to exactly the level they claim,
with no mismatch.**

| `cfgId` | Meaning |
|---|---|
| ≥ 1000 | `tier * 1000 + level`. Levels 31+ only |
| 200–299 | the sled, a family of its own; `level = cfgId - 200` |
| 1–150 | `(tier - 1) * 30 + level`, a flat table capped at level 30 |

The tiers are graded, and the cargo is what proves it. Totalling
`baseGoods.full` per (level, tier) is monotone in tier at every level with more
than one — at level 33: 7.1M, 8.9M, 10.7M, 13.3M for tiers 2..5, and 23.1M for
the sled, roughly double the best graded truck. The two schemes agree across
the level-30/31 seam (tier 4: 8.04M then 8.36M; tier 5: 10.05M then 9.20M), so
the tier digit means the same thing in both.

**The colour names are an inference and have never been checked by eye** — the
same standing as the star in §7's task families. What the evidence establishes
is the *order*; which colour the client paints each rank is not on the wire.
`tools/dev/scan_trucks.py --type` accepts tier numbers for exactly that reason.
To settle it, run the scanner beside the map and compare a named truck against
the one drawn on screen.

### Alliance march alerts and rallies (`lw.alliance.alert`) — task #994

Every world march an **alliance member** launches is broadcast to the whole
alliance in real time. This is the feed a rally (Ралли / «стяг») rides on. Three
commands carry it:

| Command | Direction | Shape |
|---|---|---|
| `lw.get.alliance.alert.info` | client → server | request → the full list of currently-active alerts (poll for a snapshot without waiting for pushes) |
| `push.lw.alliance.alert.info.create` | server → client | `{info:{…60 fields}, uuid}` — one member's march just launched |
| `push.lw.alliance.alert.info.remove` | server → client | `{uuid}` — that march ended (arrival, recall, or battle over); bare uuid only |

`remove` outnumbers `create` heavily on the wire (120 vs 9 in `capture.pcapng`)
because the client also removes marches that were already in flight at login /
scrolled out of the alliance's view.

**The `info` object** (union of all 60 keys seen):

```
uuid, teamUuid, holdUuid          this march; the rally-team id; the rally hold/assembly id
type, target, isAtk, status       kind; target-tile class; 1=attack 0=help/reinforce; lifecycle state
ownerUid, ownerName, ownerServer, ownerCurServerId, srcServer
allianceUid, allianceName, allianceAbbr, allianceIcon
power, armyWeight, squadNo, speed, combatInfos[]   attacker strength + squad (protobuf, base64)
ownerFormationUuid, fixedSoldierType, headSkinId, headFrame, ...
startPos, targetPos, path, mainPointId, diffPoint  geometry (path is "startPoint;targetPoint")
startTime, endTime                epoch-ms launch / arrival — ETA is endTime, or interpolate along path
tUid, tName, tAllianceAbbr, tResId, tHeadSkinId, tPicVer   the *target* (defender player or resource)
targetUuid, targetServer
pvpNum, pveNum, catchZombieNum, collectSpd, inBattle, isBroken   activity counters / flags
worldId, worldType, server, isAnonymity, isProto, src_action
```

`combatInfos` is a base64 protobuf per squad (hero ids, troop counts, tiers);
it decodes structurally like every other `_proto` blob, field names unknown.

**How a rally is distinguished from a solo march.** A rally is a coordinated
multi-member march: the leader opens it on a target, others join, and it sets
out as one army. On the wire the linkage is:

- **`teamUuid`** — non-zero and **shared** by the leader's and every joiner's
  alert. A solo march has `teamUuid = 0`.
- **`holdUuid`** — the rally hold / assembly point while it fills, `0` for solo.
- `target` / `targetUuid` point at the rally target; monster / boss rallies use
  the `push.world.march.world.get.new` monster stream in parallel (`type=2`,
  `monsterId`, see §7), and alliance-boss rallies also surface via
  `alliance.boss.act.info`.

**Historical note — no rally in `capture.pcapng`.** All 9 `alert.info.create`s
in the original saved capture are **solo PvP** marches (`teamUuid = holdUuid =
0`): an alliance-vs-alliance base war — `target=11` (player base), `isAtk`
alternating 1/0, `path` running base→base, `tName` the defender (e.g.
`Last Lollo → criss Lr`, `Big Boss Big → Last Lollo`). The rally-specific
values needed a **live capture taken while an alliance actually forms a rally**;
that capture has since been taken (below).

#### Live-confirmed rally structure (task #995)

A live 120 s passive capture (`tools/live_tshark.py` / raw `dumpcap` against
`<server-ip>:17935`, world 100, alliance <ALLY>) caught a full alliance rally
lifecycle. Raw pcap + decoded extract: `results/rally/rally_live.pcapng`,
`results/rally/rally_structure.json`.

The rally did **not** ride the `push.lw.alliance.alert.info.*` stream at all
(only bare `remove`s appeared there). It rode the **`push.alliance.march.*`**
family — the richer allied-march representation seen in captures A/B — which
carries the whole join→fill→launch sequence with the full member list inline:

| Command | Direction | Shape |
|---|---|---|
| `push.alliance.march.create` | server → client | a rally team is opened: `{uuid (==teamUuid), attackAllianceId, server/nowServer, targetPointId, targetContentId, targetUuid, targetUid, attackUid, attackName, attackPointId, leaderRank, leaderOffical, teamHasLight, assemblyMarchMax, waitTime/marchTime/waitMemberTime, fixedSoldierType, members:[], leaderMarch:{…}}` |
| `push.alliance.march.refresh` | server → client | same envelope, `members[]` now populated as joiners arrive — each a full march object carrying the **same `teamUuid` as `uuid`**; `waitMemberTime` advances |
| `push.alliance.march.remove` | server → client | `{teamUuid, isCancel}` — rally launched (`isCancel:false`) or cancelled |

Every **`push.world.march.new`** for a participating member also carries that
`teamUuid` (0 for solo marches), so the world-march stream alone already
distinguishes a rally: **≥2 distinct `ownerUid` sharing one non-zero
`teamUuid`**. In this capture two concurrent rallies were seen this way
(`teamUuid 1397117483466598347` — 2 owners; `…474986795` — the leader's team).

A **`…march`** object (`leaderMarch`, each `members[]` entry, and a
`world.march.new` payload) carries: `uuid, teamUuid, ownerUid, ownerName,
allianceId/Name/Abbr/Icon, power, curHp/maxHp, path ("startId;targetPos"),
startId, startTime, endTime, target, targetPos, status, headSkinId, armyInfo`.
`armyInfo` is a base64 protobuf squad (hero ids, troop counts, tiers) — decodes
structurally like every other `_proto` blob, field names unknown.

**How to distinguish rally from solo (confirmed).** `teamUuid != 0` on any
march / member entry ⇒ part of a rally team; the leader's `uuid` **is** the
`teamUuid` shared across the create, every refresh member, the remove, and all
members' `world.march.new`. `assemblyMarchMax` (5 here) caps the join count;
`waitTime`/`marchTime` is the launch deadline.

**To re-capture.** Passive sniff only (active RE is ACE-blocked; see
`socket-duplication.md` and the memory notes). Capture the game endpoint while a
rally runs, then grep the decoded transcript:

```bash
# archive raw (small, endpoint-only) — dumpcap.exe from WSL, iface from `tshark.exe -D`
dumpcap.exe -i 1 -f "host <server-ip> and port 17935" -a duration:120 -w rally.pcapng
python tools/lastwar_proto.py rally.pcapng --grep 'alliance.march|world.march.new' --json out.json
```

Filter for `teamUuid != 0` to isolate the rally from ordinary member marches.

## 8. Injected commands (task #973)

Commands verified for injection via the dup'd-socket path
(`tools/steal_via_socket.py --sniff-and-inject`). Prerequisites: VPN off,
game running, `PROCESS_DUP_HANDLE` granted (confirmed 2026-07-19).

### user.leave.world — return to base from world map

Source: `results/capture.transcript.json`, confirmed passive capture.

```
upstream:   user.leave.world  {worldId:0, serverId:<home>, _id:N}
response:   user.leave.world  {success:True, _id:N}
```

`worldId` is always `0` for the home server. `serverId` is the home server
(100). The reply carries a direct `success=True`, unlike `go.to.world` which
triggers a world-init stream with no echo.

Orchestrator: `tools/run_leave_world_inject.py`

```
/mnt/c/Python312/python.exe tools/run_leave_world_inject.py
```

### gather.collect.reward — collect world-map gathering resources

Source: `results/live_5min.log`, observed upstream frame.

```
upstream:   gather.collect.reward  {uuidArr:[<march_uuid>,...], _id:N}
response:   gather.collect.reward  {reward:[...], collect_reward:[], _id:N}
            push.resource.item.update  {resource_items:[...]}
```

`uuidArr` contains the UUIDs of completed gathering marches (troops that
returned from a resource node). Obtain UUIDs from `tools/dev/scan_trucks.py` or
by sniffing live march data (`tools/live_tshark.py`).

Orchestrator: `tools/run_gather_inject.py`

```
/mnt/c/Python312/python.exe tools/run_gather_inject.py --uuid-arr 1394584906709054020
```

### building.production.collect — collect a base building's output (task #974)

Source: `results/task967/trap_all_up_974.jsonl`, trapped live 2026-07-21 by
logging every upstream command while a human tapped the green resource bubbles
on the base screen. The command is `building.production.collect`, one frame per
production building (farm / sawmill / mine / oil / steel):

```
upstream:   building.production.collect  {uuid:<building_uuid>, _id:N}
response:   building.production.collect  {...}
            push.resource.item.update  {resource_items:[...]}
```

The only parameter is `uuid` — the per-building UUID (not a tile field). Tapping
several bubbles produced five frames with distinct UUIDs:

```
building.production.collect {uuid=1156814436946922740}
building.production.collect {uuid=1156814232810146863}
building.production.collect {uuid=1156814232810146864}
building.production.collect {uuid=1156814649652661249}
building.production.collect {uuid=1156814562004290613}
```

Two neighbours fire alongside the base collect and are worth noting:
`lw.pve.idle.reward {action:0}` (idle-production reward) and
`gm.gain.item {resource:[…]}`.

Why the earlier narrow trap missed it: `tools/trap_resource_collect.py` filters
on the substring `collect` plus a candidate list plus a novel-vs-vocabulary
check. `building.production.collect` *does* contain `collect`, so a fresh run of
that trap during a tap would now catch it — the first attempts simply didn't
land a tap inside the capture window (the game keeps stealing foreground from a
scripted click). The reliable method was `tools/trap_all_up.py`, which logs
*every* upstream command with no filter.

Builder: `build_building_collect_frame` in `tools/steal_via_socket.py`.
Orchestrator: `tools/run_collect_inject.py`

```
# get a building UUID by trapping one manual collect:
/mnt/c/Python312/python.exe -X utf8 tools/trap_all_up.py --seconds 60 \
    --tshark "C:\Program Files\Wireshark\tshark.exe" \
    --dumpcap "C:\Program Files\Wireshark\dumpcap.exe"

# then inject (repeat --uuid for several buildings):
/mnt/c/Python312/python.exe tools/run_collect_inject.py --uuid 1156814436946922740
```

## 10. Embedded protobuf

`0x0a` blobs carry protobuf messages with no shipped `.proto`. The decoder
emits best-effort `{f1: …, f2: …}` field maps alongside the raw hex.

Map tiles (`serverPointArr[].points[]`) decode as:

```
f1  = packed tile coordinate       f6  = {f1: contentId, f2: kind}
f2  = terrain / tile type          f102, f103 = serverId
```

March blobs (`push.world.march.new._proto`) embed the player name, alliance id
and per-squad hero lists in nested LEN fields.

## 11. Open questions

- **Is there a second game endpoint?** Answered. Gameplay, chat and map all
  ride one connection — even a cross-server jump reuses it. At login the client
  races **three** gateways on the same port 17935 and keeps one; there is no
  separate auth server and no separate chat server. The only genuinely distinct
  services are the asset CDN and the chat **translation** endpoint, both TLS.
- **What does a rob request look like?** Unanswered, and not answerable from
  what is here: the captured account never robbed anything, so no
  `hero.dispatch.rob.*` — under that or any other name — appears in any
  capture. The 153 client commands seen include only `hero.dispatch.list`,
  `hero.dispatch.alliance.list` and `hero.dispatch.treasure.v2.get.info`. It
  takes one live capture of a human robbing a task by hand:
  `tools/trap_command.py --match hero.dispatch`, which also flags any command
  outside the known vocabulary in case the name is nothing like the guess.
  This is the blocker on task #882.
- **Is `push.chat` ever seen for an outgoing DM?** No — only the request and
  its ack. Confirming the broadcast shape for a direct message needs a capture
  on the *receiving* account.
- **DNS answers look proxied.** In capture B, `lastwar-cdn.lastwarapp.net` and
  `count.perplexity.ai` resolved to the *same* pair of IPs, and the capture is
  full of `198.18.x`/`198.19.x` benchmark-range addresses. Combined with the
  `<server-ip3>:50080` tunnel, that suggests DNS is being answered
  synthetically by a VPN client — so do not treat IP↔domain mappings from this
  capture as authoritative.
- **`<server-ip3>:50080`** dominates by volume and is unidentified. Attribute
  it to a PID with `Get-NetUDPEndpoint` / `netstat -b` on the Windows side
  before concluding anything. If it is a tunnel, part of the capture may be
  traffic that is also visible in cleartext elsewhere.
- **Tencent flows** (`129.226.x` TCP/80 and UDP/8081) are undecoded. Low value
  — they look like SDK telemetry and NAT probing, not gameplay.
- **Where do monsters come from?** Answered — see §7. They are not on the wire
  at all; placement is client-side. What remains unknown is the generation rule
  itself, which would have to come from the game assets, not from traffic.
- **What draws the star on a secret task?** Ruled: `cfgId` family `6000` — see
  §7, which also records the one observation (a reported starred *level-4*
  task) that the rule does not yet explain. It is not a wire field, so the
  reading can only ever be re-tested against the screen:
  `tools/live_tshark.py --tasks --families`.
- **Chat-shared coordinates can be off by one** from the matching tile
  (`x=189` shared, tile at `190`). Click point vs tile origin, or a
  zero/one-indexing difference — unresolved, and it matters for navigating by
  coordinates taken from chat.
- **`uname` in a shared secret task** arrived as `"????????"`. Either the game
  masks the owner's name in a share, or the encoding is lost somewhere in this
  pipeline; not distinguished yet.
- **Protobuf field names are unknown.** Blob contents decode structurally
  (`f1`, `f2`, …) but there is no `.proto`, so semantics are inferred from
  context. Map-tile fields are guesses.
- **Tags `0x06` / `0x07`** (float / double) are inferred from the numeric
  progression of the tag table; no observed value has confirmed them.
- **Flag combinations `0xa0` (server+zlib) and `0xf4` (client+zstd)** are
  predicted by the bitfield but never observed; the decoder handles them, but
  that path is untested.
- **The live summary's "unknown TLV tags" block over-reports** — it counts tags
  from frames the decoder itself threw away during resync, and its wording
  ("the protocol has changed, update docs/research/protocol.md") invites
  writing fiction into this file. Mechanism and reproduction in §3. Fixing it
  means either restoring the counter around the `BadTag` catch in
  `iter_frames()` the way `is_game()` does, or only counting tags from frames
  whose length field is corroborated by the next frame starting where this one
  ended. Not done here — the report is misleading, not wrong-by-omission, and
  the fix has a real trade-off: blanket suppression would also hide a genuine
  new tag, since a real frame carrying one is discarded by the same path.

Note on an earlier misreading: the frame header was once described as
"8 bytes, K1 = payload[4], K2 = payload[3], mask by `i % 4`". That is wrong
and superseded by §2 — headers are 3 bytes (server) / 5 bytes (client), and
the mask indices count from the **body** start, not the packet start. The old
description happened to work only because the arithmetic coincided for the
one packet shape it was derived from.

## 12. Relationship to the "no protocol RE" decision (task #366)

Task #366 rejected protocol work because ACE kernel anti-cheat makes it
impractical. That conclusion was about **active** techniques — MITM, pinning
bypass, Frida injection — all of which touch the game process and are exactly
what ACE detects.

Everything in this document came from a **passive** capture of the host NIC. No
injection, no cert tampering, no process interaction. `network-protocol-
sniffing.md` §71 already rated passive capture as safe but assumed it "decodes
nothing without keys" — that assumption is wrong here, because the transport is
not TLS.

This is a capability note, not a decision to act. Reading `world.get.block`
responses off the wire would replace the screenshot+OCR world scan with exact
data, but it is a materially different posture from vision-only automation.
Flagging for the maintainer, not proceeding.

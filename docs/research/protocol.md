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
`3.33.246.23:17935` (AWS Global Accelerator). The client dials the accelerator
IP directly with **no preceding DNS lookup**, so SNI/DNS filters will not find
it — filter by frame shape or port instead.

Gameplay, chat, alliance events and map queries all multiplex over this
**single connection** — `push.chat` is not a separate endpoint. Two auxiliary
services do live elsewhere, both over ordinary TLS: a CDN for assets and a
**chat translation** service. Neither carries gameplay.

Two captures were analysed: capture A (173 s) and capture B (60 s, with
cross-server travel). The first showed no DNS at all for the game; the second
resolved three `lastwar` domains, so DNS is worth collecting even though the
main connection still dials a bare IP.

| Flow | Volume | What it is |
|---|---|---|
| **TCP `3.33.246.23:17935`** | 23 KB up / 388 KB down | **The game.** Everything below decodes from this one connection. |
| TCP `129.226.1.157:80` | 14 KB up, 0 down | Tencent Cloud. Custom framing on port 80, not HTTP. Telemetry/SDK — undecoded, and it never gets a reply. |
| UDP `129.226.1.x:8081` | ~7 KB | Tencent Cloud SDK. High-entropy, undecoded. |
| UDP `129.226.1.157:137`, `101.32.143.x:137` | ~1.6 KB | NetBIOS-shaped `CKAAAA…` wildcard queries — SDK NAT-type probing. |
| UDP `72.56.113.52:50080` | 21 892 pkts, 10.9 MB | **Not the game.** Header `48000001` + counter + max-entropy body, 1444 B MTU cap — reads as a VPN/tunnel. See open questions. |
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

Bytes 1–2 are the **serverId** (observed `0x03a7` = 935), not a length. `K1`
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
tag is confirmed: across both captures the decoder consumes **100% of the
bytes of every reassembled game stream with zero unknown tags**.

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

Union of both captures — 33 distinct client commands. Still not exhaustive:
capture B added 29 commands that capture A never showed, so each new activity
surfaces more. Responses echo the request's command name.

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
| `get.user.info.multi` | `uids`, `allservers` |
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

## 6. Login sequence

The client races **three gateways on port 17935 in parallel** and keeps the
fastest; the losers get one handshake and are dropped. Observed in capture C:

| Gateway | Provider | Role |
|---|---|---|
| `15.197.233.176:17935` | AWS Global Accelerator | winner — carried the whole session |
| `172.65.210.24:17935` | Cloudflare | probed, 1 frame, dropped |
| `34.145.128.94:17935` | Google Cloud | probed, 1 frame, dropped |

**The game IP is not stable.** Capture A used `3.33.246.23`, capture C used
`15.197.233.176`, and in C the old address served plain TLS instead. Never
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
1.36  --> common.chat.room.id                  -> country_935, custom_lang_ru_935
1.49  --> login.other {alliance}               -> full alliance record
1.58  --> login.ext   {hardware fingerprint}   -> {success: true}
1.49-2.5 ~90 parallel UI-population calls (activities, shops, heroes, season…)
2.64  --> meteorite.enter.world                 enter the world map
```

`init` is the whole account state in one frame — 243 top-level keys covering
items, heroes, vip, science, shops, settings and more. It is the reason the
`0x08` uint32-length flag exists.


### Chat

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
{"posType":2, "oname":"300602", "olv":6, "x":636, "y":547, "sid":935}

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
992, 1038 and 8120 — `meteorite.enter.world` fires for several `targetServerId`
values and `world.get.block` for several `serverId` values. A reader that
assumes one server per jump will mis-attribute tiles; the `serverId` inside
each `serverPointArr` block is authoritative, not the jump target.

Five commands first appeared during such a jump and are season/train scoped:
`get.server.state`, `lw.season.rq.info`, `train.march.get.pos`,
`train.refresh`, `zwl.get.target.act.info`.

## 7. World map semantics (`world.get.block`)

### Zoom

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

To lift a tile to world space, add the server's origin — the requested corner
rounded down to the local grid:

```python
ox, oy = (gx // A) * A, (gy // A) * A     # gx, gy = request leftBottom unpacked
world_x, world_y = ox + (f1 % A), oy + (f1 // A)
```

Verified: **6373/6373 tiles land inside their requested box** under this model.

### Object types (`f2` on each tile)

| `f2` | Count | What it is | Key fields |
|---|---|---|---|
| 7 | 1710 | **Resource mine** | `f6.f1` = `family*100 + level`, `f6.f8` = occupier uid, `f6.f9` serverId, `f6.f10` allianceId |
| 6 | 1116 | **Player base** | `f3.f14` name, `f3.f15` alliance abbr, `f3.f4` HQ level (4–35), `f3.f27` country, `f3.f1` uid, `f3.f7` allianceId |
| 17 | 224 | **Secret task / hero dispatch** — see below | `f10.f2` cfgId, `f10.f1` owner, `f10.f4` stealers, `f10.f8` expiry |
| 11 | 34 | Stronghold / fortress (fixed 100-tile grid) | `f101.f3` level (1/5/7), `f101.f8` reward, `f101.f1` template |
| 25 | 17 | Named facility held by a player | `f101.f5` player name, `f101.f10` alliance name |
| 21 | 4 | Alliance HQ | `f11.f12` alliance name, `f11.f6` abbr, `f11.f7` member uid list |

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
| `f10.f10` | flag, `1` or `3` | **unexplained** |
| `f102` / `f103` | serverId | `targetServer` |

**Level** is not a field of its own — it is the third/fourth digit pair of
`cfgId`, read as `LLVV` (level, variant): `50000704` = level 7 variant 4,
`300502` = level 5 variant 2. Observed levels 1, 3, 4, 5, 6, 7 — plus a
`6000 99xx` group (108 tiles) that does not fit the reading. That group is
one-per-player with a distinct template range, so it is probably a different
task class rather than "level 99".

**Robbery count** is the length of `f10.f4`: absent → 0, then 1, 2 or 3.
**The maximum is 3** — no tile or dispatch record in 636 tiles / 144 records
exceeded it, and `stealInfoList` lengths were only ever 0, 1 or 3.

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

**Open question — the prospective reward.** Nothing in these captures shows the
payout *before* a steal, because the captured account never opened a task it
did not own. To get it, capture a session that taps another player's task
marker and opens the detail panel; the request that fires there (something in
the `hero.dispatch.*` family, keyed by the task `uuid`) is the one to look for.
Failing that, the reward table may simply be client-side config, in which case
it will never appear on the wire and has to come from the game assets.

## 8. Embedded protobuf

`0x0a` blobs carry protobuf messages with no shipped `.proto`. The decoder
emits best-effort `{f1: …, f2: …}` field maps alongside the raw hex.

Map tiles (`serverPointArr[].points[]`) decode as:

```
f1  = packed tile coordinate       f6  = {f1: contentId, f2: kind}
f2  = terrain / tile type          f102, f103 = serverId
```

March blobs (`push.world.march.new._proto`) embed the player name, alliance id
and per-squad hero lists in nested LEN fields.

## 9. Open questions

- **Is there a second game endpoint?** Answered. Gameplay, chat and map all
  ride one connection — even a cross-server jump reuses it. At login the client
  races **three** gateways on the same port 17935 and keeps one; there is no
  separate auth server and no separate chat server. The only genuinely distinct
  services are the asset CDN and the chat **translation** endpoint, both TLS.
- **Is `push.chat` ever seen for an outgoing DM?** No — only the request and
  its ack. Confirming the broadcast shape for a direct message needs a capture
  on the *receiving* account.
- **DNS answers look proxied.** In capture B, `lastwar-cdn.lastwarapp.net` and
  `count.perplexity.ai` resolved to the *same* pair of IPs, and the capture is
  full of `198.18.x`/`198.19.x` benchmark-range addresses. Combined with the
  `72.56.113.52:50080` tunnel, that suggests DNS is being answered
  synthetically by a VPN client — so do not treat IP↔domain mappings from this
  capture as authoritative.
- **`72.56.113.52:50080`** dominates by volume and is unidentified. Attribute
  it to a PID with `Get-NetUDPEndpoint` / `netstat -b` on the Windows side
  before concluding anything. If it is a tunnel, part of the capture may be
  traffic that is also visible in cleartext elsewhere.
- **Tencent flows** (`129.226.x` TCP/80 and UDP/8081) are undecoded. Low value
  — they look like SDK telemetry and NAT probing, not gameplay.
- **Where do monsters come from?** Answered — see §7. They are not on the wire
  at all; placement is client-side. What remains unknown is the generation rule
  itself, which would have to come from the game assets, not from traffic.
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

Note on an earlier misreading: the frame header was once described as
"8 bytes, K1 = payload[4], K2 = payload[3], mask by `i % 4`". That is wrong
and superseded by §2 — headers are 3 bytes (server) / 5 bytes (client), and
the mask indices count from the **body** start, not the packet start. The old
description happened to work only because the arithmetic coincided for the
one packet shape it was derived from.

## 10. Relationship to the "no protocol RE" decision (task #366)

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

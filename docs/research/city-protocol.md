# City (base) protocol — what the wire shows on a City↔World switch

Enumerate base entities (buildings, troops, resources, build queues) from the game
protocol. Two findings:

1. **Scene switch carries nothing (§ below).** On a *warm* (already-logged-in) client,
   switching World→City transmits **no base data** — the server sends zero application
   payload. Base state is cached client-side; `SceneUtils.ChangeToCity()` is a local render.
2. **The login cold-load carries the whole base (§ "Cold-load login").** Killing and
   relaunching the client, capturing from the fresh TCP handshake, yields a **282 KB down
   snapshot** whose `init` message (≈417 KB decoded, 243 keys) contains every base entity:
   205 buildings with type/level/position, army formations, resources, queues, wall, lands,
   workers, heroes, science. **This is where base data lives on the wire.**

This is a companion to `protocol.md` (framing/transport) and
`game-launch-and-scene-control.md` (the Lua scene switch used to drive the transition).

## Method (exact sequence run)

1. Game already running and logged in (pid 35688), scene = **World**.
2. Started a passive sniffer, then switched to City *during* the capture, then waited
   for the client to settle. Two capture passes:
   - **Pass A** — `tools/dev/secret_task_capture.py --seconds 60 --dump results/city_capture.jsonl`
     (scapy/npcap, `--dump` = full decoded transcript, both directions) while firing
     `tools/lua_goto_world.py --to-city` (World→City).
   - **Pass B** — `dumpcap.exe -i 1 -i 2 -i 13 -f "tcp port 17935" -a duration:50 -w
     results/city_capture2.pcapng` (raw pcap on the physical Wireless + bridge +
     vEthernet interfaces at once) while doing a City→World→City round-trip, then decoded
     offline with the robust decoder: `tools/lastwar_proto.py results/city_capture2.pcapng
     --json results/city_decoded2.json`.

The scene switches were confirmed from the game's own Lua flags (Player.log markers):
`GetIsInWorld`/`GetIsInCity` flipped as expected each time.

## The decisive finding — the server sends nothing on a scene switch

`tshark` direction analysis of the raw pcap (`results/city_capture2.pcapng`), game flow
`172.65.210.24:17935`:

| direction | frames with TCP payload |
|---|---|
| client → server (up) | **51** |
| server → client (down) | **0** |
| total game-port frames | 102 (51 requests + 51 bare ACKs) |

The server **ACKs** every client packet (so the down direction *is* being captured — this
is not an asymmetric-routing miss) but sends **0 bytes of application payload**. The first
pass agreed independently: `up 1,728B / down 0B`.

Interface caveat learned along the way: capturing only on the Hyper-V `vEthernet` adapter
(`\Device\NPF_{6FEC8683…}`, dumpcap `-i 13`) sees **only the outbound** direction; the
physical Wireless/bridge adapters (`-i 1 -i 2`) see both — but even there the game server's
down payload was 0. So the negative result is real, not a capture artifact.

**Re-confirmed on a clean World→City entry** (`results/city_entry.pcapng`): started in
World, sniffer up, then a single `SceneUtils.ChangeToCity()` — a *real* base entry, not a
round-trip. Result identical: **75 up / 0 down** payload frames (150 total = 75 requests +
75 bare ACKs). Crucially, entering the base generated **no city-side request at all** — no
`user.enter`/`city.*`/`build.*`, only `user.leave.world` plus world-teardown queries. The
City entry is a pure client-side render from the cached base model; the network is not
consulted for base state. Three independent captures now agree.

**Conclusion:** buildings, troops, resources, NPCs and build queues were **not** observed,
because that data does not cross the wire on a City↔World switch. It is part of the base
snapshot the client receives **once at login** and then keeps; re-entering the base renders
from the cached model without a server round-trip.

## What the capture *did* contain — client→server request schemas

The only game payload seen was client→server: a 4-second **keepalive** and a handful of
**world**-side requests fired while leaving/entering the world map. None of these are
base/city entities, but the schemas are useful protocol intel. Observed field sets and
example values (server IDs / coords are from this account's session):

| command | fields (example values) | notes |
|---|---|---|
| `(keepalive)` | `clientTime` (ms, monotonic) | ~every 4 s, action 29/13 |
| `user.leave.world` | `serverId=935, worldId=0, _id` | fired on World→City |
| `go.to.world` | `_id` | world-entry handshake |
| `world.get.block` | `bigMap=1, x=2561, y=2492, serverId=935, worldId=0, type=0, viewLvl=0, timeStamp, blockSize=10, index=[74354,74355,…], clearUuidSet=1, leftBottom=7412541, rightTop=7532581, _id` | **world-map tile query** — `index[]` is the list of tile IDs in the viewport; `leftBottom`/`rightTop` bound the block; `blockSize=10` tiles/side. This is the map-scan request `secret_task_capture` etc. rely on. |
| `world.get.march.infos` | `x=561, y=492, needCross=true, _id` | march/troop info at a world coord (the closest thing to "troops" seen, but world-side, not base) |
| `meteorite.enter.world` | `targetServerId=935, _id` | server/event enter |
| `world.flag.get.can.effect` | `worldId=0, _id` | alliance flag effect check |
| `surprise.point.get.info` | `_id` | world event point |
| `get.world.news.info` | `_id` | world news feed |

Every request carries an incrementing `_id` (per-connection request counter). No response
bodies were captured (see above), so field *types* here are from the request side only.

## How to actually capture base/city entities

Since the base snapshot is a **login cold-load**, the only reliable way to see buildings /
troops / resources / build queues on the wire is to **capture across a fresh login**:

1. Start the raw pcap first (`dumpcap -i 1 -i 2 -f "tcp port 17935" -w login.pcapng`,
   physical interfaces so the down direction is present).
2. *Then* start the game (cold), or force a re-login, so the full base+world state burst
   is on the wire.
3. Decode offline with `tools/lastwar_proto.py login.pcapng --json login.json` and look at
   the **server → client** messages (the down direction, empty here) for the base
   snapshot — command names likely `user.*` / `city.*` / `build.*` rather than `world.*`.

That is a more invasive run (it kills/relaunches the single-session client and risks an
account kick). **It was subsequently carried out with explicit sign-off — see the next
section, which is the real answer to the task.**

## Cold-load login — the full base snapshot (the `init` message)

Ran the invasive path with sign-off: started `dumpcap` on the physical interfaces first
(so the fresh TCP handshake is captured — mid-stream reassembly is why earlier down
directions decoded poorly), then killed `LastWar.exe` and immediately relaunched it, and
let it auto-log-in.

```bash
# 1. capture FIRST, per-interface filter (a lone -f binds only to the preceding -i)
dumpcap.exe -i 1 -f "tcp port 17935" -i 2 -f "tcp port 17935" -i 13 -f "tcp port 17935" \
            -a duration:240 -w results/coldload_login.pcapng
# 2. kill + relaunch (from the game's own dir)
taskkill /F /IM LastWar.exe ; ( cd "…/Last War-Survival Game/Game" && ./LastWar.exe & )
# 3. wait for full login (~120 s) + settle, then decode
lastwar_proto.py results/coldload_game.pcapng --json results/coldload_decoded.json
```

**The game server IP is not stable** (dialled without DNS): the cold session connected to
`3.33.246.23:17935`, not the previous `172.65.210.24`. Filter by **port**, then pick the
17935 peer with the most bytes. That flow carried **up 22,934 B / down 282,934 B** across a
fresh connection (2 conns, 12 SYNs seen). Decoded: 528 messages, **303 server→client**.

The whole base arrives in **one `init` push** (server→client): ≈417 KB decoded (zstd on the
wire), **243 top-level keys**. Everything below is a field of `init` unless noted. Times are
epoch-ms; `9223372036854775807` (int64 max) = "none/never".

### Buildings — `init.building_new` (205 entries, 119 distinct types)

Each building:

| field | meaning |
|---|---|
| `bId` | building **type / config id** (e.g. `10113000`, `10117000` = functional; `1034xxxx`/`1035xxxx` = decorations, carry extra `decorNum`/`prodExtend`) |
| `lv` | **level** (observed range 0..35) |
| `pId` | **grid position id** — packed base-grid coordinate (e.g. 6531, 7261, 4553) |
| `uuid` | per-instance id |
| `hp` | building hit points (10000 = full) |
| `lCT` | last construct/complete time | 
| `lStaT` | last state-change time |
| `pEndT` | production-end time (int64-max = idle) |
| `gValT` | grid-value time |

Example rows:
```json
{"bId":10113000,"lv":24,"pId":6531,"hp":10000,"lCT":1728282623110,"pEndT":9223372036854775807,"uuid":1156814623094328384}
{"bId":10117000,"lv":34,"pId":4553,"hp":10000,"lCT":1728282614164,"uuid":1156814623085939934}
{"bId":103418000,"lv":2,"pId":7261,"decorNum":1,"prodExtend":1,"uuid":1275390269264743564}   // decoration
```
Companions: `world_building` (1, same schema — the base's world-map tile) and
`buildingRoads_new` (56 — `pId`,`uuid`, the road tiles between buildings).

### Build / train queues — `queue_new` (12) + `buildQueue`

`buildQueue = {"hasTrial":0,"maxTrial":2}` (build-queue trial slots). The live queues are
`queue_new`, one entry per queue slot:

| field | meaning |
|---|---|
| `qid` | queue id |
| `type` | queue kind (observed 0, 6, 13, 120 — construction / training / research / heal etc.) |
| `itemObj` | `{itemId}` currently in the slot (empty if idle) |
| `sT` | start time; `expireTime`; `unlock`; `isHelped`; `uuid`,`funcUuid` |

```json
{"qid":3,"type":6,"itemObj":{"itemId":"70006300"},"sT":1784410838120,"isHelped":1,"uuid":1265243863543696469}
{"qid":1,"type":13,"itemObj":{},"unlock":1,"uuid":1161210165501086753}
```

### Resources — `init.resource` (+ `resource_items`)

`resource` is a flat balance dict (this account, matches the on-screen HUD):

```json
{"money":367790725,"metal":350665019,"wood":213524231,"petroleum":15043807,
 "dragonHonorScore":10500,"obsidian":0,"electricity":0,"water":0,"people":0,"oil":0,"flint":0}
```
`resource_items` (22) — consumable resource stacks: `{itemId, number, uuid}` (e.g.
`itemId 6001 × 2,878,883`).

### Troops, hospital, heroes

- **`army_formation` (3)** — one per squad/army: `buildingUuid` (which building houses it),
  `heroes` (5 × `{heroUuid,index}`), `soldiers` (unit stacks; empty when fully deployed),
  `index`, `ownerUid`, `defencePriority`, `slots`, `chipEquipGroup`, `state`. Sibling
  formation lists: `scout_formation` (3), `formation_template` (14), plus empty
  `defend_formation`/`battlefield_formation`/`resource_formation`.
- **`hospital` (15)** — wounded per unit type: `{armyId, heal, dead}` (all 0 = no wounded).
  `rebirthHospital` (4) is the severe-wounded/rebirth pool.
- **`userHero` (31)** — roster: `{heroId, lev, rankLv, awakenLv, skills, weaponInfo, state, uuid}`
  (e.g. heroId 50017 lev 175 rankLv 26).

### Rest of the base

- **`defend_wall`** — `{durability:10000, morale:3000, protectEndTime, fireEndTime, cityBroken:false}`.
- **`lands` (48)** — surrounding land plots: `{id, state}` (state 3 = cleared/owned).
- **`workers`** — `workerLottery{curNum:30}` + `list[]` of assigned workers (`uid, cfgId, rank, effect, status`).
- **`science_new` (299)** — research tree: `{itemId, level}`.
- **`items` (467)** — full inventory (`itemId, count, para1..3, uuid`).
- Power breakdown lives in **`get.new.user.info`** / **`new.get.info`** (`baseLevel`,
  `baseArmyPower`, `buildingPower`, `buildingWorkerPower`, `armyPower`, `allArmyUnitNum` …).
- Other players' bases arrive via **`get.user.info.multi`** (`mainBuildingLevel`, `armyPower`,
  `position` …); alliance/world city objects via `city.war.get.info`, `world.get.alliance.building`.

### Takeaway

The base is a **login cold-load**, delivered as a single `init` push on the game TCP
connection right after the handshake, then mutated by incremental pushes during play. To
read buildings/troops/resources/queues you **must** capture across a fresh login (or a
forced reconnect) — never from a warm scene switch. Field *names* are stable and
self-describing; `bId`→building-type and `pId`→grid-position still need a config table
(from the game's encrypted config) to render as human names/coordinates.

## Artifacts (local, git-ignored under `results/`)

- `results/city_capture.jsonl` — pass A decoded transcript (20 frames, all up).
- `results/city_capture.pcapng` — pass B single-interface raw pcap (up only; interface lesson).
- `results/city_capture2.pcapng` — pass B multi-interface raw pcap (both directions; server down payload = 0).
- `results/city_decoded.json`, `results/city_decoded2.json` — offline `lastwar_proto` decodes.
- `results/city_entry.pcapng`, `results/city_entry.json` — dedicated clean World→City entry (75 up / 0 down; no city-side request).
- `results/coldload_login.pcapng` — full cold-login capture (3 interfaces, from fresh SYN).
- `results/coldload_game.pcapng` — the game flow extracted (`3.33.246.23:17935`, one interface, deduped).
- `results/coldload_decoded.json` — 528 decoded messages incl. the 243-key `init` base snapshot.

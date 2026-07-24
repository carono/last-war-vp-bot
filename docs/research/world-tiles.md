# World-map tiles — `world.get.block` kinds, and where monsters actually live

Goal: enumerate world-map tile kinds (`world.get.block` `f2`) beyond the known
`6/7/17/29`, and find the monster tiles. Method (strict): passive sniff first
(`tools/secret_task_capture.py --seconds N --dump`), then `SceneUtils.ChangeToWorld()`
via `tools/lua_goto_world.py`, then pan the map with `pydirectinput` drags to force new
`world.get.block` fetches. Three captures (120 s + 90 s wide sweep + 70 s over a
monster-containing view), 242 tiles total.

**Headline:** the only *new* block kind is **`f2=25` = alliance city**. Roaming
**monsters are NOT `world.get.block` tiles at all** — they are a separate world-entity
system on their own streams. The task's guess (monsters at `f2=8/9/10`) conflated the
wire `f2` with the *client* `LWWorldMonsterType` enum (below), which is numbered
differently.

## `world.get.block` response shape

`down world.get.block` → `serverPointArr[] → points[]`, each point a protobuf tile:

| field | meaning |
|---|---|
| `f1` | packed world point id (the map coordinate; `x = p % 1000`, `y = p // 1000` per `lastwar_proto`) |
| `f2` | **tile kind** (see table) |
| `f102`, `f103` | serverId (935 here) |
| kind-specific sub-message | the entity's attributes — **`f3` (base) / `f6` (mine) / `f10` (task) / `f101` (city)**, not a fixed `f14` |

There is **no top-level `f14`**; the "attributes in `f14`" are inside the kind's
sub-message (e.g. a base's `f3.f14` is the owner's name).

## Tile kinds seen (242 tiles, 3 captures)

| `f2` | count | kind | attribute sub-message (key fields) |
|---|---|---|---|
| 6 | 96 | **base** (player city) | `f3`: `f3`=HQ bId (`10100000`), `f4`=base level (35), `f14`=owner name (`"armaca"`), `f15`=alliance abbr (`"TLou"`), `f7`=alliance uuid, `f2`=player uuid, `f13`=10000 |
| 7 | 97 | **mine / resource node** | `f6`: `f1`=amount/level, `f2`=1 |
| 17 | 47 | **secret_task** (raidable SecretTask) | `f10`: `f2`=cfgId (`400703`), `f8`=expiry ms, `f9`=alliance uuid, `f100`=tile uuid |
| 25 | 2 | **alliance city** ⟵ NEW | `f101`: `f10`=alliance name (`"The New Dawn"`), `f5`=alliance tag (`"CIan"`), `f4`=owner uid, `f7`=alliance uuid, `f15`=server, `f19`=`{uuid,pos,state,…}` |

(`f2=29` = ghost_recon is known from prior work but did not appear in this area.)
Example new-kind tile:
```json
{"f1":499600,"f2":25,"f100":1356530359877216252,
 "f101":{"f1":1670,"f4":1779285600,"f5":"CIan","f7":"c14a…","f10":"The New Dawn",
         "f15":935,"f19":{"f1":"1356530359877216252","f3":499600,"f4":3,"f9":1},"f20":"6"},
 "f102":935,"f103":935}
```

## Monsters are a separate system (not block tiles)

The world view visibly has monsters — `results/world_view.png` shows two roaming
monsters tagged **lvl 19** and **lvl 22**, and the chat ticker names a **lvl 130
Zombie-Boss** — yet none of the 242 captured tiles is a monster. Panning back and forth
over the monster-containing view (3rd capture) still yielded only `6/7/17/25`. So
monsters are fetched/pushed independently of `world.get.block`.

### The client world-entity enum — `LWWorldMonsterType` (from Lua)

`DataCenter` exposes the display-type enum for all world entities (read live via
`tools/lua_eval.py`):

```
ResMetal=1  ResFood=2  Boss=3  City=4  ResGold=5  Radar=6  MonsterInvade=7
RunningMonster=8  ResObsidian=9  ResFlint=10  FlowerCar=13  S4Tank=14  S4Airplane=15
S4Missile=16  S4Boss=17  S4TankBN=18  S4AirplaneBN=19  S4MissileBN=20  S4BossBN=21
S4RunningBoss=22  Lockhart=1001
```

Monsters are **`Boss=3`, `MonsterInvade=7`, `RunningMonster=8`** (plus the seasonal
`S4Boss/S4RunningBoss`). **This is a client enum and does NOT equal the wire `f2`** —
e.g. wire `f2=6` is a base but `LWWorldMonsterType 6` is `Radar`; wire `f2=7` is a
resource mine but the enum `7` is `MonsterInvade`. Do not map one onto the other.

### Monster streams and managers observed

| message / manager | role |
|---|---|
| `push.running.boss.del` (and `.new`/`.add`) | roaming boss lifecycle (the lvl-19/22 "running monsters") |
| `monster.invasion.boss.detail` | per-boss detail query → `{uuid, ownerName:"ofbi", allianceUid, allianceAbbr:"TLou", isProtected}` |
| `push.al.zombieRushPoint.change` | alliance zombie-rush spawn points → `{zombieRushPoint, allianceId}` |
| `push.world.march.new` / `push.world.march.world.get.new` | marches (some target monsters; blob carries name, coords `x;y`, difficulty `"Normal"`, hero squad) |
| `surprise.point.get.info` | event/surprise points (empty this run) |
| Lua: `DataCenter.MonsterManager` | kill-boss counters / max attackable level (`GetCurCanAttackMaxLevel`) |
| Lua: `DataCenter.MonsterTemplateManager` | monster config templates (level → attributes) |
| Lua: `WorldPointDetailManager` | per-point detail cache (`GetDetailByPointId`) |
| Lua: `KillZombieCtrlManager`, `MonsterProtectionManager`, `MonsterLockDataManager`, `LWZombieRushManager`, `LWBerserkBossManager`, `S0/S4/Season BossDataManager` | specific monster/boss subsystems |

The roaming-monster **list** was already resident when the world loaded (like the base
cold-load in `city-protocol.md`) and is maintained by `push.running.boss.*`; it is not
re-sent on a pan, which is why the sniff never caught it as a tile. To capture the list
fresh, sniff across a cold world-enter or a `monster.invasion`/running-boss query, or
read it live from the managers above.

## Artifacts (git-ignored under `results/`)

- `results/world_tiles_capture.jsonl`, `world_tiles_capture2.jsonl`, `world_monsters3.jsonl` — the three decoded captures.
- `results/world_view.png` — world map screenshot showing the lvl-19/22 roaming monsters absent from the block tiles.

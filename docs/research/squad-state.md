# Squad state and stamina — where the game keeps them

What every squad is doing right now, and how much stamina is left, read straight off the
game's Lua VM through the warm daemon. No pcap, no UI, no window opened: this is a read
of the client's own data managers, so it works headless and beside any other action (a
read does not take the game's lease).

Everything below was read live off a running client (task #1222, daemon on 47654). The
recipe that does it is [`actions/read_squad_state.md`](../../src/lastwar_bot/actions/read_squad_state.md);
the panel's side of it is `panel/runtime/squads.py`.

## Why it is needed

A rally is raised BY a squad. So is a gather, so is an attack. A send with the squad
already out is not refused early — the search runs, the target's window opens, the squad
screen comes up, and the game says no at the last press, minutes after the operator
asked for it. Same for the stamina pool: a run started with none of it left cannot
finish. Both facts are one read away, and neither was being read.

## The squads

`DataCenter.ArmyFormationDataManager` is an ordinary Lua class (not a C# object — its
methods live in its metatable's `__index`, so `pairs()` on the manager itself does not
show them). Its `ArmyFormationList` is keyed by uuid, and each entry is one squad:

| field | meaning |
|---|---|
| `index` | the squad slot the player sees (1 / 2 / 3 …) |
| `uuid` | the formation uuid — the first argument of `MarchUtil.SendCreateMarchMessage` |
| `state` | `ArmyFormationState` (below) |
| `totalSoldierNum` | soldiers loaded; **0 in a cold session** (see the cold-formation wall in [rally-join.md](rally-join.md)) |
| `canMarch`, `dominatorUuid`, `heroes`, `soldiers`, `buildingUuid`, `defencePriority` | the rest of the squad |

`formation:IsFree()` is the game's own «this squad is idle» answer, and it is what
`ArmyFormationDataManager:IsAnyWorldFormationOutside()` is built out of.
`GetMarchArmyNum()` counts the squads whose `state` is `March`, which is the proof that
`state` is what the game itself gates on.

### `ArmyFormationState` (a global Lua table, dumped live)

| value | name | what it means for the panel |
|---|---|---|
| 0 | `Free` | in the base — **the only state a send may start from** |
| 1 | `March` | out, marching |
| 2 | `Prison` | captured |
| 3 | `Death` | разбит — wiped |
| 4 | `GoHome` | on its way back |
| 5 | `Revival` | reviving |
| 6 | `Prison_PickDNA` | captured (the DNA variant) |
| 7 | `StationBuilding` | parked out in the world |
| 8 | `Formation` | being formed up |

## The march a squad is on

`DataCenter.WorldMarchDataManager:GetOwnerFormationMarch(ownerUid, formationUuid,
allianceUid)` is the link from a squad to its march — the march objects themselves carry
no formation field, which is why listing marches (`GetAllMarches()`) can never say which
squad was sent (see [rally-join.md](rally-join.md)). `ownerUid` is `LuaEntry.Player.uid`
and `allianceUid` is `LuaEntry.Player.allianceId` (the same value the march carries as
`allianceUid`; there is no `allianceUid` field on the player).

A march is a C# object; the fields that matter are `uuid`, `teamUuid` (non-zero = part of
a rally), `type` (`NewMarchType`), `status` (`MarchStatus`), `targetPos`, `startPos`,
`startTime`, `endTime`, `serverId`, `ownerUid`, `ownerName`, `allianceUid`, `speed`.
`tostring()` on the two enum fields gives `NAME: value` (e.g. `MOVING: 1`), so the NAME
is read out of the string rather than through an enum table.

### `MarchStatus` — what the march is doing

`STATION=0`, `MOVING=1`, `ATTACKING=2`, **`COLLECTING=3`** (добывает ресурсы),
`BACK_HOME=4`, `CHASING=5`, **`WAIT_RALLY=6`** and **`IN_TEAM=7`** (стоит в стягивании —
as the leader, and as somebody who joined), `ASSISTANCE=8`, `IN_WORM_HOLE=9`,
`SAMPLING=10`, `PICKING=11`, `GOLLOES_EXPLORING=12`, `BUILD_WORM_HOLE=13`,
`DESTROY_WAIT=14`, `BUILD_ALLIANCE_BUILDING=15`, `TRANSPORT_BACK_HOME=16`,
`CROSS_SERVER=17`, `TRAIN_PULL_IN=18`, `TREASURE_DIGGING=19`,
`COLLECTING_ASSISTANCE=20`, `ZOMBIE_RUSH_WAITING=21`, `BERSERK_BOSS_WAITING=22`,
`BEHEMOTH_ATTACK_CITY=23`, `BEHEMOTH_ARRIVING=24`, `DEFAULT=-1`.

### `NewMarchType` — what KIND of march it is

`NORMAL=0`, **`ASSEMBLY_MARCH=1`** (a rally), `MONSTER=2`, `BOSS=3`, `SCOUT=4`,
`EXPLORE=5`, `RESOURCE_HELP=6`, `TRAIN=14` (the base's trains, which are NOT squads —
they show up in `GetAllMarches()` but not in `GetOwnerMarches()`), `RUNNING_BOSS=15`,
`ALL_OUT=16`, `CROSS_NORMAL=40`, **`CROSS_ASSEMBLY_MARCH=41`**, and about thirty event
types beside them.

## Stamina

One pool for the whole ACCOUNT, not per squad — `ArmyFormationDataManager:GetCurStaminaByUuid(uuid)`
ignores the squad and forwards to the player:

```lua
LuaEntry.Player:GetCurStamina()     -- 99: what is available right now
LuaEntry.Player:GetStaminaFullTime()-- 1785777706685: epoch ms when the pool is full
DataCenter.ArmyFormationDataManager:GetConfigData().FormationStaminaMax        -- 120
DataCenter.ArmyFormationDataManager:GetConfigData().FormationStaminaUpdateTime -- 300 (s per point)
```

`GetCurStamina` is computed rather than stored: it is `Player.stamina` plus the points
grown since `Player.lastStaminaTime`, capped at the config maximum. So it is current
whether or not the server has said anything lately, and reading it costs one VM call.

`Player.pveStamina` / `GetCurPveStamina()` / `GetMaxPveStamina()` are the SEPARATE pool
the campaign spends. Do not gate a world send on them.

**What a send COSTS is not readable yet.** `ArmyFormationDataManager.CostStaminaBoss` /
`CostStaminaMonster` / `CostStaminaBuild` / `CostStaminaDome` / `CostStaminaRoad` /
`CostStaminaPickGarbage` all read `0` in a session where no dispatch window has been
opened — they are filled in by the dispatch UI, not by the config. So the panel SHOWS
the pool and does not gate on it: a gate priced from a field that reads zero would
either never fire or fire always, and neither has been seen to be right.

## What is proven, and what is not

Read live, repeatedly: the enums, every squad's `index` / `state` / `IsFree()` /
`totalSoldierNum`, the stamina pool with its maximum and its full-time, and
`GetOwnerFormationMarch` answering `nil` for a squad that is home.

NOT seen live: a squad actually out. Every reading so far was taken with all three
squads in the base, so the march half of the reading — `status`, `march`, `team`,
`point`, `arrive` — is best-effort until a march is caught in one. The gate the panel
holds does not depend on it: «at home» is `state == Free` **and** `IsFree()`, both of
which have been read, and everything else only decides which WORD the strip shows.

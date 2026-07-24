# World monsters — how the wire actually carries them

Goal: cold-load the World and catch monsters at entry. **Result overturns the premise:
monsters are NOT bulk-loaded when you enter the World, and never appear as
`world.get.block` tiles.** They arrive as **event/activity messages in the login
snapshot** and as **on-demand / lifecycle push streams during play**. Companion to
`world-tiles.md` (tile kinds) and `city-protocol.md` (login cold-load).

## Method

Strict cold-load: capture from a **fresh TCP handshake** (`dumpcap` both directions,
physical interfaces), then `taskkill /F /IM LastWar.exe` + relaunch, wait for auto-login
(~120 s, lands in **City**), then the **first `SceneUtils.ChangeToWorld()` since the cold
login** (`tools/lua_goto_world.py`) — the client has no cached world data yet, so this is
the genuine world cold-load. Decoded offline with `tools/lastwar_proto.py`. Also a warm
`ChangeToWorld` sniff (`tools/secret_task_capture.py --dump`) for comparison.

## Finding 1 — nothing monster-shaped loads at world entry

The first-world-enter capture (fresh login, server `34.145.128.94`, 134 down msgs) contained
**no** `push.running.boss.*`, **no** `monster.invasion.boss.detail`, **no** bulk monster list.
The single `world.get.block` had only `f2 ∈ {6 base, 7 mine, 17 secret_task}` and empty
`triggers`. The 29 `push.world.march.new` are **player marches** (e.g. `Blanche de Namur`,
`Bucknaked` of `[TLou] THE LAST 0F US`, target coord `471553;339547`, difficulty `Normal`) —
troops moving toward monsters, **not monsters**. A warm `ChangeToWorld` is identical (the
switch is a client-side render; nothing re-fetches). So: **the World scene switch carries no
monster data**, exactly like the base scene switch in `city-protocol.md`.

## Finding 2 — monsters come as event/activity messages in the LOGIN snapshot

The fresh-login snapshot (`city-protocol.md` cold-load) *does* carry the world monsters —
as **activity messages**, with concrete type / level / coordinate / time. `pointId → (x,y)`
uses `x = pointId % 1000`, `y = pointId // 1000` (as for all world points).

| message | monster data (concrete example) |
|---|---|
| **`alliance.boss.act.info`** | an alliance world boss: `bossType=2`, **level** `difficultyLevel=100`, **coord** `bossPointId=480565 → (565,480)` on `bossServerId=935`, `bossUuid=1397117482397050809`, **time** `battleStartTime=1784833203021` / `battleEndTime=1784835003021`, `totalDamage=819837555936`, `mvpDamage=105633102555`, `isAutoRally=1` |
| **`monster.invasion.act.info`** | the Monster Invasion event: `invasionId=5`, `bossStatus=2`, `stage=1`, `attackNum`, `refreshTime`, `planTime`, reward list, and the monster arrays **`selfMonsters[]` / `aliMonsters[]`** (empty when no invasion is live — these hold the per-monster entries when one is) |
| **`zombie.rush.act.info`** | alliance Zombie Rush: `maxDifficultyId=1012`, `round=20`, `state=3`, `selectDifficultyId=1012`, `actStartTime`/`actEndTime`, `pointId` |
| **`berserk.boss.hit.base.gain.info`**, **`act.boss.get.achievement.info`**, **`monster.shop.info`** | berserk-boss, act-boss, and the monster-kill reward shop (`buyRecords` per difficulty) |
| `init` counters | `daily_kill_boss=20`, `daily_kill_boss_leader=9`, `find_monster_max_level=35`, `attack_behemoth_boss_time`, `actBerserkBoss`, `actBossTrans` — the player's monster-kill progress, not entities |

So the **boss-type monsters** (alliance boss, invasion boss, berserk boss, behemoth) are
delivered at login as their event objects, each with a `bossPointId`, `difficultyLevel`,
`bossUuid`, and battle timestamps.

## Finding 3 — roaming monsters are on-demand / lifecycle pushes

The roaming, tappable monsters (and boss movement/death) ride **push + query** streams during
play, not a bulk load (observed across the earlier world captures):

| message | role / example |
|---|---|
| `monster.invasion.boss.detail` | **on-demand** query when you tap a boss → `{uuid, ownerName:"ofbi", allianceUid, allianceAbbr:"TLou", isProtected:true}` |
| `push.running.boss.del` (and `.new`/`.add`) | roaming-boss lifecycle → `{uuid}` (spawn / move / death) |
| `push.al.zombieRushPoint.change` | alliance zombie-rush spawn point → `{zombieRushPoint:5486330, allianceId}` |
| chat/world ticker | e.g. `Ур. 130 Зомби-Босс (БЗ #935 X:519 Y:554)` — a lvl-130 Zombie-Boss at `(519,554)` (point `554519`) |

`DataCenter` managers back these: `MonsterManager` (kill counters, `GetCurCanAttackMaxLevel`,
`find_monster_max_level`), `MonsterTemplateManager` (level→attributes config),
`WorldPointDetailManager` (`GetDetailByPointId` — per-point detail fetched on demand),
`MonsterLockDataManager`, `LWZombieRushManager`, `LWBerserkBossManager`, and the
`S0/S4/Season` boss data managers.

### Client entity-type enum (`LWWorldMonsterType`, from Lua)

```
ResMetal=1 ResFood=2 Boss=3 City=4 ResGold=5 Radar=6 MonsterInvade=7 RunningMonster=8
ResObsidian=9 ResFlint=10 FlowerCar=13 S4Tank=14 S4Airplane=15 S4Missile=16 S4Boss=17
S4TankBN=18 S4AirplaneBN=19 S4MissileBN=20 S4BossBN=21 S4RunningBoss=22 Lockhart=1001
```
Monsters are `Boss=3`, `MonsterInvade=7`, `RunningMonster=8` (+ seasonal `S4Boss/S4RunningBoss`).
**This is a client display enum, distinct from the wire `f2` tile kind** (`world-tiles.md`).

## Takeaway

To read world monsters you do **not** watch `world.get.block` or the scene switch. You:
1. parse the **login snapshot** `alliance.boss.act.info` / `monster.invasion.act.info` /
   `zombie.rush.act.info` for the current event bosses (type, `difficultyLevel`,
   `bossPointId→(x,y)`, `bossUuid`, battle times), and
2. follow **`push.running.boss.*`** + tap-driven **`monster.invasion.boss.detail`** for the
   roaming/on-demand ones (or read them live from the `DataCenter` monster managers).

## Artifacts (git-ignored under `results/`)

- `results/world_coldlogin.pcapng` — fresh-login capture (login → City).
- `results/world_firstenter.pcapng` / `world_firstenter_decoded.json` — first `ChangeToWorld` since cold login (no monster bulk load).
- `results/world_coldload_monsters.jsonl` — warm `ChangeToWorld` sniff (comparison).
- `results/coldload_decoded.json` — the login snapshot carrying the monster event messages above.

## Attacking a monster programmatically via `GoToUtil` (task follow-up)

Driving the monster-attack flow out-of-process (SafeDoString, `tools/lua_eval.py`),
in **World**:

- **`GoToUtil.FindMonster(arg)`** — the working entry. Navigates the camera to a world
  monster and opens its **attack popup**. Proven: `FindMonster(2)` (then `GoAttackMonster()`)
  centered on and opened the popup for a **lvl-120 «Зомби-Босс»** — rewards (rally-initiator /
  seeker), `Найдено [TLou]mdw88`, stamina 20, recommended power 70M, and the orange
  **«Точка сбора альянса»** (alliance rally) flag (`results/attack_monster.png`). The `arg` is
  **not** the level (`2` → a lvl-120 boss; `1` → nothing) — it behaves like a search
  category/slot, resolved server-side (the request packs a number via `SFSDataSerializer`;
  calling `FindMonster()` with no arg errors `bad argument #2 to 'pack' (number expected, got nil)`).
- **`GoToUtil.GoAttackMonster(monster)`** — the attack-dispatch entry. Called with **no arg it
  is a no-op** (`ok=true`, early-return on nil); it needs the monster's world-point data object
  (what a map tap / `OnClickWorldPoint` supplies). We could not synthesize that object from the
  captures, so the reliable trigger is `FindMonster(arg)` (which resolves + opens the popup).
- **`GoToUtil.GotoBossMonsterBetweenLv(...)`** — **different signature**: `(1,30)` throws
  `GoToUtil.lua:1782: attempt to compare number with nil`, so it does not take plain
  `(minLv,maxLv)` — it reads a param table/field that was nil here.

### Where the monster data lives (live managers)

- **Invasion monsters are not cached** — `monster.invasion.act.info.selfMonsters/aliMonsters`
  were empty (invasion inactive, `bossStatus=2`). `DataCenter.ActivityMonsterInvasionDataManager`
  fetches on demand: `RequestGetMonsterInvasionPoint`, `GetInvasionBossInfo`, `JumpToBossPoint`,
  `GotoInvasionAisillaPoint` (the "Aisilla" invasion monster), `OnInvasionBossPointGot`.
- **`DataCenter.MonsterLockDataManager`** — land-lock / PvE monsters (the ones blocking land
  expansion): `allMonster` (empty here), `GetMonsterDataByPointIndex`, `ClickMonsterLockById`,
  `GetMosnterLockDataByPve`.
- **`DataCenter.MonsterManager`** — counters/limits: `find_monster_max_level=35`,
  `GetCurCanAttackMaxLevel`, `daily_kill_boss=20`, `GetRestKillBossNum`.

### Recipe

To open a monster's attack UI programmatically: be in **World**, then
`GoToUtil.FindMonster(<slot>)` — it resolves the nearest matching monster server-side and
opens the attack/rally popup. `GoAttackMonster` alone needs the monster-point object (map-tap
data), so it is not directly callable without first tapping/finding a monster.

Screenshots (git-ignored): `results/attack_monster.png` (lvl-120 Zombie-Boss attack popup
opened via `FindMonster(2)`), `results/attack_small_monster.png` (the monster field — Behemoths
lvl 3/33/120, zombie squads lvl 8/9/10/20, alliance rally flag).

### Follow-up — the active invasion has NO small monsters; `GoAttackMonster` defaults to the rally boss

Re-checked live with the invasion active. `DataCenter.ActivityMonsterInvasionDataManager`:
the current invasion is a **Godzilla summon-boss** event (`GetActivityData`: `id=80024`,
`type=210`, `summonBossId=1030091`, icon `ljq_leida_godzilla`, `summonBossScore=40`), and
`GetActData().selfMonsters` / `aliMonsters` are **`{}` — empty even after
`RequestGetMonsterInvasionPoint()` + wait**, `GetInvasionBossInfo()=nil`,
`GetInvasionSummonProgress()=40`. So this invasion type has **no small per-monster entries** —
you contribute score to *summon* the boss; the `selfMonsters/aliMonsters` arrays belong to a
different (spawn-near-base) invasion type. Getters `GetMonsterList` / `GetSelfMonsters` /
`GetAllianceMonsters` do **not** exist on this manager.

The actual small monsters are the **roaming world zombies** (seen live at lvl 1/3/8/9/20/22/33).
- `GoToUtil.FindMonster(8)` navigates to and **ring-selects a small lvl-8 monster** (arg does
  differentiate: `2` → the lvl-120 rally boss, `8` → a small monster), but it does **not** store
  the found monster in any queryable manager (`MonsterLockDataManager.allMonster` stays `{}` —
  that manager is land-lock/PvE monsters, unrelated).
- `GoToUtil.GoAttackMonster()` with no arg always opens the **alliance rally boss** popup
  (lvl-120, «Найдено [TLou]mdw88», «Точка сбора альянса») — the alliance-shared target, not the
  `FindMonster`-selected small monster. Attacking a *specific* small monster needs its
  world-point object as the arg, which the client only produces from a real map tap
  (`OnClickWorldPoint`); it is not exposed in a live manager we could read.

**Conclusion:** the monster-attack UI opens programmatically (proven for the rally boss), and
`FindMonster(level)` locates small monsters, but a fully-programmatic *solo* attack on a chosen
small monster is blocked on obtaining its world-point object without a physical tap. Screenshot
of the small-monster field + ring-selection: `results/find_monster_lv8.png`.

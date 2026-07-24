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

### Follow-up 2 — the small-monster attack UI, and why `GoAttackMonster(pt)` stays blocked

Corrected the "level-10" assumption: on the world map the **blue tank icons tagged 8/9/10 are
Iron Mines** (resource nodes, wire `f2=7`) being harvested by alliance members — tapping one
opened «Железный рудник 10 ур.» (`Добытчик [TLou]Korive, 370513/504000`), **not a monster**.
The tag is the mine level. The real small monsters are the red **Behemoth "elites"** (lvl 3/33)
and the roaming zombie squads.

Neither suggested live manager exposes the found monster's point object:
- `DataCenter.WorldPointDetailManager` — **no** current/selected-point getter
  (`GetCurrentPoint/GetSelectPoint/GetLastPoint/…` all absent); only `GetDetailByPointId(id)`
  (needs the id) and `worldPointDetailList` which was **empty** (`count=0`) after `FindMonster`.
- `DataCenter.MonsterManager` — counters only (`GetCurCanAttackMaxLevel`, `GetKillBossNum`,
  `find_monster_max_level`, …); **no** monster-entity/point getter.

So `GoAttackMonster(pt)` cannot be fed a live-obtained point through these managers — the
client only materializes a monster's world-point object from a **real map tap**
(`OnClickWorldPoint`). Doing that tap **did** open the full attack flow for a **small monster**:
a physical click on the lvl-3 **«Роковая Элита»** opened its popup (guaranteed rewards
weapon/hero EXP + iron/food/coins, recommended power **50,000**, stamina 20), and clicking its
attack button opened the **troop-dispatch UI** — my heroes (Lv.175, 3,123 units), power
**55.59M vs 50.00K → «Лёгкая победа»**, rally-time selector, and the **«Стягивание»** launch
button. The flow was left one tap short of launch: **«Стягивание» starts an alliance rally**
(an alliance-wide, outward action), so it was not pressed without explicit sign-off.

**Bottom line:** the monster-attack flow is fully reachable and a small monster's attack UI
opens end-to-end, but the trigger is a **map tap** (`OnClickWorldPoint`), not a pure
`GoToUtil.GoAttackMonster(pt)` call — `GoAttackMonster()` alone only opens the alliance rally
boss, and the per-monster point object is not exposed by any live manager we could read.
Screenshots (git-ignored): `results/monster_lv10_tapped.png` (the "10" = Iron Mine),
`results/monster_lv3_tapped.png` (lvl-3 «Роковая Элита» popup),
`results/monster_attack_dispatch.png` (the dispatch UI, «Лёгкая победа»).

### Follow-up 3 — the "Golden Zombie" identified (it is the event "Invading Zombie")

The small event monster the user calls the *golden zombie* is fully pinned down via
`DataCenter.MonsterTemplateManager.monsterTemplateDic` + localization:

| what | cfgId | name (loc) | level | size | desc (loc) | notes |
|---|---|---|---|---|---|---|
| **Golden / Invading Zombie** | **`1030000`** | `2901011` = **«Вторгшиеся Зомби» / "Invading Zombies"** | **10** | 1 | `2901027` = *"a zombie … prefers gold coins over brains"* | `type=7`, `special=9`, `recommend_power=670000`, `expire=720`, `is_stop=1` |
| **Zombie Boss** | `1031020…1031027` | `2901012` = «Зомби-Босс» / "Zombie Boss" | 100–135 | 3 | `2901028` (the mastermind) | lvl 120 = `1031024` (the big Behemoth on the map) |

Event mechanic (loc `2901024`/`2901033`/`2901034`): you **kill Invading Zombies on the world
map (500 pts each)**; enough kills **summon a Lv-N Zombie Boss**. So the "golden zombies" are
the *pre-boss* phase.

**Why none can be attacked right now:** the event is already in the **boss phase** —
`ActivityMonsterInvasionDataManager:GetInvasionSummonProgress() = 40` (maxed) and the Lv-120
Zombie Boss (`1031024`) is present on the map, i.e. the Invading/Golden Zombies were already
killed to summon it; none are currently spawned. `FindMonster(10)` centres the map but there is
no live Invading Zombie to select (it landed on an alliance base under a shield bubble, not a
monster). `GetInvasionBossInfo()` returned `nil` and `GotoInvasionAisillaPoint()` instead opened
a **placement mode** for the big Aisilla invasion boss (a crystalline Godzilla with a green
placement grid + ✓/✗) — a leader action to *place* the boss, not attack a small zombie; it was
cancelled.

**Conclusion:** the Golden/Invading Zombie is `cfgId 1030000` (lvl-10, rec. power 670K, gives
gold). Attacking one requires an **active spawn during the invasion's kill phase**; in the
current boss phase there are none on the map, so a live attack can't be demonstrated now — only
the boss (rally) and non-event small monsters (e.g. lvl-3 «Роковая Элита», whose dispatch UI was
reached in Follow-up 2). Screenshot of the placement mode: `results/aisilla_point.png`.

### Follow-up 4 — attack EXECUTED (solo march on «Обжора» lvl-19, victory)

With explicit sign-off, a monster attack was launched end-to-end. Key distinction learned:
- **Rally monsters** (event elites «Роковая Элита», the Zombie Boss) show an **orange rally
  flag** and a **«Стягивание»** (rally) button — that starts an *alliance rally* (needs the
  gather/members flow); a lone press did not produce a personal march
  (`WorldMarchDataManager:IsHaveMarchInWorld()` stayed `false`).
- **Solo monsters** show a **red crossed-swords «Атаковать»** button and a **«Марш»** (march)
  button in the dispatch UI — a direct solo attack. The lvl-19 **«Обжора»** (rec. power only
  **1.08M**, stamina 10) was soloable: tapping it → red-swords → dispatch UI (my heroes Lv.175,
  **55.59M vs 1.08M → «Лёгкая победа»**, «Марш 00:00:37») → pressing **«Марш»** launched the
  attack. Verified: `IsHaveMarchInWorld() = true` and a green march path from base to the
  monster (`results/march_launched.png`); ~50 s later the monster was **gone / killed** and the
  troops were returning (`IsHaveMarchInWorld = false`, `results/battle_result.png`).

So a fully-driven monster attack works via **map tap → «Атаковать» → «Марш»** for soloable
monsters. `GoToUtil.GoAttackMonster()` only re-opens the alliance rally boss; the launch itself
is the map-tap dispatch flow. Screenshots: `results/monster19_popup.png` (the «Обжора» solo
popup), `results/obzhora_dispatch.png` (dispatch «Лёгкая победа»), `results/march_launched.png`
(march out), `results/battle_result.png` (monster killed, troops returning).

### Follow-up 5 — the Golden Zombie found & killed (it was in the "golden vein" region)

The user was right — the golden zombies are plentiful, just in a different area. Panning the
world map up/right (away from the alliance base cluster) reached a **golden-vein region**: a
large golden boss tagged **«100»** (golden scarab, LWWorldMonsterType boss) surrounded by
**small golden zombies «10»** sitting on **piles of gold coins + orange chests**.

Tapping a lvl-10 golden one confirmed it: popup **«Вторгшиеся Зомби» ур.10** — exactly
`MonsterTemplateManager` cfgId `1030000` (**recommended power 670,000**, matching the config),
guaranteed rewards **Courage Medal ×10** + weapon/hero EXP + iron/food 268K + gold, and a
**red crossed-swords «Атаковать»** (solo) button. **Attacked and killed it:** red-swords →
dispatch UI (**55.59M vs 670.00K → «Лёгкая победа»**, «Марш 00:01:17») → **«Марш»** launched
the march (`IsHaveMarchInWorld() = true`, green march path to the golden zombie), and ~80 s
later the golden zombie was **gone / killed** (`IsHaveMarchInWorld = false`).

**Sniffer during panning (120 s):** `world.get.block` returned 34 tiles, `f2` only
`{7 mine, 17 secret_task, 6 base}` — **no monster tiles even while panning over the golden
zombies**. So golden zombies (like all monsters) are rendered client-side but **not delivered
via `world.get.block`**; the traffic while roaming is just base/mine/task tiles + `push.world
.march.*` + `push.battle.finish`. This re-confirms `world-tiles.md` (monsters ≠ block tiles).

**Recipe to attack a Golden Zombie:** pan to a golden-vein region → tap a lvl-10 «Вторгшиеся
Зомби» (on gold piles) → red-swords «Атаковать» → «Марш». Screenshots: `results/gold_region.png`
(the golden cluster), `results/golden_zombie_popup.png` («Вторгшиеся Зомби» ур.10),
`results/golden_dispatch.png` (55.59M vs 670K), `results/golden_march.png` (march out),
`results/golden_battle_result.png` (golden zombie killed).

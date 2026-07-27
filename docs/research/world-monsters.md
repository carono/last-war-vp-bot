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

## Finding 5 — attacking a monster ENTIRELY via Lua (no physical click)

The whole tap→popup→attack flow reduces to **one Lua call**:

```lua
GoToUtil.GoAttackMonster(pointId)   -- opens the UIWorldPoint attack popup, no click
```

`GoToUtil.GoAttackMonster(pointId)` is the single entry point that the physical raycast-tap
funnels into: given a world **pointId** it **sends the server "get world-point detail"
request itself** (the raycast is only there to discover the pointId), waits for the reply,
and **opens the `UIWorldPoint` popup** rendered from that detail — all out-of-process via
`XLuaManager.SafeDoString`. Verified: `GetStackWindowCount()` goes `0 → 1` and a screenshot
shows the full monster popup (rewards, recommended power, energy/timer). No `pydirectinput`,
no BitBlt, no tap.

### Getting a candidate pointId without a tap

Monsters are **not** in `world.get.block` nor any Lua data manager (Findings 1–4), so the
pointId can't be read from data. Derive it from the camera after the finder centers on one:

```lua
GoToUtil.FindMonster(10)                       -- centers the CAMERA on a nearby lvl-10 monster (returns nil)
local cam = CS.UnityEngine.Camera.main
local p, f = cam.transform.position, cam.transform.forward
local t  = -p.y / f.y                          -- ray to the y=0 ground plane
local g  = CS.UnityEngine.Vector3(p.x + f.x*t, 0, p.z + f.z*t)   -- ground look-at point
local pointId = SceneUtils.WorldToTileIndex(g) -- tile index at screen centre  → candidate pointId
GoToUtil.GoAttackMonster(pointId)
```

Caveat: `WorldToTileIndex(cameraGroundLookAt)` gives the tile at *screen centre*, which in the
isometric projection is offset a couple of tiles from the monster's sprite, so it can land on
an **adjacent** monster. In one run it opened **«Роковая Элита» ур.5** (a nearby rally elite)
instead of the intended golden zombie — see the discriminator below.

### The popup: `UIWindowNames.UIWorldPoint` (`UIWorldPointCtrl` / `UIWorldPointView`)

`w = UIManager.Instance:GetStackTopWindow()` → `w.Name == "UIWorldPoint"`, with:

- **`w.Ctrl`** (`UIWorldPointCtrl`) — the logic/data. Fields: `pointId`, `uuid`, `type`,
  `serverId`, `ownerUid`, … Methods incl. **`RequestWorldPointDetail`**, **`GetMonsterData`**,
  `GetPointData`, `GetMonsterRewardData`, `OnMarkClick`, `CloseSelf`, and a `Get*Data` per
  point kind (ruin/rescue/boss/resource/ghostrecon/zombierush/…).
- **`w.View`** (`UIWorldPointView`) — the widgets (the central round action button).

**Solo-vs-rally discriminator:** `w.Ctrl:GetMonsterData().canAttack`

- `canAttack == 1` → **soloable** (red crossed-swords «Атаковать»/«Марш»).
- `canAttack == 0` → **rally-only** (orange flag «Стягивание») — e.g. «Роковая Элита» returned
  `canAttack = 0`. **Launching a rally is an alliance-wide outward action → needs explicit
  user sign-off; do not press it.** Solo «Марш» is the pre-authorised path.

### Remaining step for a full no-click SOLO march

`GoAttackMonster(pointId)` opens the popup; to *launch* the solo march without a click the
popup's action button handler still needs to be invoked (through `w.Ctrl`/`w.View`, ultimately
`MarchUtil.OnClickStartMarch`/`StartMarch`/`SendCreateMarchToServer`), and the pointId must
resolve to a `canAttack == 1` monster (scan neighbouring tiles reading `GetMonsterData().canAttack`
until one is soloable). Screenshot of the proven no-click popup: `results/goattack.png`
(«Роковая Элита» ур.5 opened purely from Lua).

## Finding 6 — enumerating real monsters & the no-click SELECTION wall

Follow-up to Finding 5 (fully-Lua attack). `GoToUtil.GoAttackMonster(pointId)` opens
the popup but **ignores its argument** — it always targets the fixed `FindMonster`
selection (a rally elite «Роковая Элита», `canAttack=0`), never an arbitrary monster.
`FindMonster(level)` also ignores `level` and never cycles. So neither reaches a chosen
golden zombie. Determined by scanning ±40 tiles in 8 directions + exact monster tiles —
**every** call returned the same `pid=528614`.

### What DOES work (no click): enumerate the real monsters

The world controller is the MonoBehaviour **`WorldScene`** (on the `World` GameObject),
reachable via `CS.UnityEngine.Object.FindObjectsOfType(typeof(MonoBehaviour))` filtered by
`GetType().Name=="WorldScene"` (cache it in `_G.WS`). It exposes the full point/monster API:

```lua
local ws = _G.WS
local center = ws.CurTilePos                        -- Vector2Int camera tile
local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32,CS.System.Int32)()
ids:Add(1030000, 1)                                 -- whitelist of monster CONFIG ids (golden zombie = 1030000)
local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)()
ws:GetMonsterListInArea(center, 150, ids, res)      -- fills res = { uuid -> tilePos }
-- each entry: real monster uuid + tile; pointId = ws:TilePosToIndex(tilePos)
```

`GetMonsterListInArea(Vector2Int center, int size, Dictionary<int,int> monsterIds,
Dictionary<long,Vector2Int> result)` — `monsterIds` is a **config-id whitelist** (empty ⇒
0 results); `result` returns **real `uuid → tile`** per monster. This gave 3 live golden
zombies, e.g. `uuid=1397117504274540388 tile=(613,535) pid=535614`. (Visible level tags are
`UIWorldLabel` components — 33 in view; a lvl-10 label's parent GameObject is
`WorldMonster_General_invasion(Clone)`, whose world pos → `WorldToScreenPoint` gives the
exact screen pixel.) The monsters are **not** in `WorldScene.PointManager`
(`HasPointInfo(pid)=false`, `GetObjectByPoint/GetPointInfoByUuid=nil`) — invasion monsters
are a separate render/detail system, consistent with Findings 1–4.

Anchoring the popup on a chosen monster also works: `OpenWindow(UIWindowNames.UIWorldPoint,
uuid, pointId)` (signature is `(long uuid, int pointId)`) opens `UIWorldPoint` positioned
over that golden zombie, with `Ctrl.uuid`/`Ctrl.pointId` set correctly.

### The wall: the popup's monster DETAIL never loads out-of-band

The anchored popup renders **incomplete** — a bare "ур.N" header, no rewards, **no
«Атаковать»/«Марш» button**, and `Ctrl:GetMonsterData()` returns only `{canAttack=0}`. The
attack UI needs the server-fetched *point detail*, and no Lua call triggers/populates it:
`Ctrl:RequestWorldPointDetail()` (with `pid`/`uuid`/no args), `Ctrl:InitData(uuid,pid)` and
variants, `PreProcessPointData()` all run `ok=true` but leave `canAttack=0` and the detail
uncached (`WorldPointDetailManager:GetDetailByPointId` stays non-table).

The detail-fetch is driven only by the **real tap-resolution path** — `TouchInputController`
(→ world raycast → resolve monster → request detail → open full popup). Its `FingerDown(Vector3)`
/`FingerUp()` can be invoked via reflection but **do not** fire the click chain (detection reads
the real `Input` in `OnUpdate`, not the passed position). So the click is bound to OS input.

**Conclusion:** a *fully* no-click solo march on an arbitrary golden zombie is not reachable
through the exposed Lua/CS surface — monster SELECTION + attack requires the real tap. The
proven no-click pieces are: (a) open the popup for the `FindMonster` target
(`GoAttackMonster()`), and (b) enumerate any monster's exact uuid/tile/**screen pixel**. The
practical path to attack a *chosen* golden zombie is the **hybrid**: Lua computes its screen
pixel, one real tap opens the full popup, then launch «Марш» — i.e. exactly the physical-tap
kill proven in Finding 4, now precisely targeted from Lua.

> **⚠ Superseded by Finding 7.** The "selection wall" above was wrong about the *reason*:
> the wall was calling `GoAttackMonster(pointId)` (which has **0 parameters**, so the arg is
> discarded) and `OpenWindow(UIWorldPoint, ...)` (which anchors the popup but never resolves
> the point). The **right** selection entry — `GoToUtil.OnClickWorldPoint(pointId, type, uuid)`
> — was not tried. It is arg-routed and opens the exact chosen point/monster. See below.

## Finding 7 — the RIGHT no-click monster-select function: `GoToUtil.OnClickWorldPoint`

Task #1031. A full sweep of the live xLua `_G` (dump every `GoToUtil` / `SceneUtils` /
`MarchUtil` method + `debug.getinfo`/`getlocal`/`getupvalue` signatures — tools
`_dump_lua_globals.py`, `_probe_monster_fns.py`, `_probe_fn_params.py`) pinned down both the
root cause and the fix.

### Root cause — why `GoAttackMonster` "ignores its argument"

`debug.getinfo(GoToUtil.GoAttackMonster,"u")` → **`nparams=0`**, `params=[]`,
`ups=[_ENV, GoToUtil]` (defined `GoToUtil.lua:1751`). It structurally **takes no argument**;
it reads the current selection from `GoToUtil` state (set by `FindMonster`) and re-opens that
one fixed popup. So `GoAttackMonster(pid)` was never selection — the `pid` was dropped by Lua.
`FindMonster` is `nparams=1` but also never cycles (Finding 6).

### The fix — `GoToUtil.OnClickWorldPoint(pointId, type, uuid)`

The real map-tap handler, found in the sweep (defined `GoToUtil.lua:467`):

```lua
GoToUtil.OnClickWorldPoint(pointId, type, uuid)   -- params: [pointId, type, uuid]
```

It is **arg-routed** and does the full tap-resolution (server point-detail fetch + open the
populated `UIWorldPoint` popup) for the **exact point you pass** — the selection primitive the
whole flow needed. Verified live (`_verify_onclickworldpoint.py`), three distinct pids → three
distinct monsters, none the `FindMonster` default:

| call | resulting popup `Ctrl.pointId` (x,y) | `Ctrl.type` (`WorldPointType`) | `GetMonsterData()` |
|---|---|---|---|
| `GoAttackMonster()` (default) | `528614` (614,528) | `2` | `canAttack=0`, `GetMonsterRewardData()`≠nil |
| `OnClickWorldPoint(517628, …)` | `518629` (629,518) — nearest monster | `22` INVASION_WORLD_MONSTER | `canAttack=0`, reward≠nil |
| `OnClickWorldPoint(513593, 7, 0)` | `513593` (593,513) — **exact** | `5` WorldBoss | popup populated |

Notes:
- **`pointId` is the driver.** `type`/`uuid` are hints — passing `type=7, uuid=0` for a
  `WorldBoss` still opened it and `Ctrl.type` resolved to the true `5` server-side. Passing the
  real triple (e.g. from `GoAttackMonster`'s own popup: `528614, 2, uuid`) reproduces that
  popup exactly (`hasMonsterData=yes`).
- It **snaps to the nearest interactable point** when the exact tile has none (`517628` →
  monster at `518629`); pass the monster's own `pointId` (from `GetMonsterListInArea`, Finding 6)
  to hit it precisely.
- `WorldPointType` monster kinds: `WorldMonster=4`, `WorldBoss=5`, `EXPLORE_POINT=8`,
  `INVASION_WORLD_MONSTER=22` (full enum dumped in `_verify_onclickworldpoint.py`).

### End-to-end no-click attack pipeline

1. Be in **World** (`SceneUtils.GetIsInWorld()==true`).
2. Get the target monster's `uuid` + `tile` → `pointId = ws:TilePosToIndex(tile)` via
   `WorldScene:GetMonsterListInArea(center, size, cfgIdWhitelist, result)` (Finding 6).
3. **`GoToUtil.OnClickWorldPoint(pointId, type, uuid)`** — selects it, opens the populated popup.
4. Read `w.Ctrl:GetMonsterData().canAttack`: `1` = soloable, `0` = rally-only.
5. Launch: for a **soloable** monster the dispatch is `MarchUtil.OnAttackMonster(selfMarchUuid,
   targetMarchInfo, curStamina, isFormation, autoBackHome, isDirectionMarch)` /
   `MarchUtil.StartMarch` (`MarchUtil.lua:430/1828`). **Rally (`canAttack=0`) is an
   alliance-wide outward action → needs explicit user sign-off; do not auto-launch.**

**Bottom line:** the no-click monster **SELECTION** is solved — `GoToUtil.OnClickWorldPoint(pointId,
type, uuid)`, not `GoAttackMonster` (which is a 0-arg re-open of the fixed `FindMonster` target).
The only piece still gated on authorization is pressing the launch on a *rally* monster.

(Lua source lives in the encrypted `LWLF` archive `…/LocalLow/FunFly/…/lwScripts/LWScripts.data`
— per-file `*.luac` bytecode with an `ENC` marker; signatures here come from the live VM via
`debug.*`, not from decrypting it.)

## Finding 8 — the Finding-6 "detail wall" was a READ BUG; no-click select loads full detail

Deep follow-up (tools `_dump_worldpoint_api.py`, `_probe_detail_march.py`, `_test_request_detail.py`,
`_hunt_solo_monster.py`, `_probe_solo_correct.py`). **The "popup opens without attack data
(`canAttack=0`, no button)" wall of Finding 6 was never real — it was the wrong read.**

### The bug: `GetMonsterData` needs the uuid argument

`UIWorldPointCtrl:GetMonsterData` has signature **`(self, uuid)`** (`debug.getlocal` →
`params=[self, uuid]`). Every earlier check called `Ctrl:GetMonsterData()` with **no uuid**,
which returns a stub **`{canAttack=0}`** (1 field). Passing the monster's uuid —
`Ctrl:GetMonsterData(Ctrl.uuid)` — returns the **full, server-loaded detail**:

```
canAttack=1  level=19  recommend_power="…1,084,500"  marchType=2  monsterType=2
srcServer=935  restNum=20  attackMaxLv=35  needArmyDesc="Требуется юнитов 4 ур.: 700"
name=2000003  point=507599  special=0  refreshTime=…  createTime=…  (20+ fields)
```

So `GoToUtil.OnClickWorldPoint(pointId, 0, uuid)` **does** fetch and load the full point detail
(no tap). `WorldPointDetailManager:GetDetailByPointId(pid)` staying `nil` was a red herring —
invasion/world monsters cache their detail on the Ctrl, not in that manager.

### Proven: 16/16 enumerated monsters selected + fully loaded, all soloable

`WorldScene:GetMonsterListInArea(CurTilePos, 300, whitelist, result)` with `whitelist` = every
cfgId in `DataCenter.MonsterTemplateManager.monsterTemplateDic` (a **Lua table**, iterate with
`pairs`; ~41 ids) returned **32** live monsters. Feeding each `(pointId, 0, uuid)` to
`OnClickWorldPoint` opened the **exact** monster (popup `Ctrl.pointId` == passed pid, every time)
and `GetMonsterData(uuid)` read **`canAttack=1`** for all 16 sampled — levels **8–27**, powers
**159,500–1,948,500** (e.g. pid `507599` = the lvl-19 «Обжора» of Finding 4). The no-click
selection + solo/rally classification of an **arbitrary chosen monster** is fully solved.

### The launch chain (dispatch UI opens fully pre-filled)

- `MarchUtil.OnClickStartMarch(targetType, pointIndex, uuid, index, backHome, rallyType,
  targetServerId, targetWorldId, monsterSpecialType, ignoreNotice)` — called with
  `targetType = MarchTargetType.ATTACK_MONSTER (=1)`, `pointIndex=pid`, `uuid`, opens the troop
  UI **`UIFormationSelectListV2`** with everything pre-set: `targetPoint`, `targetUuid`,
  `targetType=1`, `targetServerId=935`, **`selectFormationUuid` already chosen**, `timeIndex=1`,
  `autoBackHome=1`. No tap needed to reach the dispatch screen.
- The dispatch-confirm handlers on that window's Ctrl are **`OnAtkClick`** and **`OnCreateClick`**
  (also `OnEditClick`, `StartInvestigate`). Direct-send primitives exist too:
  `MarchUtil.StartMarch(targetType, targetPoint, targetUuid, timeIndex, mUuid, fUuid, autoBackHome,
  dataObj, pos, targetServer, desTimeIndex, extraParam)` and
  `MarchUtil.SendCreateMarchToServer(formationUuid, targetType, targetPoint, targetUuid, timeIndex,
  formationData, startPos, backHome, targetServerId, destroyTimeIndex, extraParam)`.
- **Not yet confirmed which confirm-call actually launches:** `OnAtkClick()` ran `ok=true` but
  closed the dispatch back to the popup with `IsHaveMarchInWorld()==false` (no march); the next
  attempt (`OnCreateClick` + auto-accept any confirm dialog) was **not completed — the game
  process crashed twice on relaunch** and the launcher hung, so the final launch step is
  documented but unverified. Enums for the call: `MarchTargetType.ATTACK_MONSTER=1`,
  `WorldMonsterSpecialType.Normal=0 / MonsterInvasion=9`, `NewMarchType.MONSTER=2`.

`WorldScene` has **no** `OnTapTile`/`OnClickTile`/`SelectMonster` (all `nil`; its CS `__index` is
a C function so `pairs` can't enumerate it — probe names directly). Tap routing lives in
`TouchInputController` → `GoToUtil.OnClickWorldPoint`, which is exactly the Lua entry above.

### Corrected end-to-end recipe

```lua
-- in World:
local ws = _G.WS                                    -- WorldScene MonoBehaviour (cache)
local ids = CS.System.Collections.Generic.Dictionary(CS.System.Int32,CS.System.Int32)()
for k in pairs(DataCenter.MonsterTemplateManager.monsterTemplateDic) do
  if type(k)=="number" then pcall(function() ids:Add(k,1) end) end end
local res = CS.System.Collections.Generic.Dictionary(CS.System.Int64, CS.UnityEngine.Vector2Int)()
ws:GetMonsterListInArea(ws.CurTilePos, 300, ids, res)     -- uuid -> tile
-- pick a uuid/tile, pointId = ws:TilePosToIndex(tile)
GoToUtil.OnClickWorldPoint(pointId, 0, uuid)              -- select + load detail, NO click
local c = UIManager.Instance:GetStackTopWindow().Ctrl
local md = c:GetMonsterData(uuid)                          -- MUST pass uuid → full detail
if md.canAttack == 1 then                                  -- soloable
  MarchUtil.OnClickStartMarch(MarchTargetType.ATTACK_MONSTER, pointId, uuid, 0, true, nil,
                              md.srcServer, 0, md.special, true)   -- opens UIFormationSelectListV2
  -- then the dispatch-confirm handler (OnAtkClick / OnCreateClick) — final launch TBD
end
```

## Finding 9 — camera-move API scale + the launcher-restart wall (follow-up)

Re-run of the Finding-8 pipeline to verify the golden-zombie (`cfgId 1030000`) case and the
final launch. Two durable facts, and the same crash wall.

### The camera-move API takes WORLD units, not a tile index

If a scan needs to *pan* (e.g. hunt a monster type not loaded at the current camera), use the
right entry — they are on **different scales**:

- **`GoToUtil.MoveToWorldPoint(pointId)`** — tile-accurate. `pointId = ws:TilePosToIndex(tile)`.
  Proven: `MoveToWorldPoint` of tile `(661,570)` lands `CurTilePos` on `(661,570)`.
- **`GoToUtil.GotoWorldPos(Vector2Int(wx,wy))`** / **`SceneUtils` world-pos calls** take **world
  coordinates**, and `tile = world/2` (`TileSize=2`). Passing a *tile* number here lands the
  camera at **half** that tile: `GotoWorldPos(Vector2Int(700,600))` → `CurTilePos (350,300)`.
  A grid scan that feeds tile numbers to `GotoWorldPos` silently explores the **wrong region**
  (a prior scan of the up-right region was invalid for exactly this reason).

Note: with the correct whitelist (all `monsterTemplateDic` ids via `pairs`, Finding 8) a
`GetMonsterListInArea(CurTilePos, 300, …)` at the base already returns dozens of monsters, so
panning is usually unnecessary. **Golden/Invading Zombies (`cfgId 1030000`) specifically returned
0** in this session because the invasion was in its **summon-boss phase**
(`ActivityMonsterInvasionDataManager:GetActivityData().summonBossId=1030091`,
`GetInvasionSummonProgress()=40` maxed, `GetInvasionBossInfo()=nil`) — they only spawn in the
**kill phase** (Follow-up 3). Other soloable monsters (lvl 8–27) remain enumerable/attackable.

### Re-confirmed live, and the same wall

- `GoToUtil.OnClickWorldPoint(528614, 2, uuid)` reproduced the populated `UIWorldPoint` popup
  (`hasMonsterData=yes`) — Finding-7/8 selection re-verified on a fresh session.
- `GoAttackMonster(pid)` re-confirmed to **ignore its arg** (always `528614`), per #1031.
- The **final launch confirm still could not be verified**: heavy probing crashed the
  single-session ACE client, and a direct `LastWar.exe` start self-exits via
  `ApplicationLaunch.RelaunchApplicationPC` (the game detects it wasn't started by the launcher).
  Recovery needs a **manual "Play" click in `LastWarLauncher.exe`** (it does not auto-start the
  game). So the last step (`OnAtkClick`/`OnCreateClick` → `IsHaveMarchInWorld==true`) stays TBD
  until a launcher-started session with a soloable target is available.

## Finding 10 — EXECUTED: full no-click-select + launch solo attack (post-invasion roaming monster)

The invasion event ended (no golden zombies). A **solo march on a roaming lvl-22 monster
«Скупой» was launched and the monster killed**, end-to-end. Two decisive discoveries closed the
gaps from Findings 6–9.

### `GetMonsterListInArea` is INVASION-only — empty after the event ends

`WorldScene:GetMonsterListInArea(center, size, whitelist, result)` enumerates only
**invasion-area** monsters. Post-event it returns **0** for every whitelist tried (golden `1030000`,
the small `monsterTemplateDic` ids, dense ranges `1..300`, `1030000..1032000`). Note
`MonsterTemplateManager.monsterTemplateDic` is **lazily populated** (empty at world entry; each
opened monster adds its template — keys are small ints like `38`, not the `1030000` cfgId). So the
roaming monsters present after the event are **not** reachable through `GetMonsterListInArea`.

### THE no-click SELECT primitive for roaming monsters — `TouchObjectEventTrigger:OnClick()`

Every roaming monster's clone (`WorldMonster0N(Clone)`, non-Boss) has a child GameObject carrying a
**`TouchObjectEventTrigger`** MonoBehaviour whose **`OnClick` is a plain Lua function**. Invoking it
directly runs the genuine tap-resolution and opens the **fully populated** `UIWorldPoint` popup for
that exact monster — no physical click, no uuid needed up front:

```lua
local arr = CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.UnityEngine.MonoBehaviour))
for i=0,arr.Length-1 do local mb=arr[i]
  if mb and mb:GetType().Name=='TouchObjectEventTrigger' then
    local go=mb.gameObject local p=go
    while p and not string.find(p.name,'WorldMonster') and p.transform.parent do p=p.transform.parent.gameObject end
    if p and string.find(p.name,'WorldMonster') and not string.find(p.name,'Boss') then
      mb:OnClick()                                   -- opens the real attack popup, NO physical tap
      break
    end
  end
end
local c = UIManager.Instance:GetStackTopWindow().Ctrl  -- UIWorldPointCtrl
local md = c:GetMonsterData(c.uuid)                    -- MUST pass uuid → full detail (Finding 8)
-- md.canAttack==1 → soloable; c.pointId / c.uuid / c.type = the real triple
```

Proven: this opened «Скупой» **pid=528560, type=1, uuid=1397117505394419512, canAttack=1, level=22**.
With the real uuid in hand, `GoToUtil.OnClickWorldPoint(pid, type, uuid)` reopens it deterministically
(**uuid is required — `uuid=0` returns no-popup even for a valid point**, at any `type`).

### The programmatic LAUNCH is walled by `canMarch=false`; the real dispatch UI recomputes it

`MarchUtil.OnClickStartMarch(ATTACK_MONSTER, pid, uuid, 0, true, nil, srv, 0, special, true)` opens
`UIFormationSelectListV2`, but **`Ctrl:CheckCanBattle()==false`** so `OnAtkClick()` closes without
marching. Root cause: **every `ArmyFormationDataManager.ArmyFormationList` entry has
`canMarch=false`** even though the garrison formations hold real troops (`totalSoldierNum` 3123/2565/
2610), so `GetFormationListData()` returns 0 and `GetCurSoldierNum()`=0. It is **not** a free-slot
problem (`WorldMarchDataManager:GetOwnerMarches()`=0, queues free) — `canMarch` is a flag the **real
dispatch render recomputes** and a headless programmatic open does not. `BestSelect()` /
`SetSelectFormationUuid()` did not flip it. **Fully-programmatic launch remains blocked here.**

### What worked — hybrid: no-click SELECT + physical-tap dispatch

The reliable end-to-end (this session renders the 3D world fine — screenshots are usable):
1. **No-click select** the soloable monster (`TouchObjectEventTrigger:OnClick()` above) → popup with
   the red crossed-swords **«Атаковать»** button.
2. **Physically tap «Атаковать»** → the real `UIFormationSelectListV2` renders with formations loaded
   (`canMarch` recomputed): 6 heroes Lv.175, **3,123/3,123 units, 55.62M vs 1.32M → «Лёгкая победа»**.
3. **Physically tap «Марш»** → **march launched**: `IsHaveMarchInWorld()==true`, `GetOwnerMarches()==1`,
   green march path base→monster (`results/after_march.png`).
4. ~40 s later the march returned (`IsHaveMarchInWorld` true→false) and **«Скупой» was gone from the
   map** — killed (`results/battle_done.png`).

**Bottom line:** no-click SELECTION of an arbitrary roaming monster is fully solved via
`TouchObjectEventTrigger:OnClick()`. The **launch** still needs the real dispatch render (physical
tap of «Атаковать»→«Марш») because `canMarch` is not computed for a headless `OnClickStartMarch`; a
purely-programmatic launch is the one remaining gap.

## Finding 11 — FULLY no-click launch SOLVED: `MarchUtil.TryStartMarch`

The dispatch-UI wall (Finding 10) is bypassed entirely. `canMarch` turned out to be a **red
herring** — it is a plain boolean field on the `FormationData` object with no setter, and forcing
`v.canMarch=true` does **not** make `Ctrl:CheckCanBattle()` pass. The real blocker was that the
dispatch (`UIFormationSelectListV2`) only loads its formation soldier state through the physical
«Атаковать» button's runtime handler; `MarchUtil.OnClickStartMarch` opens the window with
`GetCurSoldierNum()=0`, and `OnAtkClick` then aborts.

The fix skips the dispatch UI completely — a direct server-send primitive:

```lua
-- selfMarchUuid = the ARMY FORMATION uuid (from ArmyFormationDataManager.ArmyFormationList)
MarchUtil.TryStartMarch(
  formationUuid,                    -- selfMarchUuid  (e.g. <formationUuid>)
  MarchTargetType.ATTACK_MONSTER,   -- theMarchTargetType  (=1)
  curStamina,                       -- e.g. 10
  true,                             -- isFormation
  monsterUuid,                      -- targetUuid  (from the popup Ctrl.uuid)
  monsterPointId,                   -- pointId
  true,                             -- backHome
  needSoldier,                      -- e.g. totalSoldierNum 3123
  0,                                -- destroyTimeIndex
  targetServerId)                   -- e.g. 935
```

Signature (via `debug.getlocal`): `TryStartMarch(selfMarchUuid, theMarchTargetType, curStamina,
isFormation, targetUuid, pointId, backHome, needSoldier, destroyTimeIndex, targetServerId)`.

**Proven live, no physical clicks at all:** monster selected via `TouchObjectEventTrigger:OnClick()`
(Finding 10), then `TryStartMarch(<formationUuid>, 1, 10, true, uuid, pid, true, 3123, 0, 935)`
→ `ok=true`, **`IsHaveMarchInWorld()==true`, `GetOwnerMarches()==1`**, and ~50 s later the march
returned (`true→false`) with the monster killed. This is the complete end-to-end no-click solo
attack — `TouchObjectEventTrigger:OnClick()` (select) + `MarchUtil.TryStartMarch(...)` (launch),
zero `pydirectinput`, zero dispatch-UI rendering.

Notes: `selfMarchUuid` is the **formation** uuid when `isFormation=true` (not a march uuid; `0`
also failed — pass a real army-formation uuid with troops). `needSoldier` = the formation's
`totalSoldierNum`. `MarchUtil.SendCreateMarchToServer(...)` needs a real `formationData`/`startPos`
object and did not fire with nils — `TryStartMarch` is the clean entry.

## Finding 12 — CORRECTION to Finding 11: `TryStartMarch` silently validates preconditions

Reproducing Finding 11 in a fresh state exposed that `MarchUtil.TryStartMarch(...)` returns
`ok=true` (no Lua error — SafeDoString swallows) but **does NOT always create a march**. It
silently validates preconditions and no-ops when they fail. Verified across many runs
(`tools/mini_kill_rally.py` + probes): the same call that "worked" in Finding 11 now returns
`ok=true` with `IsHaveMarchInWorld()` staying **false**. Two gates found:

1. **Formation must be loaded** — `ArmyFormationDataManager.ArmyFormationList[i].totalSoldierNum`
   must be > 0. In a cold headless session it is **0** (`GetAllTotalSoldierNum()=0`,
   `GetArmyList()=0`); a **physical «Атаковать» dispatch tap loads it to 3123** and it **persists
   after the dispatch closes**. No pure-Lua loader found (`SendFormToServer`/`AutoInitFormationData`
   no-op; `RefreshFormationSoldier`/`InitData`/`UpdateArmyFormationListData` are server-message
   handlers needing a `message` arg).
2. **Stamina/readiness** — `ArmyFormationDataManager:HasStaminaEnoughFormation(formationUuid)` must
   be **true**. After a run of test kills it went **false** for every formation
   (`GetCurStaminaByUuid=52` but `stamEnough=false`), and `TryStartMarch` then no-ops.

So Finding 11's one-off success happened only because a **prior physical dispatch had loaded the
formation** and stamina was still available. `TryStartMarch` is a genuine send primitive but is
**not a reliable cold-start pure-Lua launch** — it depends on formation-load (currently only a
physical dispatch does this) and `HasStaminaEnoughFormation`. Preflight both before calling:

```lua
local afd = DataCenter.ArmyFormationDataManager
-- pick a formation with totalSoldierNum>0 AND HasStaminaEnoughFormation(uuid)==true, else TryStartMarch no-ops
```

**Net status of the no-click attack:** SELECT is fully solved (`TouchObjectEventTrigger:OnClick()`).
LAUNCH via `TryStartMarch` works **only when the formation is loaded and stamina-ready**; loading
the formation still needs a physical dispatch tap, so a *fully cold* no-click launch is not proven.
The reliable end-to-end remains the hybrid (Finding 10): no-click select + physical «Атаковать»→«Марш».

## Finding 13 — DEFINITIVE: `TryStartMarch` does NOT launch; Finding 11 was a false positive

Re-ran `tools/mini_kill_rally.py` with formations **loaded** (`totalSoldierNum` 3123/2565/2610) and
stamina **available** (user-confirmed). Both calls —
`MarchUtil.TryStartMarch(formationUuid, ATTACK_MONSTER, ...)` and `... RALLY_FOR_BOSS, ...)` —
returned `ok=true` but created **no march**: `IsHaveMarchInWorld()==false`, `GetOwnerMarches()==0`,
alliance team-marches `0→0`. Repeated across many states (cold/loaded formation, popup/dispatch open,
various `curStamina`). **`TryStartMarch` silently no-ops — it is NOT the march-launch function.**

Finding 11's single `HV=true` was a **leftover/pre-existing march** from the physical-hybrid attack
run just before it (no baseline was logged) — a false positive. `HasStaminaEnoughFormation` is also
not the gate (it stays false at stamina levels where the physical «Марш» launches fine, so it means
something else). No pure-Lua send primitive found that launches: `TryStartMarch`,
`SendCreateMarchToServer` (needs real formationData/startPos), `OnClickStartMarch`+`OnAtkClick` (Ctrl
soldier state 0) all fail.

**Standing conclusion.** No-click **SELECT** is solved (`TouchObjectEventTrigger:OnClick()`). A fully
no-click **LAUNCH is NOT achieved** — the only reliable launch is the real dispatch «Марш» button,
whose handler is a runtime `NewButton` callback not reachable through the exposed Lua/CS surface
(`ExecuteEvents.Execute<T>` unbound; `onClick` has 0 persistent listeners; `OnMarkClick` is the
"place marker" button → `UIPositionAdd`, not attack). So the working end-to-end stays the **hybrid**
(Finding 10): `TouchObjectEventTrigger:OnClick()` select + **physical** «Атаковать»→«Марш» tap
(button position varies per monster → locate it dynamically, don't hardcode screen coords).

## Finding 14 — the REAL «Марш» handler caught via monkey-patch: `OnCreateClick` → `SendCreateMarchMessage`

Instead of guessing, the exact call chain was captured by **monkey-patching** — wrapping every
`MarchUtil.*` function AND the open `UIFormationSelectListV2` Ctrl's 55 methods with a logging
shim (`_G.__MP_ORIG`/`_G.__DC_ORIG`; each wrapper does `Debug.LogError('MPCALL/DCALL '..name)` then
calls the original), then pressing «Марш» physically once and reading `Player.log`. Safe (fires only
on the wrapped calls, no global `debug.sethook` overhead).

**The «Марш» button = `Ctrl:OnCreateClick()`** (NOT `OnAtkClick` — that was the wrong guess behind
every earlier failed launch). Full ordered chain on press:

```
Ctrl:OnCreateClick()
  → Ctrl:CheckCanBattle()
  → Ctrl:GetCostStaminaByTargetType()
  → MarchUtil.GetCanAddHeroNum()
  → Ctrl:NeedTakeArmy()
  → MarchUtil.SendCreateMarchMessage(formationUuid, 1, targetPoint, targetUuid, 1, 1, false, serverId, nil)
  → MarchUtil.IsScoutMarch()
  → Ctrl:CloseSelf() / TargetSpDeal() / Delete()
```

**Exact `SendCreateMarchMessage` args** (args-logger on the wrapper, from a real «Марш»):
`n=9 [formationUuid=<formationUuid> | targetType=1 | targetPoint | targetUuid | timeIndex=1 |
autoBackHome=1 | needSoldier=false | targetServerId=935 | destroyTimeIndex=nil]`. Note
**`needSoldier=false`** (boolean, not a soldier count) and **`destroyTimeIndex=nil`** — the values
earlier guesses got wrong.

**Reproduction status.** Calling `SendCreateMarchMessage` (or `Ctrl:OnCreateClick()`) cold via Lua
with these exact args returns `ok=true` but launches nothing — AND at this point the **physical**
«Марш» (same `OnCreateClick`→`SendCreateMarchMessage` chain, confirmed by the trace) **also** stopped
launching. Cause: `ArmyFormationDataManager:HasStaminaEnoughFormation(F)==false` even at
`GetCurStaminaByUuid=59` — i.e. the gate is **per-hero energy**, depleted by the session's ~8 test
kills; the server rejects the march regardless of caller. So the mechanism is correct
(`OnCreateClick`/`SendCreateMarchMessage`), but a launch can't be demonstrated until hero energy
regenerates. `TryStartMarch` (Findings 11–13) was simply the wrong function.

**Remaining for fully no-click:** (a) open the dispatch **with troops** without a physical
«Атаковать» (the formation-load-into-Ctrl problem, Finding 12 — still unsolved via Lua), then (b)
`Ctrl:OnCreateClick()` (now known) instead of a physical «Марш». With hero energy available, the
hybrid drops to a single physical «Атаковать» tap + Lua `OnCreateClick()`.

## Finding 15 — the chain re-traced with a `debug.sethook` frame-hook: reconciles the UI entry vs the logic call, and the stamina gate blocks the PHYSICAL button too

Re-ran the trace (task #1032) with a complementary instrument: `tools/_march_trace.py` wraps every
`MarchUtil.*` (args-logging, marker `MTR`/`MDUMP A`) **and** arms a gated `debug.sethook(fn,'c')`
call-hook (marker `MDUMP B`) filtered to march keywords, then fired **one physical** «Атаковать»→«Марш»
on a solo monster («Скупой» pid=502558 type=1 srv=935 canAttack=1, launched successfully — both army
formations visibly marched out). Captured 814 wrapped calls + 313 hook frames. The hook exposes the
**real Lua source paths** (`…/aps_client/…/Assets/Main/LuaScripts/UI/UIFormation/UIFormationSelectListV2/…`).

**The two taps, exactly:**
- **«Атаковать»** (round red crossed-swords on `UIWorldPoint`) →
  `MarchUtil.OnClickStartMarch(1, pointId, uuid, -1, 1, nil, 935, nil, 0)` — arg #1 = `MarchTargetType.ATTACK_MONSTER`,
  #4 `ownerUid=-1`, #5 `type=1`, #7 `srcServer=935`. This opens **and fully initialises**
  `UIFormationSelectListV2` (`Ctrl:InitData → RefreshTargetPoint → BestSelect → SetSelectFormationUuid`,
  loads the formation, computes `CheckBattleState`/`RefreshStaminaState`, `CalcMarchSpeedByConfig`).
- **«Марж»** (blue confirm on the selected formation cell) → hook caught
  **`FormationSelectListCellNewV2.lua:337:OnAtkClick`** — i.e. the button's UI `onClick` is the **cell**
  component's `OnAtkClick`, *not* a `Ctrl` method.

**Reconciles Finding 14.** Finding 14 (Ctrl-method monkey-patch) named `Ctrl:OnCreateClick` → `SendCreateMarchMessage`.
Both are correct and sequential: the blue button →
`FormationSelectListCellNewV2:OnAtkClick()` (cell UI handler, this finding) →
`Ctrl:OnCreateClick()` (logic, Finding 14) →
`Ctrl:CheckCanBattle` + `GetCostStaminaByTargetType` + `MarchUtil.GetCanAddHeroNum` + `Ctrl:NeedTakeArmy` →
`MarchUtil.SendCreateMarchMessage(formationUuid, 1, targetPoint, targetUuid, 1, 1, false, serverId, nil)` →
`Ctrl:CloseSelf`. The actual send is invisible to the `MarchUtil.*` table-wrappers because callers hold
the send fns as **module upvalues** captured at load time (seen only as anonymous `Util/MarchUtil.lua:2046/2297/2553:?`
frames), which is why Findings 11–13's table-level replays never intercepted it.

**Reproduction — all three confirm entries no-op via Lua, AND so does the physical button once energy is spent.**
With the dispatch opened by the *real* `OnClickStartMarch` (warm formation, `selectFormationUuid=<formationUuid>`,
`targetType=1`, `targetPoint` set) I called, in turn: `Ctrl:OnAtkClick()`, the exact selected
**cell** `FormationSelectListCellNewV2:OnAtkClick()` (found via `View.formationList`, 4 cells, matched the
selected uuid), and `Ctrl:OnCreateClick()`. **Every one returned `ok=true` but created no march**
(`GetOwnerMarches()` 0→0, `IsHaveMarchInWorld=false`). Crucially, a **physical** «Атаковать»→«Марж» on a
fresh monster («Обжора» pid≈, «Лёгкая победа» 55.62M vs 9.28M) at this same moment **also** closed the
dispatch **without launching** (monster stayed on the map, `GetOwnerMarches()`=0). The distinguishing
state: `ArmyFormationDataManager:HasStaminaEnoughFormation(F)==false` (at `GetCurStaminaByUuid=60`) — hero
**energy** was drained by the session's earlier test kills. So the gate that aborts the confirm is the
**stamina/energy check, and it blocks the physical button identically to a Lua call** — it is *not* an
execution-context (SafeDoString-thread) problem. This **confirms Finding 14's stamina conclusion** and
removes the "maybe Lua just can't reach the handler" doubt: the handler runs fine; the march is
server-gated on energy.

**Net for #1032:** the real «Марж» Lua chain is now fully mapped and cross-validated
(`OnClickStartMarch` init → cell `OnAtkClick` → `Ctrl:OnCreateClick` → `SendCreateMarchMessage`, exact
args). A fully no-click launch stays blocked **only** by hero-energy regen (untestable while depleted);
when energy is available, `Ctrl:OnCreateClick()` on a physically-opened (troops-loaded) dispatch is the
one Lua call to try. Tools: `tools/_march_trace.py` (install/gateon/gateoff/dump/restore), `tools/_trace_march.py`.

## Finding 15 — pure-Lua «Марш» is walled at `CheckCanBattle`, which is UI-interaction-bound

Deep dig (monkey-patch the whole `UIFormationSelectListV2` Ctrl class, trace both a physical «Марш»
press and a Lua `c:OnCreateClick()` call). Definitive:

- **Physical «Марш»** → `OnCreateClick` → `CheckCanBattle`==**true** → `GetCostStaminaByTargetType` →
  `MarchUtil.GetCanAddHeroNum` → `NeedTakeArmy` → `MarchUtil.SendCreateMarchMessage(...)` → march
  created (verified live this session: `IsHaveMarchInWorld==true`, green path base→monster).
- **Lua `c:OnCreateClick()`** → `OnCreateClick` → `CheckCanBattle`==**false** → immediate
  `CloseSelf`/`Delete`; it never reaches `SendCreateMarchMessage`. So `CheckCanBattle` is the exact
  gate.

`CheckCanBattle` is genuinely false in a headless Lua call and **not** a monkey-patch artifact:
after **unwrapping all 55 Ctrl methods** (restoring originals), `c:CheckCanBattle()` still returns
`false`, `GetCurSoldierNum()==0`, `currentFormationUuid==0` — while the dispatch **View** shows the
formation fully loaded («Юниты 3,123/3,123», «Лёгкая победа», active «Марш»). Neither
`SetSelectFormationUuid`, `BestSelect`, direct `currentFormationUuid=` assignment, nor a **physical
tap on a formation cell** (which fires `SetSelectFormationUuid`+`SetTimeIndex`+`InitRallyTime` but
leaves `currentFormationUuid==0`/`CheckCanBattle==false`) makes it true. Only a real **physical
«Марш» button press** flips `CheckCanBattle` to true — it reads march-ready state established by the
Unity EventSystem/View interaction that a Lua method call does not reproduce.

**Conclusion.** The full no-click attack decomposes as: no-click SELECT
(`TouchObjectEventTrigger:OnClick()`, solved) + physical «Атаковать» + physical «Марш». The launch
**works** (real march confirmed), but the final «Марш» **cannot** be replaced by Lua
`Ctrl:OnCreateClick()` / `SendCreateMarchMessage` — the `CheckCanBattle` gate is bound to real
UI-input state, not reachable from the exposed Lua/CS surface. Minimum = 2 physical taps
(«Атаковать» + «Марш»); the monster SELECTION is the only fully-no-click half.

## Finding 16 — the EXACT send captured from the live button; pure-Lua `SendCreateMarchMessage` is sent but NOT honored by the server

New session, deeper instrumentation. Two corrections to Finding 15, and a definitive result.

**(1) `CheckCanBattle` takes the formation uuid as a PARAMETER.** Prior findings called
`c:CheckCanBattle()` with no arg and got `false`; a `debug.sethook('l')` line-watch of the function
body shows the first local `uuid` is that parameter — nil when unpassed, so `formation=nil` →
`UIUtil.ShowTipsId(300007)` → returns false. **`c:CheckCanBattle(formationUuid)` returns `true`** on a
warm formation. So Finding-15's "CheckCanBattle can't be made true from Lua" was an arg bug, not a
UI-state wall. (`ShowTipsId(300007)` is a missing-translation tip → shows `<300007>`; earlier read as
a stamina/version gate — it is just "no formation selected".)

**(2) The exact send, captured live.** Wrapping `MarchUtil.SendCreateMarchMessage` to store its args in
a global, then pressing the physical «Марш» once (verified launch: `GetOwnerMarches` 0→1 + green
march path), captured the byte-exact call:
```
MarchUtil.SendCreateMarchMessage(formationUuid, 1, pointId, uuid, 1, 1, false, serverId, nil)
--   (formationUuid, MarchTargetType.ATTACK_MONSTER=1, targetPoint, targetUuid, timeIndex=1,
--    autoBackHome=1, needSoldier=false, targetServerId, destroyTimeIndex=nil)
```
Traced end-to-end: `SendCreateMarchMessage → SendCreateMarchToServer → SFSNetwork:SendMessage` → builds
`Net/Msgs/WorldMarchFormationNewMessage` (SmartFoxServer; serializes every hero via
`GenerateServerHeroArray`) → `ToBinary` → native `[C]:SendLuaMessage`. So a Lua call **does** reach the
socket-send.

**(3) DEFINITIVE: calling that exact function from SafeDoString does NOT create a march.** Across
~8 clean-baseline runs (`GetOwnerMarches().Count` confirmed 0 and stable before each; fresh
soloable target with `canAttack==1`; all 3 formations tried; with/without a preceding
`OnClickStartMarch` handshake), `SendCreateMarchMessage(...)` returns `ok=true` but `ownerMarches`
stays 0 and no march appears. The **physical** «Марш» with the **same args** launches every time
(fast one-process «Атаковать»→«Марш» double-tap; several green paths confirmed). The one apparent
pure-Lua success earlier in the session was a **false positive** — a leftover physical march still
traveling when the delayed `ownerMarches=1` was read (the exact Finding-13 trap).

**Root cause of the gap.** The message is structurally identical, reaches `SendLuaMessage`, but the
server does not honor a march request originated from `XLuaManager.SafeDoString` (which runs on a
hijacked thread outside the normal `LuaUpdater:Update` tick). The genuine dispatch flow attaches
session/sequence state on the main loop (and/or a required preceding in-session handshake) that the
off-loop call lacks; the server silently drops the request. This is not an args problem, not a
`CheckCanBattle` problem, and not stamina (`GetCurStaminaByUuid`≈66, plenty).

**Standing conclusion (unchanged from Finding 13/15, now with the exact primitive named).** No-click
**SELECT** is solved (`TouchObjectEventTrigger:OnClick()`). No-click **LAUNCH via pure Lua is NOT
achievable** with the current out-of-process SafeDoString technique — the launch function and exact
args are fully identified (`SendCreateMarchMessage`), but only the real UI flow's send is honored.
Reliable launch = HYBRID: no-click select + a fast physical «Атаковать»→«Марш» (both taps in one
process so the dispatch doesn't auto-close between them — that timing, not the button position, is
what made earlier physical attempts "miss"). TryStartMarch remains a red herring (never launches).

## Finding 16 — SOLVED: fully-automated no-hang march via main-thread timer + clean popup close

The pure-Lua launch (Findings 11–15) is finally solved by two fixes, no physical «Марш» tap:

1. **Send on the MAIN THREAD, not the SafeDoString hijack thread.** A cold
   `MarchUtil.SendCreateMarchMessage(...)` on the hijacked thread returns `ok=true` but the server
   drops it (no march). Schedule it on the game's own Lua scheduler instead:
   **`TimerManager:GetInstance():DelayInvoke(callback, delaySeconds)`** — a one-shot deferred call
   that runs the callback during the main-thread update loop. Verified: a `DelayInvoke` marker fires
   in Player.log, and `SendCreateMarchMessage` invoked from inside it **creates the march**
   (`IsHaveMarchInWorld()` false→true, `GetOwnerMarches()==1`).
2. **Close the monster popup with `Ctrl:CloseSelf()`, NEVER `DestroyAllWindow()`.** The UI "hang"
   (HUD vanishes, elements don't return) was caused by `UIManager.Instance:DestroyAllWindow()` —
   it destroys the persistent main HUD (which is not recreated; `ChangeToWorld`/`OpenWindow(UIMain)`
   did not restore it). Closing only the `UIWorldPoint` popup via its own `Ctrl:CloseSelf()` leaves
   the HUD fully intact.

**Working recipe (no physical march tap, no hang):**
```lua
-- monster uuid is NOT stored client-side (clone has only ModelHeight/AutoAdjustLod/UIWorldLabel/
-- TouchObjectEventTrigger; OnClick's upvalues are a C-binding; uuid=0 → server rejects). So a
-- server query is required to get uuid — TouchObjectEventTrigger:OnClick() (opens UIWorldPoint):
trig:OnClick()
local c = UIManager.Instance:GetStackTopWindow().Ctrl      -- UIWorldPointCtrl
local pid, uuid, srv = c.pointId, c.uuid, c.serverId
c:CloseSelf()                                              -- close ONLY the popup, keep the HUD
TimerManager:GetInstance():DelayInvoke(function()
  MarchUtil.SendCreateMarchMessage(formationUuid, MarchTargetType.ATTACK_MONSTER,
                                   pid, uuid, 1, 1, false, srv, nil)  -- needSoldier=false, destroyTimeIndex=nil
end, 0.5)
```
Proven live (HUD intact, «Очередь походов 1/3», «В пути», green march path base→monster). This
bypasses the `UIFormationSelectListV2`/`OnCreateClick`/`CheckCanBattle` dispatch entirely (Finding 15
wall) — the march is created straight from `SendCreateMarchMessage` on the main thread. `pid` is also
readable no-click from the clone position (`SceneUtils.WorldToTileIndex(clone.transform.position)`),
but `uuid` still needs the one `OnClick` server fetch.

## Finding 17 — FINAL, CONFIRMED: no-click solo attack, two modes (retracts Findings 11–13)

The no-click solo monster attack is solved and confirmed live (user-verified: HUD intact, march
created). Two reusable scripts:

- **`tools/solo_attack.py`** — MODE 1 (uuid unknown): find a `WorldMonster0N(Clone)` →
  `trig:OnClick()` (opens `UIWorldPoint`; the **server returns the uuid**) → read pid/uuid/serverId
  from the popup `Ctrl` → **`Ctrl:CloseSelf()`** (close ONLY the popup) → main-thread send.
- **`tools/dev/solo_attack_direct.py <pid> <uuid> [serverId]`** — MODE 2 (uuid known): **just** the
  main-thread send, **zero UI touch** (no OnClick, no popup, no CloseSelf). `OnClick` exists only to
  FETCH the uuid; with it in hand the march is created directly. Verified false→true from a clean
  `om=0` baseline, twice.

Both modes converge on the same two mechanisms:

1. **Send on the MAIN THREAD.** A cold `MarchUtil.SendCreateMarchMessage(...)` from the SafeDoString
   hijack thread returns `ok=true` but the server drops it. Schedule it on the game's own scheduler:
   **`TimerManager:GetInstance():DelayInvoke(fn, 0.5)`** (one-shot). Called from inside it, the send
   creates the march. Exact call:
   ```lua
   MarchUtil.SendCreateMarchMessage(formationUuid, MarchTargetType.ATTACK_MONSTER,
                                    pid, uuid, 1, 1, false, serverId, nil)
   -- args: formationUuid, targetType=1, targetPoint, targetUuid, timeIndex=1,
   --       autoBackHome=1, needSoldier=false, targetServerId, destroyTimeIndex=nil
   ```
2. **Never `UIManager:DestroyAllWindow()`** — it destroys the persistent HUD (the "UI hang";
   `ChangeToWorld`/`OpenWindow(UIMain)` do not restore it). Use `Ctrl:CloseSelf()` on the popup only.

Notes: the monster **uuid is not stored client-side** (the clone has only `ModelHeight`/
`AutoAdjustLod`/`UIWorldLabel`/`TouchObjectEventTrigger`; `OnClick`'s upvalue is a C-binding;
`uuid=0` is rejected) — MODE 1's single `OnClick` server fetch is the only way to obtain it. `pid`
alone is readable no-click via `SceneUtils.WorldToTileIndex(clone.transform.position)`. This path
bypasses the whole `UIFormationSelectListV2`/`OnCreateClick`/`CheckCanBattle` dispatch (Finding 15).

**RETRACTION — Findings 11, 12, 13 (`MarchUtil.TryStartMarch`) were WRONG.** `TryStartMarch` is
**not** the launch function; it returns `ok=true` but never creates a march. Finding 11's single
`HV=true` was a leftover/pre-existing march (no baseline was logged) — a false positive, and
Findings 12–13 chased the resulting phantom `HasStaminaEnoughFormation`/`canMarch` gates. The real
launch primitive is **`MarchUtil.SendCreateMarchMessage`** invoked on the main thread (this Finding).

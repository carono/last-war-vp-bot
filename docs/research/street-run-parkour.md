# «Уличный забег» / Street Run (Surfing endless runner)

Reconnaissance for task #1101 — a Subway-Surfers-style 3-lane endless runner event:
run as far as possible, dodge obstacles, limited attempts. Findings are **proven by
live inspection of the client** (server **935**, 2026-07-29); open items are called out.

> **Correction (2026-07-29).** Earlier sessions mapped this to *Ghost Parkour*
> (`LWGhostParkourDataManager`) — **wrong**. That manager reports `nil` even while the
> event is open. On the correct account the event is internally **Surfing**:
> `DataCenter.LWSurfingDataManager`, windows `UISurfingBattle*`, source
> `Assets/Main/LuaScripts/DataCenter/LWSurfing/LWSurfingDataManager.lua`. The two
> earlier blockers compounded: wrong account **and** wrong manager.

## TL;DR

- Display name **«Уличный забег»**; internally the **Surfing** minigame. Manager
  `DataCenter.LWSurfingDataManager` (method names say *Parkour*, e.g.
  `SendGetAllParkourInfosMessage`, `MsgDefines.ParkourFightStart` — the feature was
  renamed «surfing» in code but keeps parkour message names).
- **Event is OPEN** (live-proven). Fingerprint that pinned the manager: the panel shows
  best distance **8185** and **28** attempts → `LWSurfingDataManager` is the *only*
  manager whose `GetRemainTimes()==28` **and** `GetPersonalHightestScoreData()==8185`.
  `GetActId()==80063` = activity `id=80063, type=349` in `ActivityListDataManager`.
- ~~Because the run is real-time, per-frame state must be read by vision, not Lua.~~
  **Overturned (task #1103, 2026-07-29).** Per-frame obstacle state IS readable from Lua —
  see [§ Reading obstacles from Lua](#reading-obstacles-from-lua-1103--supersedes-vision).
  The `LWSurfingDataManager` holds only meta (records, attempts, timings), but the live
  **runner scene** exposes every obstacle as a monster object with exact lane + distance.

## Three "parkour"-named things — do NOT confuse

| Feature | Manager / entry | What it is |
|---|---|---|
| **«Уличный забег» runner** ✅ target | `DataCenter.LWSurfingDataManager`, windows `UISurfingBattle*` | The Subway-Surfers 3-lane dodge runner (metres, obstacles, revives). |
| LW Parkour campaign | `ParkourManager`, `GoLWParkourBattle()` → `UIParkourMap` | A **squad auto-battle** stage campaign. NOT the target. |
| Ghost Parkour co-op | `LWGhostParkourDataManager`, `UIGhostParkour*` | Weekly co-op «Операция Призрак» / ghost-recon. Reports `nil` here. NOT the target. |

## `DataCenter.LWSurfingDataManager` API (dumped live, 92 methods)

State / meta (live values in parens):

- `GetActId` (=80063 — the activityId) · `SetActId`
- `GetRemainTimes` (=28 — «Попыток испытания») · `GetRound` (=4)
- `GetPersonalHightestScoreData` (=8185 — best distance, metres, a plain number)
- `GetTodayPersonalProgressScore` (=3282) · `GetTheBattleEndTime`
  (=1785722400000 ms; `endTime−now ≈ 5.006 d`, matches on-screen «5d»)
- `GetResurgenceLimit` (=3) · `GetResurgenceCost` (revive price, x100 coins)
- `GetCoinId`/`GetCoinNum` (parkour coins) · `GetParkourRankInfo`, `GetSurfingRankInfo`,
  `GetMvpPlayer`, `GetAllianceScore`, `GetSurfingBuffData`, buff/battlepass getters

Run control (send server requests — do NOT call idly, each `ReqFightStartCheck`
**consumes an attempt**):

- **`ReqFightStartCheck(restart)`** — the in-game «Начать» button. `string.dump`:
  checks `ActWinterStormManager:CheckInMatchingViewState`, the start-msg cooldown
  (`GetStartMsgCD`/`startMsgTs`; on cooldown → `UIUtil:ShowTipsId(avatar_tips002)`),
  then `SFSNetwork:SendMessage(MsgDefines.ParkourFightStartCheck, restart, curTs)`.
  Server-approved flow → `OnStartGame` → the runner scene loads. **Proven live:**
  `ReqFightStartCheck(false)` started a real run (attempts 28→27).
- `ReqStartGame(restart)` — raw `SFSNetwork:SendMessage(MsgDefines.ParkourFightStart,…)`,
  skips the checks. `restart=false` = fresh run.
- `ReqRebirthGame` / `ReqRebirthInfo` — revive on the death popup (3 available, x100 coins).
- `ReqEndGame`, `ReqEndStage`, `ReqMonsterCheck`, `ReqTimeCheck`, `FightStartCheck`.
- **`GoBackToActivityPanel()`** — dismisses the «Испытание окончено» result popup and
  returns to the event panel. **Proven live** — required between runs (the popup blocks
  a fresh `ReqFightStartCheck`).

Network fetch (populate the manager): **`SendGetAllParkourInfosMessage`**,
`SendGetParkourAllianceBattlePassInfoMessage`. Rank refresh:
`UpdateSurfingBattleRankInfo`, `UpdateAllianceBattleList`.

## Confirmed mechanics (live frames — `results/street_run/frames/live_*.png`)

- **3-lane endless runner**, third-person behind-the-back. The avatar auto-runs
  forward and starts in the **centre** lane (screen x ≈ 0.49·W, y ≈ 0.63·H).
- **Obstacles**: cars, container trucks, side barriers/blocks, streetlamps — occupy
  specific lanes; dodge by switching lanes. Jump (↑) clears only LOW obstacles (barrels);
  a jump into a tall barrier is fatal (see Jump/slide findings). Slide (↓) exists but its
  targets are unverified.
- **Coins** float along a lane (collectible; top-right counter).
- **Score = distance in metres** (top-left «NNм» + running icon). Best so far 8185.
- **Uncontrolled the run dies at ~88 m** (first obstacle) in <3 s — deterministic;
  useful as a control-signal baseline.
- **Death popup** «Испытание окончено»: result metres, parkour coins earned, buttons
  **«Выйти»** and **«Воскрешение ×100»**, «Оставшиеся воскрешения: 3/3». Dismiss via
  `GoBackToActivityPanel()` (or click «Выйти»). A **«Пауза»** button sits bottom-left
  during the run.

## Vision reflex loop — approach & open items

1. **Capture** the road ROI with `mss` in a tight **in-memory** loop (no per-frame PNG
   save — the calibration capture ran ~4 fps only because it wrote a PNG each frame;
   in-memory grab+detect should hit <30 ms, fast enough).
2. **Detect** the avatar's current lane and the nearest obstacle's lane from a fixed
   band ahead of the avatar. Lane x-boundaries to calibrate from `live_*.png`.
3. **React** with `pydirectinput` (foreground input; PostMessage ignored — see memory
   `project_input_model`). **Input model UNCONFIRMED** — Left/Right = change lane and
   Up/Down = jump/slide is the genre default, but the exact keys must be tested live
   (or read off the user playing).

## Input model (confirmed by the user)

Keyboard arrows via `pydirectinput` (foreground): **← / →** switch lane, **↑** jump,
**↓** slide. v1 of the bot uses lane-switch only.

## Auto-play — how `detect()`/`decide()` work (v2, 2026-07-29)

- **Player lane**: blue-helmet centroid in the bottom-centre ROI → x-threshold to
  lane 0/1/2. Avatar sits at x≈0.49 (centre) by default. Reliable.
- **Obstacles** — the cartoon palette defeats a fixed threshold *and* even per-pixel
  labelling (gold coins are pixel-identical to a **lit barrel**: both H≈18 S≈170 V≈220;
  a white crosswalk ≈ a pale concrete barrier). v2 leans on two robust ideas instead:
  1. **Blob geometry.** Build an obstacle mask (robust road reference = median over a
     wide low road band, so the coin trail sitting on the centre patch no longer
     poisons it; a pixel is an obstacle if it is off-brown-hued = truck, brighter+
     desaturated = concrete, much more saturated = barrel/orange barrier, or much
     darker = shadow/underside). Then connected-component filter: keep large solid
     blobs, drop thin-wide markings (crosswalk/dashes), thin diagonals (lamp poles),
     and **narrow gold blobs (coins) by WIDTH** (<0.055·W) — do NOT colour-carve gold,
     that deletes lit barrels and kills the run.
  2. **Differential decide().** The game always leaves a passable lane, so a real
     obstacle shows up as ONE lane much more blocked than a neighbour; a row blocked
     ~equally across all three is a ground marking → hold. `decide()` steps into a
     genuinely-clear side lane (argmin, gated on the target being both clearer *and*
     actually open); when boxed with an obstacle dead ahead it jumps (↑) **only if the
     obstacle is LOW** (height-gated `low_ahead`).

**Jump/slide findings (live, 2026-07-29).** Controls are ←/→ lane, ↑ jump, ↓ slide.
Critically, **jumping a tall orange/concrete barrier is fatal** — the avatar clips it and
dies (verified: two jumps at a barrier → death at 89 m), so blind jumping is *worse* than
holding; only a low obstacle (a barrel) is hoppable. `detect()` therefore reports
`low_ahead` (topmost obstacle-pixel y in the player's near-lane column: barrel top ≳0.52·H
vs barrier/truck top ≲0.46·H) and `decide()` jumps only when it is set. Slide (↓) is wired
(`run … down`, `BOXED_ACTION`) but its effect on the on-legs construction barriers is
**unverified**: the live slide test was cut short when a **concurrent login from another
device kicked the session** («В ваш аккаунт был выполнен вход с другого устройства» — the
client froze mid-run, then closed on confirm). Re-testing needs sole possession of the
account. The dominant real killer remains the detector *over-blocking an escape lane*
(false positive on the right, where a parallel truck / kerb rock reads as blocked), which
makes the bot think it is boxed when a lane was actually passable.
- **Loop**: in-memory grab+detect at **~12–15 fps**. A 0.18 s cooldown after each key
  stops lane-change overshoot. Death = the big near-white «Испытание окончено» card.
- **Revive**: on death, up to 3× **click the «Воскрешение» button** (screen-relative
  (0.565·W, 0.59·H)) to continue the SAME run — distance carries over. The Lua
  `m:ReqRebirthGame()` does **not** revive (verified: the popup still reports 3/3
  after it). Revives are coin-priced and the price ramps (×100 → ×1000 → ×2000…), so
  ~3 per run is the practical limit. `remainTimes` spends 1 per whole multi-life run.
- **pid auto-resolve**: `find_win()` re-resolves the LastWar.exe pid via
  `il2cpp_probe.find_game_pid()` every call — the client self-restarts into new pids,
  so a hardcoded one silently breaks window capture.
- **Offline tuning**: `test [pattern]` runs `detect()`/`decide()` on saved
  `results/street_run/frames/*.png` and writes annotated copies — tune the detector
  without spending an attempt. `run … debug` logs per-frame perception.

## Reading obstacles from Lua (#1103) — supersedes vision

Task #1103 replaced the vision detector with a programmatic read of the Unity scene via
the xLua daemon. Reader: `tools/lib/surfing_reader.py`; bot commands `readtest` (observe)
and `runlua` (autopilot). **Proven live, server 935, 2026-07-29.**

**Where the state lives.** During a run the loaded modules include
`DataCenter.LWBattle.Logic.Surfing.SurfingLogic` (the per-run logic) and
`Scene.LWBattle.Surfing.Monster.SurfingMonsterManager` (the obstacle manager). Neither is
a singleton you can look up, so capture the live instances by wrapping their methods once,
**before** the run starts (they stash `self` into globals):

```lua
local SL = require("DataCenter.LWBattle.Logic.Surfing.SurfingLogic")
SL.OnStart = function(self,...) _G.__SR_LOGIC=self return <orig>(self,...) end
local MM = require("Scene.LWBattle.Surfing.Monster.SurfingMonsterManager")
MM.Init  = function(self,...) _G.__SR_MM=self return <orig>(self,...) end
```

**The obstacle model.** `SurfingMonsterManager.showList` is a table of monster objects
(also `allMonster`, `farmMonster`, `colliderMap`). Each monster exposes plain Lua fields:

| field | meaning |
|---|---|
| `.x` | lane centre — **one of {32, 36, 40}** (centre lane = 36, lanes 4 units apart) |
| `.dataZ` / `.curWorldPos[3]` | world Z (distance along the track) |
| `.bornId` | template id (e.g. 203001 barrel, 203015/203041 container, 203020/203029 fence) |
| `.unitType` | **4 = solid collider obstacle · 1 = score/coin · 3 = energy · 2 = box** |
| `.gameObject.name` | prefab — the definitive type (`A_Monster_surfing_mutong(Clone)` = barrel, `O_env_ditiepaoku_chexiang_*` = container, `O_Object_high_zhalan*` = fence, `A_Vehicle_truck_02` = truck) |

Player position: `SurfingLogic.player:GetPosition()` → `(x, y, z)`; lane = nearest of
{32,36,40}. Track speed: `SurfingLogic:GetMoveSpeed()` = **30 u/s** (constant), so
`dz = obstacle.dataZ − player.z` gives an exact time-to-impact `dz/30`. Obstacles are
readable ~150 u (~5 s) ahead — full deterministic look-ahead, no pixels.

**Latency.** A read round-trip through the warm daemon (`settle=0.06`) is ~0.09 s ≈ 11 Hz
— on par with the vision loop but with exact geometry and huge look-ahead. A
scene-enumeration fallback (`FindObjectsOfType(Transform)` filtered by prefab name) keeps
`read()` working without the capture hook, at higher cost.

**Classification** (by prefab name, definitive; `unitType` corroborates): barrel/`mutong`
= low, **hoppable**; `dizhalan`/low fence = low; `high_zhalan`/`gaozhalan` = tall fence,
**not** hoppable; `chexiang`/`truck`/vehicle = tall container/truck, **not** hoppable;
coins (`O_Object_score_gold`, unitType 1) and buffs are **not** collision hazards.

**Dodge policy** (`surfing_reader.decide`): (1) nothing imminent → hold; (2) a genuinely
clear adjacent lane → step in; (3) low barrel dead-ahead within the jump window → hop it;
(4) tall obstacle with no clear lane → take the least-bad reachable lane. One-step
reactive: it clears the staggered opening to **~132 m single life** (vs ~88 m no control).
The remaining deaths were **multi-lane traps** — solvable by planning over the look-ahead
rather than reacting to the nearest threat, which is what the next section does.

> **Superseded (task #1121).** Both this reader and the vision loop above are read-only
> history now. The dodge runs inside the game's Lua VM — see the next two sections.

## The track is a fixed layout, not noise (#1121)

Everything the runner throws at the player is **pre-defined config**, parsed into Lua at
stage load and dumpable with `tools/dev/surfing_dump_config.py`
(→ `results/street_run/config/*.json`):

| table | what it holds |
|---|---|
| `SurfingStageTemplateManager` | the stage (50000): scene pools, hero, camera |
| `SurfingStageSceneTemplateManager` | **bands**: `max_meters` (330), `speedZ`, the scene pool and the band's obstacle list |
| `SurfingMonsterBornTemplateManager` | the **patterns**: each is one object at an absolute `coord` = {lane x, y, z} with its monster id |
| `SurfingMonsterTemplateManager` | per monster id: `collide_damage`, `move_speed`, `monster_type`, prefab |

So a run is a chain of **330-metre bands** (21 dumped so far), each band a fixed list of
objects at fixed lanes and distances; `speedZ` is 30 in most bands and 40 in the hard ones.
The first band is identical every run — which is why an uncontrolled run always dies at the
same barrel at 88.75 m. Only the order of bands varies.

**Geometry (live-measured off the colliders, `street_run_ai.py bounds`).** The decisive
correction: an obstacle's `z` is **not its centre**. The subway carriages hang entirely
*behind* their anchor —

| prefab | length along the track | notes |
|---|---|---|
| `A_Monster_surfing_mutong` (barrel) | 1.5 (±0.75) | hoppable |
| `O_Object_high_zhalan1/2` (high fence) | ~1.0 | **cannot be jumped** — ducked under |
| `O_env_ditiepaoku_chexiang_N` (carriage) | **8.24 × N behind z**, ~0 ahead | N = 2..5 → 16–41 units |
| `O_env_ditiepaoku_chexiangxiepo_N` (ramp carriage) | same rule | the ramp ON-piece: run up it, not an obstacle |
| `O_env_ditiepaoku_qiaodong` (bridge gate) | ~34 behind z, **20–64 wide** | spans every lane |
| `O_Object_high_truck_gold_move_N` | driving, `move_speed` 20 or 40 | closes/opens at 10 or −10 u/s |

Modelling a carriage as "half a length around z" is wrong in both directions at once — it
blocks free track ahead of the anchor and misses the 40 units of body that actually kill.
That single fix is worth more than any amount of policy tuning.

## In-VM autopilot (#1121) — supersedes the Python loop

`tools/lib/surfing_ai.lua` is the dodge; `tools/street_run_ai.py` only installs it, starts
attempts and reads the telemetry back. The runner logic hands over everything needed:

- **`SurfingLogic.OnUpdate`** — wrap it and the dodge runs once per frame (60 Hz) instead
  of once per ~0.1 s round trip.
- **`logic:OnMoveLeft/OnMoveRight/OnMoveUp/OnMoveDown`** — the same calls the keyboard and
  swipe handlers make (`self.player:OnMoveX()`), so **no key presses and no window focus**.
- **`logic.monsterMgr.showList` / `.farmMonster`** — the obstacle field, ~200 units ahead.
- **`player.curLine` / `targetX` / `lineChangeTimer`**, `IsJumping()`, `IsSliding()` — the
  exact motion state, so commands are never stacked.

Motion constants, read live: `Const.LineChangeTime` **0.16 s**, `Const.SlideTime` **0.5 s**,
`player.jumpDurationValue` **0.72 s**, `Const.LineOffset` **4**, lanes at x 32/36/40,
`jumpVo` 16.5 with gravity −42 (apex 3.24), `Const.CacheCommandInterval` 0.3.

**The planner.** Every frame it rebuilds a per-lane occupancy map over the next 120 units
(1-unit buckets) and runs a DP over `(bucket, lane)` states with four moves — run on,
change lane (0.16 s, both lanes must be free for the sweep), hop (0.72 s, clears barrels),
slide (0.5 s, clears the high fences and the bridge gates). A hop or a duck is an **arc,
not a box**: only the middle stretch clears anything, so the route is only allowed one when
the obstacle falls inside that middle stretch and the takeoff and landing stretches are
clear — without that rule it hops the instant a hop is legal and lands right in front of
the barrel (a live run died at 88.8 m having jumped at 64.6 m). Only reachable-through-free-
track states are expanded, so any route it returns is collision-free under the model; it
maximises the distance reached and then takes the cheapest route, with small preferences
for the centre lane, for acting early rather than late, and for picking things up. Moving
obstacles are projected through their own drift rather than frozen. The first move of the
route is issued when it comes due; the whole thing is re-planned next frame.

**Buffs are routed to, not stumbled on.** Shield / jetpack / morph / ally are priced at 0.9
and magnet / double / box at 0.25 against a lane change at 1.0, so the route takes a
one-step detour for a shield and never trades safety for a pickup (unsafe routes are not
in the search at all). **On a jetpack** (`player:IsFlying()`) the runner is above the whole
track: the planner drops every ground obstacle from the field for as long as it lasts and
routes purely by pickups, instead of dodging things it cannot hit.

**Offline iteration.** `tools/dev/surfing_simulate.py` replays every dumped band through
the *same* `AI.planRoute` at 60 Hz against the measured collider sizes, from each starting
lane, without spending an attempt — so a policy change is checked against the real track
before it is flown.

## Status vs. the task

- ✅ **Manager identified & proven** — `LWSurfingDataManager`; probe reports OPEN.
- ✅ **Launch/loop proven live** — `ReqFightStartCheck(false)` starts a run,
  `GoBackToActivityPanel()` clears the result popup between attempts.
- ✅ **Track model** — bands, patterns and collider extents dumped and measured.
- 🟡 **Route planning beats the reflex by ~7×** — live (server 935, 2026-07-30) single
  lives of **720–1377 m** against ~132 m for the one-step reflex and ~88 m with no control;
  attempts with revives (`logic:RebirthGame()`, which does work, unlike the data manager's
  `ReqRebirthGame`) reached **1685 and 2700 m**. Reviving that way sends the right server
  request but skips the popup's button, so «Испытание окончено» stays on screen over a run
  that has already resumed — destroy `UIWindowNames.UISurfingBattleFailure` after it (only
  that window; `logic:CloseWindows()` would take the run's HUD too). The offline replay clears 9 of
  the 10 dumped bands from every start lane; the one that fails needs a template the client
  had not loaded, so the planner treats it as un-hoppable and finds no route.
- After a headless run the client is left with an empty window stack (a black screen),
  because `GoBackToActivityPanel()` has nothing to go back to. The driver now returns it to
  the base with `SceneUtils.ChangeToCity()` + `OpenWindow(UIWindowNames.UIMain)`.

`tools/street_run_ai.py`: `install`, `status`, `bounds` (dump measured collider extents),
`on`/`off`, `run [reserve] [revives]`.
`tools/dev/`: `surfing_api_dump.py` (module/method/bytecode-string dumper),
`surfing_dump_config.py` (track config), `surfing_probe_run.py` (freeze a run and dump the
scene), `surfing_simulate.py` (offline band replay).
`tools/street_run_bot.py` keeps the legacy vision loop and the meta commands (`probe`,
`shot`, `watch`).

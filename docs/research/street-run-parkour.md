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
| `O_env_ditiepaoku_chexiangxiepo_N` (ramp carriage) | same rule | carries a ramp — drive up and run the roof |
| `O_env_ditiepaoku_qiaodong` (bridge gate) | ~34 behind z, **20–64 wide** | spans every lane |
| `O_Object_high_truck_gold_move_N` | driving, `move_speed` 20 or 40 | closes/opens at 10 or −10 u/s |

Modelling a carriage as "half a length around z" is wrong in both directions at once — it
blocks free track ahead of the anchor and misses the 40 units of body that actually kill.
That single fix is worth more than any amount of policy tuning.

**Carriages are ridden, not dodged** (watched by the player, 2026-07-30). The bands put a
carriage body in all three lanes at the same metre — 741 / 742 / 745 in one run, which no
lane change can answer. The `xiepo` pieces carry a **ramp**: the runner drives up it and
then runs along the roof, and the roof carries on over the plain carriages that follow in
the same lane. A carriage is therefore a wall only when nothing leads up onto it, and what
kills is swerving into one from the side — which is exactly how a run ended, changing lane
off the middle ramp into the rampless carriage beside it. **The roof is not continuous**:
between two carriages there is a hole down to the road, and it has to be hopped — a run
rode a truck and fell off its far end. The planner marks those holes solid-but-jumpable so
the route schedules the hop.

**`dataZ` is a spawn point, not a position.** For the driving trucks it never moves, so a
planner that reads it aims at a ghost: a run swerved into a moving truck that, by `dataZ`,
was nowhere near. Movers have to be read at their live transform; the parked pieces keep
`dataZ`, which is exact for them.

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

**Safety is absolute; greed decides the rest.** Nothing unsafe is ever weighed against
anything — the search only expands collision-free states, so an unsafe route cannot be
chosen at any price. Among the routes that survive, the cost ordering is, against a lane
change at 1.0:

| | value | effect |
|---|---|---|
| shield / jetpack / morph / ally | **1.4** | worth fetching one lane away; two lanes costs two changes and stays out of reach |
| magnet / double / box | 0.25 | tie-break only |
| coins | 0.01 each | tie-break only — a lane lined for the whole 200-unit horizon is worth 0.50, so coins can tip a close call but never buy a swerve |
| being off the centre lane | 0.3 per horizon | mild preference for keeping both escapes open |

Two of those numbers were wrong until they were tested rather than asserted. Coins at 0.02
made a full trail worth exactly a lane change — greed ahead of safety, not behind it. And
the centre-lane preference was a fixed 0.006 per unit, which silently grew from a 0.72 nudge
at a 120-unit horizon into a 1.2 penalty at 200 — dearer than a lane change, drowning out
everything else, including the shield the route was supposed to fetch. Both are now
expressed relative to the lane change and checked with direct probes of `planRoute`:
centre blocked with coins on one side picks that side; a shield one step away is fetched; a
shield behind a carriage is not; coins alone never move it.

**On a jetpack** (`player:IsFlying()`) the runner is above the whole track: the planner
drops every ground obstacle from the field for as long as it lasts and routes purely by
pickups, instead of dodging things it cannot hit.

**Offline iteration.** `tools/dev/surfing_simulate.py` replays every dumped band through
the *same* `AI.planRoute` at 60 Hz against the measured collider sizes, from each starting
lane, without spending an attempt — so a policy change is checked against the real track
before it is flown. `surfing_simulate.py score` does the whole set in one round trip and
returns a single number (bands survived, distance covered). Keep it to **one start lane per
call**: replaying all thirty combinations inside one frame froze the client badly enough to
lose the process.

## Learning between attempts (#1121)

The day's ~30 attempts are the scarce resource, so each one has to leave something behind.
`tools/lib/surfing_stats.py` classifies every death from the obstacle field the autopilot
froze at that instant — `ramp_head_on`, `roof`, `side_entry`, `wall`, `fence`, `bridge`,
`unknown` — accumulates them in `results/street_run/deaths.json`, and derives bounded
tuning overrides that the driver pushes into the live autopilot.

**A suggestion is a hypothesis, not an improvement.** The obvious rule — "we keep clipping
things, so add margin" — makes the runner strictly *worse*: extra padding closes gaps that
are genuinely passable (`padExtra` 4.0 drops the offline replay from 9 bands to 8). Every
proposal is therefore scored against the real track before and after and kept only when it
is actually better; ties are rejected, so a working configuration is never traded for a
guess.

**What the record says so far** (23 attempts): the largest single cause is `unknown` — 11
deaths where nothing the model knows about was in the player's lane. Those are not tuned
against, deliberately; they are the signal that the model is blind somewhere.

Testing the two candidate explanations against the record:

* **Falling through a roof gap — ruled out.** None of the 11 sits in a hole between two
  roofed carriages, and none of them had a carriage in the player's lane at all.
* **The driving trucks — the standing suspect.** Six of the 11 had a mover in frame, and
  their length is the one number in the whole model that nothing confirms: it is read off
  the `_N` in the prefab name, never measured, because the measurement window filtered on
  `dataZ` — which for a mover is a spawn point behind the player. The last death fits it
  exactly: dead at 1220.1 m with a truck in the same lane at 1258.3, a gap of 38 units
  against the 24.7 the name implies. Until one is measured live, an unmeasured mover is
  assumed to be as long as the longest carriage in the game.

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

## Learning from expert human play (#1156)

`tools/dev/record_human_loop.py` records a HUMAN-played run frame-by-frame (bot observes,
never drives; resilient to daemon hiccups on long runs), saving each to
`results/street_run/human/run_NNN.txt` in the same per-frame format the bot logs. Three expert
runs were captured (2828 / 8153 / **12759 m** — the last a new account record).
`tools/dev/surfing_route_html.py human` replays one as an animation; the frame carries the
player's height, so roof-riding is visible, and it also stores what the bot's model *would*
have decided (`planRoute` runs every frame even under manual play), so expert play and the
bot's model can be compared side by side.

**The decisive finding.** The planner was purely 2-D (lane × distance) and had no notion of
height. Measured against `run_002`: the runner spends **~57% on the ground, ~33% on carriage
roofs (height ≈ 3–5), ~10% on a jetpack (height ≈ 20)**. And in **42%** of the frames where the
human was on a roof, the bot's model rated that lane a dead-end (reach ≈ 0) — it read the
carriage the human was riding as a wall. Roofs are a third of expert play and the model was
blind to all of it.

**Carriage roofs are a hop-chain, not a floor.** On a carriage roof the human is **airborne
~60% of the time** — the roof is crossed by hopping carriage-to-carriage over the gaps between
them, not by running along a continuous surface. Mounts are frequent (~38 in `run_002`) and
descents are almost always straight down in the same lane (35 of 37). So the pattern is:
**climb on (ramp or a hop onto a carriage) → hop nearly every carriage seam → drop straight
back to the ground when the chain ends.**

**Speed accelerates.** Measured from the frame spacing, track speed climbs **30 → 40 → 60 u/s**
over a long run. A hop covers `jumpTime × speed`, so at 60 u/s a jump flies twice as far as at
30 — the player's note "jumps fly far at speed, brake with a slide so you don't overshoot".
The planner reads the live speed (`GetMoveSpeed`) so hop/lane lengths scale, but the
roof hop-chain timing has to hold at the high end too.

**Status of the model against this.** `surfing_ai.lua` now has a first height-aware pass
(`onRoof`, height > `cfg.roofY`): carriages become floor, ground obstacles under the roof are
dropped, seams are holes to hop. It lifted the bot's roof time 0 → ~17%, but it still treats a
roof as mostly-continuous and does not reliably hop every seam nor guarantee a safe descent, so
it sometimes runs off a roof end / into a seam and falls. Getting the hop-chain and the
descent right at the accelerating speed is the open work, and it needs the offline simulator
(`surfing_simulate.py`) extended to model height/roofs so the roof policy can be iterated
against the real bands **and the recorded human runs** without spending live attempts.

## The offline replay and the live game disagree (#1160)

Two things came out of #1160. One is a tool that works. The other is a warning about what the
tool's verdict is worth, and the second matters more than the first.

### The offline loop no longer needs the game

`tools/lib/surfing_sim.lua` is the judge, split out of `surfing_simulate.py` so it can run in
two hosts: the client's Lua VM as before, and a local Lua (`lupa`) via
`tools/dev/surfing_offline.py`, which loads the real `surfing_ai.lua` and needs no game at
all. The local host reproduced the in-VM verdict rotation for rotation on the first try, and
runs a full chained scan in ~1.5 min instead of ~11, without freezing the client. It also adds
what iterating actually needs: `trace` (the planner's own per-frame decisions on the way to a
death, plus its per-lane reach), `where` (what is really on that stretch of track), `cfg` to
price a proposed tuning, and `SR_AI_LUA` to replay an older planner against the same track.
`street_run_ai.py` takes the same variable, so an old revision can be put in front of the live
game — which is how the A/B below was run.

### The track config was only a fifth of the track

`SurfingMonsterTemplateManager.monsterTemps` holds what the client has already parsed, so the
dump captured whatever a run happened to have loaded: **10 born-pattern bands out of 48**, and
three obstacle templates missing entirely. Two of those three mattered — a ramp carriage and a
pass-under bridge arch — and the fallback invented both as 24-unit walls, closing lanes that
are actually open. `GetTemplate(id)` loads any of them on demand, so `surfing_dump_config.py`
now fetches every id the born patterns place and the dump is complete by construction. Anyone
reading an old offline score should know it was scored against a fifth of the real track.

### Four planner changes that the replay loved and the game did not

Tracing the planner against the full track turned up four things that each look, and still
look, like straightforward bugs:

1. a lane change checked only the lane being **entered** for ramp/roof bodies, never the lane
   being **left**, so the route could schedule a swerve off a carriage it was riding;
2. a carriage that is part of a rideable roof was marked `noJump` like any unhoppable body, so
   a hop across a seam — which must land on the next roof — was never legal at all;
3. a seam was held to the same middle-of-the-arc rule as a solid, though a gap is cleared by
   being airborne rather than by arc height;
4. hops and ducks were priced by `earlyBias`, which charges for waiting and therefore always
   picked the earliest legal take-off — the least margin the model allows.

On the chained offline track (all 48 bands back to back at running speed, every band order)
this was a large gain: median 866 -> 2194 m, mean 1204 -> 2751, best 4606 -> 8465, rotations
reaching 3000 m 4 -> 18. The pre-fix median (866) matches what the bot really did live at the
time (~900), which looked like good reason to trust the rest.

**It did not survive contact.** A/B on one account (Casper), one session, three silent
attempts per arm:

| planner | attempts | median |
|---|---|---|
| v41 (before) | 1060, 854, 1060 | **1060 m** |
| v42 minus change 1 | 908, 927, 837 | 908 m |
| v42 (all four) | 722, 722, 910 | 722 m |

So the whole change set is a **live regression**, change 1 costs the most, and the roof
changes cost the rest. `surfing_ai.lua` is reverted to v41; the change is in history
(`5b86507`, reverted by `6294190`) and can be replayed with `SR_AI_LUA`.

**Why the replay was wrong is the open question, and the roof model is the suspect.** The
judge's rule that a ramp/roof body kills from the side was the *basis* for change 1 — so the
judge could only ever agree with it. Worse, the judge was made more permissive in the same
pass (a hop that leaves a roof now stays at roof height until it lands, which is what let seam
hops "work"), so both sides of the comparison moved together. None of that is measured against
the game; it is assumed. Before any further roof work, the roof rules need to be established
from the recorded human runs or from live observation — how far a roof chain really carries,
what really happens on a sideways exit, and what a seam hop really costs — rather than from
the model that is being tested.

### Two harness faults worth knowing about

**The supervisor's own polling was capping runs.** Every status read hijacks a thread inside
the game process, and the watch loop did it twice a second for the whole run. Same account,
same planner: polled attempts kept ending at ~317 m, the attempt whose supervisor had crashed
carried on to 558 m, and a deliberately silent one reached 722 m. The autopilot is in-VM and
needs nothing from the supervisor while it runs, so the interval is now 4 s — and any
measurement worth trusting should be taken with the loop quiet.

**The tuning gate reverted to a value it had just refused.** A rejected proposal was rolled
back to the *remembered* baseline, and that baseline was itself `padExtra: 4.0` — the very
value the replay rejects. Every live attempt for some time had been running on it, and it
nearly stops the bot moving (one move in 317 m). The gate now compares against the file
defaults and reverts to them.

### Correction: it was the template table, not the polling (#1160, second session)

The section above blames the supervisor's polling for attempts ending at ~317 m. **That is
wrong, and the correction matters more than the original claim.** Spending both accounts' full
allowance settled it:

- 29 attempts on the main account with the supervisor silent for the first 75 s — longer than
  a 317 m run lasts, so those runs were never polled at all — still produced 316/317 six times;
- two attempts on a freshly relaunched second client, driven with *literally zero* reads
  during the run, gave 317 and 76 m.

317 m is a real death, reachable under every polling regime. What actually separated the good
runs from the bad was **how much of the monster-template table the client had parsed**, and
that is measurable: a freshly launched client held **14** of the 36 template ids the born
patterns place, while one that had been running attempts for an hour held **35**. Every id
that is missing falls through `kindOf`'s unknown-template case — *solid, cannot be hopped,
cannot be ducked* — so on a sparse client the planner reads coins and buffs as walls, and
barrels and fences as things it can do nothing about. The runs that produced 317 and 530 were
early-in-session runs on sparse clients; the runs that produced 722–1060 came later, once more
of the table had loaded.

`kindOf` now calls `GetTemplate(id)` when the table lacks an id (`AI.version = 43`), which is
the same on-demand load that fixed the offline config dump. Verified on the sparse client:
before, most ids came back as plain walls; after, the coin and the shield are harmless, the
barrel hoppable, the fence duckable, the bridge arch pass-under, and the carriage its true
16.5 units. **It is not yet confirmed live** — both accounts were at zero attempts when the fix
landed. That confirmation is the first thing the next session should spend attempts on.

The grace period in the watch loop is kept: fewer hijacks in a live process is not a bad thing
on its own. But it is not the reason a run ends where it does, and nothing should be attributed
to it.

**The A/B above inherits a caveat.** Its three arms ran back to back in one session on one
client, so template coverage was drifting underneath them. The ordering it found (v41 best,
v42 worst, v42-minus-the-first-change in between) does not follow the order the arms were run
in, so drift alone does not explain it — but the margin is three attempts per arm against a
confound now known to be worth hundreds of metres. Treat "v42 is a live regression" as the
reason not to ship v42 unverified, not as a settled fact; re-run it on a client whose template
table is known to be complete.

### What a full allowance of attempts looks like

29 attempts, main account, v41, one session:

    316 316 317 317 317 317 462 462 463 486 486 486 487 487 558
    647 647 647 647 647 654 655 689 733 747 790 792 840 876

Median 558 m, mean 562, best 876. The striking part is not the numbers but their **shape**:
twenty-nine attempts landed on about eleven distinct distances, several of them five or six
times over. The bot is deterministic and the track is assembled from a pool of fixed band
patterns, so a run ends at the first band the planner cannot solve and the distance is just the
sum of the bands that came before it. The ceiling is therefore not variance to be ground down —
it is a specific, enumerable set of bands, which is exactly what the offline per-band score
lists (10 of 48 failing for v41). Deaths cluster the same way on the second account.

Note also that distances are **not comparable across sessions**: the event panel carries buff
slots («Разогревать»), which were filled earlier in the day and empty during this run, and the
historical 877–1242 m figures were recorded with them active.

### What the human recordings say about roofs (#1160, measured — no attempts spent)

The roof rules were the open question, and the three recorded human runs answer part of it
without costing an attempt. All of this is measured off `results/street_run/human/*.txt`,
whose frames carry the player's height and the perceived obstacle field.

**Riding happens at TWO heights, and the model knows one.** The height histogram over 1651
frames has flat plateaus, not a spread: y=0 (54.5%), **y≈4.0–4.5 (17.6%)**, **y≈7.0–7.5
(4.7%)**, y=20 (7.6%, the jetpack), with the rest passing through in between. The 4.3 plateau
is a carriage roof (their collider floor measures 3.53). The 7.2 plateau is a second tier the
model has no representation of at all — `cfg.roofY` is a single threshold at 2.0, so both
plateaus read as "on a roof" and are planned against the one set of carriage bodies.

**Lane changes on the roof are ordinary play, and the planner forbids them.** Of 297 lane
changes across the three runs:

| between | count |
|---|---|
| ground → ground | 186 |
| **roof → roof** | **101** |
| roof → ground | 7 |
| ground → roof | 3 |

A third of the human's lane changes happen at roof height, most at a steady y≈4.30 on both
sides. The planner cannot do any of them: `freeEnter` refuses to enter a lane whose bucket
carries a ramp/roof body, so every roof-to-roof change is illegal by construction. This is in
**v41 as well** — it is not something the reverted work introduced. It is also the assumption
the reverted change #1 doubled down on by refusing to *leave* such a lane too, which is
consistent with that change costing the most of the four in the live A/B.

The one live observation the rule was built on — a run that died swerving off a ramp into a
rampless carriage — is not contradicted by this. What it argues for is a **same-level** rule
rather than a prohibition: a sideways move at roof height is safe when the target lane is roof
*at that z*, and fatal when it is a carriage's end face or open air. "Never" is the wrong
shape.

**Movers look rideable too.** Where the model has nothing under the human at the moment of a
roof-to-roof change, the objects actually beside them are led by the parked carriages, but
`O_Object_high_truck_gold_move_2/_3` appear 37 times. A driving truck is classified
`carriage=false` purely because `move_speed > 0`, so it is only ever a wall — yet the human
appears to be up on one. `O_Object_high_zhalan2` also shows up 20 times, and its collider
floor measures y0=4.07, i.e. it sits *at* the low ride height: it is plausibly a rail met while
riding rather than a fence met on the ground.

**Confidence.** The lane-change counts are solid — they use only the player's own lane and
height. The "what was under them" attribution is weaker: the frame's obstacle list is sampled
every 15 frames and filtered to the look-ahead window, so absence there is not proof of
absence. Treat the two-tier finding and the roof lane-change finding as established, and the
mover-riding as a lead to confirm live.

**What this means for the next batch of attempts.** Do not spend them re-testing the reverted
planner. Spend them on, in order: (1) confirming the on-demand template fix (`AI.version = 43`)
on a client whose table is known sparse, since that is a measured defect with an unverified
fix; (2) allowing roof-to-roof lane changes under a same-level rule and A/Bing that against
v41. Both are grounded in measurement rather than in the replay's own assumptions, which is
what the previous round got wrong.

## Audit of the whole effort (#1162) — what was measured, and what was only believed

This section is an outside review of everything above. It spends no attempts; every claim in
it comes from the config already dumped to `results/street_run/config/`, the 93 death records
in `results/street_run/ai_moves.log`, the three human recordings, and offline replays of the
**committed** planner and judge. Where it contradicts a section above, this one carries the
measurement.

### The offline judge is wrong about the only stretch of track that decides a run

`surfing_offline.py score` reports 38 of 48 bands cleared. Replay instead the sixteen tracks
the game can actually lay down for the first two bands — every `start_scene` × every band-1
pool entry, chained, from the centre lane, at 30 u/s, with the committed planner and the
committed judge — and **all sixteen survive the full 660 m**. Live, on the same planner,
twenty-three of twenty-nine attempts died inside that same 660 m, ten of them at 316–317 m.

So the instrument that gates every tuning decision is not merely noisy on the live regime; it
is silent there. Everything scored on it — the 866 → 2194 m "large gain" of #1160, the
`padExtra` gate, the per-band pass count — was measured on track the bot has never reached.
The #1160 conclusion "the offline replay and the live game disagree" was read as a puzzle
about the roof model. It is broader than that: the replay and the game disagree at 300 m.

### The track has a generator, and it is in the config

`stage.json:50000` describes exactly how a run is assembled, and nothing in the toolchain uses
it. `pre_scene` is 66 m of empty road; `start_scene` is one of four bands; `surfing_scene`
reads `"N;pool"` — play N bands from that pool — and `infinite_scene` is what runs after them.
That gives:

| band index | drawn from | speed |
|---|---|---|
| 0 | `start_scene` — 201 202 203 204 | 30 |
| 1 | 2001 3000 310 311 | 30 |
| 2–4 | the 24-band pool | 30 |
| 5–11 | the same 24 bands | 40 |
| 12–20 | a 15-band pool (+ 518) | 50 |
| 21+ | `infinite_scene`, 23 bands | 60 |

Two independent measurements confirm it. The frame spacing in the human recordings gives a
**step** speed profile — 30, then 40, then 50 from z ≈ 3960, then 60 from z ≈ 6930 — and
3960 = 12 × 330 and 6930 = 21 × 330 exactly. And recovering each run's band ids from the
obstacles it saw puts only 6xx bands after 6930, and 518 — which exists at no other speed — at
band 14.

Three consequences. Speed is a property of the **band**, not a ramp fitted from a run, so the
judge's `speed0 + accel·z` is the wrong shape and the per-band `score` at a flat 30 u/s prices
`623` or `642` — bands that only ever appear at 60 — at a speed they never run at. The bot's
entire live distribution lives in bands 0–2 at 30 u/s, which is **eight band layouts**, six of
them distinct (203 ≡ 310 and 204 ≡ 311 are the same born pattern). And a run reaching 1000 m
is a run that has solved a fully enumerable list, not a lucky one.

### Three-quarters of the deaths are not planning failures at all

Of the 93 live deaths the autopilot froze a field for, **71 (76 %) have nothing solid in the
lane the runner died in**, by the model's own record. The bot is not being out-planned; it is
being hit by things it does not represent. `surfing_stats` already names this `unknown` and
refuses to tune on it — correctly — but the project then went on to spend its effort on the
DP's cost table, the roof rules and the A/B, none of which can touch a blind spot.

The largest single blind spot is identified. Nineteen of the 93 deaths have a saw within 8
units, and the two biggest clusters in the whole record — z ≈ 317 (×11) and z ≈ 655 (×4),
together 16 % of all deaths — are the same signature: `A_Monster_surfing_dianju01` anchored at
x = 36, the runner dead on the ground in lane 2. The human recordings say why: a single saw at
z = 318 is observed at x = 33, 34, 35, 36, 37, 38, 39 over successive frames. **It sweeps the
full width of the track.** The human crosses it on the ground, in whichever lane it has just
vacated — 0 % airborne over the seven crossings in `run_001`.

The model gets this wrong three times over, in three separate places, and none of them can
catch the other two:

* the planner blocks one lane — the saw's *projected* position — from a lateral velocity it
  estimates itself, bouncing off x = 32/40 while the real sweep turns at 33/39;
* `surfing_stats.classify` matches on the saw's **anchor** x, so a sweep death is filed
  `unknown` and the record never names its own biggest killer;
* `SIM.once` gives obstacles no lateral motion at all, so no offline replay can ever produce
  this death.

The trace of one of those runs shows the shape of it: for the entire 3 s before impact the
planner reported a first action of "move left" — toward the saw's anchor — was not busy, and
the lane never changed. Across all 93 traces, 54 % of samples want a move while free to move,
and a lane change is observed once per thirty such samples. `act` is only issued when the
route says "start now" (`az == 0`), and the trace does not log `az`, so a correctly deferred
plan and a starved one are indistinguishable in the record. That is a gap in the telemetry,
not proof of a bug — but it is the first thing to close, because the same trace is the only
evidence any future change will be judged on.

### The judge does not test the planner that flies

`SIM.once` hands `planRoute` the kind table through `AI.kindOverride`, and that table is built
by `surfing_simulate.classify` — a **second, independent** implementation of the same truth,
which prices rewards differently from the live `kindOf`: coins 0.02 against 0.01, a jetpack
0.9 against 3.0, a buff 0.9 against 1.8. Offline the planner will not fetch a jetpack (0.9 is
cheaper than the 1.0 lane change); live it detours hard for one. And `SIM.once` passes
`flying = false` unconditionally, so the planner's flight branch — which the recordings say
covers ~10 % of expert play — is exercised by no instrument at all. The judge therefore scores
a *different policy* than the one installed, and systematically penalises the behaviour that
carries a human run.

`surfing_stats.body_of` is a **third** implementation of obstacle geometry. Three copies of
one truth is how a fix that only helps because two of them disagree gets shipped.

### The learner can only ratchet

`derive_cfg` is monotone in an undecaying count: `padExtra = 1.5 + 0.25 × (tight − 1)` over
every death ever recorded, so past about eleven deaths it is pinned at its ceiling of 4.0
forever, and `roofGap = 16 − 4 × roof` reaches 0 after four roof deaths and stays there. The
`padExtra: 4.0` incident of #1160 was not an accident of a remembered baseline; it is what this
function does by construction. It is still what it does — the current record proposes 4.0 on
every attempt, and only the (broken) offline gate is stopping it.

The record it learns from is also unusable for the comparison it exists to support:
`street_run_ai.py` writes `version="v16"` into every death, hard-coded, so the 65 live deaths
cannot be sliced by planner revision. And the comment at the watch loop still asserts the
polling claim that the section above formally retracts.

### Why the A/Bs could not have settled anything

Three attempts per arm, one session, one client, against a between-arm confound (template
coverage) later measured at hundreds of metres — that is the #1160 A/B, and its own section
already says to treat the verdict as provisional. The deeper problem is that the metric was
wrong even without the confound. Distances are not comparable across sessions (event buffs),
the bot is deterministic, and the track is drawn from a small pool: an attempt's distance is
almost entirely determined by **which bands were drawn**, not by the planner. Comparing two
planners on three attempts each is comparing two dice rolls.

The fix is available and costs nothing: the band ids of a run are recoverable from the
obstacle field the autopilot already logs. Record them, and an attempt stops being one number
and becomes a per-band pass/fail — at which point two planners can be compared on the bands
they both met, and a single attempt is worth as much as the old ten.

### What was right

Worth keeping explicitly, because the list of errors above is long. Reading the obstacle field
from Lua instead of pixels was correct and is the foundation of everything. Moving the dodge
into the VM removed the round trip and gave a 60 Hz decision rate. Measuring collider extents
live instead of guessing them fixed the single largest geometry error. Recording human play
and comparing it frame by frame against what the model would have decided is the best
instrument the project has, and it is the only one that has produced a finding that survived —
the roof plateaus, the roof-to-roof lane changes, and now the saw sweep all come from it. The
in-flight work on the oncoming movers is the same method and looks right for the same reason.

### The plan, in order

Each step is verifiable without spending an attempt, except where it says otherwise.

1. **Make an attempt legible.** Log the band ids and per-band survival for every run (they are
   recoverable from the field already logged), log `az` alongside `act` in the trace, and stamp
   the real `AI.version` on every death record instead of `v16`. Verify: replay an existing
   recording and recover its band chain; check a death record names the version installed.
2. **Fix the saw.** Measure its real swept width live (the collider is already read every 20
   frames — record min/max x per prefab across a run), then represent it by what it sweeps
   rather than by where it is: until the sweep is known, treat `dianju` as spanning the lanes
   it has been seen to reach. Teach `surfing_stats.classify` to match a saw on its collider,
   not its anchor, and give `SIM.once` lateral motion so the death is reproducible offline.
   Verify: the 317 m and 655 m deaths reproduce in the replay *before* the fix and stop after.
   This alone addresses 16 % of deaths and the two most common distances.
3. **Rebuild the offline objective around the real track.** Replace "48 bands in id order at a
   fitted accel" with the generator above: draw band 0 from `start_scene`, band 1 from its
   pool, and so on, at each band's own `speedZ`. Score the enumerable early set exhaustively
   (4 × 4 × 24 = 384 tracks for the first three bands) rather than sampling rotations.
   Verify: the replay must now fail somewhere in those first 660 m at roughly the live rate.
   Until it does, the judge is not calibrated and no tuning should be gated on it.
4. **Collapse the three geometry implementations into one.** `kindOf` is the live truth; the
   judge and the death classifier should consume it, not re-derive it. Verify: delete
   `classify`'s reward numbers and confirm the offline score changes — if it does, the judge
   was testing a different policy, which is the claim.
5. **Model flight.** Give `SIM.once` the pickup that grants it and the `flying` state, so the
   branch that covers a tenth of expert play is testable at all.
6. **Replace the ratchet.** A tuning knob should be proposed from a *window* of recent deaths
   and re-derived from scratch, not accumulated; and it should be per-cause and bounded by the
   count of deaths that cause still produces. Verify: feed the existing record and confirm the
   proposal is no longer `padExtra: 4.0`.
7. **Only then spend attempts**, and spend them on the two things #1160 already identified —
   the on-demand template fix on a known-sparse client, and roof-to-roof lane changes under a
   same-level rule — measured per band, not per run.

The order matters. Steps 1–3 cost no attempts and turn a run from one number into evidence;
without them, every further attempt is spent the way the previous 90 were.

## Replaying a real route, and what it showed about the model (#1161)

#1162's plan asked for two things that cost no attempts: make a run legible by recovering its
band ids, and rebuild the offline objective around a track the game actually lays down. Both
are done, and doing them turned up three model errors — each measured against a human
recording rather than argued from the code.

### A recording names its own bands

A recording carries no band id, only the obstacles the runner had in view. But every band is a
fixed template list, so each 330-metre slot can be named by asking which band, shifted to that
slot, explains what was seen there. `surfing_simulate.band_order_from_run` does that, and on
`run_002` (12 759 m) it names 36 consecutive slots, most with every single observed obstacle
accounted for and the runner-up scoring half as much. Of 645 static obstacles the run saw, 629
land exactly on the reconstructed chain; the 16 that do not are pickups and a saw, which are
placed at run time.

`surfing_offline.py route run_002` then replays that exact chain, at the speed ramp fitted
from the recording itself (`accel` 0.00366 against the 0.0027 the rotation scan assumed —
r.m.s. 2.8 u/s against 5.2). `route <recording> extend=N` carries it on with N more bands drawn
from the pool the recordings show, weighted by how often each turned up, seeded so an extended
route is reproducible.

**Caveat on the naming.** A slot is named by the band that best explains the *observed*
obstacles, and a run only ever sees about a quarter of a band's templates. Bands 2005/2006,
3001/635, 319/626 and 316/625 share enough content to score 2:1 rather than cleanly; the
winner is used. So the chain reproduces the field that was observed, which is what the replay
needs, but it is not proof that each slot's unobserved half is right.

### The bands butt up at 330, not 340

Every matched obstacle sits at a template shifted by an exact multiple of **330**. The chained
replay spaced them 340 apart, inserting a 10-unit strip of empty road at every seam — at
precisely the place the live roof-descent deaths happen. `BAND_PITCH` is now the measured 330.

### The driving trucks come at you, and they wait for you

Two measurements off the recordings, both unambiguous:

* **Direction.** 751 frame-to-frame samples of movers put every one of them at exactly *minus*
  its declared `move_speed` (681 at −20, 70 at −40). Not one sample has a mover travelling
  with the runner. Both the judge (`live.z = obs.z + speed*t`) and the planner
  (`drift = v/speed - 1`) had them driving away. Over a chained run of several kilometres that
  put trucks hundreds of metres from where they belong, standing as walls in track they never
  reach — and, worse, removed them from the track where they do.
* **They start late.** A mover more than ~120 units ahead is still on its spawn mark; the last
  frame one is seen parked is at a gap of 122, and below 120 they are essentially always
  moving. So the gap closes in two phases: at the runner's own speed while the truck waits,
  then at the sum of the two. `SIM.moverTrigger` / `cfg.moverTrigger` = 120.

Corrected, the isolated per-band score from centre goes 38/48 → 28/48 with the old planner:
the track got genuinely harder, because the trucks now arrive. The matching planner fix takes
it back to **37/48**, which is the honest measure of that fix — 28 → 37 on the same track.

### The runner flies, and sometimes that is the only way through

The two long stretches of `run_002` at y = 20 are not roof rides. Each begins the frame a
pickup is collected and lasts **exactly 11.0 s** (three flights across the three recordings,
all 11.0). `mon.json` names it: `buffType == 3` is the aeroplane, id 100004.

`SIM.once` passed `flying = false` unconditionally, so the branch that carries a tenth of
expert play was exercised by nothing. It now models the pickup, the 11 s, and the immunity to
everything on the ground.

### ~~run_002's route is not survivable on the ground — the human got lucky~~ (retracted)

> **Retracted the same day.** The section below is kept because its method is sound and its
> measurements hold, but its headline conclusion was wrong, and wrong in the way this document
> has been wrong before: a verdict that rests on an unmeasured constant, stated as if proven.
> The correction is the next section. Read them together.

`surfing_offline.py feasible` searches every jump, slide and lane change at every decision
point — an exhaustive answer to "is there any way through", which is what makes a planner's
distance mean anything. Any path it finds is handed to the real Lua judge to be confirmed, so
a slip in the search shows up as a rejected path rather than a false all-clear.

On `run_002` it gets **482 m of 11 880, from every start lane**. What stands there is three
oncoming trucks abreast — one per lane, spawning 16 and 20 units apart — and the recording
confirms it: at that exact distance the person is at y = 20 with `right@1796, centre@1820,
left@1850, centre@1874, right@1899` streaming underneath. They flew over it.

The flight came from the ally crate (100007), and the crate is a **gamble**: its `randomData`
rolls one of five buffs at 2000/10000 each, so the aeroplane is a 1-in-5. The recordings bear
the odds out exactly — **9 ally pickups, 2 flights**. There is no guaranteed aeroplane in the
400 m before the wall.

So the 12 759 m run cannot be reproduced by any planner. It required a 20 % roll at the right
moment. That is a fact about the game, and it retires a target: "clear the human's route" is
not a thing to tune towards. What replaces it is per-band pass/fail on ground-passable track,
with `feasible` marking off the stretches no policy can be blamed for.

### Commands

    python3 tools/dev/surfing_offline.py route run_002            # replay the real route
    python3 tools/dev/surfing_offline.py route run_002 1 extend=40  # carry it on
    python3 tools/dev/surfing_offline.py route run_002 1 trace    # decisions into the death
    python3 tools/dev/surfing_offline.py feasible run_002         # is there a way through?
    python3 tools/dev/surfing_offline.py human run_002            # model vs. the path a person walked

### The wall was one unmeasured number, and the planner was three real bugs (#1161)

The "impassable" verdict above was checked by trying to break it, which is what should have
happened before it was written down.

**The recordings contradict it directly.** Taking the movers' *live* positions straight out of
the frames — no track model in between — there is exactly one place in three recordings where
three lanes are crossed inside 45 m, at `run_002` z=8404, and the person went through it **on
the ground, y=0, with a single lane change**: they were in `right` as the centre truck crossed,
stepped to `centre`, and the left and right trucks crossed at 8419 and 8449 while they sat
there. A three-abreast convoy is not by itself a wall. At the model's own wall the crossings
are 20 m apart too, and the recording shows a clean line through them — stay left for the first
three, step out before the fourth.

**What actually walled it up was the truck's length.** `back` comes from the `_N` in the prefab
name. That is verified for the train carriages: `bounds.json` measured them at 8.22 / 16.44 /
24.86 / 32.98 / 41.10, exactly 8.24×N. It is *not* verified for `O_Object_high_truck_gold_move_N`
— a different asset family that nothing has ever measured, and in this same config `_N` is
elsewhere a variant index (`qiaodong_1/2/3`). Sensitivity, on the same route:

| modelled mover `back` | exhaustive search reaches |
|---|---|
| 24.7 (as modelled) | 482 m |
| 16.5 / 8.24 / 4.0 | **5469 m** |

Eleven times the distance, from one unmeasured constant. Laying the human's own path against
the recorded truck positions refutes 41.1 — it puts the person inside a truck they survived,
which is also what the player reported live about the old `cfg.moverBack` — but cannot separate
33 from 4, because nobody ever ran that close to one in its own lane.

**The bot's own death record supplies the other side of the bound**, and it needed no live run
at all. A death names its killer, and the dump beside it carries that truck's live position, so
a runner killed by a truck whose anchor was D ahead proves the body reaches at least D behind
the anchor:

| truck | measured lower bound | modelled (8.24×N) | from |
|---|---|---|---|
| `..._move_2` | **≥ 15.6** | 16.48 | a wall death at 900 m |
| `..._move_3` | ≥ 13.5 | 24.72 | a side-entry death at 877 m |

So **8.24 is refuted** — the short-truck reading that opened the route to 5469 m cannot produce
the kill at 900 m — and the `_N` rule holds snugly on the one truck that can be tested. The
default stands, better supported than when it was a guess.

What is still open is narrower and named: the whole 482-vs-5469 difference is `move_3` alone
(it is the truck at the wall), and the record bounds it only at ≥ 13.5. The `_N` rule earning
its keep on `move_2` is real support for 24.72, not proof. `SR_MOVER_BACK` re-runs any verdict
against a candidate; a `measure()` over a `move_3` in a live run closes it outright.

**Three planner bugs, priced separately.** All three were in the four-change bundle of #1160
that failed live and was reverted whole; with a per-band instrument on a corrected track they
can go back one at a time.

1. A lane change checked the lane being **left** against `solid` alone — but a ramp is
   `sideOnly`, which sets `side`, never `solid`. So the route could step off a ramp sideways,
   which the judge kills for. On band 2007 it committed to "left in 59" at z=125, climbed the
   ramp at 157, stepped off at 184. Dead at 185 from every start lane.
2. A **seam was timed like a wall**. `clears` models a hop as an arc with takeoff and landing
   still on the ground — right for a body, wrong for a hole, which kills only while the runner
   is not airborne. The arc rule left 15.6 of a hop's 21.6 units usable at 30 u/s; the gaps are
   19. The route rode the roof to the last bucket before the drop and stood there with no plan.
3. A `sideOnly` body was marked **unhoppable**, so a seam hop had nowhere legal to land — and a
   seam is by definition the gap *between* two roofs. The judge only registers a hit on a
   `sideOnly` body while a lane change is in flight, so a straight hop passes over it.

Measured from centre on the corrected track:

| | per-band | run_002's route |
|---|---|---|
| before | 37/48 | 185 m |
| after | **45/48** | **483 m** — the exhaustive ceiling |
| after, `SR_MOVER_BACK=8.24` | **47/48** | **4523 m** of a 5469 m ceiling |

At the modelled truck length the planner is now at the limit of what the ground allows, so
nothing further is to be gained there without settling the constant. Under the shorter body
there is still a real gap — 4523 against 5469 — and that is where the next planner work is.

**What this retracts.** "The human's 12 759 m cannot be reproduced by any planner" was not
established. What is established is narrower and more useful: the aeroplane is a 1-in-5 roll
from the ally crate (nine pickups, two flights), so a route that *needs* flight is not
reliably passable — but run_002's route has not been shown to need it.

#### The next lead: the DP's reachability oscillates frame to frame

Where the model still leaves room (`SR_MOVER_BACK=8.24`), the route now dies at 4523 m trapped
in the left lane: left is a plain carriage wall at 4523, and both other lanes carry a ramp
starting at 4503 that has to be mounted head-on, so the change had to happen before then. The
decision stream shows it was not a case of never seeing the way — it is that the DP's own
answer will not sit still:

    z=4300.1  act=left  reach=221  dp=221/141/21
    z=4301.6  act=left  reach=300  dp=220/300/263
    z=4303.2  act=left  reach=218  dp=218/138/18
    z=4304.7  act=left  reach=300  dp=216/300/260

One frame apart, the centre lane goes from reaching 141 to reaching the full 300 horizon and
back, twice. A route that is available on every other frame is a route the planner cannot
commit to. The likely cause is the mover projection quantising to whole buckets — a truck that
shifts by one bucket flips a `freeRun` and collapses a whole branch — but that is a guess and
should be measured, not assumed. It is the next thing to look at, and it wants doing **after**
the truck length is settled: at the modelled length the planner is already at the ceiling, so
there is no headroom in which to tell an improvement from a regression.

### There was no wall at 482 m — the judge was charging twice for a lane change

The player disputed the "impassable" verdict: the aeroplane is a random buff and may not turn
up, but the route is passable anyway, and the obstacles at that stretch had been read wrong.
Both are right, and the second is what produced the first.

**The trucks are a stream, not a rank.** In runner coordinates, the stretch reads:

| where a lane kills (m of runner travel) | |
|---|---|
| left | 482..497 · 591..606 |
| centre | 395..405 · 431..441 · 467..477 · 503..513 · 539..550 · 576..586 |
| right | 451..462 · 519..534 |

Points at which all three lanes are occupied: **zero**. The left lane carries one truck in the
whole 200 m. "Three abreast, one per lane" came from reading three *live positions at one
instant* — 449 right, 475 centre, 508 left — as a cross-section of the track, when they are 26
and 33 metres apart along it. That was a plain misreading, and everything built on it was wrong.

**What actually stalled the search** was `SIM.once` charging a lane change for *both* lanes
over its entire 0.16 s. That is not a geometry this game can have: the measured colliders are
3.48 wide against a lane pitch of 4, so there is an x between two of them that belongs to
neither, and the runner is handed over well before the manoeuvre ends. The rule made a 5.1 m
change need a 5.1 m hole in both lanes *simultaneously* — and the gaps in that stream are 5 and
6 m. It missed by centimetres, in a place where nothing was actually blocking.

The judge now hands over at the midpoint and the planner's DP checks each lane over the half of
the sweep it owns. **run_002's route: 483 m → 5458 m**, against a ceiling the exhaustive search
puts at 5469. Per-band from centre: 45/48 → **47/48**.

#### The instrument that hid it

`human` called `y >= 15` "riding a roof". But y≈20 is the **aeroplane**, and a carriage roof
sits at **y≈4** (bounds.json: body top 3.53 + 0.76). Conflating the two is why roof-riding
looked absent from expert play and flight looked mandatory — the 84 flight frames were counted
as roofs and the 160 actual roof frames were not counted at all. Corrected, the model's roof
reconstruction is mostly sound and measurably a little too strict: it denies a roof in **12 of
the 95 frames** where the person was demonstrably standing on a carriage body.

#### The next wall is a real one, and roofs are the way over it

At 5457..5462 there are five metres where all three lanes do carry a carriage body on the
ground — a genuine carriage group, and the intended path through one is over the top. The
model's roof there stops at 5434 because `roofGap` (16) will not chain across the 24 m to the
next carriage; at that distance the runner is at the 60 u/s cap, where a 0.72 s hop covers 43 m.
So the question is whether a roof chain should carry across a gap the runner can hop, and the
12-of-95 figure above says the chaining rule is too tight somewhere. That is the next thing to
settle, and the recordings can gate it.

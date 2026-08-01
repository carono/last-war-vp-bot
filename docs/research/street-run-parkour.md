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

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
~~The first band is identical every run — which is why an uncontrolled run always dies at the
same barrel at 88.75 m.~~ Only the order of bands varies.

> **Corrected (#1163).** The first band is *drawn*, from a pool of four. Three of the four put
> a barrel in the centre lane at 86–90 m, which is why an uncontrolled run so reliably dies
> there; the fourth does not. And `speedZ` is not "30 mostly, 40 in the hard ones" — it is a
> property of the *pool*, so the same layout runs at 30, 40, 50 and 60 in four different
> slots. See [The track's generator](#the-tracks-generator-and-what-the-recordings-say-about-the-draw-1163).

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

**~~The bot's own death record supplies the other side of the bound~~** — RETRACTED, see the
section "the truck length cannot be measured from what we have" below: the `killer` field is
derived from the very geometry under test, so what follows is circular, not a measurement.
It needed no live run
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

### The truck length cannot be measured from what we have — and no longer needs to be

Asked to settle `move_3` from the data already on disk, with no attempts left. The answer is
that it cannot be settled, that the earlier claim it *had* been was circular, and that after
the lane-change fix it stopped mattering. All three parts are worth recording.

**Nothing measured a gold truck.** `bounds.json` holds 24 prefabs measured off live objects.
Not one is `O_Object_high_truck_gold*`. The carriages, fences, saws, buffs and bridge arches
are all there; the driving trucks never came into `measure()`'s sample.

**The death-record "lower bound" was circular.** `surfing_stats.classify` names the killer by
asking which body contains the runner, and `body_of` sizes an unmeasured truck as
`8.24 × N` — the exact rule under test. So "a death by `move_2` at an offset of 15.6 proves
`back ≥ 15.6`" proves only that the classifier was told to think so. Retracted.

**Elimination does not close either.** Taking the death dumps and asking "if no *measured*
body in the runner's lane contains it, and one truck is nearby, that truck did it" yields
`move_1 ≥ 55` against a modelled 8.24 — absurd, and the tell is that most of those deaths are
the ones `classify` itself calls `unknown`. The candidate set is not closed: a runner can fall
off a roof, be hit by something outside the dump's `[pz-25, pz+130]` window, or be caught by a
saw that has patrolled out of its anchor lane. Attributing the residue to the nearest truck
manufactures a bound rather than measuring one.

**What the data does support**, model-free — the runner alive, on the ground, not mid-change,
sharing a lane with a truck at offset D, which means the body cannot reach D:

| | upper bound | modelled | verdict |
|---|---|---|---|
| `..._move_1` | back < 37.0 | 8.24 | consistent |
| `..._move_2` | back < 49.0 | 16.48 | consistent |
| `..._move_3` | back < 58.0 | 24.72 | consistent |

Loose, and loose for a structural reason: neither the person nor the bot ever runs close behind
an oncoming truck in its own lane — avoiding exactly that is the game. Ten, four and one
observation respectively.

**And `_N` does not generalise across families.** Within the measured set the carriages scale
perfectly — 8.22 / 16.44 / 24.86 / 32.98 / 41.10, exactly 8.24×N — while `qiaodong_1` and
`qiaodong_2` both measure **16.39**. So the suffix means segment-count for one family and
variant-index for another, and which one the gold trucks follow is not knowable from here.

**It no longer matters.** The whole 482-vs-5469 sensitivity belonged to the broken lane-change
rule, not to the truck. With the handover fixed, the route is flat across the entire plausible
range:

| `move_3` back | route reaches |
|---|---|
| 8.24 | 5458 m |
| 24.72 (modelled) | 5458 m |
| 41.10 (already refuted by the recordings) | 473 m |

Identical at both ends of the plausible range. The ceiling now rests on the static carriage
group at 5457..5462, whose bodies are all *measured*. So the outstanding measurement is no
longer on the critical path, and the next work is the roof-chaining rule — which the recordings
can gate, and which needs no attempts either.

### A roof carries as far as the runner can hop — and the route is passable end to end

`roofGap` was a flat 16: a roof chained to the next carriage only if the gap was under it.
That is the wrong shape of rule. A gap between two roofs is crossed by **hopping** it, so the
reach is the hop — `jumpTime × speed` — and at the 60 u/s cap that is 43 m, not 16.

**Measured on the recordings, not chosen.** A roof-to-roof crossing is visible directly: the
person over one carriage body at roof height (y≈4), airborne across the gap, then over the next
without ever touching the ground. There are 40 of them across the three runs.

| | |
|---|---|
| crossings satisfying `gap ≤ 0.72 × speed` | **40 of 40** |
| greediest crossing | 23.6 m at 48 u/s — 75 % of what was available |
| crossings the flat 16 denied outright | 3 — gaps of **19.0, 23.0 and 23.6 m** |

The jump model checks out on the same data: at ~60 u/s the longest sampled arc is 45 m against
the modelled 0.72 × 60 = 43.2. `cfg.roofGap` is kept as a floor so a slow chain never does worse
than before, and `surfing_stats.derive_cfg`'s lever on it is now inert by construction.

#### Two bugs the search's own verification caught

`feasible` hands every path it finds to the real Lua judge, and that guard earned its keep the
first time a path actually got through:

* **The judge disagreed with itself about which lane it was in.** `SIM.once` read "am I on a
  roof" from the lane held *before* a change and collided against the lane *after* it. So a
  change begun on the road onto a roofed lane sailed through that roof's obstacles, and one
  begun on a roof was collided as if on the road. Both halves now read the same held lane.
* **The replay keyed its schedule by call count**, assuming the judge's Nth call is its
  (2N-1)th frame. It is not — the judge skips the call entirely while a manoeuvre is in flight,
  so the schedule slid the moment the route made its first move, and the replay died metres in
  on a fence it had been told to duck 40 m earlier. Keyed by distance now; both sides step `pz`
  with the same recurrence from the same start, so the values match exactly.

#### Where it stands

| | |
|---|---|
| run_002's route, planner | 483 → 5458 → **7390 m** of 11880 |
| exhaustive ceiling | **11880 m — the whole route, confirmed by the judge** |
| per-band from centre | **47/48** |
| roof frames the model denies | 12 of 95 → **9 of 95** |

**run_002's route is passable end to end, on the ground, with no flight buff.** That closes
the question this task kept reopening, and it closes it the right way round: not by arguing the
stretch was passable, but by producing the moves and having the judge accept them. Everything
left between 7390 and 11880 is the planner's to close, and the ceiling is no longer in doubt.

### The ceiling was three centimetres wide, and the planner was already standing on it (#1161)

"Everything left between 7390 and 11880 is the planner's to close" — the line the section
above ends on — is wrong, and the way it is wrong is worth keeping.

**The instrument that settled it.** `route` names the obstacle that collected the body and
`feasible` says the route was passable; neither answers the question between them, which is
*at which frame did the planner's own line stop being winnable?* `blame` walks the line
forward and asks the exhaustive search that at every decision point. The first move after
which the answer turns from yes to no is the mistake, and it prints the moves that would have
kept the run alive beside it, with how far each of them gets.

On run_002 it lands 6 m before the death, not 100:

    LOST IT at z=7384.2 in lane right, 6 m before the body hit at 7390

So no trap was walked into. What is at 7384.2 is a hairline. `feasible pad=P` demands P metres
of clearance of every body, which is the only fair way to read a planner that keeps 1.5 m of
its own:

| clearance demanded | route reaches |
|---|---|
| 0 | 11 880 m |
| 0.03 m | 11 880 m |
| **0.05 m** | **7 388 m** |
| 0.5 / 1.0 / 1.5 m | 7 388 / 7 388 / 7 386 m |

The whole of run_002 past 7388 m hangs on one lane change with three to five centimetres of
margin — at 57 u/s that is a fiftieth of the metre bucket the planner reasons in, and thinner
than the safety pad that stands in for a truck length nobody has ever measured. `from=23`
shows the rest is not like that: bands 23-35, the 4290 m beyond the pinch, are passable with
1.5 m of clearance from end to end.

So the 11880 m ceiling is real and useless as a target. The honest reading is that run_002's
planner distance has been at its own ceiling all along.

#### Drawn routes, because three recordings are not a test set

`pool:N[:seed]` draws a route of N bands the way the game draws one. There are three
recordings, and the planner has been read against them long enough that a good score on them
says as much about the tuning as about the track. `surfing_battery.py` runs the lot — per-band
across three start lanes, run_002, five drawn routes, each printed beside its own ceiling.

That is where the planner's real faults were: on four of the five drawn routes the ceiling at
1.5 m of clearance is the whole 11880 m and the planner was reaching a third of it.

#### What was actually wrong

**A seam hop landed in the seam.** The DP measures a hop as `ceil(jumpTime × speed)` buckets
and asked whether the bucket it landed in was still a drop. `ceil` rounds the hop's reach up
by as much as a metre. Riding the centre roof at 30.6 u/s into a seam at 178..189.6, it hopped
at 166.7: the DP read 23 units of reach and a clear landing, the hop covers 22.05, and the
runner came down 0.9 m short of the far roof. Hopping two frames later clears it outright.

**The DP believed in gaps finer than its own bucket.** Bodies were rounded inward — `ceil` on
the near end, `floor` on the far one — shaving up to a metre off each end of everything on the
track. On a drawn route that turned a 0.3 m window between a carriage's far end and a fence
into a lane change it thought it could make; it stepped into that lane and was walled 90 m
later with no way back to the ramp group that was the only path through.

**The planner could not plan onto a roof, only along one.** It knew the road, and a roof it
was already standing on. So approaching a carriage group it read every ground obstacle beyond
the ramp as a wall, went looking for a way past on the tarmac, and found a hop — taking off 2
and 3 m before a ramp on two different routes, flying the whole 17 and 25 m roof at 36-38 m of
reach, and landing past the far end on walled ground. Running up the ramp clears both routes
outright. The level is a dimension of the route search now: onto a roof at the near end of a
ramp in the lane already held, off it where the roof runs out onto road that has to be clear,
and lane changes up there roof-to-roof over roof visible under every bucket of the crossing.

#### Three faults in the arbiter, found by making it disagree with itself

`feasible` hands every path it finds to the real judge. That guard is what caught these.

**A roof was read, not mounted.** "Am I on a roof" was a question about the current z: is
there a rideable span over this lane here. A ramp's span covers the ramp's own body, so
stepping sideways into a ramp lane half-way along it put the runner instantly on the roof and
skipped the whole ground collision block — `sideOnly` included, which left it unreachable for
every ramp in the game, the one obstacle class it exists for. The planner never used it; the
search did, calling routes passable on a move the game does not offer, and `blame` then charged
the planner with declining it.

The recordings settle it. Across 257 lane changes in run_002 and run_003 there is **not one**
from the road into a carriage body; all 16 that end inside one begin at y≈4.3, already up on
the roofs — a lane change along the roofs, which stays legal. The single change that starts
below roof height starts at y=1.9, mid-hop, and lands on a ramp at 4.3. The level is state
now: mounted head-on up a ramp, or landed on from a hop off another roof.

**A seam is the absence of roof, not an object.** It killed unconditionally, so a runner on
the road between two chained carriages died on open tarmac — track it cannot even see as
special, because the ramp that roofed the carriage behind it is out of its 50 m look-back. It
kills only a runner who was up on the roofs and has run out of them.

**The offline judge handed the planner a narrower window than the game does** — `pz - 10`
against the live `pz - 50`. An obstacle's anchor is its far end and a carriage hangs up to
41 m behind it, so the carriage under the runner's own feet fell out of view.

#### Where it stands

| | before | after |
|---|---|---|
| per-band, three start lanes | 141/144 | 141/144 |
| run_002 | 7390 | 7248 of a 7386 ceiling |
| drawn route, seed 1 | 190 | 3237 |
| drawn route, seed 2 | 4853 | 6822 |
| drawn route, seed 3 | 508 | 508 — at its own 507 ceiling |
| drawn route, seed 4 | 2552 | 7430 |
| drawn route, seed 5 | 632 | 5374 |
| share of the ceiling reached | 61 % | **65 %** |

run_002 gives up 142 m, and that is the change working: its ceiling at 1.5 m of clearance is
7386, so the old 7390 was the planner living inside its own safety pad.

None of this has been near a live run. The next thing that would settle anything is an A/B in
the game — the old planner and this one, alternating, with the supervisor quiet.

### Greed was setting the clock on the manoeuvres (#1161, same session)

The last 138 m of run_002's own ceiling came off one number. `earlyBias` prices a bucket of
delay before a move at 0.004; a single coin inside the sweep is worth 0.01. So the pickup
tie-break — the one thing declared unable to buy a swerve — was deciding *when* a lane change
happened, and when is safety.

At z=7238.5 a change to the right was legal and the route scheduled it "in 1" rather than now,
for the coins. 1.9 m later the window had shut: a barrel's padded rear had closed on the lane
behind and the fence ahead had not yet cleared. At 7244.1 only a hop was left and there was no
room to time one — the barrel sat in the takeoff stretch, not the middle of the arc — and the
run died at 7248. Priced above the coin, run_002 reaches 7390 m, which is its ceiling.

Three faults in the roof model went with it: running off the end of a roof was read as landing
on the road rather than falling into the gap (so the planner was told it was on the ground on
the very frame it needed to hop); mounting a ramp was offered as a choice, which let a route
plan a line straight through a ramp body; and a roof-to-roof change was checked from the bucket
ahead when the drop is charged against the entering lane from the first frame.

`blame` is judged against the distance anything can reach rather than the finish — most routes
wall up short of 11880 m, and on those "can I still reach the end" is False from the first
frame and blames nothing.

#### Thirteen drawn routes, session start against the end of it

| | run_002 | s1 | s2 | s3 | s4 | s5 | s6 | s7 | s8 | s9 | s10 | s11 | s12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| start | 7390 | 190 | 4853 | 508 | 2552 | 632 | 632 | 1752 | 1409 | 726 | 583 | 2186 | 5407 |
| end | 7390 | 3237 | 6822 | 508 | 3774 | 10141 | **11880** | 3439 | 8050 | 3568 | 4451 | 5149 | 2587 |
| ceiling at 1.5 m | 7386 | — | — | 507 | — | — | 11880 | 11017 | 8048 | — | — | 7716 | 5421 |

(a dash is the whole 11880 m.) **Share of the ceiling reached: 34% → 63%**, per-band holding
at 141/144. Twelve of the thirteen improved. Seed 12 is the one that did not — 5407 to 2587 —
and it is where the next session starts: it dies on a seam, in a lane whose roof chain begins
outside the planner's 50 m look-back, which is the one thing the planner is structurally
unable to see.

#### Commands

    python3 tools/dev/surfing_battery.py                     # every standing measurement, ~9 min
    python3 tools/dev/surfing_battery.py seeds=12            # ... over thirteen routes, ~20 min
    python3 tools/dev/surfing_offline.py blame run_002 1     # which decision lost the run
    python3 tools/dev/surfing_offline.py blame pool:36:4 1    # ... on a drawn route
    python3 tools/dev/surfing_offline.py feasible run_002 1 pad=1.5   # ceiling at real clearance
    python3 tools/dev/surfing_offline.py feasible run_002 1 from=23   # ... of the tail alone

## The track's generator, and what the recordings say about the draw (#1163)

The track is not laid down freely. `stage.json:50000` names a **pool per slot**, and every
recording obeys it exactly. What the recordings add is the part the config cannot state: how a
band is picked out of its pool, and whether one band tells you anything about the next.

### The schedule, and the recordings sitting inside it

`pre_scene` is 66 m of empty road with nothing on it. After that the run is bands of 330 m:

| band | drawn from | ids | dumped | speed |
|---|---|---|---|---|
| 0 | `start_scene` | 4 | 4 | 30 |
| 1 | first `surfing_scene` entry | 4 | 4 | 30 |
| 2–4 | second entry | 24 | 24 | 30 |
| 5–11 | third entry | 24 | 24 | 40 |
| 12–20 | fourth entry | 24 | 15 | 50 |
| 21+ | `infinite_scene` | 48 | 21 | 60 |

("dumped" is how much of the pool the config dump has templates for — the client parses a
scene the first time it needs it, so the pools a recording never reached are half empty. Every
command prints the shortfall rather than quietly covering less than it claims.)

Naming a recording's slots **inside the pool its index allows** — `surfing_tracks.py chains` —
gives 61 named slots across `run_001`, `run_002`, `run_003` and the autopilot's own frame
buffer. All 61 lie in the allowed pool, and on all 61 the pool-restricted winner is the same
band the unrestricted search over all 45 dumped layouts picks. If the naming were noise, the
chance of 61 slots all landing inside the pool their slot allows is about 10⁻²⁴. The generator
and the naming confirm each other; either one alone was an assumption.

A recording sees a **median 27 %** of a band's templates (the runner's view is ~300 m of one
band at a time and the frame buffer holds the last ~900 samples), so the naming is still a
best-explanation and not a proof of a slot's unobserved half. It is the field that was there
that gets reproduced, which is what a replay needs.

### A scene id is not a layout — the unit of coverage is (layout, speed)

`412`, `512` and `612` lay down the obstacles of born pattern `312`. What differs is the pool
they belong to, and therefore the speed. Of the 45 dumped layouts, **24 appear at more than one
speed**, giving **92 configurations** the game can actually put on the track.

This is why the standing per-band score was measuring the wrong thing. It replays each of the
48 dumped patterns once at a flat 30 u/s: `623` and `642` exist only at 60 and were priced at a
speed they never run at, while `312`, which the game runs at all four speeds, was checked at
one. Nine layouts are unique to a single pool — the four `start_scene` bands, the four of band
1 (`3000`, `2001`, `310`, `311`) and `518`, which exists at 50 and nowhere else.

Three of those 48 are not bands at all. Sorted by id, the first three are `108`, `109`, `110` —
the flight coin trails below, which hold nothing solid and so cannot be failed. The
per-band score has been counting three free passes per start lane: **141/144 is 141 of 135**
things that could have gone wrong.

### Speed is a step, not a ramp

Frame spacing in the recordings gives the speed at every sample. Grouped by band index it is
flat inside a band and changes on the boundary:

| bands | z | speed |
|---|---|---|
| 0–4 | 0–1650 | 30 |
| 5–11 | 1650–3960 | 40 |
| 12–20 | 3960–6930 | 50 |
| 21+ | 6930+ | 60 |

— the pools' own `speedZ`, to the metre. The transition is inside the first frames of the new
band, not spread over it.

The judge models speed as `speed0 + accel·z` and `route_accel` fits `accel` off the recording
(0.00366). That shape is wrong everywhere: at 1000 m it meets obstacles at 33.7 u/s where the
game runs 30, at 6000 m at 52 where the game runs 50, and it is furthest out precisely at the
speed changes. The fix is not a better `accel` — it is a speed keyed to the band index. Until
the judge can take one, a route crossing a speed change cannot be replayed at the right speed
in one piece; `surfing_tracks.py` splits every drawn route into its constant-speed stretches
so each can be replayed at its own.

### The draw is memoryless — there is no order to find

This is the negative result the task was after, and it is worth stating plainly: **there are no
groupings, no forced transitions, no ordering inside a pool.** Every check points the same way.

* **Repeats happen, including back to back.** `run_002` has `313` at bands 12 and 13, and
  `2006` at 15 and 16. A bag dealt without replacement, or a rule against repeating, produces
  neither.
* **The number of distinct bands drawn matches a uniform draw with replacement.** 18 draws out
  of the band-12 pool gave 12 distinct where uniform-over-24 predicts 12.8; 22 draws out of the
  48-band infinite pool gave 17 where it predicts 17.8; 14 out of the band-5 pool gave 13
  against 10.8.
* **A band does not depend on the one before it.** Over 49 consecutive pairs inside one pool,
  2 repeat where a memoryless draw predicts 1.6.

The bot's own deaths add 17 more draws at the low slots, where the long recordings have lost
their opening to the frame buffer: a death names its band outright when exactly one layout in
the slot's pool has that killer, in that lane, just ahead of where the runner stopped. They put
`310`, `2001` and `311` at band 1 — 12 draws over 3 of the 4 layouts, which is what a uniform
draw looks like.

So all the structure there is lives in the schedule: **what varies is which of N, and the N is
fixed per slot.** A run reaching 1000 m has solved bands 0, 1 and 2 — 4 × 4 × 24 = 384 tracks,
fully enumerable — and not been lucky.

### Two smaller things the config settles

**The first band is drawn, not fixed.** Three of the four `start_scene` layouts put a barrel in
the centre lane at 86–90 m (`201`, `203` at 90, `204` at 86); `202` does not, and puts a
carriage in the left lane at 102 instead. That is why an uncontrolled run "always" died at
88.75 m — it did so three times in four. Both recordings that still hold band 0 show `202`.

**The flight is an overlay, not a band.** `sky_score` names layouts `108`, `109`, `110`: 250
coins each, all at y = 20, spanning 1250 m, and no solid object anywhere in them. They have
`max_meters` 0 and never occupy a slot. That is the trail the runner flies along, and it is
longer than any flight (11 s at 60 u/s is 660 m).

### The synthetic route set

`surfing_tracks.py routes --write` builds 104 routes from the model above, into
`results/street_run/routes.json` (results/ is not in the repo — the routes are reproducible
from the seeds, which is why the generator is committed and the artefact is not):

| kind | routes | what it is for |
|---|---|---|
| `opening` | 16 | every band 0 × every band 1. The bot's whole live distribution. |
| `sweep` | 8 | one pool laid end to end at its own speed, forwards and backwards — every layout of the pool and 2N−2 of its seams, in two replays. |
| `game` | 8 | 40 bands drawn slot by slot the way the game draws, with the speed steps marked. |
| `seam` | 72 | a layout whose roof runs to the end of its band followed by one whose roof starts at the beginning of its own, at 30 and at 60. The seam is where the live roof deaths are, and it exists only between two bands. |

The `game` routes replace `pool:N:seed`, which drew from "the pool the recordings show,
weighted by how often each turned up" — a distribution with no slot structure, so it could put
an infinite-pool band at index 2 and run a 60-speed band at 30.

### Coverage of every configuration the game can lay down

`surfing_tracks.py cover` replays each of the 92 configurations once at the speed its pool
gives it, from all three start lanes — 276 replays, ~10 min, no game and no attempts spent.

Against the planner at `453b842` it passes **263 of 276**:

| speed | passed |
|---|---|
| 30 | 93 of 96 |
| 40 | 69 of 72 |
| 50 | 44 of 45 |
| 60 | 57 of 63 |

Five layouts account for all thirteen failures, and the shape of them is the point:

| layout | fails at | passes at | what kills it |
|---|---|---|---|
| `312` | 30, all three lanes | 40, 50 | a carriage at 194, centre |
| `319` | 40, all three lanes | 30, 50 | a carriage at 310, right |
| `2002` | 50, from the right only | 30, 40 | a carriage at 134, right |
| `2003` | 60, all three lanes | 30, 40 | a driving truck at 168, centre |
| `2004` | 60, all three lanes | 30, 40 | a driving truck at 154, right |

**A layout's verdict is not monotone in speed, and it is not even monotone the same way
twice.** `312` is passable at 40 and 50 and fails at 30 — a roof gap needs speed to hop; `2003`
and `2004` are passable at 30 and 40 and fail at 60 — a truck closes faster than the planner
commits. Four of these five pass at 30, which is the only speed the standing per-band score
ever ran them at: it reported them clear, and the game runs them at a speed where they are not.

That is thirteen named, reproducible failures on track the game draws from every run, with no
attempt spent, and each of them is one `surfing_offline.py blame <layout> <lane>` away from a
decision to look at. (`blame` runs a route at the fitted ramp, so it reproduces the failures at
30 as they stand; the ones at 40 and above need a speed it cannot yet be given.)

#### Nine of the thirteen are the model being wrong, not the planner

Cross the failing configurations against the recordings and three of the five layouts turn out
to be track a human has run **at that exact speed, on the roofs, without flying**:

| configuration | where a human ran it | height through it |
|---|---|---|
| `312` at 30 | `run_001` band 2 | y = 4.3 — up on the carriage roofs |
| `2003` at 60 | `run_002` band 37 | y ≈ 4.1 |
| `2004` at 60 | `run_002` band 26, `run_003` band 22 | y ≈ 4.1 |

None of them is a flight: a flight sits at y = 20, and the highest sample through any of the
three is 7.3, which is a hop. And `blame 312 1` does not report a planner mistake — it reports
`still winnable: nothing`, i.e. the exhaustive search agrees the band is impassable.

For `312` the place is exact. The model has a centre roof over 121–154 and reads the next
centre carriage, body 177.6–194, as a wall; `run_001` is at y = 4.3 in the centre lane at 181,
standing on top of that carriage. The runner rode a roof the model does not know is there.

So the battery is not only a list of things to plan better. Nine of its thirteen failures are a
falsification set for the **track model** — bands where the judge forbids what a recording
shows being done — and they are the first thing to spend effort on, because no amount of
planning gets through a wall the model invented.

### The catalogue is what the tools run now, not a JSON file beside them

A catalogue that has to be pasted into a command by hand is a document, not an instrument. So
the route argument every command already takes — `route`, `feasible`, `blame`, and the battery
through them — now understands it:

    route cat:game-3 1            # a catalogue route by name
    route cat:opening-202-310     # ... the sixteen openings, the sweeps, the seams
    route game:40:7 1             # 40 bands drawn slot by slot, seed 7
    route run_002 1 steps         # a recording at the band's own speed, not a fitted ramp
    feasible cat:sweep-60 1 pad=1.5
    blame game:40:7 1

**`pool:N[:seed]` now means the generator's draw.** It used to draw from one bag holding every
band seen in any recording, weighted by how often each turned up — a distribution with no slot
structure in it at all, so it would put an infinite-pool band into slot 2 and run a band that
only exists at 60 through track moving at 30. It draws slot by slot now. The battery's five
drawn routes therefore name different tracks than they did, and their numbers start again from
this commit; what they measure is a track the game can lay down, which the old ones were not.

**The judge takes a step profile.** `SIM.once` gained a `steps` argument — `{{z, speed}, …}`,
held flat until the next entry — and `Track`, `build_field` and `run_group` thread it through,
so the roof reach, the search's frame timeline and the Lua replay all step where the game
steps. Passing nothing keeps the old ramp, which is what a recording is still replayed at by
default: the recordings' published numbers were all measured on the fitted ramp and stay
reproducible. `steps` as a bare argument asks for the accurate profile instead — on `run_002`
the two agree to a metre (7390 against 7391), which is the fitted ramp's best case, since the
accel was fitted to that very run.

A recording also knows **which slot it starts at** now. `run_002` lost its first four bands to
the frame buffer, so its chain begins at band 4: one band at 30 and then the step to 40, rather
than the five bands at 30 a route replayed from slot 0 would get.

### Running the catalogue

`surfing_tracks.py catalogue` puts every route through the planner at its own speed steps —
a `game` route stepping where the slots step, and every other kind held at the one speed its
pool runs at (a 24-band sweep of the 40-pool would otherwise run its tail at 50 and 60, which
are speeds the game never gives those layouts).

**74 of 104** from the centre lane, against the planner at `fe2fa2e`:

| kind | passed | reading |
|---|---|---|
| `opening` | **16 of 16** | the stretch every attempt runs is clear offline, on every start × every band 1 |
| `seam` | 52 of 72 | every one of the 20 failures is a band that already fails alone |
| `sweep` | 3 of 8 | four of the five failures likewise |
| `game` | 3 of 8 | five drawn runs die between 1927 m and 7391 m |

**Thirty of the thirty-two failures are the five layouts `cover` already named** — `312` at 30,
`319` at 40, `2002` at 50, `2003` and `2004` at 60 — killing the route in the band they sit in,
at the same metre they kill it in isolation. The catalogue is not turning up new track the
planner cannot read; it is turning up the same five bands over and over, which is what a
memoryless draw out of a small pool does.

The `seam` result is the one worth reading carefully, because it is a negative and negatives
are what a probe set is for. The seams were built to catch a roof running off the end of one
band into the next — the shape the live roof-descent deaths have. **Not one of the 72 dies of
that.** No seam in the catalogue kills a pair whose two bands are individually survivable.
Either the model's seam handling is now right, or the seams that hurt live are ones this half
dumped pool cannot build.

Two failures out of thirty-two are not reducible to a single band, and they are the two worth
a session:

* `game-3` dies of a **roof seam at 6922 m**, in band 20 (`3008` at 50) — a drop between two
  carriages, on a layout that clears in isolation;
* `sweep-60-rev` dies on a **barrel at 5334 m**, in band 16 (`3003` at 60) — again a layout
  that passes alone, killed by the state it is entered in.

Both are the planner arriving in a band in a lane or at a height the isolated replay never puts
it in. That is the failure mode a per-band score is structurally blind to, and it is now two
named, reproducible cases rather than a suspicion.

## The two moves the planner would not make (#1164)

The session opened with an instruction to get a drawn route through its whole 11880 m, and the
first thing the battery said was that the instruction could not be followed on the routes it
was aimed at: `run_002` dies at 7390 and its ceiling at the planner's own 1.5 m of clearance is
7386, so it is already at the end of the road; the same is true of seeds 4 and 5, which run the
whole way. **A distance without its ceiling beside it cannot be read at all**, and read
properly the battery was not a list of six failures. It was one:

| route | planner | ceiling |
|---|---|---|
| `run_002` | 7390 | 7386 — at it |
| seed 1 | **4053** | **11880 — the whole route open ahead of it** |
| seed 2 | **1927** | **9039** |
| seed 3 | **6922** | **11019** |
| seed 4 | 11881 | 11880 — at it |
| seed 5 | 11881 | 11880 — at it |

Three routes short of their ceiling, and seed 1 short by 7.8 km. That is where the session went,
and what it found there was two moves the planner was refusing to make — both of them moves the
judge has always allowed, and one of them a move the recordings show a person making seven times.

### A roof is left sideways as well as forwards

Seed 1 dies at 4053 m, hit by the rear of a plain carriage in the right lane whose body runs
4052.9–4094.1. The 40 m before that read the same on every planning frame: **"change left, in
N buckets"**, with N counting down to the same absolute metre — 4014.3, the far end of the
right-hand roof — and the move never once issued. Then at 4015.7 the plan collapsed to
`dp=0/0/34`: no route in any lane, and it held its line into the wall with the centre lane
clear beside it the whole way.

The field there leaves exactly one way on:

* right lane — a ramp with a rideable roof over 3989.3–4014.0, then 38.9 m of open road, then
  the carriage that kills. The gap is wider than the 36 m a hop reaches at 50 u/s, so the two
  do not chain and the roof simply ends;
* centre lane — a ramp with a roof over 4025.0–4058.0, which is the way on. It is mounted
  head-on and its flank kills, so it has to be entered before 4023.5;
* so the runner has to come DOWN off the right roof and be in the centre lane inside the
  nine metres between them.

The planner could not do it. Up on a roof the only lane change it knew was roof to roof — the
lane being entered had to be roofed for the whole sweep — so the last metres of a roof were a
lane it could not leave. The move it needed is a ground change begun while standing on a
carriage, and it was not in the DP at all.

**The judge has always allowed it**, and not by accident: it reads the level off the lane the
runner still HOLDS, so a roof that runs out mid-change puts the runner on the tarmac of
whichever lane it is in by then. And the recordings have seven of them — three in `run_002`
(z = 3552, 4922, 10357) and four in `run_003` (4952, 5954, 6329, 6592) — every single one
starting from a y between 2.0 and 3.2, which is a runner already on its way down off the end
of a roof, not one stepping off the middle of a long one.

So the DP gained the same move, gated the same way: *if the roof under the runner is gone by
the handover, this is a ground change begun on a carriage.* The lane being left is judged at
the level the runner will actually be at there — a roofed bucket is ridden, a bare one is run
on the road and has to be clear of a body and of a ramp flank alike — the lane being entered
gets the ordinary ground test over the half of the sweep it owns, and the landing is at ground
level. A seam anywhere in the first half is still fatal; over a drop the runner is above the
gap, not past it.

On seed 1 the change now goes out at 4010.7, three and a bit metres before the roof it is
leaving runs out, and the runner is in the centre lane at 4019 and up the centre ramp at
4025.7. **4053 → 11881: the whole route, from all three start lanes.**

### A route that goes the distance is not surrendered to one that does not

Seed 2 died differently, and the trace of it is worth reading closely, because the mistake is
one the planner makes wherever a window is narrow:

    z= 1876.7 lane=centre act=JUMP  in= 10  reach=300  dp=300/300/300
    z= 1878.0 lane=centre act=JUMP  in=  9  reach=300  dp=300/300/300
    z= 1879.3 lane=centre act=right in=  0  reach= 45  dp=0/7/45      <-- issued
    z= 1886.0 lane=right  act=hold  in= -1  reach= 38  dp=0/0/38
    ... 40 m of holding ...
    z= 1927.0 dead

Two frames plan a hop — the seam hop off the end of the centre roof, which is the way on — and
the third, 1.3 m further on, plans a lane change to the RIGHT off a route that reaches 45
buckets of 300. Because that plan says "now", it is the one that gets executed, and it takes
the runner out of the lane the hop was in and into one that dead-ends 40 m later.

The third frame is not a change of mind. **The DP reasons in one-metre buckets laid out from
the runner's own z**, so the grid slides under the track by a fraction of a metre every frame,
and where a manoeuvre's window is narrower than a bucket that is enough to hide it. Here the
centre roof ends at 1888.0 over a seam of 27.3 m and the hop reaches 28.8, so the take-off may
be taken anywhere in **1.5 m** — and one planning frame in three offered no bucket inside it.
Every collapsed frame in that stretch has the same signature: `pz` with a fractional part of
.3, the same track, a different answer.

The fix is not to chase the aliasing — a bucket is the finest thing this DP can see, and that
is load-bearing elsewhere — it is to stop acting on it. While a plan that reached the whole
horizon is less than `cfg.holdSpan` = 4 m behind, a collapsed plan issues nothing and the
runner holds its line. Four metres is a couple of planning frames at the fastest the game runs,
which covers a grid flicker and nothing longer: a road that has really closed is still closed a
bucket later, the guard lapses, and the best-effort move is taken exactly as before.

Seed 2: **1927 → 9041, against a ceiling of 9039.**

### Where it stands

Every measurement in the battery, before the session and after it:

| route | before | after | ceiling |
|---|---|---|---|
| per-band, three lanes | 141/144 | 141/144 | — |
| `run_002` | 7390 | 7390 | 7386 |
| seed 1 | 4053 | **11881** | 11880 |
| seed 2 | 1927 | **9041** | 9039 |
| seed 3 | 6922 | **11021** | 11019 |
| seed 4 | 11881 | 11881 | 11880 |
| seed 5 | 11881 | 11881 | 11880 |
| **share of the ceiling reached** | **70%** | **100%** | |

Every route in the battery is now at the end of what anything can do on it at 1.5 m of
clearance, and the per-band score did not move, which is what says the two new moves did not
cost a class of obstacle somewhere else. Outside the battery, seed 6 goes 3247 → 11881, and
seeds 7 and 8 are unchanged at 7391 and 11881.

`cover` — every (layout, speed) the game can lay down, from all three lanes:

| speed | before | after |
|---|---|---|
| 30 | 93 of 96 | 93 of 96 |
| 40 | 69 of 72 | **72 of 72** |
| 50 | 44 of 45 | **45 of 45** |
| 60 | 57 of 63 | 57 of 63 |
| **total** | **263 of 276** | **267 of 276** |

Two of the five layouts that failed before this session are gone, one to each fix: `2002` at 50
(the seed 1 killer) to the step-down, `319` at 40 to the hold guard. `catalogue` moves with
them — 74 of 104 to **77 of 104**, `game` 3 of 8 to 5 of 8.

What is left is three layouts — `312` at 30, `2003` at 60, `2004` at 60 — and every catalogue
failure but one now reduces to a band that fails on its own. The exception is `sweep-60-rev`,
which dies at 5306 m on a fence in band 16 (`3003` at 60), a layout that clears in isolation:
the one case left of the planner arriving in a band in a state the isolated replay never puts
it in, where before this session there were two. **All three layouts are on the
falsification list already**: a human ran `312` at 30 in `run_001` band 2 at y = 4.3, `2003` at
60 in `run_002` band 37, `2004` at 60 in `run_002` band 26 and `run_003` band 22, every one of
them on the roofs and none of them a flight. So the next wall is not the planner declining a
manoeuvre — it is the model putting a wall where a recording shows a person running. That is
where the next session starts.

### The route set is a test now, not a command to run

Reading a drawn route had been a command someone had to remember to type. It is a test now:
`tests/test_street_run_routes.py` replays twelve drawn routes and `run_002` and holds each to a
floor — the searched ceiling where there is one, the measured distance where there is not. It
fails both ways: below a floor is a regression, above a pinned *ceiling* means the ceiling was
measured wrong or the judge has moved under it. ~7 minutes for the set; `SR_TEST_SEEDS=3` for a
quick pass. Seeds 9 to 12 are in it as well, measured here for the first time: 8710, 11880,
1168 and 1168, the last two dying in a `312` at 30.

The per-band score stays in `surfing_battery.py`, where it belongs — it is the class-wide guard
— and the new test is for the failure a per-band score cannot see.

### Commands

    python3 tools/dev/surfing_tracks.py model            # the schedule, and what is dumped
    python3 tools/dev/surfing_tracks.py chains           # every recording's band chain
    python3 tools/dev/surfing_tracks.py stats            # what the recordings say about the draw
    python3 tools/dev/surfing_tracks.py draw 40 7        # one route, drawn the way the game draws
    python3 tools/dev/surfing_tracks.py routes --write   # the synthetic set -> results/
    python3 tools/dev/surfing_tracks.py cover            # every (layout, speed), three lanes
    python3 tools/dev/surfing_tracks.py catalogue        # every catalogue route, centre lane
    python3 tools/dev/surfing_tracks.py catalogue kind=seam 0 1 2
    python3 tools/dev/surfing_offline.py route cat:game-3 1        # one of them by name
    python3 tests/test_street_run_routes.py              # the drawn routes, each against its floor
    SR_TEST_SEEDS=3 python3 tests/test_street_run_routes.py        # ... the first three only

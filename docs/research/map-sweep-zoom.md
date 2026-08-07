# How far the map camera may be pulled back before secret tasks stop arriving

> **The box sweep itself is gone (#1272).** «Автообъезд карты», its checkbox, its three
> settings and `panel/mapsweep.py` were removed once the whole-map lap below had been
> proven: a lap that covers the entire server in under three seconds leaves nothing for a
> pass-and-rest walk over a neighbourhood to be better at. Everything measured here still
> holds and is still what «Обойти карту» and the «Зум» control are built on — the numbers
> are the finding, the checkbox was only one of the things they were spent on. Where this
> note says «the sweep walks `panel/mapsweep.waypoints`», read it as a record of how the
> measurement was taken, not as a description of code that is still there.

The map sweep («Автообъезд карты») walked the camera over a box so the client asked the
server for map tiles. It walked it in **eight-tile steps**, which is a screenful every
four or five jumps — slow, and slow for no reason anybody had measured. Task #1265 asked
the obvious question: pull the camera back, cover more ground per jump, and find the
height at which the client stops asking for the tiles the sweep exists to find.

There is such a height, it is sharp, and it is **600**. There is a second one worth
having — **1199**, the last height at which the map arrives at all, which collects bases
and mines and no tasks. And the lap itself turned out not to be slow at all once it stops
being driven from outside the game: **the whole 1000 × 1000 server, in 2.6 seconds**
(§9).

## 1. What the zoom actually is

The world camera's height is `WorldScene.Zoom` — a float, clamped by the scene's own
`ZoomMin = 50` and `ZoomMax = 17500`. It is the **second argument** of the coordinate
jump every tool and the panel already use:

```lua
GoToUtil.GotoWorldPos(CS.UnityEngine.Vector3(x*2+1, 0, y*2+1), zoom, nil, nil, serverId)
```

and the 105 that argument has always carried is not a magic number either — it is the
scene's own `WorldScene.InitZoom`, the height the in-game magnifier jumps at.

**Tile loading is not gated on the zoom directly; it is gated on the LOD the zoom falls
into.** `WorldScene.GetLodLevel()` reports the current one and `GetLodDistanceByLod(n)`
prints the ladder, which is a flat table in the client:

| LOD | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| camera height ≤ | 150 | 250 | 400 | 600 | 1200 | 2200 | 5000 | 9000 |

So every height from 401 to 600 is the same LOD 4, and 601 is already LOD 5. That is why
the threshold below is a hard edge rather than a fade.

## 2. How it was measured — the client's own point manager, not a pcap

`WorldScene.PointManager` holds the tiles the client currently knows, keyed by point id,
and each entry says what it is:

```lua
local pid  = SceneUtils.TilePosToIndex(CS.UnityEngine.Vector2Int(x, y))
local has  = WS.PointManager:HasPointInfo(pid)
local info = WS.PointManager:GetPointInfo(pid)     -- info.PointType == 17 -> secret task
```

`PointType` is the same number as the wire's `f2` (6 base, 7 mine, 11 stronghold,
17 secret task, 25 alliance city, 29 ghost recon), so a rung of the ladder is one Lua
round trip instead of a sixty-second capture. Scanning a 301×301 box of point ids costs
about 0.2 s inside the VM.

Two properties make the measurement repeatable, and both were checked rather than
assumed:

* **The point manager only holds what is in view.** Jump away and every `HasPointInfo`
  in the old area goes back to false; jump back and the same 61 tiles return. So one
  spot can be measured at every height without reloading the scene.
* **`hasReceiveViewPointsReply`** says whether the server ever answered. It is the flag
  that tells a genuinely empty area from a client that has stopped being answered
  (§6, last bullet).

Harnesses used (git-ignored, `tools/scratch/`): `_zladder.py` (the ladder),
`_zextent.py` (per-direction reach), `_zab.py` (the A/B in §4).

## 3. The ladder — one jump to (700,600), the same spot at every height

`total` is every tile kind; `tasks` is `PointType 17` alone; `extent` is the largest
`|dx|` and `|dy|` at which any tile loaded.

| zoom | LOD | extent (tiles) | total tiles | **secret tasks** |
|---|---|---|---|---|
| 105 (the game's own) | 1 | 18 × 21 | 69 | **9** |
| 150 | 1 | 18 × 21 | 69 | **9** |
| 200 | 2 | 29 × 29 | 84 | **10** |
| 250 | 2 | 30 × 29 | 92 | **10** |
| 300 | 3 | 30 × 39 | 106 | **19** |
| 400 | 3 | 40 × 40 | 135 | **30** |
| 500 | 4 | 52 × 52 | 273 | **82** |
| **600** | **4** | **60 × 59** | **368** | **112** |
| 601 | 5 | 60 × 79 | 384 | **0** |
| 700 | 5 | 80 × 79 | 437 | **0** |
| 800 | 5 | 80 × 80 | 462 | **0** |
| 1200 | 6 | 149 × 142 | 1277 | **0** |
| 2000 | 6 | 149 × 142 | 1286 | **0** |

**The threshold is the LOD-4/LOD-5 boundary: 600 works, 601 does not.** It is not a
thinning — at 601 the count goes straight to zero while the view is *wider* and the other
kinds keep coming (strongholds double, mines grow from 109 to 139). Above LOD 5 player
bases reappear as the coarse big-map layer (864 of them at 1200), which is why a naive
"more tiles arrived, so it is working" reading is wrong: more tiles, none of them tasks.

**One jump at 600 is worth twelve at 105** — 112 tasks against 9, from the same
coordinate, in the same second.

### Per-direction reach, which is what a step has to trust

`max |dx|` is a corner reading. Measured separately (`_zextent.py`), a jump at 600 reaches
**L60 R59 D48 U60** in a dense area and **L60 R59 D50 U59** in the sparse one; the same
jump at 105 reaches **L20 R15 D20 U19**. So the honest half-width is **≈48 tiles at 600**
against **≈15 at 105**, and a step must be picked on the shortest direction, not the
longest.

## 4. Old against new, same box, live

Both passes walk `panel/mapsweep.waypoints` — the panel's own geometry — over the same
**241×241 box** centred on (700,600), from the same first waypoint, with the same
three-second dwell, and count **distinct secret-task tiles inside the box** (tiles loaded
outside it do not count, or the wide setting would be credited for ground the box never
asked about). Four minutes each.

| setting | waypoints a lap needs | jumps made | wall clock | secret tasks found |
|---|---|---|---|---|
| zoom 105, step 8 (the old default) | 961 | 50 | 244 s | **103** |
| **zoom 600, step 80 (the new default)** | **16** | **16** | **78 s** | **538** |

The new setting is not "faster at the same job" — it **finished**. It walked the whole box
in 78 s and stopped, having nothing left to visit; the old one spent four minutes to get
5% of a lap done, and would have needed something like **78 minutes** to finish the same
square. Over the ground it did cover it also found less per jump: 103 tasks in 50 jumps
against 538 in 16.

A smaller box tells the same story: over a 61×61 square the new setting takes 4 jumps and
19 s and finds 13 tasks, which is the whole box; the old one needs 81.

## 5. The same thing on the wire — because that is what the panel actually reads

The point manager is downstream of the map responses; the panel's own secret-task index
is downstream of a **pcap** of them (`tools/secret_task_capture.py`), and a finding that
only held inside the Lua VM would be no use to it. So both heights were swept again with
the capture running, over the same box:

| camera height | jumps | `world.get.block` requests | blocks asked per request | tiles delivered | `f2=17` tiles | tasks the capture indexed |
|---|---|---|---|---|---|---|
| 105 | 10 | 10 | 12–16 | 172 | 23 | **10** |
| **600** | 13 | 13 | **132** | 2326 | 283 | **167** |

The capture path agrees with the VM to the tile, and it is the panel's path — so «Автолут
★» gets the whole gain without a line changing in it.

**`viewLvl` and the height.** Across 105 and 600 every request carried `viewLvl = 0`;
what changed was the SIZE of the region asked for — the `index[]` of block ids goes from
12–16 entries to a flat 132, about nine times the ground per request. An earlier revision
of this section read that as "`viewLvl` is not the camera's height". **It was wrong**, and
sampling two heights that both sit inside band 0 is how: `viewLvl` is exactly the camera's
LOD band, which §8 measures across all three. `docs/research/protocol.md` §7 carries the
table.

## 6. What did NOT work, and what wasted the most time

* **Walking the ladder on the wire.** A capture is a minute per rung and needs the map
  moving throughout; thirteen rungs that way is most of an evening, and the answer is
  the same one the point manager gives in a single call. Use the pcap to CONFIRM the
  result (§5), not to find it.
* **Resetting the view with City → World between rungs.** It works twice and then poisons
  the client: the world comes up, `hasReceiveViewPointsReply` stays `false`, no view
  request is ever sent again, the camera drifts on its own, and every rung after that
  reads zero tiles at a coordinate that is full of them. Two ladders were thrown away to
  this before the pattern was seen. **Bounce off a far coordinate instead** — the point
  manager empties on its own when the view leaves.
* **Changing the zoom in the same jump that changes position.** `GotoWorldPos` tweens
  both together, so a jump entered from 105 spends its last frames over the target at a
  *lower* height and picks up tiles the height under test would never have asked for.
  Rung 601 read "112 tasks" that way — the same 112 the previous rung had left. Set the
  height while still far away, then jump at that height. (A sweep is unaffected: every
  waypoint uses the same number.)
* **`WorldScene:SendViewRequest()` / `UpdateViewRequest()` / `RefreshView()` as a way to
  force a fetch.** All four exist and all four return without error; none produced a
  single byte on the wire while the client was in the stranded state below. They are not
  a repair.
* **Sampling two heights and calling it a rule.** The claim that `viewLvl` is not the
  camera's height came from measuring 105 and 600 — both inside band 0. A third height
  would have shown it in one run. Corrected in §8 and in protocol.md; the mistake is
  worth keeping because it is the cheap kind: two points, a straight line, no third.
* **Reasoning about a step instead of measuring it.** The wide level's step was picked at
  150 from a half-width, and 100 turns out to find 316 more bases for 2.5 s more. The
  geometry says what CAN be covered; only a lap says what arrives.
* **Measuring above LOD 5 with the point manager.** One view up there covers the whole
  server, so "bounce away to unload" unloads nothing: rungs at 1200 and 2200 returned
  byte-identical counts, which reads as a stable measurement and is the previous rung
  twice. Above LOD 5, count what ARRIVES (the pcap), not what is resident.
* **Asking for exactly 1200.** The height is a float and comes back a hair larger
  (`1200.0001`) while the LOD ladder compares on `>=` — so the round number lands one LOD
  too high and fetches nothing at all. The same epsilon is why 600 is written as 600 and
  read back as `600.0`: that one was checked, repeatedly.
* **Believing #1053's «only a drag gesture produces map traffic».** It cost this task its
  first hour, planning how to imitate a swipe. It was true of the removed `GotoPos`
  crutch and false of `GotoWorldPos`: 121 scheduled jumps, 121 requests, no input at all
  (§9). A note about a call that no longer exists needs its subject named, or it outlives
  the thing it was about.
* **Trusting `game_link.probe()` alone.** It reported `online` throughout, because one
  socket was ESTABLISHED — while every game connection on port 10012 sat in `CLOSE_WAIT`
  and nothing had arrived for an hour. The world rendered, the camera moved, the Lua VM
  answered everything, and the map was empty. `hasReceiveViewPointsReply == false` right
  after entering the world is the honest tell; `restart_game` is the cure.

## 7. Ghost recon (`PointType 29`) — same gate, now measured

The first pass of this work could not answer it: no ghost tiles were in view. A whole-map
lap (§9) finds them in one go — **189 distinct `f2=29` tiles at height 600** — and the
same lap at 1199, the top of LOD 5, finds **none at all**, alongside none of the tasks.

So ghost recon rides exactly the same gate as the secret tasks: **both kinds arrive up to
LOD 4 and neither survives LOD 5.** The one height worth sweeping for either of them is
600.

## 8. Two heights, not one — the second is 1199

600 is the last height at which the interesting tiles arrive. It is NOT the last height at
which anything arrives, and the difference is worth a second setting: bases and mines keep
coming for another whole LOD, over four times the ground per jump. Measured on the wire,
a full-map lap at each:

Every lap below sets the height FIRST (the `WorldScene.Zoom` setter is instant) and then
sweeps at that same number, so no request goes out while the zoom is still climbing. That
matters: an uncorrected lap at 2200 came back with 819 tiles, all of them from its FIRST
request, which fired at `viewLvl 1` while the camera was still on its way up. The other
nine were `viewLvl 2` and empty. One tween, one whole wrong conclusion.

| height | LOD | `viewLvl` | requests a lap | tiles | tasks | ghost | **bases** | mines |
|---|---|---|---|---|---|---|---|---|
| 600 | 4 | 0 | 122 | 21 110 | **604** | **213** | 4 251 | 8 112 |
| **1199** | **5** | **1** | **50** | 26 799 | 0 | 0 | **4 502** | 8 405 |
| 1200 | 6 | 2 | 25 | **0** | 0 | 0 | **0** | 0 |
| 1500 | 6 | 2 | 26 | **0** | 0 | 0 | **0** | 0 |
| 2200 | 7 | 2 | 9 | **0** | 0 | 0 | **0** | 0 |

**So 1199 is the answer to "the last height at which player bases are still visible", and
there is nothing above it to reach for**: from 1200 up the client asks `viewLvl 2` — whole
server squares, one to four blocks a request — and gets back no points at all. The big map
is drawn from a different message (`GetViewLevelWorldInfoMessage`), which this work did not
decode. The camera itself clamps around **5000** in practice, whatever `ZoomMax = 17500`
says, so the band above is small anyway.

**1199 and not 1200, and that is not fussiness.** The client keeps the height as a float
and hands back a hair more than it was given — ask for 1200 and it reads back as
`1200.0001` — while the LOD ladder compares on `>=`. So exactly 1200 lands in LOD 6.

### The step that goes with 1199

At `tasks` a step of 90 is complete (§9). At `bases` the tiles are far denser and the
count keeps climbing, so the step was measured rather than reasoned:

| step at 1199 | waypoints | lap | **distinct bases** |
|---|---|---|---|
| 150 | 49 | 2.5 s | 4 502 |
| **100** | **101** | **5 s** | **4 818** |
| 70 | 196 | 13 s | 4 945 |

100 is where the curve flattens against the clock — 316 more bases for 2.5 s, against 127
more for another 8 — so that is what `ZOOM_LEVELS["bases"]` carries. For comparison the
narrow level's own lap finds 4 251 bases in 6 s, and a 4× denser narrow lap 4 536 in 27 s:
**the wide mode is both faster and more complete for a base census**, which is what having
it as a separate mode is for.

Measuring above LOD 5 also traps the point manager: one view covers the server, so "bounce
away to unload" unloads nothing and every rung reads the one before it. Two rungs at 1200
and 2200 returned byte-identical counts before that was noticed. **Above LOD 5, measure on
the wire.**

## 9. The fast swipe — the whole map in under three seconds

A lap driven from Python is a lap of round trips: ~150 ms each, so 121 waypoints is twenty
seconds of socket and almost no game. `lua_actions.fast_map_sweep` hands the whole
waypoint list to the game's own `TimerManager:DelayInvoke` in **one** call; the game walks
it, and because the client does not debounce map requests, a `world.get.block` goes out
for every waypoint.

| interval | schedule spans | **wire span** | requests | responses | tiles | tasks |
|---|---|---|---|---|---|---|
| 0.10 s | 9.9 s | 10.1 s | 100 | 100 | 17 561 | 540 |
| 0.05 s | 5.0 s | 5.1 s | 100 | 100 | 17 580 | 550 |
| **0.02 s** | **2.4 s** | **2.6 s** | **121** | **121** | **20 742** | **597** |
| 0.01 s | 1.2 s | 2.9 s | 121 | 121 | 20 743 | 598 |

Not one request was lost at any rate. Below ~0.02 s the schedule outruns the wire and
buys nothing — 0.01 s scheduled the lap in 1.2 s and the traffic still took 2.9 s to
drain, for one extra task. **The floor is the wire, not the camera.**

Density does not buy anything either, for the thing the lap is FOR. A whole-map lap at
step 45 — four times the waypoints, 27 s — found **603** secret tasks against step 90's
**604** (the difference is tiles expiring mid-run, not coverage). Bases and mines do rise
a few percent at the map's outer edge, which is what the wide mode in §8 is for.

Against what the panel did before, over the same ground:

| | ground covered | time | secret tasks |
|---|---|---|---|
| zoom 105, step 8 (the old sweep) | a 241 × 241 box, 5% of one lap | 244 s | 103 |
| zoom 600, step 80 (the #1265 sweep) | that box, one full lap | 78 s | 538 |
| **zoom 600, step 90, scheduled in-game** | **the WHOLE 1000 × 1000 server** | **2.6 s** | **597** |

### And the gesture was never needed — measured twice, two different ways

The note under #1053 said a scripted camera move emits no `world.get.block` and only an
interactive drag does, so a sweep had to be somebody's wrist. **That is not true of
`GotoWorldPos`** — it is true only of the removed `GotoPos` camera crutch that note was
written about. 121 scheduled jumps produced 121 requests and 121 responses with no
gesture, no input, no window focus and no pixels: the Windows session was disconnected
throughout (`mss` cannot even take a screenshot in that state).

That answers "does a scripted move fetch anything at all". The second question is the one
worth more: **a drag is CONTINUOUS, and a jump teleports — does the sliding view pick up
ground along the way that a teleport skips?** It does not, and this is the measurement:
the same 200 × 200 region, swept twice, counting only tiles that land INSIDE it.

| lap | step | waypoints | requests | in-box tiles | bases | mines | tasks |
|---|---|---|---|---|---|---|---|
| teleporting | 90 | 9 | 10 | **741** | 284 | 318 | 124 |
| sliding (≈ a drag) | 15 | 196 | 196 | **741** | 284 | 318 | 124 |

**Identical, tile for tile.** A step of 15 against a view that reaches ±48 is a view that
overlaps itself six times over — motion as continuous as a swipe, at 22× the sampling —
and it collects not one extra tile. The client fetches what its view rect covers when it
ARRIVES; nothing is gathered in transit. So there is nothing for a gesture to add, and no
reason to imitate one: not the drag, not the velocity, not the inertia.

The one thing that could not be tried here is a real mouse drag, because the Windows
session was disconnected the whole night and this game ignores synthetic input that is not
foreground ([[project_input_model]]). It does not change the answer: the extra thing a
mouse has over a scheduled jump is continuity, and continuity is what the table above
measures as worth nothing.

(The in-engine drag path was looked at too — `WorldScene.TouchInputController` is a
third-party asset, `BitBenderGames.TouchInputController`, and exposes nothing callable
through xLua beyond `enabled`. Not needed, given the above.)

## 10. Proven from the panel itself

Everything above was measured through harnesses. The controls were then pressed on the
LIVE panel, after it was restarted onto this code, with the ★ watcher on:

* **«Зум» cycles and says what it means** — three presses walked tile → secret tasks →
  bases → tile, each writing its own line: «высота камеры: секретки — 600, шаг 90 тайлов».
* **«Обойти карту» at «секретки»** — one press, one lap: the watcher's own counter went
  **122 map responses, 21 234 tiles, 598 tasks, 33 starred**, and the log printed the
  starred tiles one by one with their coordinates.
* **The same press at «только базы»** — `SWEEP_MAP -> zoom 1199` — took the run from
  21 234 tiles to **77 890** while the task count stayed at **598**: fifty-six thousand
  more tiles and not one further secret task. That is the level doing exactly what §8
  says it does, from the button.

**The ★ table staying empty is not a fault, and it took a minute to see why.** The list
holds tiles that are raidable now or finish within ten minutes (`PENDING_WINDOW_MS`); all
33 stars were further out than that, so an empty table over a lap that plainly worked is
the designed answer. A reading that looks like a failure is worth chasing to its rule
before it is called one.

## 11. What shipped

* `tools/lib/lua_actions.py` — `jump_to_coord(..., zoom=None)`, plus `JUMP_ZOOM = 105`
  (the game's own) and `SWEEP_ZOOM_MAX = 600` (the ceiling above). A jump about one tile
  is unchanged.
* `panel/mapsweep.py` — `DEFAULT_ZOOM = 600`, `MIN_ZOOM/MAX_ZOOM = 105/600`, and the step
  and radius that go with it: **step 80** (16 tiles of overlap on the shortest direction)
  and **radius 120**. A pass is 16 jumps over 241×241 tiles where it used to be 49 jumps
  over 49×49. (The box sweep is still there for a neighbourhood on a period; the whole-map
  lap below is the one to reach for.)
* `lua_actions.fast_map_sweep` / `fast_sweep_seconds` — the lap, scheduled in-game, and
  how long it takes; `BASE_ZOOM_MAX = 1199` and `ZOOM_LEVELS` (three heights named by what
  each is FOR, each with the step that belongs to it).
* `SWEEP_MAP [ZOOM h] [STEP n] [EVERY s]` in the DSL, and `actions/scan_map.md` — the
  ability, one file, which is what the panel plays.
* «Секретки» → the coordinate bar: **«Зум»** with the three levels and **«Обойти карту»**
  beside it. The height governs every jump the tab makes, so a coordinate clicked in the
  table and one typed into the boxes arrive the same way. Mirrored on the phone as a
  cycling button and a press.
* **One camera control, not two.** `sweep_zoom` and `sweep_step` are gone from Settings:
  the height and the step are one decision — a step measured at one height means nothing
  at another — and the box sweep now takes both from the level chosen on that bar. What
  Settings keeps is what is genuinely about the box (radius) and the pace (dwell, rest).
  A profile written before this still carries the two dead keys; they are named in
  `tests/test_panel_profile_compat.py` as retired so an old profile does not read as a
  setting the panel has lost.
* `panel/runtime/daemon.py`, `panel/tabs/secret_tasks/sweep.py` — the sweep passes the
  height; every other jump still does not.
* Settings → «Автообъезд карты» → «Высота камеры», bounded at 600 so the knob cannot be
  turned to a height that finds nothing.
* `JUMP x, y [, server] [ZOOM height]` in the DSL (`docs/dsl.md`).

# How far the map camera may be pulled back before secret tasks stop arriving

The map sweep («Автообъезд карты») walks the camera over a box so the client asks the
server for map tiles. It walked it in **eight-tile steps**, which is a screenful every
four or five jumps — slow, and slow for no reason anybody had measured. Task #1265 asked
the obvious question: pull the camera back, cover more ground per jump, and find the
height at which the client stops asking for the tiles the sweep exists to find.

There is such a height, it is sharp, and it is **600**.

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

**And a correction to `docs/research/protocol.md` §7 «Zoom».** That section reads the
camera's height off the request's `viewLvl` (0 zoomed in / 1 zoomed out / 2 whole world).
It is not that: across 105 and 600 — five LOD levels apart — **every** request carried
`viewLvl = 0` and `bigMap = 1`. What the height changes is the SIZE of the region asked
for: the `index[]` of block ids goes from 12–16 entries to a flat 132, about nine times
the ground per request. Whatever makes `viewLvl` 1 or 2, it is not the ordinary camera.

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
* **Trusting `game_link.probe()` alone.** It reported `online` throughout, because one
  socket was ESTABLISHED — while every game connection on port 10012 sat in `CLOSE_WAIT`
  and nothing had arrived for an hour. The world rendered, the camera moved, the Lua VM
  answered everything, and the map was empty. `hasReceiveViewPointsReply == false` right
  after entering the world is the honest tell; `restart_game` is the cure.

## 7. Ghost recon (`PointType 29`)

Not confirmed either way: no ghost-recon tiles existed on the map during this work, so
there was nothing to lose at LOD 5. The gate is a property of the tile kind in the
server's view reply, so the expectation is that 29 behaves like 17 — **but it is an
expectation, not a measurement.** Re-run `tools/scratch/_zladder.py` over a tile known to
carry a `29` during an open Ghost Operation day and record the answer here.

## 8. What shipped

* `tools/lib/lua_actions.py` — `jump_to_coord(..., zoom=None)`, plus `JUMP_ZOOM = 105`
  (the game's own) and `SWEEP_ZOOM_MAX = 600` (the ceiling above). A jump about one tile
  is unchanged.
* `panel/mapsweep.py` — `DEFAULT_ZOOM = 600`, `MIN_ZOOM/MAX_ZOOM = 105/600`, and the step
  and radius that go with it: **step 80** (16 tiles of overlap on the shortest direction)
  and **radius 120**. A pass is 16 jumps over 241×241 tiles where it used to be 49 jumps
  over 49×49.
* `panel/runtime/daemon.py`, `panel/tabs/secret_tasks/sweep.py` — the sweep passes the
  height; every other jump still does not.
* Settings → «Автообъезд карты» → «Высота камеры», bounded at 600 so the knob cannot be
  turned to a height that finds nothing.
* `JUMP x, y [, server] [ZOOM height]` in the DSL (`docs/dsl.md`).

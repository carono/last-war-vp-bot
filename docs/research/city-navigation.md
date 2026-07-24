# Base (City) navigation — decoding building coordinates and clicking them

Turn a building's `pId` (from the login snapshot, `docs/research/city-protocol.md`) into a
screen pixel you can click. Three parts: decode `pId` → grid, read the live camera, project
grid → world → screen → desktop-pixel. Validated against a screenshot; a reusable clicker is
`tools/city_click.py`.

## 1. `pId` → grid — base is a 100-wide grid, `TileSize == 2`

Each `building_new[i].pId` (see city-protocol.md) is a packed base-grid cell:

```
gx = pId % 100        # column
gy = pId // 100        # row
```

Evidence (205 buildings from the cold-load `init`, 185 placed — `pId != 0`): **only** the
`%100 / //100` packing keeps both axes off the modulus boundary (`gx∈[17,76]`, `gy∈[25,75]`)
instead of wrapping; every other base (64/80/128/1000, `>>8`) forces one axis to span its full
range. Rendered as ASCII the cells form a coherent base — a dense core with regular
`#.#.#.#` building rows and decorations/walls around the edge — not a scatter, confirming the
packing. The 4 cells with two buildings are a functional building + a `103xxxxx` decoration
sharing an anchor.

The base grid pitch is **`TileSize = 2`** world units per cell (Lua global `TileSize`).
`BuildingUtils.GetMainPos()` returns the HQ anchor grid **`(49, 49)`**.

## 2. The base camera (read live via Lua)

`SafeDoString` (docs/research/xlua-state.md §12) with `CS.*` bindings reads the live camera —
`tools/lua_eval.py` runs a chunk and reads back `Debug.LogError` markers from the Player.log:

```lua
local c = CS.UnityEngine.Camera.main
-- pos, orthographic/size/fov, pixelWidth/Height, transform.forward
```

City base camera (this session): 

| property | value |
|---|---|
| `transform.position` | `(266.71, 240.0, -72.71)` |
| `orthographic` | **false** (perspective), `fieldOfView` **10°** (near-orthographic look) |
| render size | `pixelWidth × pixelHeight = 1576 × 1032` |
| `transform.forward` | `(-0.5, -0.7071, 0.5)` — 45° down, 135° yaw (the isometric tilt) |

The camera's ground look-at (ray to `y=0`) is world **`(97, 0, 97)`**, and the game's own
`Camera.main:WorldToScreenPoint(97,0,97)` returns **`(788, 516)`** = dead centre of
`1576×1032`. So we do **not** rebuild a projection matrix — we call the live camera's
`WorldToScreenPoint`, which tracks any pan/zoom automatically. Sanity checks:
`WorldToScreenPoint(107,0,97) = (912.7, 427.8)` (world +X → screen right+up),
`(97,0,107) = (909.1, 601.6)` (world +Z → screen right+down) — a textbook isometric basis.

## 3. grid → world → screen → desktop pixel

```
world  = (2*gx, 0, 2*gy)                     # TileSize=2, base grid on the XZ plane, y=0
render = Camera.main:WorldToScreenPoint(world)   # (x,y) in 1576x1032, ORIGIN BOTTOM-LEFT; z=depth
```

Calibration check: grid `(49,49)` (HQ, from `GetMainPos`) → world `(98,98)` → render `(812.6,
516.0)`, i.e. essentially the screen centre — exactly where the camera frames the base. The
`-1`-ish offset between `2*49=98` and the look-at `97` is under one world unit and within the
HQ's multi-tile footprint, so **`world = (2*gx, 0, 2*gy)` is used as-is** (a target anywhere on
a building's footprint is clickable; sub-tile precision is unnecessary).

Render → desktop pixel uses the window's **client** rect (Unity's y is bottom-up):

```
cw, ch      = GetClientRect(hwnd)            # 1576 x 1032 (== render size here)
ox, oy      = ClientToScreen(hwnd, (0,0))    # client top-left in desktop coords, e.g. (172, 95)
desktop_x   = ox + render_x * cw/pixelWidth
desktop_y   = oy + (pixelHeight - render_y) * ch/pixelHeight   # flip y: bottom-up -> top-down
```

A target is **on-screen** iff `depth > 0` and `render` is inside `1576×1032`; otherwise the
base must be panned to it first (this pipeline does not scroll).

### Screenshot validation

Projected all 185 placed buildings via the live `WorldToScreenPoint`; 109 fell inside the
viewport. Drew each as a marker on a focused window grab
(`results/city_grid_overlay.png`): the markers land on the base's buildings, reproducing the
diamond lattice of the building rows, with the look-at crosshair at centre. This confirms the
axis mapping (`gx→+worldX`, `gy→+worldZ`, no mirror/rotation) and the whole pipeline.
(Note: the 3D base *did* composite into the mss grab here when the window was foregrounded —
unlike the black-3D caveat in `game-launch-and-scene-control.md §4`, which stands for the
World view / unfocused grabs.)

## Clicking — `tools/city_click.py`

Input the base needs **foreground `pydirectinput`** (PostMessage is ignored —
`[[project_input_model]]`), so the tool focuses the window (Alt-key trick) and clicks the
computed desktop pixel:

```bash
C:\Python312\python.exe tools\city_click.py --grid 49 49          # dry run: prints the pixel
C:\Python312\python.exe tools\city_click.py --pid 6531 --click    # move + click that building
```

It resolves the projection **live** each call, so it is robust to camera movement, and refuses
(exit 1) when the target is off-screen. A click was issued at the computed pixel for a
left-side building (`pId 4136`, grid `(36,41)` → desktop `(475,525)`); the client then closed
on the account **session kick** (single-session, logged in elsewhere — see
game-launch-and-scene-control.md §5), so the post-click panel was not captured. The pixel
accuracy is already established by `results/city_grid_overlay.png`; a clean click→panel capture
needs a stable (throwaway-account) session.

## Remaining gap

`bId → building name` and `pId → in-game map coordinate label` still need the game's config
table (encrypted, `[[project_heroid_icon_mapping]]`), but that is only for *labelling* — the
geometry above is sufficient to locate and click any building by `pId`.

## Tools & artifacts

- `tools/lua_eval.py` — run a Lua chunk via SafeDoString, read markers back from Player.log.
- `tools/city_click.py` — `pId`/grid → live projection → desktop pixel → optional click.
- `results/building_screen.json` — every building's `pId`, grid, render-screen coords, depth (git-ignored).
- `results/city_grid_overlay.png` — the validation screenshot (markers on buildings, git-ignored).

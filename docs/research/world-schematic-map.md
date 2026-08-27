# The schematic map, and what our model of the world is missing (#2018)

The panel now draws the world map itself — «Карта: схема», one canvas of everything it
believes is out there, so a person can hold it up beside the real client and see where
the two disagree. The person's ask, verbatim: «нужно в отдельной вкладке перерисовывать
состояние игры, тайлы, объекты, состояние читать из игры… достаточно схематично… вид
пока ридонли… пока просто нужно сравнить, что видим мы с реальностью».

This page is the other half of the answer. The picture shows where our model is WRONG;
the list at the bottom is where our model is EMPTY, which no picture can show and which
is the more useful finding of the two.

## How it is built

| piece | where |
|---|---|
| the scene, assembled out of what is on disk | `panel/runtime/worldscene.py` |
| the tab, its readings and its screen | `panel/tabs/worldview.py` |
| the canvas, PixiJS, loaded on demand | `panel/web/app/src/views/WorldMap.tsx` |
| the route the scene travels on | `panel/web/api.py` → `/api/screen/data` |
| the coverage grid the capture stopped throwing away | `tools/lib/world_index.py` |

Three rules shaped all of it:

* **Nothing is asked of the game.** Every source is a file or a table this profile
  already has: the map sweep's checkpoint (`world_map.json`), the `monsters` table, the
  ★ and ghost lists (`secret_tasks_state`, `ghost_map_state`), the treasure checkpoint.
  Opening the page starts no capture and plays no scenario — `CLAUDE.md`'s «Read once,
  then LISTEN» forbids exactly the timer a live-looking map would want.
* **The scene does not ride the screen's poll.** A tab's `web_view` is re-read every few
  seconds; a scene is tens of thousands of objects. So the tab answers for it through
  `PanelTab.web_data` on a route of its own, asked once when the map opens and again
  only when the person presses «перерисовать».
* **Read-only, and unable to be otherwise.** No press, no scenario, no Lua anywhere in
  the tab; the route is a GET; a tap reports and never acts.
  `tests/test_panel_worldscene.py` pins all three.

## The one gap that was closed: where we have LOOKED

Empty ground on our picture used to mean either «there is nothing there» or «we have
never looked there» — opposite answers to the question the page exists to ask.

The fix cost no new reading. Every `world.get.block` reply already says which RECTANGLE
it answered about (`lastwar_proto.block_areas`, #1484 — the same fact the ★ list uses to
decide a tile is gone), and the world listener was discarding it. It now folds those
rectangles into a coarse grid — 25 tiles a cell, the lowest view height each cell was
heard at kept beside the time — and the panel accumulates that grid into `panel.db`
(`world_coverage`) as the checkpoint is read. The canvas paints unswept ground dark,
swept ground tinted by age, and a tap on bare ground says when the camera was last over
it.

The view height is kept because the client asks for LESS the higher it is
(`map-sweep-zoom.md`): ground swept only from above has been looked at for bases and not
for tasks, and a picture that called both «обойдено» would mislead in exactly the
direction that matters.

**Its own limit, stated:** the panel folds the grid in when the scene is read, so
coverage accumulates while somebody is looking and from whatever the capture child still
holds (its own window is a day). A sweep that happened between two looks, with the child
long gone, is lost. Closing that properly means a hook where the checkpoint is written
rather than where it is read — worth doing, not done here.

## What is still missing, in the order it is worth adding

Every item below is shown on the tab itself (`worldview.gap.*` in all eleven locales),
because a person searching the canvas for something that was never in the data will
conclude the tool is broken.

1. **Alliance cities (`f2 = 25`) are not stored anywhere.** The decoder knows them —
   `world_index.py` reads them only to learn an alliance's full NAME — and nothing keeps
   the tile. They are large, obvious objects in the client, and their absence is the
   first thing a comparison will notice. Cheapest of the remaining items: one more kind
   in the same checkpoint.
2. **Terrain and scenery do not exist for us at all.** The panel knows objects, never
   ground. The picture is dots on empty black and will stay that way; whether the game
   even sends ground data is unresearched.
3. **An object's footprint is unknown.** A base and a city cover several tiles; we hold
   one coordinate and draw one dot. So a «one tile out» difference between the two
   pictures may be ours rather than the game's, and cannot currently be told apart.
4. **Monsters are the client's view, not the map's.** Nothing on the wire names one
   (`protocol.md`), so the list comes from a read of the client's own memory — as wide as
   the camera, not as wide as the warzone. On the schematic they cluster wherever the
   camera has been.
5. **Treasures live only while the sniffer runs.** Their checkpoint is a channel between
   two processes, deliberately worthless after a restart (`panel-storage.md`).
6. **Players met through a lorry have no coordinates** — deliberately, since a truck says
   nothing about where its owner's base is (`world_index.py::_met_owner`). They are in
   the register and not on the map.
7. **A warzone's size is known only once we have swept it.** It rides on the same block
   reply as the coverage rectangle (`maxAreaSize`) and is now kept per server — before
   #2018 nothing in this repository knew the width of the map. A server never visited
   still has no frame to draw.
8. **Marches and rallies in flight are not drawn.** The rally stream is captured
   (`rally_alert_stream`) but nothing keeps it as map objects; only lorries and trains
   have interpolated positions.
9. **Real sprites are not wired up.** The person allowed them («ассетсы можно
   использовать реальные») and the extraction exists (`extract_chat_assets.py`, UnityPy),
   but there is no `cfgId → sprite` table for map objects — the monsters' `pic_name` is
   the only handle we have. Schematic colour until then, which is also the safer default:
   a picture that looked exactly like the game would hide the differences it exists to
   show.

## What was measured

* The bundle: the application is 232 kB (72 kB gzip) and PixiJS is a **separate 879 kB
  chunk (253 kB gzip) fetched only when this map is opened** — `import('pixi.js')` is
  dynamic on purpose, so a phone that never opens the tab pays nothing.
* The caps, and they are said out loud on the page rather than applied quietly: 4 000
  objects per kind in one scene, 13 000 coverage cells kept per profile, 8 000 in the
  capture child's own grid.

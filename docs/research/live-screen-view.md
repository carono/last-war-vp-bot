# Broadcasting what the CLIENT can see right now (#2018)

The schematic map that shipped draws what the panel has GATHERED — every base, mine,
★ tile and ghost tile it has ever been told about, plus where the camera has swept. The
person asked for something else and said so plainly: «я хочу, чтобы на вкладку
транслировалось текущее схематичное изображение экрана игры, то что клиент видит по
факту».

That is a different picture from a different source: not our accumulated model, but the
client's own view — where the camera stands, how high it is, and which objects the client
is holding around it at this second. This file is what one such reading costs and what
«transmitting» it would actually mean. **Nothing periodic was put in place: a broadcast is
a repeated reading, which is exactly what «читаем один раз, дальше слушаем» forbids
without the person's word (`CLAUDE.md`).**

All values below are of the shape observed on a live client, with the account's own
numbers replaced where they identify anything.

---

## 1. What the client knows about its own screen, and how to read it

Every field is already in the client's memory. Nothing here asks the server anything.

| what | where it lives | note |
|---|---|---|
| the scene | `SceneUtils.GetIsInWorld()` / `GetIsInCity()` / `GetIsInPve()` | the three the status strip already reads (`player-place.md`) |
| the window on top | `UIManager.Instance:GetStackTopWindow().Name` | `nil` = the player is looking at the scene itself |
| **the camera's tile** | `WorldScene.CurTilePos` → `.x`, `.y` | live: `cam=718,390`. This is the coordinate `player-place.md` looked for and did not find on `WorldFavoDataManager.curPos` (which is `nil`) |
| **the camera's height** | `WorldScene.Zoom` | live: `105.0` — the scene's own `InitZoom` |
| the detail band | `WorldScene:GetLodLevel()` | live: `1`. The ladder is in `map-sweep-zoom.md` |
| **what is in view** | `WorldScene.PointManager` — `HasPointInfo(pid)` / `GetPointInfo(pid).PointType` | `PointType` is the wire's `f2`: 6 base, 7 mine, 17 ★ task, 25 alliance city, 29 ghost |
| monsters near the camera | `WorldScene:GetMonsterListInArea(centre, size, ids, out)` | `ids = nil` for «any» |
| this account's marches | `DataCenter.WorldMarchDataManager:GetOwnerMarches()` | live: 1–3 in the air, changing between readings |

`WorldScene` is a C# `MonoBehaviour`, found once with `FindObjectsOfType` and cached in a
`DataCenter` slot the way every recipe here already caches it. **It exists only in the
world scene** — a client standing in the base answers `ws=false`, which is the honest
«there is no world view to broadcast», not a failure.

**The point manager holds a BOUNDED window, and that is the finding that makes this
cheap.** At `Zoom = 105` a 41×41 box around the camera and an 81×81 box return the SAME
366 points — the client simply does not hold more than that around the camera, so «what
the client sees» is a few hundred objects and not a map.

**Not the Lua-clone route.** `project_env_read_lua_clones` enumerates `WorldScene`
GameObject clones and is remembered as crash-prone. Nothing above enumerates anything
after the one cached `FindObjectsOfType`; the readings are field accesses on an object
the client already has.

## 2. What one reading costs — measured live

Inside the VM, with `os.clock` around each part (median of three runs on the world map):

| part | cost |
|---|---|
| scene + top window | 0.0 ms |
| find `WorldScene` — first time | 4–10 ms |
| …every time after, from the cache | 0.0 ms |
| camera tile + zoom + LOD | 0.0 ms |
| 21×21 tiles out of the point manager (160 points) | 1 ms |
| 41×41 (366 points — the client's whole window) | 3 ms |
| 81×81 (the same 366 points) | 10–11 ms |
| monsters in a 160-tile box | 0–1 ms |
| this account's marches | 0.0 ms |
| **everything above, one chunk** | **14–15 ms** |

And the part that actually matters — the panel↔client round trip, `> action` to
`< action` in the profile's own log:

| | run 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| the whole screen read | 2.63 s¹ | 1.15 s | 0.96 s | 0.75 s | 0.76 s |
| a one-line read with no work in it | 1.00 s | 0.57 s | 3.40 s² | | |

¹ first play after a restart — it scanned for the scene and warmed the link.
² the play waited for the claim; the log says so («игру ведёт default/timer»).

**So the work is free and the round trip is everything: ~0.6–1.2 s of EXCLUSIVE link per
reading, occasionally 3 s when something else is driving.** The link is exclusive — a
second of it is a second the robberies, the rally joins and the errands do not get. One
reading a second is the whole link; one every 5 s is roughly a fifth of it.

## 3. The contradiction, stated for the person to settle

A broadcast is a repeated reading. The rule is «читаем один раз, дальше слушаем, никаких
активных действий в фоне», and the honest position is that **there is nothing to listen
to**: the camera is CLIENT state, so no server push carries it (the same wall
`player-place.md` hit for the scene and the open window). Nobody may put a clock on this
without the person saying so, and this file exists so they can decide with numbers.

The options, with what each costs:

**(a) Read only while the tab is OPEN, on an interval the person chooses.**
No hook, no client change, works today. The price is linear and known: at 5 s ≈ 20 % of
the link while somebody is looking, at 2 s ≈ 50 %, at 10 s ≈ 10 %. Watching it for a
minute at 2 s costs the bot half a minute of its own work. Nothing is spent when the tab
is closed, and nothing is spent by the other profiles.

**(b) A hook inside the client that announces the move; the panel listens.**
The precedent is real but only half of it applies. `tools/lua_trace.py` proves the
mechanism — a Lua shim writes a line into the client's own `Player.log` and a reader tails
the file, touching neither the game nor the server afterwards — and `UIWorldPointCtrl:
InitData` (#1420) proves a Lua method can be wrapped. **But `WorldScene` is C#, and xLua
cannot wrap a C# method**, so the hook would have to sit on whatever LUA object hears
about the view moving. Whether such an object exists has NOT been established; finding out
is a probe of its own (~half an hour of live reading, no game state changed). If one
exists this is the shape the rule asks for: one reading at the start, then changes
announced. If none exists, (b) is off the table and the choice is between (a), (c) and (d).

**(c) Ride the work that is already happening.** The panel plays scenarios all day —
errands, robberies, joins — and each one already holds the link. A 15 ms read appended to
plays that happen anyway costs no new round trip and asks the game nothing extra; the
picture is then as fresh as the bot's own activity, which on a live profile is seconds to
a couple of minutes, and the page says how old it is. No new clock, no background
question. What it cannot promise is smoothness: nothing moves while the bot is idle.

**(d) A snapshot on a press, and no broadcast at all.** The «Обновить» the tab already
has: one reading when the person asks for one, its age drawn beside it. Costs exactly what
the person asks for and nothing else, and it is what the panel does today for the status
strip (`panel/runtime/header.py`). This is the only option that needs no decision, because
it is already the rule.

A combination is available and probably the right answer: **(d) always, (c) for free
freshness, and (a) only while the tab is open and only at an interval the person names.**

## 4. What was NOT done, on purpose

* No clock, no timer, no trigger, no «refresh every N seconds» anywhere — the decision is
  the person's and had not been taken when this was written.
* The probes used to measure all of the above (`dev/_t2018_screen.md`,
  `dev/_t2018_tiny.md`) were deleted afterwards, exactly as #2016's were. The only trace
  they leave in the client is a cached scene reference in a `DataCenter` slot, which the
  next client restart drops.

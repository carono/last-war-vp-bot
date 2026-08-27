# Where the player is standing in the client — scene, window, warzone (#2016)

Goal: the web panel's status strip has to say WHERE the player is right now — the base,
the world map, an operation — and which screen of the game is open on top of it. Nothing
in the panel read any of that; the DSL's own `scene` condition read half of it and threw
the other half away.

Method: live probes through the panel's web API against a logged-in client
(`src/lastwar_bot/actions/dev/…`, deleted afterwards). No wire capture: every value below
is already in the client's memory, so this costs one VM round trip and no question on the
wire.

Result: `actions/read_player_place.md`, and `panel/runtime/header.py` behind the strip.

All values below are of the shape observed, with the account's own numbers replaced.

---

## 1. The scene — three flags, and the HUD decides what «city» means

```lua
SceneUtils.GetIsInWorld()   -- the world map
SceneUtils.GetIsInCity()    -- the home base
SceneUtils.GetIsInPve()     -- an operation / instance
```

Live, on a client sitting on the world map: `world=true city=false pve=false`, and
`UIManager.Instance:IsWindowOpen('UIMain')` — the main HUD — `true`.

**The city is only reported when the HUD is up as well**, which is the rule
`script_engine._scene_reading` already keeps for the DSL's `scene`: a client that is
still building the base answers `GetIsInCity() == true` while nothing is playable yet, so
the honest answer there is `unknown` rather than «дома». The scenario keeps the same rule
so that the strip and a `WAIT scene == city` cannot disagree about the same client.

`GetIsInPve()` is the third scene and had never been read anywhere in this repository.

## 2. The window on top — the stack, not a scan of the names

Two ways to ask, and only one of them can order the answer.

**The scan.** `IsWindowOpen` over the whole of `UIWindowNames` — 2231 names — answers
which windows are open:

```
names=2231 open=UINpcTalkLayer,UIMain,TouchScreenEffect,UILWAlMain
```

Measured inside the VM with `os.clock`: **1.0 ms** for the whole sweep, which is nothing
next to the round trip that carries it. But `pairs` walks the table in its own order, so
the list cannot say which of two windows is in FRONT. It also mixes layers into the
answer — `UIMain` is the HUD and `TouchScreenEffect` is an input overlay; neither is a
screen anybody «is on».

**The stack**, which is what the client itself uses:

```lua
UIManager.Instance:GetStackTopWindow().Name   -- the screen on top, nil when none
UIManager.Instance.windowStack.length         -- how many are stacked
```

`windowStack` is a doubly linked list — each node is `{_prev, _next, removed, value}`,
and `value.Name` is the window's id. Measured live with the alliance screen open:

```
length=1 || 1: keys=_prev(table),removed(boolean),_next(table),value(table) val=UILWAlMain
top=UILWAlMain
```

…and with nothing open, on the world map: `length=0`, `GetStackTopWindow()` is `nil`.
**The HUD never enters the stack**, which is why an empty stack is the honest «the player
is looking at the scene itself» rather than a failed read.

So the scenario reports the stack's top and its depth, and does not scan. The stack is
the order; a list that cannot say what is in front would be the panel guessing.

## 3. The warzone — the camera's, and the account's

```lua
DataCenter.WorldFavoDataManager.curServerId   -- the warzone the camera is in
LuaEntry.Player.serverId                      -- the warzone this account belongs to
```

The first is the same field every coordinate jump already reads
(`lua_actions.current_server_expr`). Live on an account at home: `cur=935 home=935`. They
differ exactly while the client is standing in somebody else's warzone — a cross-server
jump — which is the one case where «текущий сервер» has two honest answers, so both
travel and the strip marks the camera's when it is not the account's.

`WorldFavoDataManager.curPos` is **nil** — there is no camera coordinate to be had from
that object, and none is reported.

## 4. What it costs

One play of `read_player_place.md`, end to end through the panel's own runner, measured
from `profiles/<name>/debug.log` on the live client:

| run | `> action` | `< action` | elapsed |
|---|---|---|---|
| 1 | 22:22:25.656 | 22:22:25.823 | **167 ms** |
| 2 | 22:22:32.331 | 22:22:32.524 | **193 ms** |
| 3 | 22:22:39.007 | 22:22:39.226 | **219 ms** |

The same order as the resource balance (`base-resources.md`: 168–260 ms), and for the
same reason: the cost is the panel↔VM round trip, not the work in the chunk — the chunk's
own window sweep was 1.0 ms and is not even in the shipped recipe.

**Which is the whole design problem of a status strip.** It is on screen on every page,
`/api/state` is polled every 2.5 s per open page, and the game link is exclusive — time
spent here is time the schedule, the robberies and the rally joins do not get. Reading
the place on every poll would hold the link about **8 %** of the time, permanently.

So `panel/runtime/header.py` paces the two halves apart:

* the place at most every **10 s** (≈2 % of the link) — it genuinely moves, because the
  panel drives the client all day;
* the character (name, HQ level) at most every **10 minutes** — a name never changes and
  a level changes a few times a season.

Both plays go in at `claims.DETACHED`, below every ordinary errand, and neither is booked
at all while the link is busy or the profile's gate is shut. Nothing ticks: `state()` is
called by the route, so a panel nobody is looking at reads nothing.

## 4a. What it costs in PIXELS, which is the other budget

The strip is sticky and drawn above every screen, so it is spent on every page — the same
budget #1976 fought over. Measured in WebKit on real device profiles
(`~/playwright-tests`), `header.offsetHeight` with the panel live:

| | iPhone 13 mini (720 px tall) | iPhone 15 Pro Max (739 px) |
|---|---|---|
| before this change (picker row) | 43 px | 43 px |
| after, ONE profile open | **37 px** | **37 px** |
| after, several profiles open | 43 + 16 px | 43 + 16 px |

With one account open the strip absorbs the profile's name and the picker's row goes
altogether, so the header comes out 6 px SHORTER than it was. With several open the picker
keeps its row — it is a tap target — and the strip adds 16 px under it. The whole line
(`default · Player1 · ур. 35 · сервер 935 · Карта мира · UIMainMiniMap`) fits without
wrapping on the narrowest phone in the set; the window id ellipses first if it ever does
not.

## 5. What was looked for and is not there

* **A push.** The resource balance is driven by `push.resource.item.update` (#1990) and
  the same shape was wanted here. There is none: the scene and the window stack are
  CLIENT state — nobody tells the server that a player opened a screen — so there is no
  event to subscribe to and a paced read is the only honest option. The one thing that
  does travel is a cross-server jump, and it is already covered by re-reading.
* **A camera coordinate.** `curPos` is nil, and the world scene object that does hold one
  is found by enumerating `MonoBehaviour`s (`attack_golden_zombies2.md`) — seconds of
  work, for a line the strip does not need.
* **A translated window name.** The window's id (`UILWAlMain`) is the game's own
  identifier and it is shown raw. The alternative is the panel keeping a table of two
  thousand ids and being wrong about the ones a new season adds — the same reasoning as
  the resource names in `base-resources.md`, arrived at from the other side: there the
  game had a name and the panel used it, here the game has no name and the panel does not
  invent one.

## 6. What a client that has not logged in answers

Plausibly, and wrongly — the state this repository has been caught by twice already
(`game-clock.md`). The gate is inside the recipe, where it costs nothing: the same round
trip reads `UITimeManager:GetServerTime()` first and answers an empty string when it is
not an epoch. The header then keeps whatever it last knew, with its age climbing, and a
header that has never read anything says so in words instead of drawing a name-shaped
dash beside a warzone of 0.

# «Под руинами» — the seasonal descent mini-game (#2021)

**Status: the autopilot plays live — it opens the machine, drives the descent and
plays round after round on its own (#2021).**

EN «Beneath the Ruins», RU «Под руинами». One of the four arcade machines on the
seasonal map. Locale keys `s6_cave_exploration_*` / `s6_minigame_*`.

`MiniGameType`: `GTetris=1`, `GSheep=2`, `GBiuBiu=3`, **`GoGoGo=4` — this one.**

Rules as the game states them: two rounds a week off-season (Mon–Tue and Thu–Fri),
**attempts are not limited**, the ranking keeps the best result per machine, first
place makes you champion of that machine (avatar frame + reward) and takes the city
it belongs to. The separate **Duel** mode stakes war merit, five a day — that is a
different thing and is out of scope here.

## Where the ability lives in the client

### The meta, in Lua

`DataCenter.LWGGGoDataManager` — `activityId`, `GetCurrentLevel()`,
`GetChallengeMaxLevel()`, `CanChallenge()`, `IsDayPass()`, `GetRankData()`, `room`.
`DataCenter.LWGGGoManager` carries the PvP side (`GameLiftPing`, `ReConnectPvp`) —
PvP runs over a separate GameLift connection and is not used by the PvE ladder.

### The round, in Lua

`package.loaded['DataCenter.SmallGameManager.SmallGameManager']` is used **as a
singleton on the class table itself** — call it with a colon:

```lua
local S = package.loaded['DataCenter.SmallGameManager.SmallGameManager']
local g = S:GetGameByType(4)        -- the GGoGoGo round object
g:Enter()                           -- opens the mini-game from the city  ← the door
g:Again()                           -- starts a fresh round once the window is up
```

`g` also has `Start`, `End`, `Settlement`, `Exit`, `CanNext`, `IsEnd`, `IsPass`,
`GetStageCfgId`, `GetCurrentLevelConfigID`, `GetMaxLevel`, `Validation`, and the
fields `data` (`bid`, `uid`, `stageCfgId`, `passMaxLevel`, `stageStartTimeInMills`),
`result` (`level`, `battleTimeMills`, `validationStr`, `boot`) and `gameView` (the
`UILWGGGoGame` window).

**Two doors that are NOT it.** `S:ToStartGame(4)` does nothing at all, and
`S:ToEnter(4)` / `S:ToStartByCity(4)` throw inside `SmallGameManager.lua` and leave
the window destroyed — they take arguments of another shape. Use `g:Enter()`.

### The game itself, in C#

The round is an ECS (`Leopotam.EcsLite`) under `MiniGame.GGGo.*`, with its client
half under `MiniGame.GGGo.Client.*`. Nothing of it is Lua.

| what | where |
| --- | --- |
| the round | `GGGoRuntime` (a MonoBehaviour on the `UILWGGGoGame` window) — `.Game`, `.LevelRootGO`, `.IsPlaying`, `.IsRunning` |
| the world | `.Game` is a `MiniGame.Core.GameWorld` — `.World` (`EcsWorld`), `.Env`, `.State` |
| the numbers | `.Game.Env` is a `GGGoEnv` — **`Distance` is the score** (depth, negative), `RollSpeed` (−3), `GameOver`, `GameTime`, `LogicTickCount` |
| the state | `.Game.State` — `Preparing:1`, `Running:2`, `Settlement:3` |
| the player | `UIGGGoPlayerController` — `.transform.position`, `.PlayerID`, `.Entity`, `._isGrounded` |
| the input | `UIGGGoMain` — `OnJoystickMove(Vector2)`, `OnJoystickEnd(Vector2)`, `OnClickLeftBtn()`, `OnClickRightBtn()` |

**The geometry does not need the ECS.** The drawn level is an ordinary Unity
hierarchy: `GGGoRuntime.LevelRootGO` → `GGGoScene(Clone)` → `DynamicRoot`, whose
children are the platforms in view (11 of them at a time). Their prefab names carry
the kind — `Obstacle(Clone)`, `ObstacleDisappear(Clone)` — and `.position` carries
where they are. Measured: **1.5 units between platforms in y**, and about **2.1
units of spread in x**.

The ECS way, if it is ever wanted, is `FuncRegion.TryGetClosestPlatformBelow(EcsWorld,
FP x, FP y, out int entity, out FVector2 pos)` and `FuncRegion.GetPlatFormHalfSize(SpawnType)`;
`FuncGame.IsPlaying(EcsWorld)` answers whether a round is live. `FP` is a fixed-point
struct, so calling these from Lua needs an `FP` value built first — the Unity
transforms avoid that entirely.

`SpawnType`: `Normal`, `Spike`, `Disappear`, `Bounce`, `RollL`, `RollR`, `PveInit`,
`PvpInit`, `Destination`, `Delete`, `ItemSpawner`.

## The per-frame tick — how an autopilot can exist at all

A descent platformer cannot be steered from outside: one `READ_LUA` round trip
through the panel costs ~1.5 s, and a round lasts under a minute. The steering has
to run **inside the client**, and the game has a Lua tick for exactly that: the
global `UpdateBeat`.

```lua
local node = UpdateBeat:CreateListener(f, owner)
UpdateBeat:AddListener(node)
-- and, when done
UpdateBeat:RemoveListener(node)
```

`xlua.util` is **not** loaded in this client, so `util.cs_generator` coroutines are
not available, and `UpdateBeat:Add(f)` does not exist — `AddListener` wants a node
built by `CreateListener`, not a bare function. `UpdateManager.Instance` offers the
same thing as `AddUpdate` / `AddLateUpdate` / `AddSecondUpdate`.

### The hazard, paid for once

A listener that throws, or that does heavy work every tick — three
`FindObjectOfType` calls was enough — **takes the whole Lua VM down with it**. Every
`READ_LUA` times out, every errand of the panel reports «нет связи с игрой», and the
listener cannot be removed, because removing it also needs the VM. The only way back
was restarting the game client.

So a listener written here must, without exception:

* wrap its body in `pcall` and switch itself off on the first error;
* **cache** the objects it works with instead of searching the scene every tick;
* throttle on a counter (every 4th tick is plenty);
* carry its own deadline and take itself off the beat when it passes.

### And a long `WAIT` in a scenario is not a way to watch a round

The panel's own errands take the game link back: a dev recipe that sits in `WAIT 25`
loses its lease mid-run («LeaseLost»). Measurements are taken the other way round —
one run installs a recorder into a global, a later run reads the global back.


## The door, and why `Enter()` alone is not it

`g:Enter()` opens the window **only when the round object already carries the server's
own round data** — a fresh client leaves `g.data` empty, `Enter()` returns without a
word, and nothing appears. The data is on the DATA MANAGER, not on the round, so the
door is three calls:

```lua
local M = package.loaded['DataCenter.SmallGameManager.SmallGameManager']
local g = M:GetGameByType(4)
local d = DataCenter.LWGGGoDataManager     -- carries data.bid / uid / stageCfgId
g:ChangeSource(2) g:UpdateGGGoInfo(d.data) g:Enter()
```

The window is up about ten seconds later and starts its own first round. `g:Again()`
starts the NEXT one — and only once a round has finished: called on a window that has
never played it throws inside `GGoGoGo.lua` («attempt to index a nil value (field
`result`)»), so it is worth calling only out of `Settlement`.

The manager's own doors take mixed arguments and none of them is a way in:
`M:ToGetInfo(4)` sends but nothing arrives, `M:IsDownload(g)` wants the round OBJECT,
`M:ToEnter(g)` wants the TYPE, and `M:ToStartByCity(…)` belongs to the alliance city.
`M:ToStartGame(4)` does nothing at all.

## Steering, measured

* **The joystick works, and its sign is mirrored.** `OnJoystickMove(Vector2(1, 0))`
  moves the player towards SMALLER Unity `x`. To go towards a larger `x`, push `-1`.
* **It has to be pushed on every tick.** Pushing once and only on a change of direction
  reads as no input at all — the pad's own `Update` consumes what it was given.
* **The player is fixed on screen and the level scrolls past it.** Its transform sits at
  the same place all round; what moves is the platforms.
* **`FindObjectOfType` can hand back a pooled, frozen instance.** The first
  `UIGGGoPlayerController` a round hands out may be a leftover that never moves — the
  live one is the one whose `gameObject.activeInHierarchy` is true, and it is worth
  re-finding every few dozen ticks, because a new round makes a new one.
* Platforms are the children of `LevelRootGO` → `GGGoScene(Clone)` → `DynamicRoot`, in
  the SAME space as the player: 1.5 units apart in `y`, about 2.7 units of play in `x`.
  `Obstacle(Clone)` is ordinary, `ObstacleDisappear(Clone)` falls away under you.
* **The score is `Env.Distance`** — depth, negative, and an `FP` fixed-point value: it
  answers `tostring` and NOT `+ 0`, so read it as text and parse the number out.

## What the panel plays

* `actions/play_beneath_ruins.md` (`ARGS rounds`) — opens the machine if it is shut,
  arms the autopilot inside the game and returns at once. The pilot lives on
  `UpdateBeat`: every second tick it finds the platform below worth aiming at (cost =
  horizontal distance + 0.6 × the drop, and a `Disappear` one costs 0.4 more), pushes
  the pad towards it, counts a round when the state falls out of `Running`, plays the
  next with `Again()` and closes the window with `Exit()` when the budget is spent.
* `actions/read_beneath_ruins.md` — how many rounds have gone, the best depth, the last
  one, and it takes a finished pilot off the beat.
* «События» carries the card and the two presses on the phone.

## What is still open

* **How good the steering is.** Measured on one stage: free fall reached 8–35 and the
  pilot 24–69 of depth, and the layout looks the same from round to round, so a policy
  change shows up as the same number moving. What has not been tried is looking further
  than one platform ahead, or the horizontal speed the pad actually gives.
* **The reading the pilot steers by goes stale mid-round, and why is not known.** With
  the listener installed, the only active `UIGGGoPlayerController` in the scene often
  stops at the spawn pose for the whole round — the same `x` and `y` to two decimals,
  while the score goes on climbing — so the pilot aims at one platform for a whole
  descent and every round ends at exactly the same depth (24.58 on the stage measured).
  Re-finding the object does not help: the frozen one is the only one there is. Without
  the listener the same object moves perfectly well (532.15 → 524.83 over four seconds),
  and the rounds that reached 36 and 69 were ones where it did. Two guesses worth
  testing: the pad being pushed on EVERY tick holds the player where it is, and the beat
  running before the game's own update hands back last frame's transform. Until it is
  answered, the pilot is a fixed policy playing blind, which is why it beats falling and
  loses to a person.
* Whether `Disappear` platforms need to be left quickly, and what `Spike` costs.
* Whether the stage the ladder is on (`GetCurrentLevel`) changes the layout enough that
  the rule has to change with it.

## How the reconnaissance was done

Through the panel's web API — `POST /api/actions/run` playing throwaway recipes under
`src/lastwar_bot/actions/dev/_t2021_*.md`, `profiles/<name>/panel.log` read back —
plus `results/il2cpp_dump.json` for the class list and .NET reflection
(`GetFields` / `GetProperties` / `GetMethods` with `BindingFlags` 60) from Lua for the
members the dump does not carry.

# The keyboard macros: where a chosen target is kept, and how a squad is sent at it

Task #1283, then #1328. Five keys: **1 2 3 4** send that squad at the target the person
CLICKED — with no «Атака» pressed and no squad screen opened at all — and **CapsLock**
sends the last one again with nothing on screen either. Everything below was read out of
a live client through the Lua VM (`tools/lib/lua_client.py`).

Every identifier in this file is invented. The shapes are real — a 19-digit uuid, a
six-digit tile index, a three-digit server — the digits are not (`CLAUDE.md`).

---

## What #1328 changed, and why the old answer was only half of one

#1283 read the target off the **squad-selection screen**, which meant the key was only
worth pressing once the person had already clicked the target AND pressed «Атака» AND had
a window in front of them. Three actions to save one. The ability people actually wanted
is one earlier and one window fewer: **click the target, press the key, the squad goes.**

That needs the client to answer a different question — not «what is this screen marching
on», which it holds obligingly, but «what did the person just click», which nothing was
keeping. The rest of this file is the old answer (still live: an open screen still wins,
see below) followed by the new one.

---

## The question the whole task rests on

A person clicks a target on the map — a monster, a mine, another player's base, a rally
somebody raised, an event boss — presses the action in its popup, and the game puts up
the squad-selection screen. **What does the client hold at that moment?** If the answer
is «everything the march needs», the macro is a key that presses a button the person was
about to press anyway. If it is «only what is on screen», the panel would have to
reconstruct a target, and a second answer to «what is being marched on» is exactly the
kind of thing that goes wrong quietly.

The answer is the first one.

## The screen IS the state: `UIFormationSelectListV2`

Two windows, depending on the client's `formation_v2_switch` config —
`UIFormationSelectListV2` and `UIFormationSelectListNew` — and their controller carries
the whole march. Read live, with the screen open on an event boss:

```
top=UIFormationSelectListV2
  targetType=33  targetPoint=<pid>  targetUuid=<19 digits>  targetServerId=<server>
  timeIndex=1    autoBackHome=1     selectFormationUuid=<19 digits>
  currentFormationUuid=0            formationType=1        defaultMarchIndex=-1
  isTargetMoving=false              directionWaitResult=false
```

…and with the screen open on a «Стягивание» against a level-35 elite, the same fields
with `targetType=7` and `timeIndex=5` — the rally's wait slot, which is a field of the
screen rather than of the target.

| field | what it is |
|---|---|
| `targetType` | `MarchTargetType`. 1 attack a monster · 2 gather · 6 join a rally · 7 raise one · 11 attack a base · 17 scout it · 33 the «Кодовое имя» boss · … |
| `targetPoint` | the target's tile index |
| `targetUuid` | the target's server uuid — **what actually addresses it** |
| `targetServerId` | whose server it stands on |
| `timeIndex` | the wait slot (a rally's countdown; 1 for a plain march) |
| `autoBackHome` | come home by itself |
| `selectFormationUuid` | the squad the screen has highlighted |

### How the names were found without opening a window

The class table is reachable from the window CONFIG, whether or not the window has ever
been opened:

```lua
UIManager.Instance.windowsConfig[UIWindowNames.UIFormationSelectListV2].Ctrl
```

so `string.dump` on its methods names every field it touches — the client's Lua is not
stripped ([[project_lua_string_dump_decompile]]). `InitData` is the one that matters:

```
InitData :: currentFormationUuid formationType targetType targetPoint targetUuid
            timeIndex autoBackHome MarchAutoBackType selectFormationUuid
            targetServerId monsterSpecialType rallyType InitRallyTime InitMarchSpeed
OnCreateClick :: … NeedTakeArmy SendCreateMarchMessage timeIndex autoBackHome
                 targetServerId … destroyTimeIndex
OnCheckTime :: GetTimeFormCurPosToTarPos … targetType JOIN_RALLY … OnCreateClick …
```

The last two lines are the launch button, end to end: `OnCheckTime(formationUuid,
destroyTimeIndex)` runs the game's own pre-checks and then `OnCreateClick` makes the
one send this repository already knows —

```lua
MarchUtil.SendCreateMarchMessage(formationUuid, targetType, targetPoint, targetUuid,
                                 timeIndex, autoBackHome, needSoldier,
                                 targetServerId, destroyTimeIndex)
```

— the same call as [`attack-and-scout.md`](attack-and-scout.md),
[`rally-join.md`](rally-join.md) and [`codename-event.md`](codename-event.md). **The
type is the SECOND argument, after the formation and before the point** (the rake from
#1277).

## The two sends, and why they are not the same one

**Keys 1..4 press the screen's own button.** `View:OnSelectClick(formation)` is the tap
on the squad's cell, `Ctrl:SetSelectFormationUuid(formation)` is what the tap records,
`Ctrl:OnCheckTime(formation, nil)` is the launch. The macro replaces the MOUSE and
nothing else: every pre-check the game makes for that target type still runs, and the
screen still closes itself. (The same press `rally_launch` has been making since
[`rally-create.md`](rally-create.md).)

**CapsLock has no screen to press**, so it makes the send itself, from what the launch
wrote down a moment before it pressed — the shape [`codename-event.md`](codename-event.md)
proved: the target is addressed by uuid, the server works the path out for itself, and
no window is opened, no camera moved, no tile waited for.

Both memories live in the game's VM, because `TAP` carries no arguments and the second
one has to outlive the scenario that filled it:

```
DataCenter.__lw_macro      = {squad, formation, type, point, target, server,
                              timeIndex, back, need, before, result}
DataCenter.__lw_macro_last = the same, as the last launch actually sent it
```

### Reading and pressing are ONE call (#1290)

The first version was three: read the screen, ask what the reading said, press. Each is
a round trip of ~90 ms, and the middle one is a question standing between the key and
the march — so a person's press spent a fifth of a second going back and forth over a
screen their own click had put up and could close at any moment.

`macro_send` is all three inside one chunk, on the game's own thread, in one frame:
nothing can close the screen between the reading and the press, and what it decided is
parked for the recipe to read back AFTERWARDS:

```
ACT macro_send squad=2 result=1 screen=1 type=33 point=… target=… formation=… marches=0
```

| `result` | what happened |
|---|---|
| `1` | the screen's own launch was pressed |
| `0` | no squad screen is open — nothing was chosen |
| `-1` | the game has no squad with that number |
| `-2` | the screen is open and its target could not be read |
| `-3` | the screen's own launch raised |

`macro_repeat` does the same with its own three answers (`1` scheduled, `0` nothing to
repeat, `-1` the last one was a rally). Both buttons declare `wait=0.0`: a `wait` is a
plain sleep with the game claim held, and both recipes then count the marches, which is
a wait for the thing rather than for a number somebody guessed.

The whole budget, before and after, is in
[`game-call-latency.md`](game-call-latency.md#a-key-press-is-a-whole-run-1290).

### The rake that cost the most: `NeedTakeArmy`

`OnCreateClick` passes a `needSoldier` flag it works out with the screen's own
`NeedTakeArmy`, so the first version of the macro asked the screen for it. **Called
bare it answers `true`** — like `CheckCanBattle` in #1259, it takes arguments the caller
cannot see — and a send with `needSoldier = true` is ACCEPTED and creates no march:

```
ACT macro_repeat scheduled squad=2 type=33 target=<uuid> marches=0
ACT macro_repeat ok=true err=nil
ACT sent=0     <- eight polls, four seconds, nothing
```

The same send with `false`, and nothing else changed:

```
ACT macro_repeat scheduled squad=2 type=33 target=<uuid> marches=0
ACT macro_repeat ok=true err=nil
ACT sent=1     <- first poll
```

`false` is what every proven send in `lua_actions.py` passes, and it is what both macros
pass. Nothing asks the screen.

### A rally is not repeated

`macro_repeat` refuses when `MarchUtil.IsRallyMarch(type)` — the game's own predicate,
rather than a list of numbers copied out of an enum that grows every season. A banner is
raised through the screen's own launch, which fills in a wait slot and a disband time
the screen owns; the plain send has never been proven for a rally type, and the one time
#1283 tried it live **the client went down in the middle of the run** (`err=299` from
the daemon, the process replaced by a fresh one). Nothing pins that crash on the send —
the client had been up for hours and the launcher was running beside it — but «unproven»
plus «the client restarted while it ran» is not something to keep pointing at somebody's
account.

## The click itself: `UIWorldPointCtrl:InitData` (#1328)

A tap on the map opens **`UIWorldPoint`**, and the popup's controller is where the click
lands. `string.dump` on its `InitData` — the class table is reachable from the window
config with no window open, the same trick that found the squad screen's fields — names
exactly what the click brought in:

```
InitData :: … LuaEntry Player GetCurWorldId GetCurServerId … uuid tonumber pointId
             ownerUid type isAlliance buildId desertId isArrow byDetect … serverId …
```

So `Ctrl.pointId`, `Ctrl.uuid`, `Ctrl.serverId`, `Ctrl.ownerUid` and `Ctrl.type` are the
click, complete. **`Ctrl.type` is `WorldPointUIType`** — the popup's own idea of what kind
of thing was tapped — and NOT a `MarchTargetType`; the two are separate enums that share
some small numbers, which is exactly the sort of coincidence that turns a gather into an
attack. Both were dumped live:

```
WorldPointUIType   Monster=1 Boss=2 City=3 Build=4 CollectPoint=5 CollectArmy=6 Road=7
                   … AllianceCity=13 Ruin=34 Ghostrecon=43 …  (85 entries)
MarchTargetType    ATTACK_MONSTER=1 COLLECT=2 JOIN_RALLY=6 RALLY_FOR_BOSS=7
                   ATTACK_ARMY_COLLECT=10 ATTACK_CITY=11 SCOUT_CITY=17 …
```

### Catching the click without polling anything

`UIManager.Instance.windowsConfig[UIWindowNames.UIWorldPoint].Ctrl` is the CLASS table and
every popup instance indexes into it, so wrapping `InitData` **once** catches every click
there is — a finger on the map, a scripted `GoToUtil.OnClickWorldPoint`, a jump out of the
magnifier — with no timer left running in somebody's game and no round trip per second:

```lua
cls.__lw_pick_orig = cls.InitData
cls.InitData = function(s, ...)
  local r = table.pack(orig(s, ...))                      -- the game's own, FIRST
  pcall(function() DataCenter.__lw_macro_pick = DataCenter.__lw_pick_read(s) end)
  return table.unpack(r, 1, r.n)
end
```

The original runs first and unprotected: a popup that opened blank because a macro was
listening would be a far worse bug than any this fixes. Everything of ours is inside a
`pcall`, and `InitData`'s own return values are handed back untouched. Arming is
idempotent (`rawget(cls, '__lw_pick_orig')` is both the saved original and the flag) and
happens inside the key's own chunk, so a client that restarted between two presses is
watched again at no extra call.

### Which march a clicked point becomes

Read out of the two enums BY NAME, so a season that renumbers them changes nothing:

| clicked | becomes | why |
|---|---|---|
| `Monster` / `Boss` with `canAttack == 1` | `ATTACK_MONSTER` | the game's own «this one can be soloed» |
| `Monster` / `Boss` with `canAttack == 0` | **refused** | a banner is raised through its own screen, never by a key — the same refusal `macro_repeat` has made since #1283 |
| `City`, somebody else's | `ATTACK_CITY` | |
| `City`, the player's own | **refused** | |
| `CollectPoint` | `COLLECT` | a resource tile has `uuid = 0` and addresses by tile |
| `CollectArmy` | `ATTACK_ARMY_COLLECT` | somebody else's squad, mid-gather |
| anything else | **refused, by name** | the log says which kind, so the next one can be added on purpose |

`GetMonsterData` is asked **with the uuid** — called bare it answers a one-field stub whose
`canAttack` is `0`, and every monster in the game would read as rally-only
([`world-monsters.md`](world-monsters.md), Finding 8). It is asked at CLICK time, because
the popup's controller is the only thing that can answer it and it is long gone by the time
a key is pressed.

Verified live against a running client, feeding the reader hand-made controllers of the
right shape (nothing on screen was touched, nothing was sent):

```
monster-solo  = Monster/mtt=1/can=1        mine     = CollectPoint/mtt=2
monster-rally = Boss/mtt=nil/can=0         gatherer = CollectArmy/mtt=10
other-base    = City/mtt=11                own-base = City/mtt=nil
road          = Road/mtt=nil
```

### What ends a pin

Never the panel's own bookkeeping — a press does NOT spend the click, so three keys in a
row put three squads on one target, which is what clicking a boss is usually for. What ends
it is the world:

* **time.** `stale`, 180 s by default, measured on the GAME's clock
  (`UITimeManager:GetInstance():GetServerSeconds()`, never the PC's —
  [`game-clock.md`](game-clock.md));
* **the scene.** Walking off the world map drops it (`SceneUtils.GetIsInWorld()`);
* **the account.** The pin records `LuaEntry.Player.uid` and `.serverId` as they were at
  the click, and a press from another account or another home server refuses rather than
  marching somebody else's squad at somebody else's tile.

Each of the three is its own refusal in the log, so «ничего не отправилось» always says
which of them it was.

### The one that had to be found the hard way: the panel clicks too

The bot opens `UIWorldPoint` popups all day of its own accord — a rally hunt, a treasure
sweep, a jump to coordinates — and every one of them goes through the same `InitData`. A
macro that simply took the newest pin would put somebody's squad on the tile an automation
was looking at rather than on the one they clicked. **This is not hypothetical: the very
first pin this watcher ever caught, minutes after being armed on a live client, came from
the panel's own scan and not from a finger.**

**Two fixes were tried before the right one, and both are worth keeping written down.**

*First:* record an errand's popup and refuse it at press time. That reads fine in a test
and destroyed the ability in a game — the panel opens a world-point popup every few
seconds, so a person's click survived about ten seconds before an errand overwrote it and
every key from then on answered «эту точку открыла панель». Read live ten seconds after a
press:

```
PIN kind=DispatchTask script=1 age=10 desc=DispatchTask @[<x>,<y>|<server>]
```

*Second:* keep only the opens that did not come from a chunk. That froze the pin
completely: the person clicked elsewhere all day and the key kept marching on the original
target. The reason is the whole point of this section.

### Who opened a popup CANNOT be asked

The idea was that a scripted open leaves a `[string "…"]` frame on the stack while a finger
does not. It does not work, and the stack says why — read live at a real open:

```
1:[string "chunk"]  2:[C]  3:[string "chunk"]     <- the watcher's own two frames
4:…/UI/UIWorldPoint/View/UIWorldPointView.lua
5,7,8:…/Framework/UI/UIManager.lua
```

**There is no `GoToUtil` frame at all.** The point's detail is fetched from the server and
the window is filled in when the REPLY lands, so whoever asked for it returned long ago.
The test therefore read «scripted» off the watcher's own two frames and answered that to
everything, a finger included — and since a scripted open was not kept, the pin never moved
again.

So the rule is the safe way round: **every open moves the pin, and the PRESS judges.** A pin
that always mirrors the last point opened can be refused by kind in one honest sentence; a
pin that sometimes refuses to move is a squad marching at a target the person walked away
from. What the errands open — a secret task, a treasure, a ghost tile, a rally-only elite —
is refused by kind anyway; what a person clicks is marched on.

### A wrapper has to be replaceable

A client runs for days while the panel restarts several times a day, so «install once and
leave it» means a live client keeps yesterday's wrapper whatever the code says — and
wrapping the wrapper only puts the old body underneath the new one, still doing the old
thing. The arming carries a version (`__lw_pick_ver`): a different one puts the game's own
`InitData` back first and wraps that. The reader needs no version — it is re-assigned every
time, which is why a correction can land there and reach a client already running.

### Which march a clicked point becomes

Read out of the two enums BY NAME, so a season that renumbers them changes nothing:

| clicked | becomes | why |
|---|---|---|
| `Monster` / `Boss` with `canAttack == 1` | `ATTACK_MONSTER` | the game's own «this one can be soloed» |
| `Monster` / `Boss` with `canAttack == 0` | **refused** | a banner is raised through its own screen, never by a key — the same refusal `macro_repeat` has made since #1283 |
| `City`, somebody else's | `ATTACK_CITY` | |
| `City`, the player's own | **refused** | |
| `CollectPoint` | `COLLECT` | a resource tile has `uuid = 0` and addresses by tile |
| `CollectArmy` | `ATTACK_ARMY_COLLECT` | somebody else's squad, mid-gather |
| anything else | **refused, by name** | the log says which kind, so the next one can be added on purpose |

`GetMonsterData` is asked **with the uuid** — called bare it answers a one-field stub whose
`canAttack` is `0`, and every monster in the game would read as rally-only
([`world-monsters.md`](world-monsters.md), Finding 8). It is asked at CLICK time, because
the popup's controller is the only thing that can answer it and it is long gone by the time
a key is pressed.

Verified live against a running client, feeding the reader hand-made controllers of the
right shape (nothing on screen was touched, nothing was sent):

```
monster-solo  = Monster/mtt=1/can=1        mine     = CollectPoint/mtt=2
monster-rally = Boss/mtt=nil/can=0         gatherer = CollectArmy/mtt=10
other-base    = City/mtt=11                own-base = City/mtt=nil
road          = Road/mtt=nil
```

### What ends a pin

Never the panel's own bookkeeping — a press does NOT spend the click, so three keys in a
row put three squads on one target, which is what clicking a boss is usually for. What ends
it is the world:

* **time.** `stale`, 180 s by default, measured on the GAME's clock
  (`UITimeManager:GetInstance():GetServerSeconds()`, never the PC's —
  [`game-clock.md`](game-clock.md));
* **the scene.** Walking off the world map drops it (`SceneUtils.GetIsInWorld()`);
* **the account.** The pin records `LuaEntry.Player.uid` and `.serverId` as they were at
  the click, and a press from another account or another home server refuses rather than
  marching somebody else's squad at somebody else's tile.

Each of the three is its own refusal in the log, so «ничего не отправилось» always says
which of them it was.

### The one that had to be found the hard way: the panel clicks too

The bot opens `UIWorldPoint` popups all day of its own accord — a rally hunt, a treasure
sweep, a jump to coordinates — and every one of them goes through the same `InitData`. A
macro that simply took the newest pin would put somebody's squad on the tile an automation
was looking at rather than on the one they clicked. **This is not hypothetical: the very
first pin this watcher ever caught, minutes after being armed on a live client, came from
the panel's own scan and not from a finger.**

**And the first fix for it was the wrong one, which the first live session showed in
ninety seconds.** Recording an errand's popup and refusing it at press time reads fine in a
test: the pin is honest, the refusal is named, nothing marches at the wrong tile. In a
game it destroyed the ability. The panel opens a world-point popup every few seconds — a
treasure sweep, a secret-task scan, a rally hunt — so a person's click survived about ten
seconds before an errand overwrote it, and from then on every key answered «эту точку
открыла панель». **One press worked and nothing after it.** Read live, ten seconds after a
press:

```
PIN kind=DispatchTask script=1 age=10 desc=DispatchTask @[<x>,<y>|<server>]
```

— a secret-task tile on another server, standing where the person's monster had been. So
the pin BELONGS to the person: an errand's sightseeing is not recorded at all, and only a
click may write it.

**The keeping lives in the reader, not in the wrapper**, and that is a deployment fact
rather than a taste: a wrapper is installed once and stays for the life of the client, so a
correction inside it never reaches a client wrapped by yesterday's panel — and re-wrapping
only puts the old body underneath the new one, still overwriting. The reader is re-assigned
by every arming, so it is the half a fix can land in. (Verified on the client that was
already wrapped: a scripted open now leaves the pin alone.)

The stack tells them apart. A scripted open runs inside a chunk this repository sent, and
a chunk compiled from a string reports `short_src = [string "…"]`, while the game's own Lua
reports its file path:

```
lvl=1 what=Lua   src=chunk   short_src=[string "chunk"]      <- ours
lvl=2 what=C     src=[C]
lvl=3 what=main  src=chunk   short_src=[string "chunk"]
```

(`short_src`, not `source`: the raw source of a `SafeDoString` chunk is only its name.) So
the pin records `script = 1` when any frame of the stack is a string chunk, and a press on
a pin like that refuses — «эту точку открыла панель, а не ты». Verified live: the reader
called straight from a chunk reports `script=1`; the same reader inside a real popup's
`InitData` does not.

The one place this is deliberately overridden is the on-the-spot read of an already-open
popup: nothing is being opened there, and a popup standing open at the moment of the key
press is the best evidence of what is chosen there is.

### The second half of «works once»: the run holds the client

A run holds the game claim for its whole length, and a press that finds the client claimed
by something of equal standing is refused — «занят», in the log, and nothing started. The
first version of this recipe then stood for up to **seven seconds** after a send, counting
marches to prove one went out. Live, that read as:

```
12:20:57  CapsLock: повторяю последний марш
12:21:02  клавиша 1: отправляю отряд 1 на кликнутую цель
12:21:02  занят — дождись завершения текущего действия      <- the key is gone
12:21:06  … WHILE -> LIMIT 12 reached, giving up
```

So «three keys in a row put three squads on one boss» was impossible by construction: the
proof of the first march ate the second and third presses. Two changes, in the two places
that own the two halves:

* **the clicked path does not wait.** It presses and ends. The verdict is not dropped, it
  is DEFERRED — every press reads the march count the PREVIOUS one wrote down and says
  whether that one really marched, so a send that quietly achieved nothing is still
  reported, one press later and at no cost. The open-screen path still waits: nobody
  presses a second key at a screen;
* **a key waits for its turn** rather than being thrown away. `panel/runtime/hotkeys.py`
  holds a queued press for a few seconds while the client is claimed, which is a WHEN and
  not a WHAT — the run is unchanged, and the worker's queue keeps the presses in the order
  they were made. A claim that never frees still ends in the honest «занят».

### And the same tail, measured, on CapsLock

The clicked path stopped waiting; `march_repeat_last` did not, and a person felt it as
«CapsLock reacts after three seconds». Timed off the live log, per press, from the run's
own start:

```
start=+0.00  TAP=+0.08  ready=+0.14  poll1=+0.21 … end=+3.42
start=+0.00  TAP=+0.08  ready=+0.16  poll1=+0.22 … end=+3.90
start=+0.01  TAP=+0.23  ready=+0.28  poll1=+0.34 … end=+3.50
```

Everything past `+0.2` is the march-count poll, and the claim is held for all of it. The
same deferral fixes it, and the same measurement proves it — the whole run, live, after:

```
+0.000  > action: march_repeat_last
+0.067    TAP repeat the last macro march
+0.123    READ_LUA ready = 1
+0.171    READ_LUA squad = '1 (previous press: a march went out)'
+0.173  < action: march_repeat_last OK
```

**3.42–4.37 s → 0.173 s**, and the deferred verdict is in the line the person reads.

Two other numbers from the same session, so nobody has to guess again: the press chunk
itself costs **122–173 ms** in the VM against a **83 ms** bare round trip, and the send's
own wait — `TimerManager:DelayInvoke`, which exists so the send leaves from the GAME's
thread rather than the hijack one — was **0.3 s** for no measured reason and is **0.05 s**
now. What matters there is the thread, not the wait.

**It is not a CapsLock-specific fault**, which was worth ruling out: the hook queues on
`WM_KEYDOWN` only, there is no debounce and no waiting on the key's state, and the log
puts the run's start **0–26 ms** after the key's own line. The key was fine; the tail was
not.

### The two paths, in order

`macro_send` tries the **open squad screen first** and the pin second. A person who opened
that screen went that way on purpose, its target is fresher, and it carries a rally's wait
slot which a tile does not — so #1283's ability is intact and nothing about it changed. The
pin is what answers when there is no screen, which is now the ordinary case.

If nothing is pinned but the popup is still open, it is read on the spot through the same
reader. That covers the very first press after a client restart, when the watcher was armed
a moment too late to have seen the click.

## The keys themselves

`panel/runtime/hotkeys.py`, a `WH_KEYBOARD_LL` hook on a thread of its own.

**Why not `RegisterHotKey`.** A registered hotkey is taken away from whatever is in
front, system-wide, for as long as the panel runs — the person could no longer type `1`
anywhere on the machine. The low-level hook sees each press first and decides, per
press.

**1 2 3 4 are never swallowed.** They go to the game untouched. The game does nothing
with a digit outside a text box, and inside one (the in-game chat) the digit must still
be typed. The macro fires anyway and the scenario refuses in one line of the log —
«no target is chosen» — because it is only meaningful with the squad screen open, and
asking the game about that would mean a round trip inside the hook. Windows gives a hook
about a quarter of a second (`LowLevelHooksTimeout`) before it removes it without saying
so, and a Lua round trip is half that on a good day.

**CapsLock IS swallowed**, and only while the game is the foreground window — otherwise
every repeat would flip the keyboard into capitals. That is the one keyboard side effect
the design accepts: CapsLock does not toggle while the game has focus. Nothing else on
the machine is touched, and the panel takes the hook down when it closes.

**Nothing fires unless the game is in front.** One `GetWindowTextW` on the foreground
window against `game_paths.window_title()` — a title compare rather than a process
lookup, because this runs inside the hook's budget. A second client belonging to another
profile lives in its own Windows session and cannot be the foreground window of this
desktop, so the press always belongs to the profile whose page is showing.

---

## Where it lives

| | |
|---|---|
| keys 1..4 | `src/lastwar_bot/actions/march_selected_squad.md` |
| CapsLock | `src/lastwar_bot/actions/march_repeat_last.md` |
| the presses | `tools/lib/game_buttons.py`, `macro_send` / `macro_repeat` |
| the Lua | `tools/lib/lua_actions.py`, `macro_*` |
| the click watcher | `tools/lib/lua_actions.py`, `_PICK_READ` / `_PICK_ARM` / `macro_pick_arm` |
| the listener | `panel/runtime/hotkeys.py`, started by the shell |
| the tests | `tests/test_march_macros.py` |

## What is proven, and what is not

**Proven against a live client — keys 1..4, twice, on two different target types.** With
the squad screen open on a level-35 elite («Стягивание», `targetType=7`) the recipe ran
end to end and the march count went `2 → 3`; with it open on the «Кодовое имя» boss
(`targetType=33`) the presses read `screen=1 type=33 … formation=<uuid>` and the count
went `0 → 1`. Neither run opened a window, moved the camera or touched a squad cell with
anything but the screen's own call.

**Proven: CapsLock.** With the squad home again and nothing but the remembered target to
go on, `macro_repeat` sent and the march count went `0 → 1` on the first poll — the same
squad, at the same boss, with no window opened and the camera untouched. Its refusal is
honest too: run while that squad was still out on the previous march, the send went out
(`ok=true err=nil`) and no march appeared, which is what the recipe reports.

**Proven: the keyboard hook itself.** Installed under the panel's own interpreter, a
synthetic `3` produced `log.macro.send squad=3` and a play of `march_selected_squad
{"squad": 3}`; a synthetic CapsLock produced `log.macro.repeat` and a play of
`march_repeat_last` — **and the CapsLock state did not change**, which is the swallow
working. `stop()` takes the hook down and the keyboard goes back to Windows.

**Not proven: a rally repeat**, and it is refused rather than left to chance (above).

### #1328, on a live client

**Proven: the watcher catches a real popup.** Armed on a running client
(`wrapped=true`, `reader=function`), left alone, and a minute later the pin had filled
itself in off a popup the session opened by itself:

```
PIN false nil          mtt=nil
PIN true  CollectPoint @[<x>,<y>|<server>]  mtt=2   <- the wrapper fired, unprompted
```

Nothing polled it and nothing asked for it — `InitData` ran, the reader ran inside it, and
the pin was there to be read afterwards. That is the whole mechanism, end to end.

**Proven: the reading, on every kind the macro supports.** The reader was fed hand-made
controllers of the right shape against the live enums — nothing on screen was touched and
nothing was sent:

```
monster-solo  = Monster/mtt=1/can=1        mine     = CollectPoint/mtt=2
monster-rally = Boss/mtt=nil/can=0         gatherer = CollectArmy/mtt=10
other-base    = City/mtt=11                own-base = City/mtt=nil
road          = Road/mtt=nil
```

**Proven: the press is honest with nothing to press.** `macro_send` run with no squad
screen and no pin answered `result=0 screen=0 … marches=nil` and sent nothing; run again
once that first pin had aged past its window it answered `result=-4 kind=CollectPoint
age=356`, which is the staleness gate refusing on a real client with a real reading.

**Proven: a scripted open is told from a click.** The reader called straight from a chunk
reports `script=1`, which is the refusal above.

**Proven live, and then DISPROVED by the person playing — twice.** The first session found
the macro «works once and then nothing»: an errand's popup had taken the pin and the
seven-second poll answered the next key with «занят». The second found the pin FROZEN: the
attempt to keep errands out kept everything out, for the reason in «Who opened a popup
cannot be asked». Both write-ups are above, because the wrong turnings are the useful part.

**Proven after the third try**, driving the two kinds of open the way they really arrive —
a game-originated one through the game's own timer, an errand's straight from a chunk:

```
pin after A          CollectPoint @[<x1>,<y1>|<server>]  point=<A>
pin after B          CollectPoint @[<x2>,<y2>|<server>]  point=<B>   <- the pin follows
press with that pin  result=-1 kind=CollectPoint age=14              <- every gate walked,
                                                                        stopped at squad 0
```

`InitData` was also counted on both opens (`C.InitData=1` each time, the second with the
popup already up and no `V.OnCreate`), so a second click on another target really does
reach the watcher.

**Still not proven under a finger:** a real tap on a monster followed by a real `1`, `2`,
`3`, ending in three marches. That is the one check the person makes.

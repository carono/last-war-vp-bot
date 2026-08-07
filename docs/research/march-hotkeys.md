# The keyboard macros: where a chosen target is kept, and how a squad is sent at it

Task #1283. Five keys: **1 2 3 4** send that squad at whatever the game is currently
asking a squad for, and **CapsLock** sends the last one again with nothing on screen at
all. Everything below was read out of a live client through the Lua VM
(`tools/lib/lua_client.py`).

Every identifier in this file is invented. The shapes are real — a 19-digit uuid, a
six-digit tile index, a three-digit server — the digits are not (`CLAUDE.md`).

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
                              timeIndex, back, need, before}
DataCenter.__lw_macro_last = the same, as the last launch actually sent it
```

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
| the presses | `tools/lib/game_buttons.py`, `macro_arm` / `macro_launch` / `macro_repeat` |
| the Lua | `tools/lib/lua_actions.py`, `macro_*` |
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

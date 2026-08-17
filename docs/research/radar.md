# The radar («Радар») — the errand board, its four messages and its ceiling

Tasks #1414 (the wire, off a recording) and #1470 (the board itself, off a live client on
2026-08-17). **Every value in the examples below is invented and of the same shape as the
real one** — uuids, point indices, player names and alliance tags included.

The recording this started from is `results/traces/20260815_080129_радар_trace.log`; its
`results/traffic/…_traffic.jsonl` is empty (three lines — the sniffer dropped out), so
everything on the wire here was read out of the trace's `SFSNetwork.SendMessage` lines
and their `SFSObject.Put*` neighbours, and everything about the board was read out of the
live Lua VM afterwards.

## What the feature is

The radar hands out a board of small errands («detect events»). Each is a
`DetectEventInfo` with its own `uuid`, and they come in kinds — kill a Doom Legion camp,
gather a mine, pick up rubbish, rescue soldiers, run an errand for an alliancemate. An
errand ripens on its own clock; a ripe one pays out when it is claimed.

Three things a person does on the board, and only two of them are this ability:

| In game | What it really is |
|---|---|
| «Получить все» | one `receive.detect.event.reward` per finished errand — **not a command** |
| «Быстро выполнить» | one `detect.event.help.start` per eligible errand, then a finish each |
| «Перейти» | put the target on the map, then an ORDINARY MARCH — not part of this |

## The wire

Five messages, all of them `MsgDefines` entries the client already names:

```
get.detect.info                 {openWnd: bool}            DetectInfoGet
receive.detect.event.reward     {uuid: long}               DetectEventRewardReceive
detect.event.help.start         {uuid: long, eventType}    DetectEventHelpStart
detect.event.help.end           {uuid: long, eventType}    DetectEventHelpEnd
detect.event.put.point.in.world {uuid: long}               DetectEventPutPointInWorld
```

`get.detect.info` is sent as `SFSNetwork.SendMessage(MsgDefines.DetectInfoGet)` with **no
argument** — the message class writes `openWnd = true` into the payload itself. The flag
is the server's copy of «a window asked»; it does not open one, and passing it from Lua
would only be a second spelling of what the message already does.

There is more in `MsgDefines` than this ability uses — `reset.detect.event`,
`upgrade.detect.power`, `detect.event.claim.level.reward`,
`detect.event.batch.put.point.in.world`, and a long tail of the seasonal digs and
treasure activities that ride the same `detect.*` prefix. None of them is touched here.

### «Получить все» is a client-side loop

The recording shows `arrayV2.iterator` and then **eleven separate**
`receive.detect.event.reward` sends in a row, matching the red badge of 11. So claiming
all of them and claiming one of them are the same primitive, which is why the recipe
`xall`s it.

### «Быстро выполнить» is start, wait, finish — and the finish is the client's

Three `detect.event.help.start {uuid, eventType = 18}` went out at once. Right before each
one the client computes `Mathf.Min(3000, <distance> * 100)` — the two tile positions are
in the trace immediately above it, and their distance times a hundred is the second
argument — so **an errand takes at most three seconds**.

The finishes come later, and what fires them is visible: a `UISlider.SetValue` climbing
through `Mathf.Clamp01(0.97…)`, `0.983`, `0.99`, `0.9986` — the radar window's own
progress bar — and the instant it lands, all three `detect.event.help.end` are sent.

**That is a UI timer.** With the window closed nothing sends the finish, so a headless run
has to send it itself, or the errands sit half-done until somebody opens the board. That
is the one place this ability is not simply «reproduce the message».

## The board, in the client

`DataCenter.RadarCenterDataManager` — a module-scoped manager, which is why #1414 could
not name it off the trace. `DetectResultDataManager` (the candidate it guessed at) is the
scout-mail store and has nothing to do with the errands.

```lua
local M = DataCenter.RadarCenterDataManager
M:GetDetectEventCount()          -- errands on the board
M:GetFinishedDetectEventNum()    -- of them, ripe (this is the red badge)
M:GetMaxDetectNum()              -- NOT a ceiling: detectInfo.eventNum, see below
M:GetDetectEventInfoUuids()      -- the uuids, in no order
rawget(M, 'events')              -- uuid -> DetectEventInfo
rawget(M, 'detectInfo')          -- the board's own head, below
```

### `GetMaxDetectNum` is the day's ALLOWANCE, not a capacity

The name is a trap and it cost a wrong first cut of the recipe. Measured across three
runs an hour apart, claiming as it went:

| run | `GetDetectEventCount()` | `GetMaxDetectNum()` |
|---|---|---|
| 1 | 12 | 40 |
| 2 | 12 | 18 |
| 3 | 12 → 8 | 2 → 0 |

The board sat at twelve every time and only fell below it once the other number reached
zero. So `detectInfo.eventNum` is **how many errands the radar will still hand out**
before `nextRefreshTime` refills it, and the board's own holding capacity is not a number
the client exposes — twelve is what it was observed to be on this account.

The consequence for hoarding is the opposite of the obvious one: a hoard does not
overflow, it **blocks**. A board at its capacity has nowhere to put a new errand, the
allowance goes undrawn, and the refresh takes back what was never drawn.

`detectInfo`, as it reads live (shape, not values):

```jsonc
{"completeNum": 1234, "eventNum": 40, "level": 9, "nextRefreshTime": 1700000000000,
 "power": 20, "resetNum": 0, "rewardLevel": 9, "signal": 4,
 "specialOpsNum": 10, "specialOpsOrder": 0}
```

One errand, and every field it has:

```jsonc
{"uuid": 1000000000000001, "eventId": 24160, "pointId": 400500, "state": 1,
 "startTime": 1700000000000, "endTime": 1700028800000, "cost": 1, "isFrozen": false,
 "template": {"id": 24160, "type": 18, "type2": 1, "name": 140011, "quality": 1, …},
 "helpInfo": {"uid": 1000000000000002, "name": "Player1", "abbr": "AL1", "picVer": 1,
              "bUid": 100000000000000001, "headSkinId": 20000, "headSkinET": 0},
 "completeByHelper": {"uid": 1000000000000003, "name": "Player2", "abbr": "AL1", …},
 "rewardList": […], "originalData": {…}}
```

`helpInfo` names the alliancemate this errand is FOR; `completeByHelper` names the one who
finished it for you. An errand carries one or the other, never both.

### The two enums, verbatim

```lua
DetectEventState = {NOT_FINISH = 0, FINISHED = 1, REWARDED = 2, NOT_IN_WORLD = 3}
```

`GetFinishedDetectEventNum` counts `state == FINISHED`; `GetUnFinishedDetectEventNum`
counts everything not yet `REWARDED`, which is a different question from what its name
suggests and is **not** the complement of the first.

`DetectEventType` has forty-odd members. The four that matter here:

| Value | Name | What it needs |
|---|---|---|
| 18 | `HELPER` | nothing — start, three seconds, finish |
| 16 | `GATHER_RESOURCE` | a squad and a march |
| 11 | `RESCUE` | a squad and a march |
| 2 / 6 | `DetectEventTypeNormal` / `DetectEventPickGarbage` | a squad and a march |

The rest are the seasonal and activity kinds (`ZOMBIE_BUS_TRAIN`, `CAVE_EXPLORATION`,
`SPECIAL_OPS`, `TREASURE`, the off-season set, …) and are read but never acted on.

**`HELPER` is the whole of the marchless part**, and that is what the recipe does: an
errand of any other kind is a squad out of the base for ten minutes, which a recipe called
«do the radar» has no business spending without being asked.

### Claiming: the message, not the method

`RadarCenterDataManager:ClaimDetectEventRewardByEventData` is the WINDOW's version of the
press. Its constants say what it does before the send: asks `ResourceItemDataManager` /
`SoldierDataManager` whether the bag or the barracks would overflow, may raise a confirm
dialog for a rescue errand whose soldiers would not fit (`radar_army_01`), and queues a
fly-to animation through `RadarFakeUIMarchManager:AddClaimingTask`.

So the headless press sends `receive.detect.event.reward` directly. **The trade is
explicit**: the client-side «your barracks are full» warning is skipped, and a rescue
errand claimed with no room pays whatever the server decides to pay. The warning is advice
to a person, not a rule of the server.

## The duel day, and how the recipe decides which one today is

Claiming is what scores on the duel day the radar belongs to — Monday, on the week
`docs/game/daily_cycle.md` was written from — so a week's errands claimed on that one day
are worth far more than the same errands claimed as they ripen. Against that stands the
allowance above: a board sitting at its capacity blocks the day's supply, and the refresh
takes back what was never drawn. That pair is the whole of «не доводить до максимума
заданий» (#1051) and is the `claim` / `keep_free` pair of `actions/do_radar_tasks.md`.

**The weekday is read; WHICH weekday is given.** The recipe asks the client
`UITimeManager:GetInstance():GetTomorrowZero()`, steps back a day to the start of the one
now running, and takes its UTC weekday — 1 = Monday … 7 = Sunday. It is not the PC's:
the server's midnight is 02:00 UTC on this warzone, so a machine west of it spends hours
calling the game's Tuesday «Monday» and would hoard through the very day it meant to
spend. Live on 2026-08-17 the reading came back `1`.

### Negative finding: the client does not say which activity scores today

Searched for, on a live client, and not found — the same answer #1467 reached for the star
day, for the same reason.

| asked | answer |
|---|---|
| `AllianceCompeteDataManager:CheckIfAllianceCompeteOpen()` / `CheckIfIsInCompete()` | `true` — the duel is on and we are in it |
| `…:IsBattleDay()` / `IsSettleStage()` | `false` / `false` — the WEEK's phase, not the day's objectives |
| `…:GetExtraActivityList()` | `nil` with no argument; the per-day list arrives with the duel screen's own fetch |
| `…:HaveOpponent()` | a table of 2 — the two sides, no calendar |
| `alliance_duel_prompt_tips` | 6 rows of `id, priority, condition, desc, icon, jump` — condition-driven UI hints, not a plan |
| `TableName` matching duel/compete/vs | `al_duel_infinity_box_reward`, `al_duel_infinity_box_season`, `alliance_duel_prompt_tips`, `lw_champion_duel_*` — rewards, seasons and a different event |
| `GetDuelScoreManager.duelInfos` | `curScore` / `targetScoreList` / `scoreData` per score type — thresholds, no per-day objectives |

So `duel_day` is a fact about the player's season and warzone, given to the recipe, and
what is derived from the game is only the weekday it is compared against. Left at 0, the
plain `claim` decides; a weekday the client could not answer falls back to `claim` rather
than guessing «not today».

## Three live runs, 2026-08-17 (#1470)

All with the recipe's defaults (`claim = 1`), an hour or so apart, on the day the player
says is the radar's duel day.

| run | board before | ripe before | ally errands | allowance before | claims |
|---|---|---|---|---|---|
| 1 | 12 | 12 | 0 | 40 | **22** |
| 2 | 12 | 1 | 6 | 18 | **16** |
| 3 | 12 | 0 | 6 | 2 | **6** |

**44 errands claimed, 12 ally errands carried out**, and `completeNum` — the game's own
lifetime tally — moved 3784 → 3828, which is 44 exactly.

Run 1 is why `xall` re-reads rather than trusting the badge:

```
radar: 12 finished, 0 ally errand(s) ready to run
TAP Radar: claim one finished errand (12; 0 left)
TAP Radar: claim one finished errand (17; 0 left)
TAP Radar: claim one finished errand (20; 0 left)
TAP Radar: claim one finished errand (21; 0 left)
TAP Radar: claim one finished errand (22; 0 left)
TAP Radar: claim one finished errand xall -> 22 press(es)
```

Twenty-two out of a badge of twelve: the count came back HIGHER after each batch, because
the server ripens fresh errands as fast as the room is made. The loop stopped by itself at
zero.

Runs 2 and 3 are the proof of the `HELPER` path, which run 1 could not give — six pending
each time, and the board's ripe count went 1 → 7 across the three seconds:

```
radar: 0 finished, 6 ally errand(s) ready to run; the day will still hand out 2; game weekday 1
radar_help_started=6
radar_help_ended=6
… READ_LUA finished = 6
TAP Radar: claim one finished errand xall -> 6 press(es)
```

That exercises the part that was actually uncertain — the finish the client only sends
while its own window is open, here sent by the recipe with no window at all.

The wire agrees independently: the trigger ear logged `push.resource.item.update` during
run 1, so the rewards really landed.

### Run 4, and the limit it found

A fourth run, after the day's allowance had reached 0, met two `HELPER` errands and did not
finish them: `radar_help_started=2`, `radar_help_ended=2`, and the ripe count stayed at
zero. **A start/end pair is not always accepted.** What is different about those two, read
straight afterwards:

| | the six that finished | the two that did not |
|---|---|---|
| `state` | 0 → 1 | 0, and still 0 |
| `cost` | 1 | 0 |
| `detectInfo.eventNum` | 18 / 2 | 0 |
| `detectInfo.signal` | 4 | 1 |

`GetDetectHelpTypeCostNum()` returns 10, a constant, and `signal` fell 4 → 1 across the
day. So there is a per-day price on the help and the account had run out of it; `cost` on
the errand looks like «this one has been paid for» rather than a price of its own (in the
first read of the day, every already-helped errand carried `cost = 1`).

**Not turned into a gate**, deliberately: the correlation is one afternoon's, and a gate on
an unproven predicate silently skips work that would have gone through. What the recipe
does instead is SAY it — the closing line reports how many ally errands are still runnable,
so «started two and finished none» is visible rather than reported as success.

**Not exercised at all**: the hoarding branch (`claim = 0` / `duel_day` on a non-duel day),
which needs a different day rather than another run.

## What is NOT known

* **Whether an errand claimed while hoarding is the OLDEST one.** The recipe claims in
  `pairs` order, which is a Lua hash order and therefore arbitrary. It matters only in the
  hoarding branch, and only for which errand is spent to make room.
* **The board's own holding capacity.** Twelve, observed — no getter found that says so.
  `keep_free` is therefore expressed as «open this many places», measured against where the
  board stood when the hoard began, rather than against a capacity nobody can read.
* **`cost` and `signal`.** Every `HELPER` errand read live carried `cost = 1` and every
  other kind `cost = 0`. `detectInfo.signal` read 4 and later 1, so it is spent by
  something. `GetDetectHelpTypeCostNum` is a constant read off the manager. Whether the two
  are the same currency was not established and nothing here spends against them.
* **`GetCurEventNum()` returned 52 against a board of 12 and an allowance of 40,** and 8
  against a board of 8 and an allowance of 0. Its constants mention `GetMaxDetectNum`, so
  it is not a plain count. Unused.
* **`reset.detect.event`** — `IsCanReset()` was true and `GetResetNum()` was 0. Rerolling
  the board is a thing the game offers and this does not touch it.

## Where it lives

* `tools/lib/lua_actions.py` — the sends and the board's readings, one function each.
* `tools/lib/game_buttons.py` — `radar_read_board`, `radar_claim` (with `count_lua` and
  `batch_lua`), `radar_help_start`, `radar_help_end`.
* `src/lastwar_bot/actions/do_radar_tasks.md` — the ability.
* `panel/timers.py` — the schedulable row, and where `claim` / `keep_free` are set.
* `panel/tabs/checklist/model.py` — the row on «Чеклист» (in the group that is still off,
  #1275).

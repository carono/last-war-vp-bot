# Helping an alliancemate's secret task (`hero.dispatch.assist`)

How the alliance's own finished hero-dispatch tasks are helped headless, why it is **not**
the same feature as «Помочь всем», and the one thing that makes a correct-looking press
help nobody.

- Recipe: `src/lastwar_bot/actions/assist_secret_task.md`.
- Buttons: `tools/lib/game_buttons.py` (`assist_secret_task`,
  `refresh_alliance_secret_tasks`); the Lua is `tools/lib/lua_actions.py`
  (`secret_task_assists_left`, `secret_task_assist_refresh`, `secret_task_assist_rule`,
  `secret_task_assist_scan`, `secret_task_star_field`, `secret_task_assists_pending`,
  `assist_next_secret_task`, and the walk behind them all, `_ASSIST_SCAN`).
- Standing order: the «Секретки» tab's «Автопомощь» checkbox on the alliance page →
  `panel/tabs/secret_tasks/autoassist.py`.
- Read out of the live client with `string.dump` constant tables (the technique is
  written up in [`alliance-help.md`](alliance-help.md), «Reading a Lua function without
  its source»). Task #1272.

## It is a different feature from «Помочь всем»

The question that opened the task was exactly this one, and the answer is no. Three
things live near each other and only look alike:

| | «Помочь всем» | «Помочь» a secret task | «Украсть» a secret task |
|---|---|---|---|
| command | `al.help.all` | **`hero.dispatch.assist`** | `hero.dispatch.steal` |
| whose | any alliancemate's build/research queue | an alliancemate's finished task | a stranger's finished task |
| budget | unlimited (only the help POINTS cap) | **5 a day** (`aid_count`) | 5 a day (`steal_count`) |
| counter | `GetHelpNum()` (a red point) | `GetTodayAssistNum()` | `GetTodayStealNum()` |
| daily plan | «помочь союзникам» | **«помочь выполнить 5 секретных заданий ранга UR или Звезда»** | — |

`MsgDefines` carries both: `AlHelpAll = al.help.all` and `DispatchAssist =
hero.dispatch.assist`. They share no manager, no gate and no counter, and spending one
does not touch the other.

## The press

`UI.UIActivityCenterTable.Component.DispatchTask.DispatchTaskItem:OnGoClick`, its
constants in order:

```
SceneUtils | CheckCanGotoWorld | LuaEntry | Player | AtHomeNow | DataCenter |
ActDispatchTaskDataManager | IsCrossServerSwitchOpen | UIUtil | ShowTips | GetString |
500021 | IsInBlackRange | ShowMessage | TaskGotoWorld | GetTodayAssistNum | toInt |
GetDispatchSetting | aid_count | SFSNetwork | SendMessage | MsgDefines | DispatchAssist |
infos | uuid | targetServer | ShowTipsId
locals: self | isCrossServerSwitchOpen | mgr | todayAssistNum | assistMax
```

which reads back as: check the cross-server switch, then — with the day's budget still
open — send

```lua
SFSNetwork.SendMessage(MsgDefines.DispatchAssist, self.infos.uuid, self.infos.targetServer)
```

and otherwise raise a tip. **The message is two fields wide.**
`Net.Msgs.DispatchTask.DispatchAssistMessage:OnCreate` puts exactly `PutLong(uuid)` and
`PutInt(targetServer)` into the SFSObject, so the send needs no window, no marker tap and
no camera move — the same shape as the robbery next door.

The reply's handler says what a success does:

```
AlHelpAll-style: errorCode | UIUtil | ShowTipsId | reward | fromDispatchAssistMessage |
DataCenter | RewardManager | AddRewardsAndRes | ActDispatchTaskDataManager | ShowReward |
UpdateTodayNum | uuid | DeleteAllianceTasks
```

— pay the reward, bump `todayAssistNum`, and **drop the task from `allianceTask`**. A
refusal takes the `errorCode` branch and raises a tip instead; nothing else moves.

## The gate

Two halves, and both are readable client-side:

* **the budget** — `GetTodayAssistNum()` against `toInt(GetDispatchSetting("aid_count"))`.
  Live: `aid_count = 5`, and the whole five were spendable in one run.
* **the task** — finished and unrewarded. That is what
  `GetAllianceAssisTaskCount()` counts, confirmed by measuring both in one chunk: 200
  alliance tasks, 133 still running, **67 finished, and the method answered 67**. Its
  constants (`allianceTask | UITimeManager | GetInstance | GetServerTime | pairs |
  completionTime | rewarded`) say the same thing, and `DispatchTask:RefreshAlncRedPoint`
  draws the red point as `min(that count, aid_count - todayAssistNum)`.

The RANK is not part of the client's gate at all — any finished task may be helped. It is
part of what is WORTH helping, because the daily plan pays for «UR или Звезда». The
config row answers both (`v.cfg:getValue("color")` reaches 5 at UR, `is_special` draws the
star), which is the same source the raid list reads since #1267 — never the cfgId's
digits.

**Measured, because it decides the rule.** Of 200 live alliance tasks: **one** carried
`is_special = 1`, and 34 finished ones were `color = 5`. A star-only auto-help would fire
roughly never; «UR or ★» is the daily plan's own wording and the only version of the rule
that can spend five a day.

## The priority: a star first, and a ripening one holds a help back (#1292)

«UR or ★» says which tasks are worth a help. It does not say what to do when both are on
the table, and the first version got that wrong: the pick ranked tasks by `lvl*2+spec`,
so a level-7 UR beat a level-6 star, and the same measurement above says why that
matters — a star is one task in two hundred, and by the time the day's star matures the
five helps have gone on URs.

So the rule is an ORDER, not a filter:

1. **a ready star before any ready UR**, whatever their levels. Among stars the level
   still decides, and among URs too;
2. **a star still counting down RESERVES one help.** Five helps and two ripening stars
   spend three on URs now and keep two in hand. It is one help per star, not the whole
   budget — thirty-four unspent URs is the other way to waste the day;
3. **and the waiting has a floor.** A star is worth a held help only while it can be
   helped *today*: it has to finish before its own `actEndTime`, before the daily reset
   the counter rides on, and inside the operator's own `autoassist_star_wait_min`
   («Ожидание звезды», 240 min by default; 0 = as long as the first two allow). A star
   that fails any of the three is counted, **said out loud** and left — the help goes to
   a UR instead.

**The daily reset is 02:00 UTC**, and it is measured rather than assumed: 597 of 636
secret-task tiles in one capture shared an expiry of 01:59:59 UTC
([`protocol.md`](protocol.md), «Expiry is a daily reset»), and the treasure activity's
own `expire` fell on the same boundary ([`world-treasures.md`](world-treasures.md)). It
is what «до конца дня» has to mean for a counter that comes back once a day.

All of it is one walk over `allianceTask` (`lua_actions._ASSIST_SCAN`), which leaves
behind everything the three consumers need — the count `xall` re-reads between presses,
the task a press takes, and the numbers the recipe says out loud:

```
ACT assist_scan star_ready=0 ur_ready=34 star_pending=1 star_eta_min=90 star_lvl=7 star_late=0 left=5 hold=1
  LOG "waiting for star 7 (ready in 90 min) — holding 1 of 5 help(s) back"
  TAP Help a secret task (alliance) xall -> 4 press(es)
```

Four URs, one help kept, and a line saying which. The panel repeats the same reading —
«придерживаю помощь под звезду до 14:35 (★7)» on the tab and on the phone — because a
budget deliberately held back and an order that has died look identical from outside,
which is what #1227 was.

`hold` is `min(pending, left)` rather than the star count, and the whole priority block
sits inside the `ELSE` of the budget test. Both of those came out of the live run: a
spent day with two stars still running said «no assists left today» and then, three
lines later, «holding 2 of 0 help(s) back» — a choice described that was not being made.

`tests/test_assist_star_priority.py` runs the whole decision in a real Lua VM against a
stand-in dispatch manager: the priority, the reserve, and each of the three bounds on the
waiting. `tests/test_panel_autoassist.py` covers what the panel makes of it.

## The trap: the local list goes stale, and a stale send looks like no send

This cost two of the day's five before it was understood, and it is the reason the recipe
opens with a re-read.

The client's `allianceTask` is only corrected by pushes it has to be listening for and by
the alliance window's own query. A headless bot has neither, so its copy keeps tasks other
players have already helped with. Sending at one of those comes back as

```
UIUtil.ShowTipsId("dispatch_des028")
  ru: «Спасибо, но задача уже решена с помощью других лиц»
```

and **`todayAssistNum` does not move, the task stays in the list, and nothing else
changes** — from outside it is indistinguishable from a bot that pressed nothing. Two
attempts failed exactly that way (one on a finished task, one on a still-running one, so
the state of the task was not what was wrong).

The fix is one message: `GetAllAllianceTasksFromServer()` — `hero.dispatch.alliance.list`
— and then choose. Live, the assistable count dropped 72 → 42 on the re-read, and the very
next send landed.

```
before:  used = 0/5    assistable = 42
         --> hero.dispatch.assist  uuid=…  targetServer=…
after :  used = 1/5    the task is gone from allianceTask
```

The press ALSO drops its chosen task from the local list before sending
(`DeleteAllianceTasks`, which is what the success path does anyway). Without that, a
refusal would leave `xall` picking the same doomed uuid every round until the loop's cap,
because a refusal costs no budget and so changes no count.

## Acceptance

Live, task #1272, with one help already spent by hand:

```
> action: assist_secret_task
  TAP Re-read the alliance's secret tasks
  LUA local M=DataCenter.ActDispatchTaskDataManager M.__lw_assist_level=6
  READ_LUA helps_left = 4
  IF helps_left == 0 -> False
  TAP Help a secret task (alliance) (1; 4 available)
  TAP Help a secret task (alliance) (2; 3 available)
  TAP Help a secret task (alliance) (3; 2 available)
  TAP Help a secret task (alliance) (4; 1 available)
  TAP Help a secret task (alliance) xall -> 4 press(es)
< action: assist_secret_task OK

after: used = 5/5
```

Four presses, four helps, and `xall` stopped at the cap rather than on its iteration
limit — the count is re-read between presses, so the loop ends because the budget did.

## What is still open

* **What a help pays.** `RefreshShow` carries a `parsed_aid_extra_reward` /
  `aid_extra_reward_show` pair, so the item quotes an extra reward for helping, but the
  reward window's contents were not recorded on the run above. Nothing depends on it —
  the rule aims at rank and level, not at a payout — but it would make «сначала лучшие»
  provable rather than reasonable.
* **`GetAssistorName` reads a `fakeAssistorName` out of `dispatchtask_setting`.** The
  client evidently shows a stand-in helper somewhere; whether that is cosmetic or a
  second mechanism was not chased.
* **`IsCrossServerSwitchOpen`** was `true` throughout, so the `TaskGotoWorld` branch of
  `OnGoClick` — walking to the tile instead of sending — has never been exercised here.
  If an account ever reads `false`, expect the headless send to be refused and the game
  to want a march.

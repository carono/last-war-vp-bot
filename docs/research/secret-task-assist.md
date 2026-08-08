# Helping an alliancemate's secret task (`hero.dispatch.assist`)

How the alliance's own finished hero-dispatch tasks are helped headless, why it is **not**
the same feature as «Помочь всем», and the one thing that makes a correct-looking press
help nobody.

- Recipes: `src/lastwar_bot/actions/assist_secret_task.md` (the ordinary order) and
  `assist_star_sprint.md` (the last seconds of a star's countdown, #1294).
- Buttons: `tools/lib/game_buttons.py` (`assist_secret_task`,
  `refresh_alliance_secret_tasks`, `scan_secret_task_stars`, and the sprint's
  `arm_assist_sprint` / `assist_secret_task_sprint` / `finish_assist_sprint`); the Lua is
  `tools/lib/lua_actions.py` (`secret_task_assists_left`, `secret_task_assist_refresh`,
  `secret_task_assist_rule`, `secret_task_assist_scan`, `secret_task_star_field`,
  `secret_task_assists_pending`, `assist_next_secret_task`,
  `secret_task_assist_sprint_arm` / `_press` / `_pending` / `_verdict`, and the walk
  behind them all, `_ASSIST_SCAN`).
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

## The star sprint: being there in the second it matures (#1294)

The priority above holds a help back for a ripening star. Live acceptance of it measured
what was still missing:

> the day's only ripe star was gone from the alliance list in **under two minutes** —
> taken by alliancemates — and `star_ready` never read non-zero on a single poll.

The reserve had worked and the help was still not spent. A rule that waits for a star and
then arrives late loses twice: the star goes to somebody else *and* the URs it held the
budget from go unhelped as well. Помощь is not competitive in general — it pays the helper
and the owner both — but the STARS are, because everybody's daily plan wants the same rare
thing.

### The moment is known in advance, so nothing polls faster

`completionTime` is on the task. The five-minute poll therefore learns the exact instant a
star matures **hours ahead** — live, three level-7 stars announced themselves 78, 79 and
233 minutes out, to the millisecond. Nothing has to look more often to *discover*
readiness; the only problem is being awake for it.

So the scan parks the countdown in seconds as well as minutes (`__lw_star_eta_sec`), the
recipe says it out loud (`star countdown: <n> s to star <lvl>`), and the panel's standing
order **schedules**: it sleeps until a few seconds before the star is due, plays
`actions/assist_star_sprint.md`, and returns to the ordinary period. The poll interval is
untouched and no game read happens while the star ripens — the whole cost is one extra
wake-up per star.

### The sprint is the robbery's shape, aimed at a moment

`arm_assist_sprint` → `assist_secret_task_sprint xall` → `finish_assist_sprint`, which is
`steal_secret_task`'s loop with the target chosen by time rather than by a queue:

* the armed target is the ready star if there is one and otherwise the **nearest ripening
  one** — the recipe is played early on purpose, so at arming time the star usually has
  not finished yet. Never a UR: thirty-four of those sat unhelped in one live reading, and
  the ordinary recipe spends them at its own pace;
* the press **leaves its target armed** (the opposite of `assist_next_secret_task`, which
  drops its task so `xall` moves on), because pressing the same task again is the point;
* the loop stops on the SERVER: `todayAssistNum` moving, or a tip saying the task is gone.
  `dispatch_des028` — «уже решена с помощью других лиц» — *is* the lost race, so it is
  terminal; an unfamiliar tip leaves the loop pressing, exactly as the robbery's list
  rules;
* a window (default 20 s) bounds the case the clock cannot: a star that never matures
  because its owner cancelled the task.

**The lead has to cover the recipe's own preamble.** Measured live: from `run_action` to
the target being armed is **3.5–4.7 s** — the mandatory re-read of the alliance list is
most of it — so the arming was moved to sit directly after the scan, ahead of the six
`READ_LUA`s the log lines need, and `autoassist_sprint_lead_sec` defaults to **10**. A
lead of three would have the first press land *after* the star matured, which is the
original failure with extra steps.

**Pressing before the star matures is free**, on the evidence already in this file:
`HandleMessage` takes the `errorCode` branch on a refusal, and `todayAssistNum` reaches
the client only on the success branch, out of the server's own reply. An early press
therefore spends nothing — the same guarantee `steal_secret_task` leans on.

The verdict line is the measurement: `ACT assist_sprint_done how=<taken|gone|unanswered>
lvl=<n> presses=<n> tip=<id>`, and the panel keeps a session tally («спринты: взято 1 /
упущено 0, нажатий 4») on the tab and on the phone.

### The listener was checked on the wire, and there is nothing to listen to

`MsgDefines` does carry a push family for hero dispatch — `push.hero.dispatch.task.patch`
(`PushDispatchOneTask`), `…task.full`, `…task.del`, `…task.add.follow.count`, beside the
`push.hero.dispatch.mission.steal` already known. It looks exactly like the readiness
event this feature would want.

It is not. `SFSNetwork.HandleMessage` was wrapped with a counter and watched on a live,
logged-in client with 160 alliance tasks running:

```
45 minutes, ~3000 messages, 34 distinct commands
hero.dispatch pushes: 0
hero.dispatch seen at all: only the REPLY to our own `alliance.list`, 3 of them
alliance task count:  160 -> 170 -> 199, and it moved only on those three re-reads
```

Nothing in the push family arrived, and the local `allianceTask` table did not change
except when it was asked to — which is the same finding as «the list goes stale» below,
seen from the other side. The pushes evidently concern the account's OWN dispatches, not
the alliance's list. `tools/known_commands.txt`, built from captures, says the same: the
only observed `hero.dispatch` push is `mission.steal`.

**So a listener would not have helped, and the schedule does not need one.** Recorded here
so the next person does not spend an afternoon re-hooking the same function.

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

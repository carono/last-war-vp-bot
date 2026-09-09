# «Гонка вооружений» — the calendar, the phases and what pays points

The event the game calls *Arms Race*: six four-hour phases a day, each naming ONE kind
of progress and paying points for it. Three chests per phase at three point totals, and
three more for the DAY at one, two and three phases finished.

Everything below was read off the live client. What is written down is the SHAPE — the
manager, the message, the field names, the ids — never one account's numbers.

## The manager

    DataCenter.ActivityPersonalArmsDataManager

Two ids travel with it: the activity itself (`29` on the account this was read from) and
a `heroActivityId` (`28`). **Neither is written down in the code.** The panel finds the
activity by looking for the one entry of `dataDict` that carries an `event_id`, because
an id that is 29 here has no promise of being 29 on another server or another season.

### `dataDict[<activity>]` — the phase running NOW

Arrives unasked and is kept up to date by the server. What the panel reads off it:

| field | meaning |
|---|---|
| `event_id` | which of the five kinds this phase is (below) |
| `curDay` | which day of the event's week, `1..7` |
| `curStage` | which of the day's six phases, **zero-based** — the same numbering `claimStatus` keys use |
| `stage_end_time` | server seconds at which the phase ends |
| `sc` | points scored in THIS phase |
| `scoresList` | the ids of the `score` rules in force this phase |
| `score_rewards[1..3]` | `{target, receive}` — the three chests of the phase |
| `day_rewards[1..3]` | `{target, receive}` — the three chests of the day |
| `claimStatus` | keyed `<day>_<stage>`, non-zero once that phase counts as finished |

`sc` is the SERVER's count, which is why the panel never keeps one of its own: points
made from the phone, or by the person playing, are in it already.

### The calendar is EMPTY until you ask

`calenderDataDict` starts `{}` on a panel-driven client and **nothing fills it by
itself**. One message does:

    SFSNetwork.SendMessage(MsgDefines.ActivityHeroCalender)     -- activity.hero.calender

It is the game's own get — the one the client fires when a person opens the event's
calendar — and it fills

    calenderDataDict[<activity>].dayArr[1..7].eventArr[1..6] = {eventId, name, startTime, endTime}

A whole week, six phases a day, with the server's own start and end seconds. **So the
schedule is known exactly and there is nothing to poll**: an alarm is set on the border
of the next phase, and the border is a number the server already gave.

This is the easy gap to miss. The CURRENT phase's numbers arrive unasked, so a panel
that never sent the get looks entirely reasonable — it draws one phase and «what comes
next is unknown» over an event whose whole week is already decided.

Beside it there is a push: **`push.person.arms.sc.change`** — a score that moved
announces itself. Nothing about this event needs a clock.

## The five kinds of phase

| `eventId` | the game's name |
|---|---|
| `120000` | «Улучшение героя» |
| `120001` | «Строительство Города» |
| `120002` | «Прогресс юнита» |
| `120003` | «Исследование технологий» |
| `120004` | «Улучшение Дрона» |

A day draws six phases out of those five, so one kind repeats; which one, and in what
order, is the calendar's business and differs by day.

`hero_activity.cycle = 240` minutes is the phase length in the client's own config —
read rather than assumed, and never used in place of the calendar's own `startTime` /
`endTime`.

## What pays points

`scoresList` names rows of the client's `score` table, and the row says what the deed is
worth. They are read LIVE every round rather than written down here: a phase whose
numbers moved would otherwise be ground at with last week's arithmetic. What one live
hero phase carried, as an example of the shape:

| rule | deed | points |
|---|---|---|
| `122` | one hero recruit | 400 |
| `121` | spending at least 2 000 hero XP at once | 1 |
| `103` | buying a diamond bundle | 30 |

With a top chest at 12 000, thirty recruits is that chest exactly — which is the
arithmetic the recipe does at run time off `score_rewards` and the `score` row, not off
these numbers.

**Only the CURRENT phase's rules arrive.** There is no way to ask what the phase after
next will pay; the client learns it when the phase starts. That costs nothing, because
what a phase of a given KIND wants is the kind's own business and is known from the
config.

## The drone phase is paid for in STAMINA, and the stamina is not its own

The person's words for `120004`: **«Час дрона, 300 энергии, это стамина, тратим только
стягами»** — the phase's points come from raising rallies, each rally costs stamina, and
one run may spend 300 of it.

Two things about that are worth writing down, because both are easy to get wrong.

**«Энергия» here IS the stamina, and it is the SAME purse the golden-zombie hunt
spends.** `LuaEntry.Player.stamina` is what both read; the hunt merely calls it `energy`
on its card (`actions/read_golden_zombies.md`). So the two abilities compete for one
bar: a drone phase told it may spend 300 leaves that much less for zombies, and a hunt
that ran first can leave the phase with nothing. Neither knows about the other, and
nothing in the panel shares the bar out — that is a decision for the person, not for an
agent.

**The price of a rally is ASKED, never written down.**
`MarchUtil.GetCostStaminaByTargetType(MarchTargetType.RALLY_FOR_BOSS)` — the same call
the hunt makes for `ATTACK_MONSTER`, which answers 10. The rally figure has **not been
read live yet**, and the recipe refuses to loop if the build answers 0: a ceiling of
«300 stamina» over a spend the game prices at nothing is a ceiling that cannot bite, and
a run that discovered that by looping would be a run raising unbounded banners.

**And it has NO rally allowance at all — the join caps are not its ceiling (#2574).**
It spent out of the elite group's daily cap until then, and that was wrong twice over.
The per-kind numbers in `panel/rally_limits.py` are a budget for JOINING somebody else's
banner (the «rally_auto_join» trigger, counted per join); this phase RAISES banners, the
account creates the march itself, the game charges it in stamina and caps it nowhere.
The person's words: «Автостяги с дроном никак не связаны, на стяги, что мы создаем
лимитов нет». Measured cost of the mistake: on 2026-09-05 at 14:01 UTC a drone run
halted with «no rally allowance was handed over» while the account had stamina, a free
squad and an unscored chest — refused by a ceiling that was never about it, and the
same book was being emptied by auto-join at up to 14 banners in three minutes. The
recipe's ceilings are the stamina, the top chest and the squad.

## The game keeps NO history of a phase, and that is why the panel books one (#2579)

Asked of the live client, so it is measured rather than assumed. `dataDict` carries:

* `score_rewards[1..3]` — the CURRENT phase's three boxes, each with the server's own
  `receive` flag;
* `day_rewards[1..3]` — the day's own ladder, the same way;
* `claimStatus`, keyed `<day>_<stage>` — and its value is a **flag**, not a count. Read
  live mid-afternoon on day 7 it was `{7_0: 1, 7_1: 1, 7_2: 1, 7_3: 1, 7_4: 0, 7_5: 0}`:
  one per phase already finished, zero for the two still to come.

Nothing else per phase exists. `M.rewards` and `M.scoreGroupDict` are empty on a
panel-driven client, the calendar rows carry only the kind and the two borders, and a
phase that has ended is simply gone. **So «сколько сундуков собрано в каждом часе»
cannot be asked — it can only have been WRITTEN DOWN while each phase was the current
one**, which is `panel/runtime/arms_book.py`: every arms reading that lands (the
four-hourly errand's and the person's own «Обновить») is one entry, and no question is
asked to fill it. A phase nobody read while it ran is a dash on the card, never a zero.

The day is the SERVER's, keyed by `game_day.day_key` exactly as the rally counts are, so
a book from yesterday answers «nothing today».

## The drone phase is worked to its END, and the wake-up is the march's own clock (#2574)

Measured on the live account, seven consecutive drone phases: **seven runs, one per
phase, and four of the seven raised nothing at all.** The person's report — «1 или 2
стяга за 4 часа события» — is what that looks like from the game.

The cause is two rules meeting. `arms_race_drone` stopped as soon as the squad was
not free, and the squad is not free from the moment the first banner goes out; and
`perform_arms_race` books its next turn on the PHASE BORDER, because that is the right
answer for the five phases whose work is done in one pass. So the phase raised one
banner in its first minute and slept for four hours.

What changed:

* the run no longer stops when the squad is out. It says WHICH gate refused — the gate
  answers a word now, not a boolean. It USED to leave in `next_run_in` the seconds to the
  nearest march this account had out (`WorldMarchDataManager:GetOwnerMarches()`, each
  march's own `endTime`) plus 30 s; **#2661 removed that booking entirely** — the return
  is an event the wire announces, and one clock read per run only ever books the first of
  them;
* **and the hour is worked PER SQUAD since #2661.** The gate used to be asked about one
  squad named in the order, so the next fire found it in the air and failed the whole run
  — «the squad screen would not take squad 4», measured on 2026-09-09 with three squads
  standing idle at the base. `ARGS squads` is the set the order may spend and the gate
  hands back the lowest FREE one; a busy squad is skipped, never a refusal;
* the **stamina ceiling became the PHASE's** rather than one run's. A per-run 300 over
  however many runs a phase now has is not a ceiling; the purse is parked in the VM
  against the phase's own `stage_end_time`, so a new phase resets it and a second run
  inside one finds what the first spent;
* the chests are claimed after every round, not only at the start of the next run;
* and the banners the phase raised are remembered between its runs by the panel
  (`Schedule.register_report` → `panel/tabs/events/tab.py::arms_report`), which is what
  «Стягов за окно» draws. They are NOT written into the join book: that book counts
  joins, and a raise is not a join (#2574).

**That clock is gone since #2661, and the wire trigger it declined is what replaced it.**
The person's decision, in their words: «Какой нахуй повтор через 10 минут, у тебя есть
пуши, отправили стяг, ждем пока закончим и вернемся на базу, и сразу снова отправляем
тех, кто пришел на базу». The objection above was right about the COST and wrong about
the outcome: a clock read once per run books ONE return, so a phase whose squads come
home four times hears about the first and sleeps through the rest — measured, one or two
banners per four-hour hour.

So `arms_drone_relay` (`panel/triggers.py`) subscribes to `push.world.march.del` and
plays `arms_race_drone` on every one, `immediate=True`. The «not only ours» problem is
paid for on the far side rather than avoided: the recipe's FIRST statement is one Lua read
of which arms-race phase is running, and anything that is not the drone hour stops on it,
before the calendar get inside `read_arms_race` is sent. One VM round trip (~0.15 s) is
the whole price of a foreign march ending, and only during a drone hour does a fire go any
further.

The errand keeps its turn on the phase border, and that is now the SAFETY NET: a profile
whose wire ear is down still works the hour, only slowly.

## The rules arrive for the current phase only — so judge by the score MOVING

There is no way to ask what the phase after next will pay, and what paid yesterday is
worthless. So `arms_race_drone.md` carries no rule id at all: it reads `sc` before a
banner and again after it, and stops on the spot when the number did not move. That is a
check the game itself answers and it survives the rules changing under it.

## What the panel does with it

* `actions/read_arms_race.md` — sends the calendar get, then reads the phase running now
  (`arms`) and the whole day (`arms_day`). Presses nothing, spends nothing.
* `actions/perform_arms_race.md` — the errand. Reads the phase, plays whichever recipe
  that kind has, and leaves the seconds to the next border in `next_run_in`, so the
  schedule books the turn ON the border rather than grinding a period against an event
  that changes five times a day.
* `actions/arms_race_hero.md` — the `120000` phase: recruit in the tavern up to the
  phase's top chest or the allowance the person gave, whichever comes first, and never
  in diamonds.
* `actions/arms_race_drone.md` — the `120004` phase: raise rallies up to the stamina
  ceiling, the phase's top chest, or the squad coming off the board, whichever comes
  first. No join allowance is asked for or spent.

## An empty purse pauses a banner, it does not end the hour (#2664)

#2661 taught the hour to take the day's FREE energy before calling the purse empty, and
stopped there — «buying is the person's press, not a trigger's». The person ended that
reading in their own words: «Правила на энергию мы писали, берем бесплатное если есть,
покупаем за 300 алмазов, остальное берем из сумки». The order was already settled (#2390)
and already written down; what was missing was the drone hour walking it.

So `arms_race_drone` plays `actions/top_up_march_energy.md` — free, then the 300-diamond
refill, then the bag — in two places: before its first banner, and inside its loop when the
gate has just refused. `ARGS energy_top_up = 1` switches the whole ladder off.

Two things are deliberate:

* **the diamonds are only spent when the purse is the ONLY refusal.** The reading above the
  ladder repeats the gate's other tests — the phase is still 120004, its ceiling is not
  spent, a chest is still owing, a squad is free — so a phase that would raise nothing buys
  nothing. A purchase cannot be undone; a reading costs one round trip;
* **the price is named before it is paid.** `buy_stamina_refill` buys only while the game
  says no refill has been bought today (the cheap one by the person's ladder 300 / 500 /
  1000), prices the purchase off the diamond purse afterwards, logs what it cost, and
  blocks itself for good if that came out above `cap` = 300. Clearing the block is
  `python -m panel.forget stamina_refill_block`.

## The other three phases: the ceilings, and what the client would not give up

The person's ceilings, in their own words and settled: **«На стройку и науку нужно 3000
минут для выполнения часа, юнитов просто ускоряем, чтобы освободить очередь»**, plus
level **9** for the training and «собирай сразу» for the chests.

### What was measured, and can be relied on

**Training pays 28 points for one level-9 soldier.** `SoldierDataManager:GetSoldierIdByLevel(9)`
is `3013`, and the `score` row for it is id `1121`, `type = 4`, `group = 114`, `points = 28`.
The same group holds the ladder for the lower levels — 3005…3011 pay 5, 6, 7, 13, 15, 19,
22 — and 28 on the ninth continues it, which is what makes the row trustworthy rather
than a lookalike. **12 000 ÷ 28 = 429 soldiers** for the top chest, and that is the
number a ceiling should be, not a guess about «максимум».

**The phase's own rules are the only mapping, and they arrive only while it runs.** The
`score` table is 1475 rows and **nothing in it names an event**: a full scan for
`120001`, `120002` and `120003` across `gopara`, `name`, `tips` and `group` returns zero
rows each. Rules were found for the hero phase (`type 42`, 400 for one hire; `type 87`,
1 for 2 000 hero XP; `type 20`, 30 for a diamond bundle) only because that phase was
running and had handed its `scoresList` over. So the rate for a speed-up phase cannot be
derived offline, and a recipe must read it at the moment the phase opens.

### The surface each phase will need

| what | where |
|---|---|
| build queues | `DataCenter.BuildQueueManager` — `GetAllQueue`, `GetMinRemainTimeQueue`, `GetQueueDataByBuildUuid`, `IsQueueTimeFinish`, `IsAnyQueueFree` |
| a queue's job | `DataCenter.BuildManager` — `GetBuildQueueByUuid(occupyUuid)`, `GetBuildQueueState`; the queue ROW carries no remaining time |
| research | `DataCenter.ScienceDataManager` — `GetAllScienceOnlyRead` (312 rows), `GetScienceById`; plus `ScienceManager` |
| soldiers | `DataCenter.SoldierDataManager` — `GetSoldierIdByLevel`, `GetCanTrainHighestLevelSoldier`, `GetInsideSoldiers`, `GetAllSoldiers`; the yard is `CityArmyYardManager` |
| speed-ups | `DataCenter.ItemData:GetSpeedItem()` — three kinds on the account read, all `type = 2`, `type2 = 1` |
| the chests | `MsgDefines.ActivityHeroScoreReward = activity.hero.score.reward`, `ActivityHeroDayReward = activity.hero.day.reward` |

The box rows themselves are already readable and say what a claim has to name:
`score_rewards[i] = {index, receive, target, value}` and
`day_rewards[i] = {index, receive, resourceItemId, resourceNum}` — `index` is ZERO-based
and `receive` is 1 once taken.

### What did NOT work, so nobody repeats it

* **`ScoreRewardGet` / `DailyRewardGet` are not the senders.** `debug.getlocal` over them
  gives `(self, message)` — they are the reply handlers. The send is a
  `SFSNetwork.SendMessage(MsgDefines.ActivityHero…Reward, …)` made from the window.
* **The message classes are not in `_G`.** Searching for `HeroScoreReward`,
  `HeroDayReward` and `ActivityHero` among the globals returns nothing; they are required
  modules, so the field list cannot be read the way `AlHelpAllMessage`'s was.
* **And `string.dump` is closed** (since 2026-08, silently inside a `pcall`), so the
  constant-dump trick that answered the alliance help is gone. The remaining routes are
  the UI class while its window is open, or a capture of the outgoing frame.
* **The item template is thin.** `ItemTemplateManager:GetItemTemplate(200200)` carries
  `id`, `type`, `type2` and nothing else — how many MINUTES a speed-up is worth is not
  there, and «профильное или универсальное» is not `type2` either (all three kinds on the
  account read `type2 = 1`).

`debug.getlocal` on a method DOES work and is the cheap way to get a signature —
`GetScoreBoxState(self, data, index)`, `GetCurData(self, activityId)`,
`IsAllBoxRewardReceivedByType(self, activityType)` all came from it.

## What a minute of speed-up is worth — the client says so, and it says it offline

The section above is right that the `score` table names no event, and that a phase hands
its own rules over only while it runs. It was wrong to conclude from that that **nothing**
about the rate is knowable in advance. A different table, a plain global, holds it:

```
SpeedScoreValue            = { Build = 7, Science = 6, Soldier = 4, Heal = 9 }
ItemSpdMenu2SpeedScoreValue = { [3] = 4, [4] = 9, [6] = 6, [7] = 7 }
SpeedUpItemId              = 200103
```

`SpeedScoreValue` is points per **minute** of speed-up spent, by what the minutes were
spent on, and `ItemSpdMenu2SpeedScoreValue` is the same four numbers keyed by the tab of
the speed-up bag — so menu 3 is soldiers, 4 healing, 6 research, 7 building. Read against
the 12 000 of the top chest that gives the minutes each phase actually needs:

| phase | per minute | minutes for 12 000 |
|---|---|---|
| 120001 building | 7 | 1 715 |
| 120003 research | 6 | 2 000 |
| 120002 units, by speeding a queue | 4 | 3 000 |

Which is worth reading beside the ceiling the person named — «на стройку и науку нужно
3000 минут» — because 3 000 is the number for SOLDIERS at 4 a minute, and building and
research reach the same chest on rather less. The ceiling is not wrong; it is simply
above what the top box costs, and a recipe that stops at the box stops first.

**None of that removes the reading.** The rate is a client constant and the phase's own
rules are the server's; a run still checks that the score MOVED, exactly as the drone
recipe does, because a constant that used to be true is the classic way to spend an
account's items for nothing.

### A phase names its own rules, in a field beside the score

The live row carries `scores` — the ids of the `score` rows this phase pays by, packed
into one string with `|`:

```
event_id=120000  sc=<points>  curDay=<n>  curStage=1  activityId=<n>
score_reward_max=12000  day_rewards_max=18  scores=<id>|<id>|<id>
minLevelStage=31  maxLevelStage=35  stage_end_time=<epoch>
```

So «what does this phase pay for» is two reads and no capture: `scores` for the ids, the
`score` table for the rows. Checked against the hero phase, the three it named came back
as exactly the rules the section above had to wait for a running phase to learn — `type
42` 400 for one hire, `type 87` 1 per 2 000 hero XP, `type 20` 30 for a diamond bundle.

**The config does NOT hand the same thing over in advance.** `hero_event` holds a row per
phase (`120000`…`120004`) with its name key and a handful of unnamed integer columns —
the table arrives without metadata, so the columns have numbers instead of names — and
none of them is the rule list the server sends. `hero_activity` is the day plan: 28 rows,
`cycle = 240` minutes (which is where the four-hour phase comes from), `day`, the day
rewards and the rank ladder, over the `100000…100004` series rather than this one.
Neither answers «what pays what» for a phase that is not running.

## `require` still opens a UI class, and it is the way past a closed `string.dump`

A window's Lua is a module, and `require` loads it **without opening the window**. The
paths follow a convention worth writing down, because guessing it wrongly reads as «not
found» and looks like the class does not exist:

```
UI.<Window>.View.<Window>View          -- the widgets, the listeners, and the SEND
UI.<Window>.Controller.<Window>Ctrl    -- (also seen as UI.<Window>.Ctrl.<Window>Ctrl)
```

`require('UI.UISpeed.View.UISpeedView')` returns 75 functions, and `debug.getlocal` names
their arguments even though `string.dump` is closed:

| what | signature |
|---|---|
| the send | `SendMsg(self)` |
| one speed-up chosen | `GetOneSpeedUp(self, list)` · `GetSpeedItem(self)` |
| what a set of items is worth | `GetSpeedUpTime(self, speedItemList, time)` |
| spending it | `ConfirmUse(self, id, item, time)` · `UseAddItem(self, itemId, count)` |
| the client's own log line | `AppendUseItemActionLog(self, itemId, count, approachStr)` |

**And that is where it stops.** Every one of them takes `self` — the open window, its
list, its slider, its target queue — so none is callable from a recipe, and `SendMsg`
builds its message out of that `self`. The names settle WHICH message it is (`item.use`),
not what rides on it.

`Util.LWResourceLackUtil.GetSpeedUpGoods(self, endTime, speedType, itemList)` is the
game's own chooser — which speed-ups to spend for a given end time and kind — and is the
place to look when «профильные раньше универсальных» has to be reproduced rather than
re-invented.

### The message names, settled

| what | `MsgDefines` |
|---|---|
| spend a speed-up | `ItemUse = item.use` (and `PushItemUse = push.item.use`) |
| start a training batch | `BuildingCampTraining = building.camp.training` |
| start a research | `ScienceResearchNew = science.research.new` |
| the free five minutes | `FreeSpeedQueue = free.speed.queue` |
| the two chests | `ActivityHeroScoreReward` · `ActivityHeroDayReward` |

Two senders that ARE reachable from a recipe, for completeness:
`DataCenter.ArmyManager.ArmyManager:SendSpeedFinishQueue(qUuid)` and
`DataCenter.QueueData.QueueDataManager:AllianceHelpAddSpeed(uuid, endTime, startT)`.
Neither spends an item.

## The four sends, settled — and the route that settled three of them without a press

The section below was right that `SendMsg` builds its packet out of an open window and
that `string.dump` is closed. It was wrong to conclude that the packets therefore could
only be HEARD. **The message classes are loaded modules**, not globals, and `require`
reaches them exactly as it reaches a window's view:

```
package.loaded['Net.Msgs.BuildCcdMNewMessage']
package.loaded['Net.Msgs.QueueCcdMNewMessage']
package.loaded['Net.Msgs.BuildingCampTrainingMessage']
```

`debug.getlocal` over each class's `OnCreate` names its arguments, and where an argument
is a TABLE the field names come out of a proxy — a table whose `__index` records the key
and answers `nil`, handed to `OnCreate` on a message that is built in memory and never
sent:

| what | `MsgDefines` | the call |
|---|---|---|
| speed up a BUILD queue | `BuildCcdMNew = build.ccd.m.new` | `(param, golloesSpeedTime)`, `param = {bUUID, isFixRuins, itemIDs, useGold}` |
| speed up ANY OTHER queue | `QueueCcdMNew = queue.ccd.m.new` | `(param, golloesFreeTime)`, `param = {qUUID, itemIDs, useGold}` |
| start a training batch | `BuildingCampTraining = building.camp.training` | `(uuid, type, sLevel, sNum, fromLevel, itemIds, goldForTime)` |
| a chest | `ActivityHeroScoreReward` · `ActivityHeroDayReward` | `(activityId, index)` |

`itemIDs` is the game's own **`"<itemId>;<count>"`** string, `useGold` is `false` and the
gold-for-time argument is `0` on every send this repository makes — a phase that could
only be finished with diamonds is a phase the recipes leave unfinished.

**A build queue names the BUILDING it occupies, every other queue names ITSELF.** That is
the whole difference between the two messages: `bUUID` is the queue row's `itemId`,
`qUUID` is the queue row's `uuid`. Getting it the wrong way round is a send the server
drops in silence.

The heard press that confirmed the first and the fourth, painted by the ear:

```
build.ccd.m.new({bUUID=<a building uuid> isFixRuins=false itemIDs=200211;11}, 0)
activity.hero.score.reward(29, -1)
```

`ItemUse = item.use` is a real message and is NOT the queue speed-up — that was the
guess this route replaced.

### The queues, and what a `type` means

`DataCenter.QueueDataManager:GetAllQueue()` hands over every queue in one list; the build
ones are also in `DataCenter.BuildQueueManager`. A row carries `uuid`, `type`, `state`
(2 = running), `startTime`, `endTime` in **milliseconds**, and `itemId` — the building
uuid for a build queue, the science id for a research one.

`NewQueueType` names the numbers: `Default = 0` (building), `Science = 6`,
`Hospital = 3`, `CarSoldier = 1`, `FootSoldier = 8`, `BowSoldier = 9`, `ArmyUpgrade = 34`,
and a long tail of barns, missiles and hospitals. Healing is deliberately not a kind any
arms-race recipe touches.

### The bag says what a speed-up is WORTH, and the item template does not

`DataCenter.ItemData:GetSpeedItem()` returns the universal ones only.
`GetItemsByType(2)` returns them all, and each row carries what matters:

* `speedUpType` — **the same key as `ItemSpdMenu2SpeedScoreValue`**: 1 universal,
  7 building, 6 research, 3 soldiers, 4 healing.
* `para3` — the item's worth in **SECONDS** (60, 300, 900, 3600).
* `count` — how many are held.

So «профильные раньше универсальных» is a sort on `speedUpType`, and «сколько минут
осталось до коробки» is arithmetic over `para3` — neither needs the item template, which
carries `id`, `type`, `type2` and nothing else.

### What looked like it was missing, and was not

`building.camp.training` was written down here as unknowable without a press by hand, on
the grounds that its `type` «is an arm, most likely a `NewQueueType`». It is 0, the send
goes out positionally, and a probe run had already made it work — see «the training send
is settled» below. The lesson is worth keeping: the argument NAMES came out of the class
and the guess about their VALUES came out of nowhere, and the log of what this repository
had already sent answered in one line what the guess could not.

## The ear: what it answered, and why nothing is waiting on it any more

`SFSNetwork.SendMessage` is wrapped by a recorder that keeps the command and its
arguments for anything naming a speed-up, a training batch, a research or an arms-race
chest, and sends nothing itself. **It is not a permanent fixture**: the wrapper keeps the
original in a closure and `getupvalue` is closed, so the only way to take it off is to
restart the client — which every client restart does for free, and which is why a session
that needs the ear arms it again rather than assuming it is still there.

Three of the four shapes never needed it in the end (the message classes are loaded
modules — see above), and the chest send was heard on the one press that was made:

```
build.ccd.m.new({bUUID=<a building uuid> isFixRuins=false itemIDs=<id>;<count>}, 0)
activity.hero.score.reward(29, -1)
```

**And the training send is settled too — it had already been sent by a probe run before
anybody wrote down that it could not be.** `building.camp.training` goes out POSITIONALLY,
the way its `OnCreate` names its arguments, and only the first four are needed:

```
SFSNetwork.SendMessage(MsgDefines.BuildingCampTraining, <barracks uuid>, 0, <soldier level>, <how many>)
```

`type` is **0** — not a `NewQueueType` after all, which is what «most likely» would have
guessed wrong. `fromLevel`, `itemIds` and `goldForTime` are left off entirely: a fresh
batch promotes nothing, spends no speed-up item and never touches gold.

The two neighbours of that send are as plain:

| what | the call |
|---|---|
| take a finished batch | `BuildingCampCollect(<barracks uuid>)` |
| speed a batch up | `BuildingCampAccel(<barracks uuid>, "<itemId>;<count>", false)` |

**All three are proven live now**, the accel last, on a test account: one five-minute
soldier speed-up (`"<itemId>;1"`) sent to a barracks with 9 026 s left took it to 8 722 s
— **exactly 300 s of it, four of which were the clock** — and the bag went 51 → 50 of that
piece. The batch itself was untouched (`productBase` unchanged), which is the point: the
send buys TIME, not soldiers. So the argument the class calls `itemId` is the same
`"<id>;<count>"` string the queue speed-ups take, and `useGold` false keeps it off
diamonds.

`actions/arms_race_units.md` still reads what the barracks had left before and after and
says how much the send moved. Not because the shape is in doubt any more, but because a
run that believed a refused send would train into a barracks that is still busy — and the
measurement costs one reading.

A barracks is `itemId == 10103000` in `DataCenter.BuildManager`. `productBase` is the size
of the batch it is running — and the size the game has already accepted for it, which is
what the recipe asks for again rather than calculating one — and `productEndTime` is when
that batch is done, in milliseconds. A barracks with a FINISHED batch still counts as
occupied: it has to be collected before it will take another.

## The exchange of hours: what it costs, how it is sent, and which way it points

Measured on a test account, one exchange spent (there is one a day):

* **The sender is the manager's own**, and the raw message is not worth building by hand:
  `DataCenter.ActivityPersonalArmsDataManager:SendExchange(aid, fromIndex, fromStage,
  toIndex, toStage)`. A hand-built `activity.hero.exchange` table went out «ok» and did
  nothing — the class's `OnCreate(param)` reads the table its own way and the proxy
  trick lists no keys for it, so the manager's method is the only reliable route.
  Alongside it: `GetLeftExchangeTimes(actId)`, `IsExchangeFuncOpen(actId)`,
  `NeedExchangeConfirmMessage(aid)` / `SetExchangeConfirmed()`, and `OnExchange(res)` —
  which is where a reply would land, and which was **never called** for any of the sends.
* **The free one costs nothing.** The event record carries `resourceItemId = 9003` and
  `resourceItemNum = 6`, and the account that made the exchange holds **none** of that
  item by any getter — so those two fields price a FURTHER exchange, not the day's free
  one.
* **Nothing happens when you press it.** The counter stayed `used=0 left=1` and the
  running phase stayed what it was for twenty minutes; both moved **at the next phase
  border** — `used=1 left=0`, and a fresh four-hour window.
* **And the direction is the opposite of the obvious one.** Sent as «from the slot I am
  standing on, to the slot I want» (`3,3 → 4,4`, slot 4 being the unit hour), the border
  brought round the phase we were ALREADY playing — building again, with its score
  already at the top chest and its boxes already taken, for four more hours. The unit
  hour did not arrive. So this send moves the phase you are ON into the slot you name;
  to ARRIVE at a phase, the argument order to try is the reverse — `from` = the slot
  holding the phase wanted, `to` = the slot playing now. **Untested**, and it costs a day
  per attempt, so the next account to try it should write down which way round it went.

The calendar is needed for either direction and it is WIPED within a minute or two of
arriving, so it is re-asked (naming the activity) immediately before reading the slots
rather than once at the start of a run.

## What is proven live

* **The minutes phases, both of them.** A technology phase and a building phase were each
  taken to their top chest exactly — 3 000 minutes for the second, in two parcels, the
  first of which is deliberately ONE piece so the rate is measured rather than trusted.
  The client's own `SpeedScoreValue` says 6 a minute for research and the phase paid
  **10**, which is why the constant is only ever the opening guess.
* **Both chest ladders.** Three phase boxes and three day boxes claimed in one pass.
* **The hero phase.** One hire, 400 points.
* **The unit phase's three sends.** Two barracks collected (918 soldiers) and two started
  on 500 level-9 soldiers each, with the phase score moving 0 → 28 000 of its 75 000 in
  the same minute — 28 points a soldier. And the freeing one, on a test account: one
  five-minute piece moved a barracks 300 s and left the batch alone.
* **The calendar, on two accounts.** The ask has to NAME the activity; named, it answers
  with the day's six phases and their times on both.

## Open

* **The unit phase end to end.** Its two sends are proven; the recipe that strings them
  together has only been gated live (it refuses a phase of another kind in one line) and
  waits for a unit phase to come round.
* **The rally cost in stamina has not been read off a live client.** Everything the
  drone recipe does is bounded by it, so it is the first thing to check when the phase
  next comes round — the drone phase is the one recipe here that has not run live at all.
* **The stamina bar is shared with the golden-zombie hunt and nothing shares it out.**
  Written down here rather than solved: which of the two gets the bar on a day both want
  it is the person's call.

## The card on «VS» reads it once and then listens (#2635)

The errand's own card stands at the top of the «VS» page and draws three things off the
reading above: which hour is running (with the window the calendar gives it), which of the
hour's three chests the server has flagged `receive`, and `sc` against the top chest.

It costs no question of its own. The reading is played by the «VS» tab on three occasions
and no others — the client getting into the game (`bus.GAME_READY`), the event's own
`push.person.arms.sc.change` (debounced, so a burst is one reading), and the border of the
hour, which `until` already names — and lands in `panel/runtime/arms_live.py`, one row of
this profile's `blobs`. «События» writes the same row when its own card is read, so there
is one state and two drawings of it, never two states.

Two things stay dashes rather than becoming zeros, for the reason this file has already
measured: an hour nobody read while it ran has no chest count anywhere in the client, and
a client that has not answered has no score. Both draw as «nobody asked».

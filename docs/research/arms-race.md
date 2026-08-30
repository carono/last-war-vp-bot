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

**And it never gets a rally allowance of its own.** The rallies a day is worth are the
person's own caps, per monster group, counted in `panel/rally_limits.py` (#2051/#2055).
The arms race spends OUT OF those: the panel hands the recipe what is left, `0` raises
nothing, and a drone phase that therefore scores nothing is the right outcome rather
than a bug. An event that quietly overspent the day's rallies is exactly what the caps
exist to stop.

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
  ceiling, the day's remaining rally allowance, the phase's top chest, or the squad
  coming off the board, whichever comes first.

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

## Open

* **The ceilings are all settled; the SENDERS are what is missing.** `120001` and
  `120003` spend 3 000 minutes of speed-up into the queue with the LONGEST remaining
  time, specialised kinds before universal ones; `120002` speeds a training queue up only
  far enough to FREE it, then collects and trains the most level-9 soldiers it can; the
  chests are claimed as soon as they are owed. None of that can be written until the
  «use a speed-up on this queue», «start a training batch» and «claim this box» sends are
  known — see «What did NOT work» above for the three routes that are closed and the two
  that are not.
* **The rally cost in stamina has not been read off a live client.** Everything the
  drone recipe does is bounded by it, so it is the first thing to check when the phase
  next comes round.
* **The stamina bar is shared with the golden-zombie hunt and nothing shares it out.**
  Written down here rather than solved: which of the two gets the bar on a day both want
  it is the person's call.

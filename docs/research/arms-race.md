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

## What the panel does with it

* `actions/read_arms_race.md` — sends the calendar get, then reads the phase running now
  (`arms`) and the whole day (`arms_day`). Presses nothing, spends nothing.
* `actions/arms_race_hero.md` — the `120000` phase: recruit in the tavern up to the
  phase's top chest or the allowance the person gave, whichever comes first, and never
  in diamonds.

## Open

* The other four phases spend the player's speed-ups, drone data and stamina. **Each
  needs its ceiling agreed with the person before a recipe is written** — a phase recipe
  with a guessed ceiling is a recipe that spends somebody else's items.

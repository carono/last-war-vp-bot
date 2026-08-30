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

## Open

* `120001` «Строительство Города», `120002` «Прогресс юнита» and `120003` «Исследование
  технологий» spend the player's speed-ups and troops. **Each needs its ceiling agreed
  with the person before a recipe is written** — a phase recipe with a guessed ceiling
  is a recipe that spends somebody else's items. Asked and not yet answered: how much
  speed-up per phase and whether any queue or only the one already running; which unit,
  how many batches, and what resource floor; and whether the chests should be claimed
  automatically.
* **The rally cost in stamina has not been read off a live client.** Everything the
  drone recipe does is bounded by it, so it is the first thing to check when the phase
  next comes round.
* **The stamina bar is shared with the golden-zombie hunt and nothing shares it out.**
  Written down here rather than solved: which of the two gets the bar on a day both want
  it is the person's call.

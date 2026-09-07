# Hidden Treasures — the weekly compass board (protocol & measurements)

Task #2382. The event the player calls «Скрытые Сокровища»: the tab beside the explorer
chests in the secret-squad window. Digging a treasure map pays a random handful of
**compasses**, and a week's worth of them unlocks ten reward steps, the last at **6000**,
which is the week's whole point — about twenty digs at the average pay.

Everything below was read off a live client on **2026-09-02**. Where a number is the
game's own it says which call produced it; where it is a measurement it says what was
done and what came back.

## This is NOT the world-map treasure

Two different features share the English word, and confusing them cost the first half of
this investigation:

| | world-map treasure | hidden treasure |
|---|---|---|
| found by | `world.get.block`, tile `f2=21` | nothing — there is no tile |
| taken by | `detect.event.claim.treasure {uuid,targetServer}` | `hero.dispatch.dig.treasure <set>` |
| costs | a march and a share of a daily group cap | one of each of seven map fragments |
| pays | resources into the bag | compasses towards a weekly board |
| doc | [`world-treasures.md`](world-treasures.md) | this file |

They have no manager, no item and no cap in common. `activity_sports_uitips_015` — the
per-group daily cap documented for the world-map one — does not apply here at all.

## Where the state lives

Two managers, both under `DataCenter`:

* **`DigTreasureBoxRewardManager`** — the BOARD. The compasses, the weekly cap, the ten
  reward steps and the activity id.
  * `GetBoxRewardItemCount()` — compasses this week. **This is the reading that lags; see
    below.**
  * `GetMaxNum()` — the weekly cap. Answered `6000` live, which is the number the person
    asked for by name.
  * `GetTreasureBoxRewardList()` — the ten steps, each row carrying `target` (the score it
    stands at) and `isReward` (non-zero once it has been collected). Live targets: 300,
    600, 1000, 1500, 2000, 2600, 3300, 4000, 5000, 6000.
  * `GetActId()` — the event's activity id, which is how its row is found in
    `ActivityListDataManager.activityList` and therefore when the week opens and closes
    (`startTime` / `endTime`, both in **milliseconds**).
* **`ActDispatchTreasureManager`** — the BAG.
  * `GetCanDigCount()` — how many digs the fragments still allow. It is the **minimum of
    the seven** fragment counts, computed by the client; there is no separate dig quota.
  * `digExchangeType` — the fragment set the event runs on, and the one argument the dig
    takes.

The compasses are an ordinary item in the resource system (id `771051`), and the seven map
fragments are the consecutive run `771011`–`771017`. Nothing else was found to be spent.

## The three sends

```lua
-- ask the server for the board; the tier flags come back, nothing is spent
DigTreasureBoxRewardManager:SendMainBoxRewardUIMessage()

-- dig ONE treasure. `set` is the client's own digExchangeType, POSITIONAL.
SFSNetwork.SendMessage(MsgDefines.DispatchDigTreasure, set)

-- take every step the week has already earned, in one send
DigTreasureBoxRewardManager:SendGetBoxRewardMessage(1)
```

The dig rides `hero.dispatch.dig.treasure` on the wire. **The argument must be positional**
— handing the same value inside a parameter table is accepted by the API and produces no
send at all, which is the shape of failure that wastes an afternoon: no error, no traffic,
no change on the board.

The send returns nothing useful. What proves a dig happened is `push.item.del` taking one
of each of the seven fragments the same second, so `GetCanDigCount()` falling by one is
the only honest verification and it is what `game_buttons.py` verifies on.

## The measurement that shaped the whole ability

**The compass count does not move while the client is running.** Three digs were made; the
seven fragments were decremented on the wire the same second each time, and
`GetBoxRewardItemCount()` read **0** for the six seconds after every one of them. The
client was then restarted and the same call read **750**.

So a scenario that loops «dig until the score reaches the goal» never ends. The ability
therefore **plans once and counts down**: it works out off the score the client is holding
how many digs the distance is worth, parks that number, and spends it. The score catches
up between sessions, and the next run plans off the true one.

A page drawing this must say so, or a person reading an unchanged score right after a run
will conclude the digs paid nothing.

## Claiming does not spend the score

Measured with the board standing at 750 compasses: one `SendGetBoxRewardMessage(1)` turned
**both** the 300 and the 600 step to «taken» and left the score at 750. The steps are
milestones, not purchases.

This is worth stating because the person who reported the feature had hit exactly the
opposite assumption — «ты скорее всего не подтверждаешь получение кладов». A step that has
been earned and not collected is a reward standing on the board doing nothing, so the
ability claims **at the end of every run, including a run that dug nothing**.

## What a dig pays

Read off the event's own reward table in the client config, not sampled:

| pay | share |
|---|---|
| 150 / 180 / 240 | 6 in 10 |
| 350 / 450 / 600 | 3 in 10 |
| 600 / 700 / 900 | 1 in 10 |

That averages near **320**, which puts 6000 at about **19 digs** — matching the person's
«в среднем нужно 20 кладов копнуть». The average is a knob (`pay`) rather than a constant,
because it decides only how many digs the distance is planned as: too low and the run digs
more than it needs, too high and it stops short and finishes on the next run. Neither is
a loss, since nothing but fragments is spent.

## Caps

* **No daily cap on digs was found**, in the managers or on the wire. What limits a day is
  the bag: seven fragment counts, and the smallest of them is the number of digs in hand.
* **The weekly cap is on the SCORE**, not on the digs — `GetMaxNum()`, 6000 live. Digging
  past it earns nothing more that week.
* The week's two ends come from the activity row, so «closed» is a real reading and not a
  guess from the day of the week.

## How it is built

* Lua primitives — `tools/lib/lua_actions.py`, `hidden_treasures_*`.
* Presses — `tools/lib/game_buttons.py`: `ask_hidden_treasures`, `read_hidden_treasures`,
  `plan_hidden_treasures`, `dig_hidden_treasure`, `claim_hidden_treasures`.
* The ability — `src/lastwar_bot/actions/dig_hidden_treasures.md` (`goal`, `cap`, `pay`),
  the reading — `src/lastwar_bot/actions/read_hidden_treasures.md`.
* The card — a row of «Таймеры» (#2597). The page of its own is gone: the errand
  `dig_hidden_treasures` (`panel/timers.py`) carries the three knobs as its `args`,
  the gear draws them (`panel/runtime/errand_args.py`), and the live line under the
  card — compasses of the week's cap, digs in the bag, digs still to the goal —
  comes off the one daily reading (`panel/runtime/errand_stats.py`, the
  `hidden_*` fields of `actions/read_daily_checklist.md`), so the card costs the
  game nothing.

## Open ends

* The reward table above is the config's, and no long sample was taken to confirm the
  client rolls it evenly. It only affects how many digs are planned, so being wrong about
  it costs a run and not a resource.
* Where the fragments come from is not part of this ability — they arrive from the secret
  squad's own errands, and the bag is simply read.
* Nothing pushes when the score moves, so there is no subscription to make: the board is
  read on a press and on the first look at the page, and the reading's age is drawn beside
  it.

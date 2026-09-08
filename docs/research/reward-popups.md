# The reward popups: an ear in the client, and a book beside it (#2027)

How the «вот что вам дали» modals are caught the moment they open, closed without a press
of ours, and written down — what was given, and what the panel was doing at the time.

- The ear: `tools/lib/lua_actions.py::reward_watch_install` (+ `reward_watch_hold`), fired
  as the button `watch_reward_popups` in `tools/lib/game_buttons.py`.
- The recipe: `src/lastwar_bot/actions/collect_reward_popups.md` — installs the ear and
  drains its ring. Called at the end of a recipe that earns something.
- The book: `panel/runtime/rewards.py`, the table `all_reward_popups` in `profiles/panel.db`
  (schema v9), the page `panel/tabs/rewards.py`.
- The switch (#2408): the standing order `reward_popups`, registered by
  `panel/runtime/panel_orders.py` and drawn among the listeners on «Таймеры». It plays
  `src/lastwar_bot/actions/set_reward_popups.md`, which carries the wish to the client
  through `reward_watch_mute`.
- Tests: `tests/test_reward_popups.py` (the ear, in a real Lua VM),
  `tests/test_panel_rewards.py` (the book).

Every value below is of the shape observed on a live client, with the account's own
numbers replaced.

---

## 1. What was there before, and why it was not enough

`game_buttons.py::dismiss_reward_popup` — a sweep of every open window whose name carries
`Reward` or `GetGift`, closing each with `Ctrl:CloseSelf()`. It is used as a step in four
recipes (`collect_alliance_gifts.md`, `collect_secret_tasks.md`,
`collect_truck_resources.md`, …) and it works.

It is a PRESS, and that is its whole limit:

* it happens only where a recipe remembered to put it, so a popup raised by the assist
  (`assist_secret_task.md`) sat on the client until something else ran;
* it says nothing about what was in the window — the point of the popup;
* it fires whether or not anything popped up, which is a round trip spent on nothing;
* and it sweeps 2 221 names to find the one that is open.

## 2. What the client offers to be wrapped

Measured live on a logged-in client through the panel's own web API (a scenario under
`actions/dev/`, deleted afterwards — the same method as #2016):

```
UIManager=table | Instance=table | Instance.OpenWindow=function | mt=table
DataCenter.RewardManager=table | RM{__ctype:number,_class_type:table} | UIUtil=table
```

So both objects are Lua tables whose class sits behind a metatable:

```
UIManager.Instance          -- a table; getmetatable(...).__index carries OpenWindow,
                            -- GetWindow, GetStackTopWindow, DestroyWindow, …
DataCenter.RewardManager    -- the same shape; its class carries the show-methods
```

`RewardManager`'s class, read live, carries **ShowCommonReward, ShowSingleReward,
ShowGiftReward, ShowTwoLinesRewards, SequenceShowReward, ShowCommonHeroReward,
ShowGiftBoxOpenReward, ShowDailyTaskReward, ShowGeift, ShowDetectEventCombineReward**,
beside the parsers (`ParseRewardsInfo`, `RewardItemList`) and `AddRewardsAndRes`.

That is what makes the ear possible at all: a `rawset` on the INSTANCE shadows the class
for that instance alone, so the wrapper is invisible to everything else in the client —
the same form #1420 used on `UIWorldPointCtrl:InitData` and #1990 on the resource writers.
`UIManager` being C# would have ended the design (that is exactly what stops the world
camera being wrapped, `live-screen-view.md` §3c); it is not.

## 3. The shape: listen, never poll

The rule is `CLAUDE.md`'s: «читаем один раз, дальше слушаем, никаких активных действий в
фоне». A popup has no push behind it, so the tempting version is a clock that reads
`GetStackTopWindow()` every few seconds — and that is precisely the background poll the
rule forbids, on the one link the whole bot shares.

The ear costs no reading at all, because it runs INSIDE calls the client is making anyway:

```
RewardManager:ShowCommonReward(list)   -> the wrapper notes WHAT, then calls the original
UIManager:OpenWindow(name)             -> the original runs, then the wrapper decides
```

Nothing is asked of the game and nothing is asked of the server. The rows wait in a ring
inside the client until the panel is talking to the VM anyway.

## 4. The three guards — the part that decides whether this is safe

Closing «whatever popped up» is the one way this design could cost something expensive: a
mini-game holds its own window for a whole match (#2021), a march holds the squad screen, a
purchase holds its dialog. A window is closed only when all three hold:

| # | guard | why it alone is not enough |
|---|---|---|
| 1 | the name is in `REWARD_WINDOWS` — an explicit list, never a substring | a list can be added to carelessly |
| 2 | a reward show fired in the last 3 000 ms of the game's clock | a reward-named window can be opened by a person |
| 3 | no recipe holds a window (`__lw_rewards.hold`) | a list and a span can both be right and still be wrong for THIS run |

**An unknown reward window is recorded and LEFT OPEN** (`unknown|<name>`). That is how the
list grows — by evidence on the «Награды» page and one line in the log per new name —
rather than by a wrapper deciding for itself.

The hold carries a DEADLINE rather than a flag (`reward_watch_hold(minutes)`), because the
recipe that needs it most — the mini-game — arms its match and returns, leaving nobody to
lift a flag afterwards. Half an hour, longer than any match; a client restart clears it
with everything else.

### Why close at all, even over our own work

A reward popup acknowledges something the SERVER has already granted: closing it takes
nothing back, and there is no button on it that matters. What it does do is sit on top of
the client, where it blocks the vision steps (`FIND`/`CLICK`) and any press that goes
through the window stack. So the popup is the thing in the way — and guard 3 is what
protects the one case where the window IS the work.

## 5. What comes back

The ring is drained by `collect_reward_popups.md` into one log line:

```
reward_popups: 1756402331000|reward|ShowCommonReward|101x2,205x7 ;; 1756402331080|closed|UIGiftPackageRewardGet
```

| kind | means |
|---|---|
| `reward` | the client said what was given: the show's name, then `<id>x<count>` per row |
| `closed` | a whitelisted popup, shut by the ear |
| `popup` | a whitelisted popup that would NOT shut (no `Ctrl`, or `CloseSelf` raised) |
| `unknown` | a reward-shaped window that is not on the list — left open on purpose |
| `held` | a popup left alone because a recipe held a window |
| `lost` | rows the ring dropped, counted rather than hidden |

The ring holds 80 rows. A drain empties it; the recipes that earn things drain as they go.

## 6. «За что» — and why «не знаю» is an allowed answer

Nothing in the client knows why a reward arrived: by the time the window opens, the reply
that carried it is gone. What IS known is what the PANEL was playing — `rt.activity`'s
oldest live `activity.action` step, which is the scenario the runner put there
(`panel/runtime/actions.py`).

So the book writes that scenario's name into `why`, and **leaves the field empty when the
panel was playing nothing at all**: a reward that arrived from a push, an alliancemate's
gift, something the person did by hand. The page draws an empty one as «не знаю». A guess
there would be indistinguishable from a fact, and this repository has paid for that
distinction before.

## 7. Where the rows live

A table, not a file and not a blob (`CLAUDE.md`, «Game data lives only in the database»,
and the unit-of-write rule from #1963): this grows without bound, is written a row at a
time as rewards arrive, and is read back narrowed («the last fifty», «the unknown ones»).
Schema v9, `all_reward_popups`, `profile` first in every index, reached through the
per-connection view `reward_popups` like every other table since #2025.

Ninety days are kept; the first drain of a session prunes what is older.

## 8. What it costs

`collect_reward_popups.md` is one round trip when the ring is empty (the `TAP` install is
free on a client that has the ear, and the count read is one expression) and two when it
has something. On the same client the round trip is 150–250 ms, which is the price of the
line — not of the wrapper, which runs inside a call the game was making anyway.

## 9. What is NOT done

* **No clock anywhere.** Not in the ear, not in the book, not on the page.
* **`AddRewardsAndRes` is not wrapped** even though it carries the same list. It fires for
  rewards that raise no window at all, and this book is about the POPUPS; adding it would
  double every row that does raise one.
* **The whitelist is not derived from a pattern.** `Reward`/`GetGift` matches 190 of the
  client's 2 221 window names, including previews, rank tables and shop pages. The list is
  18 names, and it grows only by an `unknown` row somebody has read — which is exactly how
  the eighteenth arrived (#2642): the base truck's collect raised
  `UIZombieBattleHangUpReward` twice, the ear recorded both as `unknown` and left them
  standing, and the name was added once a person had read the evidence.

## 10. The switch, and where the wish lives (#2408)

The ability worked and appeared nowhere. It is in no catalogue — nothing installs it, every
recipe that earns something puts it back as it goes — so «Триггеры» had no row for it, and
the page that draws its book (`panel/tabs/rewards.py`) is `IN_DEVELOPMENT` and absent from
the live profile. The person's words: «мы поставили триггер на авто закрытие сообщений о
подарках, к слову работает отлично, но я не вижу в триггерах её карточку».

It is a STANDING ORDER now, the same shape «Автолут ★» has had since #2017, and registered
from `panel/runtime/panel_orders.py` rather than from a tab — an order that lives on a tab
the profile has switched off is the fault #2010 found in the ghost robbery.

**The wish is `DataCenter.__lw_rewards_off`, a global of its own, and deliberately not a
field of the ear's ring.** The ring is rebuilt by every install, and an install happens on
every collect: a wish kept inside it would be a switch that flips itself back on within
minutes. The wrappers read the global when they RUN — both of them, so a muted ear closes
nothing and records nothing — and the flag costs a table lookup per window the client opens.

Where the value really lives is the profile's own setting `reward_popups`
(`panel/runtime/settings.py::DEFAULTS`, on by default because that is what every profile
has been doing since #2027). Moving the switch writes that and plays the recipe.

**A client that restarts forgets the wish**, because the global dies with it. That is
answered by an EVENT and not by a clock: `RewardBook.watch` tells the order the rows of
every drain, and a drain is the one proof there is that the ear is listening again — so a
switched-off order re-asserts itself there and nowhere else.


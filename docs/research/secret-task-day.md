# The star-secret-task day — what the client knows, and what had to be derived

Task #1467. The question was «tell me, for ANY warzone, whether today is its star-secret-task
day — from the data if the data has it, and from a schedule of our own if it does not».

The short answer: **the data does not have it.** The client's 742 config tables carry how
many star tasks a base of a given level may hold, the pool of task templates and the
buttons of the events screen — and no per-day, per-warzone plan of any kind. The one
schedule the client is told is the activity list of the warzone it is standing in, which
is the account's own and no other (`docs/research/server-events.md` §3). So the panel keeps
a book of what it has SEEN and derives a cycle from it — `tools/lib/secret_day.py`,
`panel/runtime/secret_day.py`, and the two columns on «Серверы».

## 1. Three states, not two

The player's own description is the specification, and it has three states rather than two:

* **day** — the star day itself, star tasks handed out in numbers;
* **post** — the day after, star tasks still appear but noticeably more rarely;
* **plain** — an ordinary day.

The middle one is the one that decides whether a monitor is worth running, and a yes/no
answer describes it wrongly whichever way it is rounded. All three travel through the
model, the database, both front-ends and the locales.

**Neighbouring warzones run the same cycle at different points.** A run of consecutive
numbers is on the day, the next couple are on the day after it, the ones after that are
on ordinary days — so the state is a function of the WARZONE and the DATE and never a
global constant, and a warzone nobody has watched is best guessed at by its nearest
neighbour in NUMBER. That is exactly what the fitted schedule does and what it says it is
doing (`neighbour` as the source of the answer).

## 2. What was read, live, and what each table turned out to be

Read out of a live client through the panel's web API and a throwaway recipe under
`actions/dev/` — the technique of `docs/research/server-info.md` §7.

| table | rows | what it is | is it the schedule? |
|---|---|---|---|
| `lw_dispatch_settings` | 116 | the dispatch rules by BASE LEVEL (`baselv` = `1-12`, `13-17`, …): `spe_task_count` / `spe_task_pool` (the star tasks), `task1..3_count/pool`, `steal_count`, `aid_count`, `max_taskqueue`, `refresh_item`, plus `season_condition` and `season_condition_server` (a season and a warzone RANGE the row applies to) | **no** — how many, never which day |
| `lw_dispatch_tasks` | 328 | the task templates themselves: `is_special`, `level`, `color`, `task_star`, `refresh_pool`, `show_time`, `protect_times`, `steal_maxtimes`, the rewards | **no** — the pool, not a calendar |
| `calendar` | 16 | the events screen's list: one text key per event (zombie rush, the queen challenge, the winter battlefield, …) | **no** — names, no dates |
| `activity_clock` | 19 | the clock entries beside those events: `calendar_id`, `event_group`, `title`, `goto`, `timer_dialog` | **no** — UI |
| `activity_calendargroup` | 20 | how the entrance buttons are grouped: `group_name`, `group_priority` | **no** — UI |
| `DayAct` | 15 | two labelled types per row (`type1`, `type1_text`, `type2`, `type2_text`) | **no** |
| `lw_season_war_calendar` | 4 | the season-war week's rows (`group`, `row`, `type`, `day7_*`) | **no** — the season war, a different cycle |
| `LW_Season` (`SeasonTemplateManager`) | 1 248 | the season plan, per warzone — already used by «Серверы» | **no** — seasons, months long |

`DataCenter.ActDispatchTaskDataManager` holds what the client is currently working with:
`allianceTask` (147 rows on the read that wrote this), `singleTask`, `todayStealNum`,
`todayAssistNum` — a live list, not a plan. `ActivityListDataManager.activityList` is the
server's own «what is running», and is empty on a client that has not finished logging in.

**Nothing found says «warzone N has its star day on date D».** If such a message exists it
is one the client never asks for: the dispatch family on the wire is
`hero.dispatch.steal` / `.assist` / `.leave.message` and the pushes beside them, none of
which carries a schedule.

## 3. What the game CAN be asked, and what it is worth

One reading, and it is evidence rather than a verdict:

```
actions/read_secret_day.md   ARGS server = 0
  secret_clock   own=<id> asked=<id> now_ms=<epoch ms> day_end_ms=<epoch ms>
  secret_counts  <server>=<stars>/<tasks> …
```

It walks the alliance's LIVE dispatch tasks (not expired) and counts, per warzone, how many
of them are starred. Live on the client that wrote this: **`<own>=0/122`** — 122 tasks
standing, none of them starred, which is what an ordinary day looks like from inside the
client with no map lap at all. The clock line is the game's own (`GetServerTime`) and the
day boundary is the game's own (`GetTomorrowZero`), so an observation taken at 01:00 lands
on the day the game thinks it is (`docs/research/game-clock.md`).

A number of stars out of a number of tasks is not a state by itself. It becomes one only
through a calibration LEARNT from days somebody labelled — `secret_day.calibrate`, two
thresholds derived from the labelled examples, and **no thresholds at all** until both ends
of the scale exist. A rule fitted to one side of a boundary labels everything on that side
and calls the result knowledge.

## 4. The derived schedule

`tools/lib/secret_day.py`. One cycle shared by every warzone — a word of states of length
`period` — and one offset per warzone into that word. Both are FITTED to the observations:
for each candidate period (2…28) the warzone with the most sightings sets the pattern, each
other warzone is slid against it until it fits best, and the period with the best
(agreements − disagreements) wins. A warzone with no sightings of its own borrows the
offset of the nearest one BY NUMBER, and the answer says so.

Four sources, in order, and every answer carries which one it is:

| source | what it means |
|---|---|
| `game` | the client itself said so, about the account's own warzone |
| `observed` | somebody wrote down what that warzone did that day (or the counts were labelled by the calibration) |
| `schedule` | the fitted cycle, on a warzone that has sightings of its own |
| `neighbour` | the same cycle, on a warzone borrowing its nearest neighbour's offset |
| `calendar` | the three-day cycle, placed by the warzone's own AGE — see §4.5 |
| `unknown` | nothing is known, and nothing is being claimed |

**The self-check is the point.** `conflicts()` returns every observation the fitted cycle
contradicts, the count is on the window's status line and on the phone's head card, and
nothing computed is ever written back into the observations. A schedule that has started to
lie says so instead of agreeing with itself.

Too little data fits NOTHING: fewer than three labelled sightings, or sightings from fewer
than two distinct days, and there is no schedule at all. Any period fits a single day
perfectly, which is the failure this guards against.

## 4.5 The cycle is THREE DAYS, and a warzone's own age says where it stands

A player-made cycle chart was handed in as a cross-check. It is a third-party ESTIMATE and
says so on its own face — «estimates based on server start dates and may be slightly off» —
but its method is the interesting part, and the panel could test it against readings of the
game it already holds.

Checked against this machine's own opening dates (`get.other.server.info`, thousands of
warzones on file), over one block of 128 consecutive warzones:

* the chart's three groups — «today», «tomorrow», «in two days» — are **exactly the three
  residue classes of the warzone's AGE modulo 3**, where age is whole game-days since it
  opened;
* the class sizes the panel computed from its own dates — 36 / 44 / 48 — are the three
  numbers the chart prints on its own tabs, to the warzone.

So the star day walks a **three-day cycle**, and where a warzone stands in it is decided by
when that warzone OPENED. That is the closest thing to a fact this question has: the
opening moment is read from the game, and the arithmetic on top of it is fitted here rather
than assumed (`fit_calendar`, `tools/lib/secret_day.py`).

Fitted from the panel's own book after the chart's day-set was written down as
observations: **period 3, zero disagreements**, one phase «day» and one «plain», the third
phase still unknown because nothing has been written down about it yet.

**The third phase is settled, and it is settled by GEOMETRY.** The three states are not
three independent things to be fitted separately — they are defined by their distance from
the star day: the day itself, the day after it, and every other day. So a cycle that knows
which phase carries the day knows the whole word (`with_geometry`): the class whose day was
YESTERDAY is today's post-day, the class whose day is TOMORROW is an ordinary day. A
player's description of a neighbouring block had those two the other way round and was
withdrawn in favour of the chart and of the arithmetic that agreed with it.

**Completing the word is not the same as silencing the book.** The completed pattern is what
the panel draws and what `calendar_conflicts` is judged against, so an observation that
argues with it — «ordinary», written down on a warzone whose star day was yesterday — is
reported as a disagreement and still WINS for its own warzone on its own day
(`answer` reaches an observation before it reaches any cycle). Live, that is exactly the
state of the book: period 3, one warzone in disagreement, and the disagreement is a reading
taken from the game rather than a typo.

## 5. Where it lives and what draws it

* `secret_days` — a table of its own in the profile's `panel.db` (schema v5). It is queried
  by warzone and by day on every draw, which is why it is a table rather than a row in
  `blobs` (`docs/panel-storage.md`). The SOURCE is part of the primary key, so a person's
  reading and a lap's count of the same day are two rows and the disagreement survives.
* `panel/runtime/secret_day.py` — the profile's book: record, observations, the fitted
  schedule, the answer for one warzone, and `decorate()`, which puts the answer on the
  drawable rows as LOCALE KEYS.
* **The window:** «Серверы» grows two columns — «★ день» (state · source) and «★ смена»
  (the date it turns over) — three buttons that write down what the SELECTED warzone is
  doing today, a «Прочитать из игры» that plays the scenario, and a status line with the
  book's own health.
* **The phone:** the same two readings as facts on each warzone's card, the graph's health
  on the head card, and the same four presses — the three marks ask which warzone, since a
  phone has no selected row.
* **«Куда идти сегодня»** — the magnifier beside the «Сервер» box on the ★ tab
  (`panel/tabs/secret_tasks/server_picker.py`): a grid of the warzones a robbery is
  possible on, coloured by today's state, and a cell is a JUMP rather than a number typed
  in. The slice is `server_list.same_phase` — see §7. The phone gets the same warzones in
  the same order as items, with the same press behind each
  (`SecretTasksTab.picker_view` builds both).

A mark is an OBSERVATION, never a tick: the panel is not keeping a second copy of something
the game would answer, because the game does not answer this at all. That is the line
`CLAUDE.md` draws around a press that marks, and this stays the right side of it.

## 6. What is NOT wired yet

**A lap of the map now feeds the book by itself**, and it is the only source that costs
nothing: every tile a capture decodes already passes through `SecretTasksTab._tiles_land`,
so the hook is a dict tally in a loop that was running anyway plus one queued statement per
warzone. It counts BEFORE the star filter — the share of starred tiles among all of them is
what tells a star day from an ordinary one, and the list itself keeps only the starred ones
— and it ACCUMULATES over the game-day (`SecretDayBook.saw_tiles`), because a lap arrives as
a hundred small batches and the last batch alone would say «2 of 3». The rows carry counts
and no state: they become a label only through a calibration learnt from days somebody
named, which is what makes the age cycle checkable against a FACT rather than against
another estimate.

**A wrong mark is corrected by marking again**, not by a «forget» button: the row's key is
(warzone, day, source), so pressing another of the three overwrites today's mark for that
warzone. `SecretDayBook.forget()` exists for a caller that needs to drop one outright and
no front-end offers it yet.

**Two panel-side lessons worth not re-learning.** `play_async` hands what a scenario READ to
`on_result`; `on_done` is handed nothing, so recording a reading there records an empty
dictionary («записано: серверов 0» about counts that had just arrived). And on the web API
the profile travels as a QUERY parameter on a GET and as a FIELD IN THE BODY on a POST — a
POST with `?profile=…` is answered by the ACTIVE profile, which is how three presses meant
for one account landed on another's book.

## 7. What would make this unnecessary

A message, a config table or a push that names the day per warzone. Two places worth
looking if one ever surfaces: the reply to `get.other.server.info` (today it carries an
opening moment and nothing else) and whatever fills `ActivityListDataManager` for a FOREIGN
warzone (today: nothing does). Until then the schedule stays derived — and the moment a
fact appears it wins, because `answer()` already prefers it.

## 8. Which warzones a robbery is possible on — the picker's slice (#1471)

The magnifier of §5 first drew a run of **consecutive numbers** around the account's own,
on the reasoning that consecutive numbers are consecutive ages and the star-day cycle is a
function of age (§4.5). That is true about the CYCLE and wrong about the WINDOW: the
operator's complaint was that most of what it drew is a warzone the game does not open to
this account — «показывается от начала сервера, а там грабить нельзя» — and a grid half of
which cannot be acted on is worse than no grid.

**The rule is the operator's own: «ограничивать сезоном или соответствующим
межсезоньем».** The slice is now `server_list.same_phase` — every warzone whose season
plan puts it in the SAME season numeral and the SAME stage of it as ours right now
(`phase_of` = `(step, stage_of(...))`, judged against the game's clock). It costs no wire
traffic: the plan for every warzone the client knows about is already on disk
(`docs/research/server-events.md` §1), so the edge is arithmetic and moves by itself when
the next season opens. **There is no number for it anywhere in the code, and there must not
be** — it is a different number on a different account and a different one again next
month.

Why the numeral alone is not enough: half of a numeral is mid-season while the other half
is months past it. Live, the block below ours was still PLAYING the season after ours (it
ends in a week) while ours had settled and been over for two and a half months — the same
config table, the same day, two different phases. The stage is what separates them.

Why not the season row's own group: `GetConfigDataByServerId(<own>):getValue('server')`
gives the nine warzones of the cross-server match group, which is far too narrow — it
starts well above the edge the operator can actually reach.

### What the game was asked, and what it would not answer

Four readings, all negative, all worth not repeating:

| asked | answer |
|---|---|
| `CrossServerUtil.TryGetCrossEnableServerList()` | `nil` — the list is transient, filled only while a cross-server event authorises one |
| `Global.CrossServerEnableList` (the table `GetCrossEnableReason` reads; found by `string.dump`) | `nil`, same reason |
| `CrossServerUtil.GetCrossEnableReason(<id>)` over a wide sweep | `-2` («Disable») for every warzone but our own — it answers about that transient list, not about where we may go |
| `CrossServerUtil.GetCrossServerIsInSameSeason(<id>)` for **every** id 1…2600 | `true` for all 2 600, including numbers no warzone has — it is not a filter |
| `lw_dispatch_settings.season_condition_server` | global bands (`3-9999`, `3-36`, `37-9999`) that pick which rule row applies by warzone AGE; nothing per account |
| `ActDispatchTaskDataManager.allianceTask` | 200 live tasks, every one with `targetServer` = our own — the alliance's list, not a cross-server pool |

So there is **no live list to read**, and the config-derived phase is the honest answer
rather than a convenience. Checked against the operator's own landmark — they named the
earliest warzone they can rob today — and the computed edge lands within one warzone of it:
the first warzone that left the season with us. The one below is still playing it.

### The anchor is the account's HOME warzone

Said by the operator in one line — «исходи от сервера игрока» — and it matters more than
it looks. The magnifier sits beside the «Сервер» box, and that box holds wherever the
camera was last sent (`_jump` writes every jump into it, #1280). Anchoring the slice on it
answers «what is in the same phase as the warzone I am LOOKING at», which is a different
question from «where may THIS account go robbing» the moment somebody types a foreign
number in.

So `_picker_anchor` reads the account's own warzone off the LIVE client — `own_server()`,
`LuaEntry.Player.serverId`, the same number «не грабить на своём сервере» judges every row
against — and nothing else. It is an account's answer, not a machine's: each profile has
its own, and it stays the HOME warzone even while the camera is standing in a foreign one
(measured: `IsInOtherServer() == true` and `serverId` unchanged).

**Unreadable is drawn as «unknown», never as the box.** A client that has not finished
logging in answers everything plausibly and wrongly
(`docs/research/server-link-status.md`), so a zero produces an empty grid and a line
saying the client has not said — not a grid drawn around a guess. The ask goes on a thread
and is one-at-a-time (`_priming_own`), because the phone may redraw the screen on a loop
while the client is out of the game.

### What the two front-ends show

`SecretTasksTab.picker_view` builds one reading for both: the cells, and a header saying
which phase this is (`secrettasks.picker.slice` — season numeral, stage, and where the
block starts and ends). The window prints it above the grid, the phone as the card's first
row. The count under the grid is the real number of warzones in the slice, which is what it
always was — it just is not a hundred-and-twenty-eight any more.

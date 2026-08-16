# What is running on a warzone right now — seasons, stages, and the rest

Task #1464. The question was «the game starts events on a schedule that is the same for
every warzone — pre-seasons, seasons, post-seasons, the shop, the golden zombies, the paid
battle passes — find the list», and the lead was the Monument building, which shows a
server's own history without saying what any of it was.

The short answer: **the season plan is a config table the client already ships, and it
answers per warzone** — so which season any of the 2 558 warzones is in, and when its
pre-season, its settlement and its end fall, is a table lookup with **no message on the
wire at all**. Everything else — the shop, the zombies, the battle passes — arrives as
the SERVER's own activity list, for the account's own warzone only.

## 1. The season plan: `LW_Season`, per warzone

`DataCenter.SeasonTemplateManager` holds it: `all` is 1 248 rows and
`GetConfigDataByServerId(<id>)` picks the one that names that warzone's current season.
Read live on 2026-08-16 (values below are this account's neighbours, invented ids in the
examples that follow the shape):

```
GetConfigDataByServerId(<own>)   -> id 1044, season_step «V»,
                                    pre 2026/03/23, start 2026/04/06 00:10,
                                    settlement 2026/05/25, end 2026/05/31 23:00
GetConfigDataByServerId(<other>) -> id 1088, season_step «Ⅵ»,
                                    pre 2026/04/20, start 2026/05/04 00:10,
                                    settlement 2026/06/22, end 2026/06/28 23:00
```

So the four moments of a season are `pre_start_time`, `start_time_str`,
`settlement_time`, `end_time`, and `season_step` is the Roman numeral the game itself
prints. A row carries 79 columns in all — `peace_day`, `season_battle_day`,
`season_war_day`, `pre_activity` (the ids of the pre-season's activities), `package`,
`server` (the semicolon-separated list of warzones the row applies to) and so on.

**Read the fields with `row:getValue(<name>)`.** A plain `row.<name>` answers on one call
and is `nil` on the next — the row fills itself lazily, which cost an hour of «it worked a
minute ago» before it was pinned down.

**The moments are calendar dates and are treated as such.** The row also has a unix
`start_time`, and it disagrees with `start_time_str` by a different amount on every
warzone checked (−5:10 on one, −6:50 on another), so there is no offset that would make
the pair consistent. A stage lasts weeks; `tools/lib/server_list.py` reads the strings as
UTC and says so rather than claiming minutes the table does not have.

**The chain is readable too, and it is short.** Filtering `all` by the `server` column
(column 5, semicolon-separated) gives every season that warzone has ever been assigned:
five of them on the account's own — I, II, III, IV, V. There is **no row for the season
that has not started yet**, which is why a warzone between seasons has no future moment in
its own row at all.

## 2. The account's own warzone, exactly

`DataCenter.SeasonDataManager` holds milliseconds rather than calendar dates, and one
thing the table does not have — the start of the NEXT season:

| call | what it gives |
|---|---|
| `GetSeasonStartTime()` / `GetSeasonEndTime()` | the current season, in ms |
| `nextSeasonStartTime` | when the next one begins — the only source for it |
| `GetNowSeasonAndSeasonDay()` | which season (5) and which day of it (133) |
| `GetSeasonDurationDay()`, `GetSeasonWeek()` | 132 days, week 5 |

Live on 2026-08-16 the account's own warzone was **between seasons**: season V ended
2026-06-01 and the next starts 2026-08-24. The config-only reading says exactly the same
thing («off»), which is the cross-check that the calendar dates are good enough for the
stage.

## 3. Everything else is the server's activity list

`DataCenter.ActivityListDataManager` holds what is running: `activityList` had **27**
entries and `nowActivityList` 26, each with `id`, `type`, `startTime`, `endTime`,
`endViewTime`, `seasonType`, `preSeason` and a `desc_info` text key. Types seen in one
read: 237, 308, 108, 305, 261, 343, 142, 303, 370, 126, 251, 312, 125, 302 — the shop
cycles, the zombie events and the battle passes are in there.

**And it is the account's own warzone only.** The list is pushed to the client for the
warzone it is standing in; nothing in the client answers «what is running on warzone
1234», and no message was found that asks. So «what is on right now» is answerable for
one warzone and «which season and which stage» for all of them — which is the split the
panel's «Серверы» window draws.

## 4. What the Monument turned out not to be

* `aps_pve_monument` — 354 rows of PvE levels (`level`, `build_condition`,
  `enter_resource_cost`). Not a history.
* `activity_updatelist` — 6 rows of client-update notes (`update_history_*` text keys,
  `server_area` ranges). The «server history» the Monument shows is these, and they are
  release notes rather than a schedule.

Neither carries a per-day plan. If the Monument's screen shows dates, it is showing the
activity list of §3 and the season plan of §1 — both of which are read here directly.

## 5. How the tables are read at all

The client's whole config set — **742 tables** — is reachable from Lua:

```lua
local inst = LocalController.instance()      -- note: instance is a FUNCTION
inst:GetTableLength('aps_pve_monument')      -- 354
inst:getTable('activity_showlist')           -- {index = {<column> = {<n>, <type>}}, data = {…}}
inst:getLine('activity_cycle', 1)            -- one row: getValue / getIntValue / _lineData
```

`TableName` is the registry of their names. Worth knowing for anything that needs a
config table later: `Calendar` (16 rows), `DayAct` (15), `ACTIVITY_CYCLE` (1),
`activity_showlist` (7), `LW_Shop`, `BattlePass`, `LW_BattlePassV2`, `PVEZombie`,
`LWZombieRush`, `activity_challenge_zombie`, `MONSTER_SHOP`, `ACTIVITY_CYCLE_SHOP`.
None of them is a «day of the server → event» plan; they are the templates the server's
own activity list points at.

## 6. What the panel does with it

`actions/read_server_list.md` reads the season plan for **every** warzone on file on every
run — it costs no wire traffic, and a plan read a month ago would show a warzone still in
a season it has left. `tools/lib/server_list.py` turns the four moments into a stage
(`pre` / `season` / `settle` / `off`) judged against the GAME's clock
(docs/research/game-clock.md), and «Серверы» draws the season, the stage and the date the
stage turns over — in the window and on the phone alike.

Live: 2 414 of 2 558 warzones came back with a plan; 768 were in a season, 64 in
settlement, 1 582 between seasons and 144 had no row at all (the newest warzones, which
have not been assigned one).

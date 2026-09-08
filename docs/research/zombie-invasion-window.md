# «Вторжение зомби» — what says it is running, and when the next window falls

Task #2647. The report: «Карточка с золотыми зомби работает и без события вторжение
зомби, нужно учитывать и не гонять в пустую». The golden zombies
([`golden-zombies.md`](golden-zombies.md)) are the invasion's own monsters — config
`1030000`, `special = 9` `WorldMonsterSpecialType.MonsterInvasion` — so outside the
event's window the whole chain walks its opening (the world scene, a squad refill, the
day's free energy, a refill bought for diamonds, a lap of the map) to discover an empty
list.

Everything below was measured on a live client on 2026-09-08, with the event OFF, through
the panel's own web API ([`panel-web.md`](panel-web.md)).

## 1 — the manager is the answer, and it answers «no» plainly

`DataCenter.ActivityMonsterInvasionDataManager`, every non-table field it carries with no
invasion running:

```
invasionId=0  progress=0  point=0  summon_score=0  aisillaActStatus=0
GetActivityData()  -> null      GetActData()          -> null
GetInvasionActivityId() -> null GetLastPlanTime()     -> null
```

A null C# object reaches Lua as something that `tostring`s to `<invalid c# object>` and
raises on arithmetic, so every read of it goes through a `pcall` and a `v + 0`
(memory: `tonumber` on a game value raises, and inside a `pcall` it does so silently).

**`invasionId` is the whole gate.** It is `0` with no invasion and carries the running
one's id otherwise (`monster.invasion.act.info` on the wire has `invasionId=5`,
`world-monsters.md`). Asking the server directly changes nothing when the event is off:
`ReqMonsterInvasionActInfoMsg()` was sent and two seconds later every field above was
still empty — which is the point of sending it, because a client that has never asked and
one that was told «no invasion» are otherwise indistinguishable.

The client's own list agrees: `GetMonsterListInArea` over `1030000/1/2` answered **0**.

## 2 — the activity row, when there is one

`GetInvasionActivityId()` into
`DataCenter.ActivityListDataManager:GetActivityDataById(id)` gives the row the server
sent, with `startTime` / `endTime` in **milliseconds** — the same shape every other
activity has (`server-events.md` §3). With the event off there is no row at all: the id
is null, and the invasion is in neither `nowActivityList` (33 rows), `GetLaterActivityList()`
(empty) nor `GetOverActivityList()` (empty). So the row answers «when does the running one
end» and never «when does the next one start».

## 3 — the next window is a SEASON DAY, out of the client's own config

`LocalController.instance():getTable('advanced_monster_invasion')` — 6 rows, one per
season, matched by the `season_condition` column («0-1», «2-2» … «6-6»):

| column | row 1 (seasons 0–1) | rows 2…6 (seasons 2–6) |
|---|---|---|
| `season_day` | 1 | **57** |
| `prep_time` / `challenge_time` | 0 / 0 | 60 / 3600 |
| `summon_boss_id` | 0 | 1030091 |
| `bannerTittle` | `2901000` — «Вторжение Зомби» | `activity_name_godzilla` |

So the invasion falls on a fixed DAY of the season, and the game says which day the season
is on today: `SeasonDataManager:GetNowSeasonAndSeasonDay()` answered `season 6, day 16`.
With the day boundary (`UITimeManager:GetInstance():GetTomorrowZero()`) that is a moment:

```
next_at = tomorrow_zero + (season_day - today - 1) * 86400
```

Live: `1788919200 + (57 - 16 - 1) × 86400 = 1792375200`, and the same number comes out of
the season's own start plus 56 days — the two arithmetics agree, which is the only check
there is. **It is an estimate to the day and is drawn as one** — the panel says «день
сезона 57 · через 41 д» and never a date, because a date is a claim about a clock nobody
here has checked (`game-clock.md`).

It also lands within an hour of the season's own `endTime`, so the invasion is the last
day of a season rather than something in the middle of one. That matches when the golden
zombies were last hunted (2026-08-19…21, days before season 6 began on 2026-08-24).

## 4 — what the panel does with it

* **`actions/read_zombie_invasion.md`** — the reading. Headless; sends one message
  (`ReqMonsterInvasionActInfoMsg`) only when the manager holds nothing at all, then reads
  again after two seconds. Leaves `inv_open`, `inv_ends`, `inv_next_at`, `inv_seen`.
* **The ability's gate is in the recipe**, where `CLAUDE.md` says it belongs: all three
  chains (`attack_golden_zombies.md`, `…2.md`, `…_pair.md`) open with
  `CALL read_zombie_invasion` before they switch scenes or spend anything, and `STOP` on
  a closed reading. The one thing that overrules it is the client still SEEING golden
  zombies — an invasion that has just ended leaves its monsters for their twelve minutes
  — and `-1` («the base is on screen, nobody could ask») is not a sight.
* **`panel/runtime/invasion_live.py`** — the schedule's own gate, so a shut window costs
  no run at all rather than one reading an hour: while the panel's reading says closed the
  errand is not started (`Schedule.register_precondition`). Ignorance is never a refusal —
  no reading, one older than `STALE_SEC`, or one whose own `next_at` has come round lets
  the run go and look. The reading is taken on `bus.GAME_READY`, on the invasion's own
  record arriving, and on every hunt run (`register_report`); there is no clock.
* **The cards say it.** «События» draws the state with its AGE and the next window;
  the hunt's row on «Таймеры» says «вторжения нет · день сезона 57 (через 41 д)» instead of
  promising attacks the purse cannot spend (`errand_stats._golden_hunt`).

**A REFUSED LOOK IS NOT A TRY** — measured on the live panel the first time this shipped
(#2647). The bounded first look of #2636 gave up after six, and all six were spent inside
two minutes of a restart on «занят — дождись завершения текущего действия» while three
profiles did their own boot work: nothing was asked of the game and the ear stopped
having read nothing. A play that never started does not count against the six now; the
waiting is bounded by `GATE_WAIT_TRIES` instead, exactly as a shut gate is.

`tests/test_invasion_live.py` pins all of it, including that no date or epoch is written
into the Lua.

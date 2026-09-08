# The alliance duel («VS»): the whole week, both sides, and what was losing it

Task #1304. Everything below was read off a live client on 2026-08-08 and stored four
times over; the values in the examples are invented and of the same shape.

## What the duel actually sends

`al.battle.rank.info` — `MsgDefines.AllianceCompeteRankList`, the ranking the duel screen
draws. One command, **three** rankings, told apart by `type` in both the request and the
reply: `AllyDuelRankType.Day = 0`, `Week = 1`, `Month = 2`. The client sends it from
`AllianceCompeteDataManager:FetchRankList(type)` and nothing else.

```
-- the request the screen sends, and the only one this needs
DataCenter.AllianceCompeteDataManager:FetchRankList(0)
```

A `type = 0` reply carries **every day of the week at once**, each row stamped with its
own `day` — the client bins them into `dailyRank[day]` in `RefreshRankList`. Measured on
a live week: six days, 182 rows each.

**Both sides are in the one list.** 100 rows of one alliance and 82 of the other, on two
different servers, in the same `rankInfo` array. Nothing has to be opened to see the
enemy; every row says which side it is on:

```jsonc
{"uid": 1000000000000001, "name": "Player1", "aid": "aaaa…", "abbr": "AL1",
 "serverId": 901, "score": 60, "day": 1, "picVer": 16, "headSkinId": 20008}
```

The two alliances themselves are in `GetDuelScoreManager.duelInfos[2].scoreData`:

| Field | What it is |
|---|---|
| `vsAllianceInfo[i]` | one entry per side: `alName`, `abbr`, `allianceId`, `serverId`, `power`, `icon`, `mvpPlayer`, `win` (days won), `winScore` |
| `…[i].scoreHistory` | **that side's score for each FINISHED day**, `[{day, score}]` |
| `…[i].alScore` | that side's score for the day **in progress** — not the week |
| `targetAllianceId` / `targetServerId` | the OPPONENT — the only thing that says which side is ours |
| `minDayScore` / `minWeekScore` | the thresholds the event pays out against |

### `alScore` is today's, and that was worth measuring

The obvious reading — `alScore` is the week's total — is wrong, and reading it that way
would have put one number in the place of six. The check that settles it: the per-day
player rows sum EXACTLY to `scoreHistory` for every finished day, and the running day's
rows sum to `alScore` (still climbing between two reads seconds apart). So `scoreHistory`
holds the days that have ended and the running day exists only in `alScore` — which is
why the collector files it under today's `weekday_index` rather than under «no day».

### Which side is ours is derived, never guessed

There is no «this is you» field. `targetAllianceId` names the opponent, so the other of
the two entries is the player's own alliance. With no opponent named — a bye week, or a
read that came back without the head — **no row gets a side at all**. An empty column is
honest; a guessed one looks answered.

## Negative findings, loudest first

**`champion.duel.activity.info` is NOT the daily VS breakdown.** It was the standing
candidate when this task opened, on the strength of a Send and a Handle in the log. It
belongs to the *Champion Duel* — the 32-fighter tournament whose final board is
`champion.duel.result.show.rank.list` — and has nothing to do with the weekly alliance
duel. Everything the duel has is under `al.battle.*`; the neighbours worth knowing about
are `al.battle.week.vs.info`, `al.battle.all.week.vs.info` and
`al.battle.week.result.info`.

**The daily rankings were already crossing the wire, and the store was eating them.**
Rows were keyed on `(uid, board)`. A `type = 0` reply is the same 182 players six times
over, so days 1..5 were overwritten by day 6 and what got stored was one day wearing the
whole week's name — visible in the old history as two snapshots that are not sorted by
score while the other thirteen are. The key is `(uid, board, day)` now, and the day is
part of the change hash.

**`raw_json` was never the raw row.** It was the decoder's flattened fifteen-field view.
Anything the decoder had no column for — `headSkinId`, `picVer`, `chatBubbleId`, and
whatever the next event adds — was seen once and dropped. `payload_json` is the row as it
arrived; `raw_json` stays what it was.

**The collector dropped in silence.** A reply that failed the shape test left no trace,
so «a message carrying what you are looking for» and «no message at all» wrote identical
logs. Every ending now writes a `sightings` row: what was seen, how many rows, whether
they were kept, and which test turned them away — with the row's SHAPE (field names and
types) and never its values.

**An alliance id does not fit the `uid` column.** It is hex; the column is INTEGER, so it
stores NULL while the change hash was comparing the offered string. Every alliance board
therefore differed from itself and six days of finished history were rewritten on every
run. The hash compares what is STORED now, and carries `alliance_id` for the identity the
NULL uid no longer provides.

## The history that went missing between 02.08 and 07.08

Snapshots from 31.07, 01.08 and 02.08 are in the panel log and not in the file. The file
was not truncated: `id` starts at 1 and `sqlite_sequence` equals the row count, so no row
was ever deleted from it — **it is a different, newer file**, created empty at 07.08
07:57.

What happened at 07:57 on 07.08 is #1276: the profiles moved from `panel/profiles/` to
`<project>/profiles/`. The old database was at `panel/profiles/default/`. No copy of it
exists anywhere on the disk — `/tmp`, the worktrees and `results/` were all searched —
so **31.07–02.08 is gone and cannot be recovered**.

The mechanism the fix closes is the one that makes such a loss possible without anybody
noticing: `_migrate_profile_dirs()` was silent in all three of its endings. A destination
directory that already existed was skipped with a bare `continue`; both failure paths
were `except OSError: continue`. Now a skip and a failure travel back in the return value
the caller logs, and a marker is written into the old directory naming what stayed put
and why. The files are still never overwritten — that part was right — but the decision
is no longer invisible.

## What is stored now

One read, into the profile's `leaderboard_history.db`:

| Board | Rows |
|---|---|
| `al.battle.rank.info/type=0/day=N` | one per player per day — both sides, 182 × 6 on a live week |
| `al.battle.rank.info/type=1` | the standing week |
| `al.battle.vs.alliances/day=N` | one per side per day: score, power, days won, MVP |

A day is its own board so a finished day dedups against itself; without that the whole
week was rewritten every run because the running day inside it had moved.

Columns: `day`, `side` (`own`/`enemy`), `scope` (`player`/`alliance`), `alliance`,
`alliance_id`, `server_id`, `source` (`wire`/`game`) and `payload_json`.

## Cost, and what the passive collector still cannot do

The whole read — two requests and the parse — is **7–9 s** on a live client, of which the
two `FetchRankList` round trips are about 4. It presses nothing and spends nothing.

It cannot go back in time: the server answers for the week it is in. A day nobody asked
about while it was current cannot be fetched afterwards, so a complete history means
running it once a day. The passive collector remains what it was — it catches the board
when a person opens the screen — and now files what it catches by day and by side.

## How to run it

```
python tools/vs_rankings.py --sqlite profiles/<name>/leaderboard_history.db
```

or the scenario, which is what the panel's «Записать дуэль» plays:
`src/lastwar_bot/actions/collect_vs_duel.md`.

## The score the PAGE draws, with no request at all (#2645)

The whole read above sends two `FetchRankList` round trips. The «VS» page does not need
them: `DataCenter.GetDuelScoreManager.duelInfos[2].scoreData` is already filled in when
the client is in the game, and it holds everything the person asked for — «мои очки дуэли
и альянса, прогресс… в виде процентов».

Measured live on 2026-09-08; the numbers below are of the right SHAPE and invented:

| Field | What it is |
|---|---|
| `curScore` (= `currentScore`) | THE PLAYER'S OWN duel score — what the personal reward ladder is paid against |
| `target` | that ladder, the game's own `\|`-joined milestones, e.g. `40000\|150000\|…\|7200000` |
| `vsAllianceInfo[i]` | a SIDE: `abbr`, `alName`, `allianceId`, `alScore`, `power`, `win` (days won) |
| `targetAllianceId` | the OPPONENT's alliance id — the only thing that says which side is ours |
| `minDayScore` / `minWeekScore` | what an alliance must reach for the event to pay out |
| `readyTime`, `fightStartTime`, `fightEndTime`, `weekEndTime` | the week's own clock, in ms |

**`duelInfos[1]` is NOT the duel.** It is the arms race (`eventId = 120004`, `curStage`,
`scores`), and reading the two the same way is the easy mistake: the alliance duel is
`eventId = 110001`, in `duelInfos[2]`.

The percentages the page draws are arithmetic on those three numbers and nothing more:
our share of the duel is `alScore / (ours + theirs)`, and the personal bar is `curScore`
against the LAST milestone of `target`. `actions/read_vs_score.md` is the whole reading —
one `READ_LUA`, no send, and the side is derived from `targetAllianceId`, never guessed.

**There is no push behind it that we have found.** The score is therefore read when the
client gets into the game (`bus.GAME_READY`) and drawn with its AGE beside it, which is
what `CLAUDE.md` asks for when a reading has no signal to subscribe to.

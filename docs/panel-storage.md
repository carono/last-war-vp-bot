# Where the panel keeps everything

**One line, because that is the point: everything the panel remembers is in
`<project>/profiles/`.** Copy the project folder and you take your panel with you; an
empty `profiles/` is a clean panel with nobody else's settings in it. Nothing is written
to your home directory, to `%APPDATA%`, to a temporary folder, or to any path spelled
into the code.

Russian copy of this page: [`panel-storage.ru.md`](panel-storage.ru.md).

## The layout

```
<project>/
  panel/                        the code — nothing local is written here
  profiles/                     ← EVERYTHING the panel keeps
    panel.db                    ← THE ONE DATABASE: every profile's settings and data
    settings.json               panel-wide settings, until they are carried into panel.db (then .imported)
    timers.json                 template a new profile's timer catalogue is seeded from
    triggers.json               template a new profile's trigger catalogue is seeded from
    panel_debug.log             fallback debug log — only before a profile's own is open
    _bot/                       the DSL bot's own --profile files (NOT panel profiles)
      <id>.json
    <profile name>/             one directory per account — logs, locks, checkpoints
      …everything below
```

## One database, one level above the profiles (#2025)

**There is one `panel.db`, it is `profiles/panel.db`, and every row in it says which
profile it belongs to.** The person asked for it in these words: «Давай сделаем одну базу
на всех и конфиги и профили, вынеси ее на уровень выше, из профилей, меньше проблем с
целостностью и консистентностью будет».

It was one database per profile until #2025, inside that profile's own directory, and the
isolation was the file itself. That is the strongest isolation there is — and it is also
why a rename was a directory move, a delete was a tree removal that could half-happen,
and an account's settings and an account's data could end up disagreeing about that
account's own name. One file makes each of those one transaction.

**Why here and not beside `profiles/`.** Everything local the panel has is under
`profiles/`, so an empty `profiles/` is a clean panel and copying the project folder
brings the panel with it (#1276). A database in the project root would have broken both
on its first day. `profiles/panel.db` is still out of every account's directory and
shared by all of them, which is what the decision asked for.

**What keeps the accounts apart, now that the file does not.** Every table is named
`all_…` and carries a `profile` column, first in its primary key. A store is built for
one profile — `Store(path, profile)`, with no default, because «the active profile» as a
module-level answer is the mechanics of #1306 — and every connection it opens carries
TEMP VIEWS under the OLD table names, each one filtered to that profile. So:

* a read that says `FROM players` is scoped whether or not its author thought about it;
* a write that says `INTO players` fails loudly («cannot modify … which is a view»)
  instead of landing in every account at once;
* the writes this layer makes name `all_players` and pass the profile as a parameter, so
  forgetting it is a parameter-count error rather than somebody else's row.

Two tests pin it: `test_two_profiles_share_one_file_and_see_nothing_of_each_other` and
`test_a_write_by_the_old_table_name_fails_instead_of_crossing_profiles`
(`tests/test_panel_store.py`).

**Several writers, which is now every open profile of every panel on the machine.** WAL,
so readers never block the writer and the writer never blocks readers, across processes
as well as threads; a 15-second busy timeout, so a second writer waits instead of raising
«database is locked»; short transactions with nothing inside them that reads a widget or
asks the game; `BEGIN IMMEDIATE` taken **before the schema version is read**, so two
panels opening the file for the first time cannot both decide the tables are missing; and
a database written by a newer panel is refused rather than migrated backwards.

`panel/paths.py` is the only file where any of these paths is written down. Every module
imports them from there — that is what stops the store from meaning two different places
in one process, which is exactly how it went wrong before (see «Why there were two» at
the bottom).

## Inside one profile — `profiles/<name>/`

### Settings

| File | What it is |
|---|---|
| `config.json` → **`panel.db`** | this profile's settings, and until #2025 also the thing that made the directory a profile. **A row in the `profiles` table since #2025** (`name`, `config`, `created_at`) — see «One database» above for what a profile is now. Still only what DIFFERS from the `default` profile's own block; `default` holds the whole thing and is the base every other profile layers onto (#1246). An existing file is adopted once, on the first start, and kept beside the database as `config.json.imported` |

### Logs

| File | What it is |
|---|---|
| `panel.log` | plain-text mirror of the log widget — what you see in the window |
| `debug.log`, `debug.log.1…3` | technical log: every action, every traceback, rotated at 5 MiB |
| `autostart.log` | every launch the hourly check made, and anything a panel printed before its own logging was up |

### What the tabs keep between runs

**Every list-shaped store here now lives in `panel.db`, not a file (#1398, #1465).** A
row below marked → `panel.db` moved; its old file is renamed `<name>.imported` the first
time the new code opens that profile and kept beside the database for good, never
deleted (see «The database» below for the mechanics). What is left in this
table is either a CAPTURE CHECKPOINT (a channel between two processes, rewritten whole
every tick, deliberately worth nothing after a restart — moving it into the database
would only make it durable, which is the one thing it must not be) or an append-only log
(`.jsonl`), which was never the "whole file rewritten on every change" cost `panel.db`
exists to remove in the first place.

| File | What it is |
|---|---|
| `panel.db` → **`profiles/panel.db`** | **THE DATABASE** (#1398, #1465, #2025, `panel/runtime/store.py`). One per profile until #2025, in the profile's own directory; ONE for the whole panel since, one level up, reached through `rt.store` and opened nowhere else. An existing per-profile file is carried across whole the first time that profile is opened — the register, the monsters, the ★ list, the ghost tiles, the map coverage, the day counters and the import marks, so nothing has to be imported twice — and is then kept beside the shared one as `panel.db.imported`, with its WAL companions, never deleted. Holds every whole-list checkpoint the panel keeps — the register of players (its own table, `players`, sorted and searched by), and everything below marked → `panel.db` (a named row in the shared `blobs` table — a new list-shaped store is a new `name`, not a new migration, the same way a new player is a new row and not a new migration). Its schema is a HISTORY (`MIGRATIONS`, `PRAGMA user_version`), not a `CREATE TABLE` written wherever somebody needed one |
| `secret_tasks.json` | what the secret-task scan currently sees on the map (a capture checkpoint, rewritten every tick — stays a file, see above) |
| `secret_tasks_state.json` → **`panel.db`** | the «Секретки» tab's OWN list — the starred tiles it is showing, with their countdowns, the book of what has been robbed and the book of what has been dismissed (#1242, #1280, #1416). **In the database since #1465**, under the name `secret_tasks_state` |
| *(new in #1479)* → **`panel.db`** | where the four-hourly star round has got to today — which warzones it has already walked and how many laps it has made (`tools/lib/star_round.py`). Never a file: it was born in the database, under the name `star_round_state`, and it is keyed by the GAME day, so a day that turns over empties it by itself |
| `secret_tasks_log.jsonl` | append-log of secret-task findings. Append-only, never rewritten whole — stays a file |
| `secret_shared.jsonl` | which secret tasks have already been shared with the alliance (#1245). Append-only — stays a file |
| `ghost_recon_tiles.json` | what the ghost-recon scan currently sees (a capture checkpoint — stays a file) |
| `ghost_map_state.json` → **`panel.db`** | the «Призрак: карта» page's OWN list — what it has gathered and kept (#1251). **In the database since #1465**, under the name `ghost_map_state` — the one blob TWO tabs meet over since #2010: «Секретки» fills and saves it, «Командный пункт» READS it, because the standing order that spends the event's OWN five robberies a day — counted apart from the five secret-task ones — has to choose out of the list the person is looking at. The name lives in `panel/runtime/store.py` (`GHOST_MAP_STATE`) so neither tab has to import the other |
| `world_treasures.json` | what the treasure scan currently sees (a capture checkpoint — stays a file) |
| `world_map.json` | what the SECOND listener inside the secret-task capture currently sees off the same map responses (#1289, #1335) — mines, player trucks, alliance trains and now players. A live view: rewritten every tick, stale rows evicted, each kind capped. A capture checkpoint — stays a file. It also carries WHERE THE CAMERA HAS BEEN since #2018 (`coverage`, written by `WorldIndex.checkpoint()`), which the panel folds into the `world_coverage` blob in `panel.db` — so the grid crosses a file on its way into the database. Asked and answered by the person, «Оставь»: this file is the CHANNEL between the panel and the child it spawned, not the store; the durable copy is the blob (`docs/research/world-schematic-map.md`) |
| `world_state_monsters.json` → **`panel.db`** | the world «Monsters» page's own gathered list — the ONE of the four world pages that keeps one at all; mines, trains and trucks are re-read from `world_map.json` above and never had a file of their own. **In the database since #1465** as the blob `world_state_monsters`, and **in a TABLE of its own since #1963** (`monsters`). It outgrew the blob and the measurement says by how much: 31 828 rows, 9.8 MB of JSON, re-serialised and written **from the Tk thread** on every poll of the follow clock — 0.20–0.32 s, five times a minute, per profile. A table writes the fifty-odd rows a poll actually saw, ages out with one `DELETE … WHERE seen_at < ?` instead of a rewrite of the survivors, and answers «только текущая зона» with a `WHERE server = ?`. Both older homes — the blob and, before it, the file — are carried across once by `store.monsters_import_blob_once`, which also drops the blob row so the megabytes stop looking like a live checkpoint |
| `players.json` → **`panel.db`** | the «Игроки» REGISTER — every player this account has met, kept for good (#1335, #1371). **In the database since #1398**; the file is imported once and then kept beside it as `players.json.imported`. Written through ONE entrance, `rt.players.sighted(records, source=…)` (`panel/runtime/players.py`), by everything that already sees a player: the map sweep's checkpoint, the live block of banners, the chat, the alliance roster and the owner of a tile. Every field carries `src[field] = [source, when]`, stamped when the VALUE changes and never on a mere re-confirmation — a lap re-lists four thousand unchanged players every twenty seconds. Not `world_map.json`: that one is what the capture can see right now, this one only ever grows and gives a row up for one reason, which is a person pressing «Забыть» (`panel/tabs/players/tab.py`; the `Kept` type this used to name was deleted in #2660 — it was never adopted, and the rule it described is enforced by the register itself). Holds what the map says (name, HQ level, alliance tag and name, coordinates, server, country), what a profile reply added if one ever arrived (power, army power, kills, SVIP), the note the GAME holds on that player, and the mark the PERSON wrote here — which no lap may touch |
| `rally_log.jsonl` | rally-monitor output. Append-only — stays a file |
| `rally_limits.json` | the per-KIND daily caps the auto-join obeys — a SETTING a person edits from the «Авторалли» page; since #2017 it is a row in `panel.db` (`settings:rally_limits`) rather than a file. Since #1317 the kinds are the game's own species (Doom Elite, Doom Walker, Zombie Boss, the General's Trial's two instructors, the Alliance Exercise, the Zombie Invasion). It carries a `v`, which is what tells a pre-rename `doom_elite` from the species of that name and whether a seed of ours that changed has been carried across (`v = 3`: the Wandering Mummy Warlord went back to the ordinary twenty, and a file still holding the old seed is moved once and rewritten). Every kind ships capped at 20 and the four Golden ones uncapped. **The total daily ceiling is NOT here** — it is one number in the tab's config block (`autorally.daily_max`), judged against the game's own count, and neither is the soldier floor (`autorally.min_soldiers`) |
| `rally_counts.json` → **`panel.db`** | what the panel has counted today, per kind — a COUNTER, not a setting, so unlike its `rally_limits.json` neighbour it moved (#1465). The counts carry the client's own `day_end_ms`, so they reset on the SERVER's day. **In the database since #1465**, under the name `rally_counts` |
| `resource_stats.json` → **`panel.db`** | day-keyed tally of resources gained. A push can arrive several times a minute, and the old file was rewritten whole on every one — the exact cost this migration exists to remove. **In the database since #1465**, under the name `resource_stats` — and keyed by the GAME's day since #2743, off `rt.day.day_key()`, because a counter zeroed at the warzone's reset must be filed under the boundary that zeroes it. Rows written before that keep the PC date they were written under: a history is not rewritten. **A second row of the same shape lives beside it, `resource_stats_base`** — only what the base's own buildings paid, which is what the card of «Сбор ресурсов» draws. Nothing on the wire says where a gain came from, so the source is the panel's own knowledge that `collect_base_resources` was running at that moment (`panel/runtime/resource_book.py`); a harvest made by a thumb in the game is in the whole-day tally alone. **Since #2746 the book hears that from the RUN REGISTER** (`panel/runtime/interrupt.py`), which does not care who pressed — the schedule's record of last runs knows nothing about `/api/actions/run` — counts EVERY gain inside the window rather than only the first, ASKS for three readings once a harvest ends (a panel nobody has open takes none otherwise, and six harvests of 2026-09-11 were priced as zero) and takes its baseline on `bus.GAME_READY`, because a diff cannot price the first reading it ever sees. **Since #2744 both rows also hold the ITEMS the base's lines pay in** — drone parts, gears, the pet's training papers, hero experience — keyed `item:<the game's item id>` beside the four resources, because the game names them and the panel must not; the game's own word and picture for each is kept in a row of its own, `resource_item_labels`, refreshed whenever a reading lands so a card drawn before the first read of a session still says «Запчасти дрона» rather than a number |
| `leaderboard_history.db` | accumulating snapshots of the ranking boards. Its own database, its own connection — not `panel.db`, because it is opened by a standalone collector (`tools/scan_leaderboard.py`) and by report tools that have no profile to ask for one. **Schema versioned the same way `players` is since #1465** (`tools/lib/leaderboard_store.py`'s own `MIGRATIONS`, `PRAGMA user_version`) — no more hand-added columns with no version behind them |
| `chat_log.jsonl` | raw capture written by the chat reader |
| `chat_history_<uid>.db` | the chat store the panel pages through — **one per character**, because one account can hold several and their chats must not mix. Its own database too, opened once per character on the Tk thread. **Schema versioned since #1465** (`panel/chat_history.py`'s own `MIGRATIONS`) |

### Schedule

| File | What it is |
|---|---|
| `timers.json` → **`panel.db`** | this profile's timer catalogue: what runs, how often, with what arguments. **A row since #2017** (`settings:timers`); the file is what an older profile is carried across from, once, and is kept beside the database as `timers.json.imported` |
| `timers_last_run.json` | when each scheduled errand last ran, and — since #1333 — when it BEGAN (`began_at`). A daily errand's next turn is measured from the start rather than from the finish, so a run that straddles the server's midnight is charged to the day it actually spent. A file written before that has no `began_at` and falls back to the finish |
| `day_reset.json` | when THIS profile's warzone starts a new day — the client's own `GetTomorrowZero()`, re-read at most four times a day and kept so a fresh panel starts knowing it. Per profile because two accounts can be on two warzones, and every «раз в сутки» errand is anchored to the reset of its own. Never read → the measured 02:00 UTC stands in |
| `triggers.json` → **`panel.db`** | this profile's wire- and poll-driven errands. **A row since #2017** (`settings:triggers`), carried across the same way |
| `timers_seen.json` | every errand name this profile has ever been OFFERED (`panel/timers.py`, `adopt_new_errands`). It is what carries «this update learnt a new errand» into a profile that already has a catalogue of its own, **and** what keeps an errand the operator deleted deleted. Settings, not data — it belongs beside `timers.json` and stays a file. An earlier revision of this page called it a leftover nobody reads; that was wrong, and #1398 checked before believing it |

### Session bookkeeping

| File | What it is |
|---|---|
| `panel.lock` | an open file the panel holds an OS lock on for its whole life — «a panel is on this profile» answered by the kernel, so it cannot go stale |
| `panel_alive.json` | the heartbeat the open panel rewrites once a minute |
| `autostart.json` | what the hourly check last made of that heartbeat |
| `children-<pid>.json` | which child processes that panel process started, so a crashed panel's children can be cleaned up |
| `maintenance/<stamp>-<state>.json` | ONE RAW RECORDING of a real server maintenance — everything the client answered, verbatim, plus what the light said at the time (`panel/runtime/status.py::_record`). A sample, not a store: nothing reads it back, it is never rewritten, and it exists because every word of the detector was inferred from the game's own tables rather than from a recording. Git-ignored, and a file for the same reason a capture is one — putting it in the database would make durable and trustworthy a thing whose only value is that it is a raw dump somebody opens by hand (#2660) |

## Beside the profiles — `profiles/`

| File | What it is |
|---|---|
| `panel.db` | **THE ONE DATABASE** — see the section above. Every profile's settings and every profile's data, keyed by profile; the panel's own settings under a scope no account can be named (`:panel`) |
| `settings.json` → **`panel.db`** | facts about the PANEL rather than about an account: `active_profile`, `open_profiles` (what was last open — a record), `keep_profiles` (what the machine WANTS farmed — a wish only a person writes, #2068), `language`, the web block, `dev_updates` (release channel vs branch tip). **A row since #2025**; an existing file is carried across once and kept beside the database as `settings.json.imported` |
| `timers.json` | the template a profile with no catalogue of its own is seeded from |
| `triggers.json` | the same for triggers |
| `panel_debug.log` | fallback debug log, used only until the panel points logging at a profile's own file |
| `_bot/<id>.json` | the DSL bot's `--profile <id>` files. **Not panel profiles** — a different feature that happens to use the word |

`_bot` never appears in the panel's profile list and cannot be created as a profile
name; the panel refuses it.

## What is in the project but NOT in `profiles/`

These are not settings, and they are deliberately elsewhere:

| Path | What it is |
|---|---|
| `results/` | captures, traces and scans from sniffing sessions — development material |
| `screenshots/` | pictures taken while working on the bot |
| `.env` | the optional environment variables (`.env.example` lists them) |
| `tools/data/instances.json` | the registry of second game clients, if you run any |

All of them are git-ignored, and all of them travel with a folder copy.

## What is genuinely outside, and cannot be otherwise

Two things live in Windows rather than on disk here, so a copied folder does **not**
bring them along — and should not:

* **The autostart scheduled task.** It names an interpreter and a working directory,
  i.e. one particular checkout. A copy registers its own from its own Settings page.
* **The saved RDP credential** for a second Windows session (`TERMSRV/<address>` in the
  Credential Manager), if multi-instance is in use.

There is also `~/.last_war_panel.json` — where the language used to be kept, before
#1276. It is read exactly once, to bring your choice across, and never written again.
Delete it whenever you like.

## Coming from an older checkout

Nothing to do. The first time the panel starts it brings across, into `profiles/`:

* `panel/profiles/<name>/` — the profiles themselves;
* `panel/settings.json` — the panel-wide file;
* `panel/timers.json`, `panel/triggers.json` — the two templates;
* `~/.last_war_panel.json` — the language;
* and any loose `profiles/<id>.json` left lying beside the profile folders goes down
  into `_bot/` where it belongs.

A directory is **moved** where the filesystem allows it. Where it does not — Windows
will not move a tree it has a file open in, and a running panel has several — it is
**copied**, and a `MOVED-TO-PROJECT-PROFILES.txt` is left in the old directory so a later
start cannot put stale files back over fresher ones. **Nothing is ever deleted**, and an
existing file in the new place is never overwritten. If both exist, the new one wins and
the old one stays on disk for you to look at.

## The database — `profiles/panel.db`

**ONE database for the whole panel** (#1398, #2025, `panel/runtime/store.py`), one level
above the profile directories. It was one per profile until #2025 — see «One database,
one level above the profiles» at the top of this page for the decision, and for what
keeps the accounts apart now that the file does not.

What has not changed is whose the rows are. A register of players, a ★ list and a day's
counters belong to an ACCOUNT, never to the window and never to «the first profile that
opened» — which is what `docs/research/profile-isolation.md` is a list of. A caller asks
`rt.store` and is handed its own profile's view; nothing opens the file for itself.

### Why, in one measurement

On a live profile `players.json` was 11.5 MB and 17 374 rows. `json.load` took 0.97 s,
`json.dump` took 1.45 s, and the whole file was rewritten on **every change** — which,
while a lap of the map is running, is almost every tick. The «Игроки» page then read all
of it into memory to filter and sort it in Python. None of that is a bug in the
register; it is what a whole-file JSON list costs once it stops being small.

### What is in it, and what is deliberately not

| | |
|---|---|
| **In** — data | the register of players (`players`, its own table), the monsters the client has drawn (`monsters`, its own table since #1963 — the one store here that MOVED OUT of `blobs`, because it is written a row at a time and narrowed by warzone), the book of star-secret-task days (`secret_days`, its own table since #1467 — it is searched by warzone and by day on every draw of the «Серверы» grid, which is the same reason `players` earned columns of its own), and, since #1465, in the shared `blobs` table: the ★ tile list with the book of what has been robbed and the book of what has been dismissed (`secret_tasks_state`), the ghost map's own list (`ghost_map_state`), the daily rally counts (`rally_counts`), the daily resource tally (`resource_stats`), where today's star round has got to (`star_round_state`, #1479) and the day-keyed tally of the golden-zombie hunt — marches sent, energy they cost, most seen in one run (`golden_zombie_runs`, #1519, born in the database with no file to import) and the firework book — how many gift-box announcements the profile's ear heard today, how many boxes actually ARRIVED and how many the server refused, when the last one came in, how long after the announcement it did, and a count per day for the last month (`firework_state`, #1677, extended #1854, likewise born in the database). The per-day counts are the one thing the game cannot be asked for afterwards — the client keeps a lifetime record of the boxes and no history of days — and they are read and written WHOLE, which is why they are a blob and not a table «Гонка вооружений» keeps two rows of `blobs` and they answer different questions: `arms_chests_day` is the panel's own BOOK of what each hour of today paid (#2579) — the client keeps no history of a phase that ended, so a chest nobody saw taken is a chest nobody can ask about afterwards — and `arms_live` is simply the LAST reading, kept whole with the moment it landed (#2635), so the card on «VS» draws the hour, its chests and its points without asking the game and both pages that take a reading write the one row. Both are read and written whole and are small, so both are blobs. The reward popups the client raised are the newest table of the three (`reward_popups`, #2027): they arrive a row at a time as an ear inside the client closes each modal, they grow without bound and a page narrows them by kind, so the same unit-of-write rule that moved the monsters out of `blobs` puts these in a table from the start The three READINGS kept the same way are `market_live` (#2636), `shops_live` (#2666) and `arena_live` (#2688): what «Сверкающий рынок», every shop's shelves and the arena building last said, with the moment it landed, so the cards and the autobuy draw one reading instead of each asking the game. Both are read and written whole and are small, so both are blobs. |
| **In** — settings, since #2017 | `timers.json`, `triggers.json` and `rally_limits.json`, each one row of `blobs` under `settings:<name>` (`panel/runtime/settings_files.py`). The person's decision, in their words: «Никаких json, все должно быть в базе». An older profile's file is carried across ONCE and kept beside the database as `<name>.imported` |
| **Both of them moved in #2025** | They were listed here as the two that had not, and each for a reason that has since expired. `config.json` was «a settings store AND the thing that says a directory IS a profile» — moving it did mean redefining what a profile is, and it is a ROW in the `profiles` table now. `profiles/settings.json` was «panel-wide, and there is no machine-wide database» — there is one now, and the panel's own settings are rows in it under the `:panel` scope. Both were asked and agreed with the person first, which is what the sentence they replace was asking for |
| **Out** — settings a template ships | `panel/timers.json`, `panel/triggers.json`, `timers_seen.json`. The first two are code — part of the repository, not of an account. The third is the record of what a profile has been OFFERED, and it lives beside the catalogue it explains |
| **Out** — logs and session | `panel.log`, `debug.log*`, `autostart.log`, `panel.lock`, `panel_alive.json`, `autostart.json`, `children-<pid>.json` |
| **Out** — a capture's checkpoint | `secret_tasks.json`, `ghost_recon_tiles.json`, `world_treasures.json`, `world_map.json`. A capture CHILD writes them and the panel reads them: they are a channel between two processes, rewritten whole every fifteen seconds, and worth nothing after a restart — moving one into the database would make it durable, which is the one thing it must not be |
| **Out** — append logs | `rally_log.jsonl`, `secret_tasks_log.jsonl`, `secret_shared.jsonl`. Never rewritten whole, so the cost `panel.db` exists to remove was never theirs; the JSON-file rewrite that motivated #1398 does not apply to them |
| **Out** — schedule bookkeeping, not game data | `timers_last_run.json`. The SERVER told the panel nothing here — it is the panel's own record of when ITS OWN scheduled errands last fired, the same kind of fact as `panel_alive.json`/`autostart.json` above, not a tile or a tally |
| **Out** — a single cheap-to-reread reading | `day_reset.json`. One timestamp (`GetTomorrowZero()`), re-askable of the game in under a second and asked at most four times a day — kept only so a fresh panel does not have to ask before it can decide anything. Nothing here accumulates and nothing is lost by asking again, which is exactly the property a capture checkpoint has and a database row does not need to buy |

**The rally pair used to split down that line, and #2017 closed the split**: the caps
are a SETTING and the counts are a COUNTER, and both are rows now — the caps because
the person ended the «settings stay files» half of the rule («Никаких json, все должно
быть в базе»), the counts because #1465 had already moved them. What has not changed is
the reason the two were ever told apart: a counter resets on the server's day and a cap
does not, and they are separate rows for that reason.

### The schema is a history

`MIGRATIONS` in `panel/runtime/store.py` is every version of the schema in order, and a
database carries how far it has got in `PRAGMA user_version`. Adding a column is
**appending** a migration; editing one that has shipped is not allowed, because it has
already run on somebody's live profile and would leave two databases both calling
themselves version N. A database from a NEWER panel is refused (`StoreTooNew`) rather
than migrated backwards — running against a schema we do not know silently ignores what
the newer version wrote, and migrating down deletes it.

The two databases that predate this — `leaderboard_history.db` and
`chat_history_<uid>.db` — are being brought under the same layer: one way to open a
connection, one place the schema is written down. Their data is not rewritten.

### Several threads, and several processes

Both are real. The panel writes from the capture reader's thread, the banner block, the
chat poll and the Tk thread; a standalone tab (`python -m panel.tabs.players`) is a
second PROCESS on the same directory. What answers it:

* **WAL** — readers never block the writer and the writer never blocks readers, across
  processes as well as threads;
* **a busy timeout of 15 s** — a second writer waits instead of raising «database is
  locked» at whoever pressed first;
* **short transactions** — `store.write()` is `BEGIN IMMEDIATE … COMMIT` and nothing
  inside it reads a widget, asks the game or sleeps;
* **one connection per thread**, in thread-local storage.

### Nothing writes on the Tk thread

`store.submit(job)` hands the write to this store's writer thread, which drains
everything queued within 10 ms into **one** transaction. A sweep that sees four thousand
players is one commit rather than four thousand: the cost of a burst is the number of
COMMITs, not the number of rows.

### Moving a file in loses nothing, and keeps the file

`import_once` reads the old JSON and writes the rows **in the same transaction as the
mark that says it has been done** — so a panel killed halfway leaves neither, and the
next start imports cleanly instead of half-again. Only then is the file renamed to
`<name>.imported` and **kept beside the database**. It is insurance: an import that
turns out to have misread a field is answered by opening the file, and a delete is
answered by nothing. The mark is also what stops a restored backup or a stale copy from
overwriting, months later, what a person has since edited.

`tests/test_panel_store.py` pins all of it: the migrations, the refusal, the concurrent
writers in threads and in a separate process, the batching, the rollback, and the four
promises the import makes.

## A list whose removals name a reason — the rule, and the type that was deleted

Three of these files lost data in one day, in the same way each time: a read came back
EMPTY or FAILED, was treated as authority, and rows a person had paid for with laps of the
map were deleted. **The rule that came out of it stands and is binding:** a row leaves a
list for its own countdown running out, or because the game answered ABOUT THAT ROW that
it is gone, or because a person pressed «очистить» — and «the read came back empty» is
deliberately not one of them, because an empty read is the ordinary shape of a client that
was busy, not logged in, or answering something else.

#1272 wrote the rule out for the ★ tile list, in prose, with every removal site naming the
clause it executes and an audit test that walks every door (`THE_LIST_RULE` in
`panel/tabs/secret_tasks/tab.py`). That is where it lives and it works.

**#1282 also put the invariant in a TYPE — `panel/kept.py`, a list with no `clear()`, one
removal call taking `EXPIRED` / `GAME_SAID_GONE` / `PERSON_ASKED`, and a `merge()` that
could only add — and no store was ever migrated onto it.** It sat for months with eleven
tests and no callers, which reads to the next person like machinery something depends on,
so #2660 deleted it. The design is in that commit's history if the next list wants it;
what is NOT optional is the rule above, however a given store chooses to enforce it.

## Why there were two directories called `profiles`

Worth writing down, because it cost somebody three attempts to get an answer.

The panel kept its state in `panel/profiles/`. The project root ALSO had a `profiles/` —
that one belonged to the DSL bot's own `--profile` flag (`src/lastwar_bot/profile.py`),
held one flat `<id>.json` per operator, and was addressed relative to the working
directory, so which one you got depended on where you launched from. A person looking for
their settings opened the obvious one, in the root, and found a stale file from months
earlier. Being told «no, the other one, inside the panel folder» is not an answer — it is
a thing to remember, and nobody should have to.

Two different features may not share one name blindly. So there is one directory now, in
the root, and it is the panel's; the bot's profiles moved down into `_bot/` where they
cannot be mistaken for an account.

Pinned by `tests/test_panel_storage.py`, which fails if any module starts building its
own state path again, if the language leaves the settings file, or if the migration
overwrites something.


## Daily statistics — a row per day, never one number overwritten (#2705)

**The person's decision, in their words:** «Когда мы собираем какую либо статистику по
дню, например сколько раз отправили грузовиков, сколько секреток собрали и все остальное,
то это все должно храниться в базе и исторически сохраняться, чтобы при желании строить
графики». The rule itself is in `CLAUDE.md`, «A DAY'S STATISTIC IS A HISTORY»; this is the
audit behind it — what already keeps yesterday and what throws it away.

The shape everything below is moving TO:

```sql
CREATE TABLE all_day_stats (
    profile TEXT NOT NULL,   -- whose day it is
    day     TEXT NOT NULL,   -- the GAME's day (`panel/runtime/day_reset.py`), YYYY-MM-DD
    name    TEXT NOT NULL,   -- `trucks_sent`, `secret_tasks_taken`, `rally_joined`…
    value   REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (profile, day, name)
)
```

An upsert on that key is «add to today» and cannot reach yesterday; the write goes through
`store.submit`, never off the Tk thread; the day turns over by ADDING a row, so «сегодня»
stays a `SELECT` and the history is the by-product.

**The table EXISTS since schema v11** (`panel/runtime/store.py`, `SCOPED_TABLES` →
`all_day_stats`), with an `at` column beside the value so a reading can say how fresh it is
and an index on `(profile, name, day)` so a graph is one seek. Four methods on `Store`:

| method | for |
|---|---|
| `day_stat_add(day, name, amount=1)` | a TALLY — the upsert adds, so a burst of pushes is a burst of `+1` |
| `day_stat_set(day, name, value)` | a READING — a benchmark taken twice today is the machine as it is now, not twice as fast |
| `day_stat(day, name)` | «сколько сегодня», a plain `SELECT` |
| `day_stat_history(name, limit)` | `[(day, value, at), …]` newest first — the graph the rule exists for |

Both writers go through `store.submit`, so no caller pays a transaction for a statistic.

**The first three names in it** are the map lap's own speed measurement (#2705):
`sweep_bench_ms`, `sweep_bench_tiles`, `sweep_bench_division` — written with `day_stat_set`
by «Замерить скорость» on «Секретки», and read back on the first draw of the card so a
panel restart does not make it say «не замерялось» about a machine measured an hour ago.

### Already keeps a per-day history

| tally | where | shape | note |
|---|---|---|---|
| resources gained | `blobs` `resource_stats`, and `resource_stats_base` beside it (`panel/resource_stats.py`) | `{date: {food, metal, oil, gold, item:7038, …}}`, a new key a day — any key that arrives with a gain since #2744 | day key is the **GAME's** since #2743; older rows keep the PC date they were written under |
| golden-zombie hunt | `blobs` `golden_zombie_runs` (`panel/golden_zombies.py:30`) | `{date: {attacks, spent, found, runs}}` | day key is the **PC** date (`:34`) |
| firework boxes taken | `blobs` `firework_state.days` (`panel/runtime/firework_wire.py:66`) | `{game_day: taken}`, trimmed to 30 days | only `taken`; the other four counters in that blob lose yesterday |
| reward popups | table `all_reward_popups` (`panel/runtime/store.py:651`) | a row per popup, kept 90 days | a stamped log rather than a day tally, but yesterday is recoverable |
| secret-task day observations | table `all_secret_days` (`panel/runtime/store.py:411`) | a row per `(server, day, source)` | about the WARZONE, not about what the bot did |

**The PC-dated one left is a bug of its own**: a counter zeroed at the warzone's reset
and filed under the computer's midnight files part of one game day under each of two
dates. When they are moved, the day key becomes the game's.

### Loses yesterday — the list to move, one at a time

| tally | where | what happens at the boundary |
|---|---|---|
| rally joins per type | `blobs` `rally_counts` (`panel/rally_limits.py:427`) | `RallyCounts.rolled` hands back an EMPTY count past `day_end_ms` (`:344`), applied on load (`:417`, `:451`) |
| errand runs today | file `timers_last_run.json` (`panel/timers.py:1964`) | `runs_today` reads 0 on a new day (`:2028`) and is written back zeroed (`:2080`) |
| alliance gifts taken | `blobs` `alliance_gifts_day` (`panel/runtime/gift_book.py:27`) | a different day reads as `{took: 0, runs: 0}` (`:58`); the next `note()` overwrites it (`:79`) |
| arms-race chests | `blobs` `arms_chests_day` (`panel/runtime/arms_book.py:38`) | a new day reads empty (`:68`) and `record()` writes over the old (`:99`) |
| fireworks heard / named / refused | `blobs` `firework_state` (`panel/runtime/firework_wire.py:359`) | four scalars zeroed on the day change |
| survivor tickets spent | `blobs` `SURVIVOR_TICKETS` (`panel/tabs/vs.py:744`) | `spent` set to 0 on a new day (`:787`) |
| star-round warzones walked | `blobs` `star_round_state` (`tools/lib/star_round.py:46`) | `{walked: [], laps: 0}` on a new day (`:166`, `:188`) |
| arena battles and wins | `blobs` `arena_live` (`panel/runtime/arena_live.py:46`) | every `record()` replaces the whole row (`:88`); yesterday's final score is gone |
| shop purchases | `blobs` `shops_live` (`panel/runtime/shops_live.py:39`) | a snapshot of the GAME's `bought`/`limit`, overwritten on every read (`:82`); the panel keeps no tally of its own at all |
| market / invasion lines | `blobs` `market_live`, `invasion_live` | one `{raw, at}` snapshot, overwritten (`market_live.py:85`, `invasion_live.py:94`) |
| secret-task robberies, ghost steals, trucks sent, treasure digs, and the rest of the daily checklist | **memory only** — `DailyReads._values` (`panel/runtime/errand_reads.py:66`) | overwritten by every read and lost entirely on a restart; consumers in `panel/runtime/errand_stats.py` |

**Nothing here is moved in one sweep.** Each is its own commit: add the day's row, write
to it where the counter is already written, and carry what is already counted into the day
it stands for — `<name>.imported` beside the database, like every other import here. A
counter the SERVER keeps (the five robberies, the arena's attempts) stays the game's to
answer; what this table holds is the history of those readings, so a graph can be drawn.

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
    settings.json               panel-wide: which profile shows, which are open, language, update channel
    timers.json                 template a new profile's timer catalogue is seeded from
    triggers.json               template a new profile's trigger catalogue is seeded from
    panel_debug.log             fallback debug log — only before a profile's own is open
    _bot/                       the DSL bot's own --profile files (NOT panel profiles)
      <id>.json
    <profile name>/             one directory per account
      config.json
      …everything below
```

`panel/paths.py` is the only file where any of these paths is written down. Every module
imports them from there — that is what stops the store from meaning two different places
in one process, which is exactly how it went wrong before (see «Why there were two» at
the bottom).

## Inside one profile — `profiles/<name>/`

### Settings

| File | What it is |
|---|---|
| `config.json` | this profile's settings. Only what DIFFERS from the `default` profile's own file; `default` holds the whole thing and is the base every other profile layers onto (#1246) |

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
deleted (see «The profile's database» below for the mechanics). What is left in this
table is either a CAPTURE CHECKPOINT (a channel between two processes, rewritten whole
every tick, deliberately worth nothing after a restart — moving it into the database
would only make it durable, which is the one thing it must not be) or an append-only log
(`.jsonl`), which was never the "whole file rewritten on every change" cost `panel.db`
exists to remove in the first place.

| File | What it is |
|---|---|
| `panel.db` | **THIS PROFILE'S DATABASE** (#1398, #1465, `panel/runtime/store.py`). One per profile, in the profile's own directory, reached through `rt.store` and opened nowhere else. Holds every whole-list checkpoint the panel keeps — the register of players (its own table, `players`, sorted and searched by), and everything below marked → `panel.db` (a named row in the shared `blobs` table — a new list-shaped store is a new `name`, not a new migration, the same way a new player is a new row and not a new migration). Its schema is a HISTORY (`MIGRATIONS`, `PRAGMA user_version`), not a `CREATE TABLE` written wherever somebody needed one |
| `secret_tasks.json` | what the secret-task scan currently sees on the map (a capture checkpoint, rewritten every tick — stays a file, see above) |
| `secret_tasks_state.json` → **`panel.db`** | the «Секретки» tab's OWN list — the starred tiles it is showing, with their countdowns, the book of what has been robbed and the book of what has been dismissed (#1242, #1280, #1416). **In the database since #1465**, under the name `secret_tasks_state` |
| `secret_tasks_log.jsonl` | append-log of secret-task findings. Append-only, never rewritten whole — stays a file |
| `secret_shared.jsonl` | which secret tasks have already been shared with the alliance (#1245). Append-only — stays a file |
| `ghost_recon_tiles.json` | what the ghost-recon scan currently sees (a capture checkpoint — stays a file) |
| `ghost_map_state.json` → **`panel.db`** | the «Призрак: карта» page's OWN list — what it has gathered and kept (#1251). **In the database since #1465**, under the name `ghost_map_state` |
| `world_treasures.json` | what the treasure scan currently sees (a capture checkpoint — stays a file) |
| `world_map.json` | what the SECOND listener inside the secret-task capture currently sees off the same map responses (#1289, #1335) — mines, player trucks, alliance trains and now players. A live view: rewritten every tick, stale rows evicted, each kind capped. A capture checkpoint — stays a file |
| `world_state_monsters.json` → **`panel.db`** | the world «Monsters» page's own gathered list — the ONE of the four world pages that keeps one at all; mines, trains and trucks are re-read from `world_map.json` above and never had a file of their own. **In the database since #1465**, under the name `world_state_monsters` |
| `players.json` → **`panel.db`** | the «Игроки» REGISTER — every player this account has met, kept for good (#1335, #1371). **In the database since #1398**; the file is imported once and then kept beside it as `players.json.imported`. Written through ONE entrance, `rt.players.sighted(records, source=…)` (`panel/runtime/players.py`), by everything that already sees a player: the map sweep's checkpoint, the live block of banners, the chat, the alliance roster and the owner of a tile. Every field carries `src[field] = [source, when]`, stamped when the VALUE changes and never on a mere re-confirmation — a lap re-lists four thousand unchanged players every twenty seconds. Not `world_map.json`: that one is what the capture can see right now, this one only ever grows and gives a row up for one reason, which is a person pressing «Забыть» (`panel/kept.py`, `PERSON_ASKED`). Holds what the map says (name, HQ level, alliance tag and name, coordinates, server, country), what a profile reply added if one ever arrived (power, army power, kills, SVIP), the note the GAME holds on that player, and the mark the PERSON wrote here — which no lap may touch |
| `rally_log.jsonl` | rally-monitor output. Append-only — stays a file |
| `rally_limits.json` | the per-KIND daily caps the auto-join obeys — a SETTING a person edits from the «Авторалли» page, so it stays a file. Since #1317 the kinds are the game's own species (Doom Elite, Doom Walker, Zombie Boss, the General's Trial's two instructors, the Alliance Exercise, the Zombie Invasion). It carries a `v`, which is what tells a pre-rename `doom_elite` from the species of that name and whether a seed of ours that changed has been carried across (`v = 3`: the Wandering Mummy Warlord went back to the ordinary twenty, and a file still holding the old seed is moved once and rewritten). Every kind ships capped at 20 and the four Golden ones uncapped. **The total daily ceiling is NOT here** — it is one number in the tab's config block (`autorally.daily_max`), judged against the game's own count, and neither is the soldier floor (`autorally.min_soldiers`) |
| `rally_counts.json` → **`panel.db`** | what the panel has counted today, per kind — a COUNTER, not a setting, so unlike its `rally_limits.json` neighbour it moved (#1465). The counts carry the client's own `day_end_ms`, so they reset on the SERVER's day. **In the database since #1465**, under the name `rally_counts` |
| `resource_stats.json` → **`panel.db`** | day-keyed tally of resources gained. A push can arrive several times a minute, and the old file was rewritten whole on every one — the exact cost this migration exists to remove. **In the database since #1465**, under the name `resource_stats` |
| `leaderboard_history.db` | accumulating snapshots of the ranking boards. Its own database, its own connection — not `panel.db`, because it is opened by a standalone collector (`tools/scan_leaderboard.py`) and by report tools that have no profile to ask for one. **Schema versioned the same way `players` is since #1465** (`tools/lib/leaderboard_store.py`'s own `MIGRATIONS`, `PRAGMA user_version`) — no more hand-added columns with no version behind them |
| `chat_log.jsonl` | raw capture written by the chat reader |
| `chat_history_<uid>.db` | the chat store the panel pages through — **one per character**, because one account can hold several and their chats must not mix. Its own database too, opened once per character on the Tk thread. **Schema versioned since #1465** (`panel/chat_history.py`'s own `MIGRATIONS`) |

### Schedule

| File | What it is |
|---|---|
| `timers.json` | this profile's timer catalogue: what runs, how often, with what arguments |
| `timers_last_run.json` | when each scheduled errand last ran, and — since #1333 — when it BEGAN (`began_at`). A daily errand's next turn is measured from the start rather than from the finish, so a run that straddles the server's midnight is charged to the day it actually spent. A file written before that has no `began_at` and falls back to the finish |
| `day_reset.json` | when THIS profile's warzone starts a new day — the client's own `GetTomorrowZero()`, re-read at most four times a day and kept so a fresh panel starts knowing it. Per profile because two accounts can be on two warzones, and every «раз в сутки» errand is anchored to the reset of its own. Never read → the measured 02:00 UTC stands in |
| `triggers.json` | this profile's wire- and poll-driven errands |
| `timers_seen.json` | every errand name this profile has ever been OFFERED (`panel/timers.py`, `adopt_new_errands`). It is what carries «this update learnt a new errand» into a profile that already has a catalogue of its own, **and** what keeps an errand the operator deleted deleted. Settings, not data — it belongs beside `timers.json` and stays a file. An earlier revision of this page called it a leftover nobody reads; that was wrong, and #1398 checked before believing it |

### Session bookkeeping

| File | What it is |
|---|---|
| `panel.lock` | an open file the panel holds an OS lock on for its whole life — «a panel is on this profile» answered by the kernel, so it cannot go stale |
| `panel_alive.json` | the heartbeat the open panel rewrites once a minute |
| `autostart.json` | what the hourly check last made of that heartbeat |
| `children-<pid>.json` | which child processes that panel process started, so a crashed panel's children can be cleaned up |

## Beside the profiles — `profiles/`

| File | What it is |
|---|---|
| `settings.json` | facts about the PANEL rather than about an account: `active_profile`, `open_profiles`, `language`, `dev_updates` (release channel vs branch tip) |
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

## The profile's database — `panel.db`

**One database per PROFILE, in that profile's own directory** (#1398,
`panel/runtime/store.py`). Not one per window and never «the first profile that opened»:
a register of players, a ★ list and a day's counters belong to an ACCOUNT, and a store
held in a module global belongs to whichever profile imported first — which is what
`docs/research/profile-isolation.md` is a list of. A caller asks `rt.store`; nothing
opens the file for itself.

### Why, in one measurement

On a live profile `players.json` was 11.5 MB and 17 374 rows. `json.load` took 0.97 s,
`json.dump` took 1.45 s, and the whole file was rewritten on **every change** — which,
while a lap of the map is running, is almost every tick. The «Игроки» page then read all
of it into memory to filter and sort it in Python. None of that is a bug in
`panel/kept.py`; it is what a whole-file JSON list costs once it stops being small.

### What is in it, and what is deliberately not

| | |
|---|---|
| **In** — data | the register of players (`players`, its own table), the book of star-secret-task days (`secret_days`, its own table since #1467 — it is searched by warzone and by day on every draw of the «Серверы» grid, which is the same reason `players` earned columns of its own), and, since #1465, in the shared `blobs` table: the ★ tile list with the book of what has been robbed and the book of what has been dismissed (`secret_tasks_state`), the ghost map's own list (`ghost_map_state`), the world monster page's own list (`world_state_monsters`), the daily rally counts (`rally_counts`) and the daily resource tally (`resource_stats`) |
| **Out** — settings | `config.json`, `timers.json`, `triggers.json`, `timers_seen.json` and **`rally_limits.json`**. A person edits these by hand, and «copy the folder and your panel comes with you» has to keep meaning something |
| **Out** — logs and session | `panel.log`, `debug.log*`, `autostart.log`, `panel.lock`, `panel_alive.json`, `autostart.json`, `children-<pid>.json` |
| **Out** — a capture's checkpoint | `secret_tasks.json`, `ghost_recon_tiles.json`, `world_treasures.json`, `world_map.json`. A capture CHILD writes them and the panel reads them: they are a channel between two processes, rewritten whole every fifteen seconds, and worth nothing after a restart — moving one into the database would make it durable, which is the one thing it must not be |
| **Out** — append logs | `rally_log.jsonl`, `secret_tasks_log.jsonl`, `secret_shared.jsonl`. Never rewritten whole, so the cost `panel.db` exists to remove was never theirs; the JSON-file rewrite that motivated #1398 does not apply to them |
| **Out** — schedule bookkeeping, not game data | `timers_last_run.json`. The SERVER told the panel nothing here — it is the panel's own record of when ITS OWN scheduled errands last fired, the same kind of fact as `panel_alive.json`/`autostart.json` above, not a tile or a tally |
| **Out** — a single cheap-to-reread reading | `day_reset.json`. One timestamp (`GetTomorrowZero()`), re-askable of the game in under a second and asked at most four times a day — kept only so a fresh panel does not have to ask before it can decide anything. Nothing here accumulates and nothing is lost by asking again, which is exactly the property a capture checkpoint has and a database row does not need to buy |

**The rally pair splits down that line and stays split**: `rally_limits.json` is a
SETTING (the per-kind caps a person edits) and remains a file; `rally_counts.json` is a
COUNTER (what today has spent) and goes into the database. Agreed with the operator
in #1398 — please do not re-litigate it in passing.

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

## A list whose removals name a reason — `panel/kept.py`

Three of these files lost data in one day, in the same way each time: a read came back
EMPTY or FAILED, was treated as authority, and rows a person had paid for with laps of the
map were deleted. #1272 answered it for the ★ tile list as a prose rule; #1282 put the
same invariant in a type, so the other stores can have it without anybody re-deriving it.

A `Kept` list has **no `clear()` and no way to assign its contents** — a wipe fails where
it is written. It removes rows through one door, and that door takes a reason:

| reason | what it means |
|---|---|
| `EXPIRED` | the row's own countdown ran out |
| `GAME_SAID_GONE` | the game answered ABOUT this row and said it is not there |
| `PERSON_ASKED` | somebody pressed «очистить» — the only clause that may empty a list |

Each store declares which of the three it accepts, so a list that may only shed expired
rows refuses the others by construction. **«The read came back empty» is deliberately not
a reason**: `merge()` only ever adds and updates, so an empty read removes nothing and a
partial one keeps the fields it did not mention. Writes are atomic — a panel killed
mid-save reads back the previous whole list, never half of one.

`tests/test_panel_kept.py` pins all of it, including the absence of every name a wipe
might plausibly be written under.

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

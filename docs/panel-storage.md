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

| File | What it is |
|---|---|
| `secret_tasks.json` | what the secret-task scan currently sees on the map (rewritten every tick) |
| `secret_tasks_state.json` | the «Секретки» tab's OWN list — the starred tiles it is showing, with their countdowns (#1242) |
| `secret_tasks_log.jsonl` | append-log of secret-task findings |
| `secret_shared.jsonl` | which secret tasks have already been shared with the alliance (#1245) |
| `ghost_recon_tiles.json` | what the ghost-recon scan currently sees |
| `ghost_map_state.json` | the «Призрак: карта» page's OWN list — what it has gathered and kept (#1251) |
| `world_treasures.json` | what the treasure scan currently sees |
| `rally_log.jsonl` | rally-monitor output |
| `rally_limits.json`, `rally_counts.json` | the per-KIND daily caps the auto-join obeys, and what the panel has counted today under each. Since #1317 the kinds are the game's own species (Doom Elite, Doom Walker, Zombie Boss, the General's Trial's two instructors, the Alliance Exercise, the Zombie Invasion) and the counts carry the client's own `day_end_ms`, so they reset on the SERVER's day. Both files carry a `v`, which is what tells a pre-rename `doom_elite` from the species of that name and whether a seed of ours that changed has been carried across (`v = 3`: the Wandering Mummy Warlord went back to the ordinary twenty, and a file still holding the old seed is moved once and rewritten). Every kind ships capped at 20 and the four Golden ones uncapped. **The total daily ceiling is NOT here** — it is one number in the tab's config block (`autorally.daily_max`), judged against the game's own count, and neither is the soldier floor (`autorally.min_soldiers`) |
| `resource_stats.json` | day-keyed tally of resources gained |
| `leaderboard_history.db` | accumulating snapshots of the ranking boards |
| `chat_log.jsonl` | raw capture written by the chat reader |
| `chat_history_<uid>.db` | the chat store the panel pages through — **one per character**, because one account can hold several and their chats must not mix |

### Schedule

| File | What it is |
|---|---|
| `timers.json` | this profile's timer catalogue: what runs, how often, with what arguments |
| `timers_last_run.json` | when each scheduled errand last ran |
| `triggers.json` | this profile's wire- and poll-driven errands |

### Session bookkeeping

| File | What it is |
|---|---|
| `panel.lock` | an open file the panel holds an OS lock on for its whole life — «a panel is on this profile» answered by the kernel, so it cannot go stale |
| `panel_alive.json` | the heartbeat the open panel rewrites once a minute |
| `autostart.json` | what the hourly check last made of that heartbeat |
| `children-<pid>.json` | which child processes that panel process started, so a crashed panel's children can be cleaned up |

A profile directory may also hold `timers_seen.json` — written by an older version, read
by nothing now. Harmless; delete it if you like.

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

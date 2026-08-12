# Where the client puts itself, and what an update moves

*Task #1320. Measured on a live machine on 2026-08-12, the day a client update landed.*

The bot resolves every one of these through [`tools/lib/game_paths.py`](../../tools/lib/game_paths.py)
and nowhere else (`CLAUDE.md`, «Nothing about one machine is written into the code»).
This note is the evidence behind the shape that module now has.

## 1. The symptom, and why it is misleading

After a client update the panel reported that it could not find the game. «Игра не
найдена» is a true sentence about at least three different situations:

* nobody has started the client;
* the client is running, and the bot is looking for the wrong window or process;
* the client is running and found, and some **path** the ability needs has moved.

From outside they are word for word identical, and the last two are exactly what a
client update can cause. That is why the fix is not «correct one literal» but «stop
having a single literal to correct», plus a diagnosis a person can read.

## 2. What the update of 2026-08-12 actually changed

Measured against a live client, in the order somebody would check them.

| Thing | Before | After | Verdict |
|---|---|---|---|
| Window title | the client's usual name | unchanged | ok |
| Process name | the client's usual name | unchanged | ok |
| Install folder | `%LOCALAPPDATA%\<publisher>\<product>` | unchanged | ok |
| Launcher / client executables | unchanged | unchanged | ok |
| Asset index (`gameres`) | in the install | unchanged | ok |
| **Bundle cache** | assumed `<install>\Cache\AssetBundles` | **another drive entirely** | **broken** |
| **Language tables** | newest build under the install | **a newer build in the download tree** | **silently stale** |
| Server port | the fallback constant | the client dials a different one | already handled — the capture tools ask the live socket |

Two real breakages, and the second is the nastier of the two: a stale language table is
a perfectly readable language table, so every reading taken from the game's own wording
(the sentence a session kick is recognised by, a glossary term) simply became one build
old with nothing to show for it.

**The install had no `Cache` folder at all.** Not moved within the install — gone from
it. The installer offers to keep the tens of thousands of downloaded bundles somewhere
else, and a machine that took the offer has them on a different disk from the game.

## 3. The launcher writes down what it chose

`LastWarLauncher.json`, beside the launcher, rewritten by every update. It is the only
thing on the machine that knows what THIS install decided, because it is written by the
thing that decided it:

```jsonc
{
  "app_name": "<the product>", "display_name": "<what the build calls itself>",
  "company_name": "<the publisher>",
  "app_dir": "<the install folder>",
  "uninstall_string": "\"<install>\\<sync>.exe\" --root \"<install>\" --app \"<download tree>\" --temp \"<staging>\" --bundle \"<bundle root>\""
}
```

The interesting directories are inside the uninstall command rather than fields of their
own, which is odd but stable, and `--bundle` is the answer no default can be. The window
title is in there too (`display_name`), which is what makes a renamed build findable
without anybody setting anything.

## 4. Two trees, and both hold language tables

Confusing them costs an afternoon:

* the **install** (`%LOCALAPPDATA%\<publisher>\<product>`) holds what the client shipped
  with — every language it has, in the build it was installed at;
* the **download tree** (Unity's `persistentDataPath`, under `%LOCALAPPDATA%Low`) holds
  what the client has fetched since — including a NEWER build of the language tables,
  but only for the languages actually being played in.

So neither tree is «the» answer. On the machine measured, the install held nineteen
languages at the older build and the download tree held exactly one at the newer one.
Taking «the newest build» whole would have lost eighteen languages the first time the
client updated; taking the install alone reads yesterday's wording for the language the
person is actually playing in. The answer is per language: the newest table for each,
wherever it sits (`game_paths.locale_tables()`).

## 5. What the code does now

1. **The manifest is asked before any default.** Download tree, bundle root, bundle
   cache and the build's own window title all come from it when it can be read; it never
   raises, and an unreadable one is simply «no answer from here».
2. **Where several answers are possible, the one that EXISTS wins** — except an
   environment variable, which wins outright whether or not the path is there. An
   override is a person's statement about their machine; quietly overruling a typo with
   the ordinary install is worse than failing on it.
3. **The window is found by process when no title matches.** Several titles are tried
   (the build's own, then the one the client has always used, or whatever
   `LW_WINDOW_TITLE` names — several, separated by `;`); failing all of them, the largest
   visible window of the game's own process is the client, whatever it calls itself. It
   warns on the way past, naming the title it found, because that is what belongs in the
   variable.
4. **A search that comes up empty explains itself, once.** Every path, what it resolved
   to, what supplied that answer, whether it is on disk, and the variable that moves it —
   into the debug log the first time a probe finds no client.

## 6. Checking a machine by hand

```
C:\Python312\python.exe tools\lib\game_paths.py     # …or python3, from WSL
```

One line per path, `ok` or `MISSING`, with the source and the override beside it, and
the window titles and process name it will search for. Exits non-zero when something is
missing, so it can be the first thing anybody runs when an install stops being found.

## 7. What is NOT worth doing

* **Watching the manifest for changes.** It is read on demand and cached against its own
  timestamp, so an update is picked up without a restart. A watcher would be a thread
  for a file read that costs under a millisecond.
* **Deriving the install from the running process.** Tempting — the client's executable
  path names it — but it only answers while the client is up, and every one of these
  questions is asked precisely when it is not.
* **Guessing drives.** The bundle root can be anywhere; the manifest already knows, and
  `LW_BUNDLE_ROOT` covers the case where it does not.

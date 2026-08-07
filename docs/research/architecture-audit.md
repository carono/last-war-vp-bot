# Architecture audit — what to optimise and what to rebuild (task #1279)

An audit, not a rewrite. Nothing here was changed; every item is a proposal with a
number in front of it, an estimate of the win, an estimate of the risk, and a size.
The list is sorted by win/risk, and the last section is what NOT to do and why.

**Everything below was measured on this checkout or read out of the commit history.**
Where a number came from an earlier task's write-up it says so and names the file; where
it was taken during this audit the command is given, so it can be taken again.

Read alongside [`game-call-latency.md`](game-call-latency.md) (the press, link by link),
[`panel-freezes.md`](panel-freezes.md) (the Tk thread) and
[`panel-tabs-refactor.md`](panel-tabs-refactor.md) (how the tabs became plugins). This
file does not repeat what they measured; it says what is left.

## How the numbers were taken

```
# the panel's own cost, on the Windows interpreter, in a throwaway worktree
C:\Python312\python.exe -X importtime -c "import sys;sys.path[:0]=['.','tools/lib','src'];import panel.__main__"
C:\Python312\python.exe tests\test_panel_page_build.py         # the page-build harness
C:\Python312\python.exe tools\dev\panel_load_bench.py          # event-loop lateness, N profiles
```

The page-build figures come from `tests/test_panel_page_build.py::_Harness` driven four
times in one process: the first build still has the tab modules to import, the rest are
warm. The commit-history figures come from `git log -200` over the tree.

## The shape of the tree, for scale

| | files | lines |
|---|---|---|
| tracked Python | 315 | 125 509 |
| `panel/` | 96 | 41 242 |
| `tools/` (excl. ignored `scratch/`, `archive/`) | 111 | 56 957 |
| `tests/` | 86 | 36 168 (1 394 test functions) |
| `src/lastwar_bot/` | 22 | 4 286 |
| scenarios `actions/*.md` | 32 (+ 10 under `dev/`) | — |
| locale keys | 1 323 × 11 languages | — |

---

# 1. The press, from the button to the game

The chain itself was measured under #1230 / #1232 and is not re-litigated here: under
3 ms of Python in front of the call, ~2 client frames of floor (33 ms at 60 fps, 75 at
21), and the answer channel already moved off `Player.log`. What is left is everything
that still SLEEPS or still SERIALISES.

## 1.1 The daemon holds its lock across the settle — WIN/RISK: high

**Fact.** `tools/lua_daemon.py::Daemon.run` takes `self._lock` and holds it for the whole
of `LuaEval.run`, and `lua_eval.collect` does its sleeping *inside* that call. So a
background reader waiting out a deadline blocks every press behind it. Across `tools/`
alone there are **132 places that pass a settle, summing to 164.8 s of literal wait,
median 1.20 s per call**.

The lock exists because the hijack is not reentrant. The settle is a wait AFTER the
invoke and needs no lock at all. #1230 already named the blocker: two chunks reading the
answer file at once would have to tell their lines apart, and every one writes under
`ACT`.

**Change.** Give each call its own identity. `lua_eval.wrap_chunk(chunk, path)` already
takes the answer path as a parameter, so the cheapest form is a per-call nonce written
into the preamble and matched by `collect` alongside the marker; the byte offset stays as
it is. Then `Daemon.run` holds the lock for `_send` only, and `collect` runs outside it.

* **Win:** every background read stops standing in front of the next press. This is the
  measurement to watch afterwards (see §6.7): lock-seconds per wall-minute at idle.
* **Risk:** medium. Concurrency around a hijack that must stay serialised; a nonce that
  leaks into a chunk's own output would corrupt an answer.
* **Size:** ~1 day, plus an acceptance run of `tools/dev/check_answer_channel.py`.

## 1.2 `early` is opt-in, and `tools/` never opted in — WIN/RISK: high

**Fact.** `early=True` (settle becomes a deadline) appears at **8 places in production
code, all of them under `panel/`** — plus `script_engine._run_lua`, which asks for it on
everything a scenario runs. **`tools/` has none**: 132 settle sites, 164.8 s of literal
sleep, all patient.

The consequence is concrete and is the one CLAUDE.md points at. `tools/ghost_recon_steal.py
--queue-only` — the child the ghost robbery still spawns — is `read_status` (settle 1.0)
plus `ghost_recon_queue_set` (settle 0.6): **1.6 s of pure sleep** out of a run that also
costs two round trips.

**Change.** Two steps, in this order.

1. **Cheap and safe:** pass `early=True` at the tool call sites whose chunk logs its own
   whole answer — which is what `read_status` and `queue_set` both do. One line each.
2. **Then invert the default.** `patient=True` becomes the opt-in for the chunks whose
   marker is an ACKNOWLEDGEMENT and whose answer arrives later with a server reply (the
   treasure refresh and the command-post reads are the ones #1230 named). Prefer the SURE
   form where the chunk has a recognisable last line: `sentinel=` ends the wait without
   guessing, and there are only 7 uses of it today.

* **Win:** step 1 is ~1.6 s off the ghost robbery for an hour's work. Step 2 is most of
  the 164.8 s budget, spread over every tool a person or a timer runs.
* **Risk:** step 1 low; step 2 medium-high — a wrongly flipped caller returns an EMPTY
  LIST and says nothing. Mitigate by flipping one file at a time with a sentinel.
* **Size:** 1 hour, then 1–2 days.

**And correct the note in `CLAUDE.md` while doing it.** It charges the spawned child with
five seconds and tells the next agent to «measure the child before deciding it is
affordable». Measured: **starting the Windows interpreter and importing the tool is
0.21 s** (`tools/ghost_recon_steal.py --help`, three runs; a bare interpreter is 0.151 s,
the module import 0.11 s). The spawn is not the cost. The patient settles are.

## 1.3 A button's `wait` is a fixed sleep chosen by feel — WIN/RISK: medium-high

**Fact.** `tools/lib/game_buttons.py` has 55 entries; **56 `wait` values summing to
62.5 s, median 1.0 s, maximum 4.0 s**, and every one of them is a round number. They are
unconditional `time.sleep` calls in `script_engine._do_tap`. #1230 measured what that
means for a single press: `TAP call_help xall` with one press to make cost **1228 ms, of
which 1000 was the button's own pause**.

They are not all wrong — a press whose effect only lands with a server reply genuinely
has to wait — but nothing distinguishes those from the ones that were guessed.

**Change.** Let the wait be a DEADLINE over a re-read, the same trick as `early`. Add an
optional `verify_lua` to `Button` (§4.1 wants it anyway, for a different reason): press,
then poll that expression until it moves, up to `wait`. A button with no `verify_lua`
keeps exactly today's behaviour, so this is incremental by construction.

* **Win:** a recipe is mostly pauses — `collect_alliance_gifts` is 4.3 s of them against
  4 ms of interpreter. Halving the guessed ones halves the recipe.
* **Risk:** medium — a next step that starts before the client is ready looks like a
  flaky game rather than a bad deadline.
* **Size:** 1 day for the mechanism, then one expression per button, incrementally.

## 1.4 `collect` re-reads the whole tail on every poll — WIN/RISK: medium, small

**Fact.** `lua_eval.collect` calls `_tail(path, since)` and `_matching()` every
`POLL_SEC` (10 ms), each time reading and splitting everything the chunk has written so
far. A 200-line answer polled over a 2 s deadline is up to 200 full re-reads and
re-splits of the same text.

**Change.** Advance `since` as lines are consumed and only split what is new.

* **Win:** milliseconds, and it matters exactly where the answers are biggest — the map
  sweep and the alliance dumps.
* **Risk:** low. **Size:** an hour. Covered by `tests/test_lua_settle.py`.

---

# 2. The panel

## 2.1 Cold start: 0.35 s of it is two imports nothing needs yet — WIN/RISK: high

**Measured** (`-X importtime`, three runs, Windows 3.12):

| | cost |
|---|---|
| `import panel.__main__`, whole | 0.99 – 1.39 s |
| ↳ `panel.runtime.autostart` | 207 ms — of which `xml.sax.saxutils` **158 ms** |
| ↳ `panel.runtime.diag` | 172 ms — of which `urllib.request` / `http.client` / `ssl` / `zipfile` via `panel.debug_sender` |

Neither is needed to draw a window. `autostart` pulls an XML writer for the scheduled
task; `diag` pulls an HTTP stack for sending a log somebody has to press a button to send.

**Change.** Move both imports inside the functions that use them.

* **Win:** ~0.35 s off every panel start — and off every `python -m panel.tabs.<id>` and
  every child process that imports the runtime.
* **Risk:** low. **Size:** an hour.

## 2.2 Page build, today's numbers — a baseline, not a complaint

Four builds in one process, a temporary profile, `staged=False`:

```
import panel + harness            1389 ms
first page build                  1667 ms      7 tabs made, 3 drawn (the EAGER ones)
warm page build   454 / 411 / 414 ms   median  414 ms
```

Against #1215's recorded 1209 ms first / 471 ms warm: **the warm build is fine and the
first has grown 38 %**. The lazy contract itself still holds — three of seven drawn — so
the growth is in the eager tabs and the registry, not a regression of laziness. Worth a
number in the bench (§6.2) rather than a fix.

## 2.3 The phone defeats the laziness it polls — WIN/RISK: medium

**Fact.** `panel/web/api.py::screen` calls `rt.tabs.realize(tab)` and then
`tab.web_view()` **on the Tk thread**, and `panel/web/static/app.js` polls it every
`POLL_MS = 2500` while the page is visible. So a phone left on a screen forces that tab
to be BUILT (undoing #1215 for it) and then hops the Tk thread twice every 2.5 s, per
open screen, per profile — which is the shape #1226 spent a task removing.

**Change.** Build the view once and serve a cached copy; invalidate it from the tab's
own tick/bus when a reading actually moves. `realize` stays, but once.

* **Win:** the phone stops being a second event-loop tenant; the Tk thread's p95 lateness
  with several profiles open stops depending on how many phones are awake.
* **Risk:** low-medium — a stale card is worse than a slow one, so the invalidation has
  to be wired per tab.
* **Size:** half a day plus one line per tab that already has `web_view`.

---

# 3. Architecture — where the second copies of the truth live

The «panel only plays scenarios» rule is largely held, and it is worth saying so with a
number: **45 places under `panel/` play a scenario against 11 that call the VM directly**,
and of those 11, nine are reads. That is not where the debt is.

## 3.1 `panel/__main__.py` is 4 898 lines and one class — WIN/RISK: medium, large

**Fact.** One `Panel(tk.Tk)` with ~180 methods, holding: the dashboard poller, the update
block, recovery, the watchdog, panic/resume, geometry and the resize damper, the log
widget, the command line, the game-button row, the coordinate jump, the profile dialogs.
CLAUDE.md says nothing new goes in it. **In the last 200 commits it was touched by 20
different tasks** — the third-largest contention surface in the tree.

**Change.** One block per task, into `panel/runtime/`, exactly as the tabs became plugins.
Start with the two that are already self-contained: the dashboard poller
(`_dash_loop` / `_dash_tick` / `_render_dashboard`, which already has `panel/dashboard.py`
beside it) and the update block.

* **Win:** the shell stops being where unrelated tasks collide, and «nothing new goes in
  `__main__.py`» becomes true rather than aspirational.
* **Risk:** medium-high — it is the boot path — but LOW per block if done one at a time.
* **Size:** several days total; each block is half a day.

## 3.2 A tab's settings live in its widgets — WIN/RISK: medium, large

**Fact.** 17 tabs implement `config()` / `apply_config()`, and `config()` READS Tk
variables. Three consequences, all of them already-observed failures rather than theory:

* an undrawn tab has no widgets, so it must hand back `stored_config()` instead — the
  contract calls this out as the half that «would fail SILENTLY», and getting it wrong
  writes defaults over every tab's settings at once (`panel/tabs/base.py`,
  `docs/panel-tabs.md`);
* writing `config.json` under an OPEN profile is silently undone by the binder's next
  save (project memory, «Открытый профиль живёт в виджетах»);
* the web front-end has to hop the Tk thread to read a setting, which is §2.3.

**Change.** A per-profile settings store as the single source; widgets bind to it rather
than being it. `config()` disappears; `stored_config` disappears with it.

* **Win:** removes a whole class of quiet data loss and unblocks §2.3.
* **Risk:** high — it touches every tab.
* **Size:** large. Do it behind `PanelTab` so tabs migrate one at a time and the two
  models coexist during the move.

## 3.3 «Raidable» is written three times — WIN/RISK: medium

**Fact.** The same eligibility rule — the owner's dispatch has completed, the tile has
not expired, a loot slot is free — is implemented independently in:

* the wire decoder — `tools/lib/lastwar_proto.py::SecretTask.can_loot` and
  `GhostTask.can_loot` (two of the three `can_loot` properties in that file);
* the Lua reads — `lua_actions.secret_task_raidable_alliance()` and its wider sibling;
* the panel — `SecretTasksTab._raidable` / `_collectable` / `_takeable`.

Each carries its own game-clock handling. Two of the three splits are DELIBERATE and
documented (the human's ten-second window against the standing order's two), and those
should stay; what should not is three separate answers to «has this tile matured».

**Change.** One Python predicate over a normalised row, called by the decoder, the tool
and the tab alike. The Lua keeps the READ and loses the rule.

* **Win:** a game change is one edit instead of three, and the tool can no longer rob
  tiles the tab does not list (which is what #1267 was).
* **Risk:** medium. **Size:** 1–2 days.

## 3.4 Eleven of nineteen tabs are `in_development` — a question, not a finding

`panel/tabs/__init__.py` marks 11 of 19 `in_development=True`, so a profile that is not in
development mode shows **7 tabs**. Two of the hidden ones are `EAGER` — `command_post`
and `treasure_debug` — and EAGER means «this has to be listening whether or not anybody
opens it». Worth confirming with the person that the ghost standing order and the
treasure drain are meant to be off for an ordinary profile; #1273 already had to correct
`farming.md` for promising a button the reader did not have.

---

# 4. Development quality — the invariants that are prose instead of code

## 4.1 A plain `TAP` reports success from «the Lua did not raise» — WIN/RISK: high

**This is the mechanism behind «панель уверенно сообщает не то», and it is countable.**

`script_engine._press_button` wraps the button's Lua in a `pcall` and logs
`ACT tap=ok` when it did not throw. That says the call ran. It does not say the game did
anything.

| | count |
|---|---|
| buttons in the catalogue | 55 |
| …with a `count_lua` (so `xall` can verify by re-reading) | 15 |
| …with nothing to verify against | **40** |
| `TAP` lines in the shipped recipes: `xall` (verified) | 12 |
| `TAP` lines in the shipped recipes: plain (unverified) | **32** |

So **32 of 44 presses in `actions/*.md` cannot tell «pressed» from «did anything»**. Six
fixes in one day were the same shape — the client was told it was being restarted and
was not (#1259), «Развести клиенты…» reported success and changed nothing (#1263), a live
socket of another service vouched for a dead game link (#1266), «на связи» was read as
«готов играть» (#1269) — and every one of them is an action reporting from the fact that
it was ISSUED rather than from a re-read of the thing it changed.

**Change.** An optional `verify_lua` on `Button`: an expression whose CHANGE after the
press is the proof. `TAP` fails when it does not move; `wait` becomes the deadline on it
(§1.3, same edit). A button without one behaves exactly as today, so this ships
incrementally and never breaks a recipe on the way.

* **Win:** the class, not one instance of it — plus §1.3's speed as a side effect.
* **Risk:** low-medium. **Size:** 1 day for the mechanism, then per button.

## 4.2 A failed read may still delete stored state — WIN/RISK: high

**Fact.** Three data losses in one day, all the same class: an EMPTY or FAILED read was
treated as authoritative and used to delete rows the person had paid for with laps of the
map (`7885032`, `a1bf34b`, `1511c48`). #1272 answered it properly for ONE list — a prose
rule (`THE_LIST_RULE` in `panel/tabs/secret_tasks/tab.py`), every removal site naming its
clause, and an audit test that walks every door.

The rule is right and the write-up says why. What it is not is CHECKABLE anywhere else.
The other stores the panel keeps have no such guard: `ghost_map_state.json`,
`rally_limits.json` / `rally_counts.json`, `resource_stats.json`, `secret_shared.jsonl`,
`timers_last_run.json`, the chat databases (`docs/panel-storage.md` lists them all).

**Change.** Put the invariant in a TYPE. A small store whose only removal API takes a
reason — `EXPIRED` / `GAME_SAID_GONE` / `PERSON_ASKED` — and which has no `clear()` at
all; each store declares which clauses it accepts. A wipe then fails to compile rather
than shipping and being found by the person who lost the data.

* **Win:** «three fixes would leave a fourth waiting» stops being true.
* **Risk:** low — additive, and the secret-task list is a ready-made first customer.
* **Size:** 1–2 days.

## 4.3 There is no way to run the tests — WIN/RISK: highest in the document

**Fact.** 86 test files, 1 394 test functions, 36 168 lines — **29 % of the tracked
Python** — self-running scripts with no runner, no CI, no tiering, and a mix of what needs
Tk, a display, or a live client. `AGENTS.md` §8 says «no pytest» and stops there. There
is no command an agent can run before committing.

**What that costs, measured today:**
`tests/test_panel_page_build.py::test_a_page_draws_only_the_tabs_that_have_to_be_there`
is **RED on clean `HEAD`** (checked in a throwaway worktree at `7727e60`, so it is not
somebody's uncommitted work). It asserts `len(tabs) - len(drawn) > 5`; #1273 hid 11 tabs
behind development mode, so a default profile now has 7 tabs and 4 undrawn. A #1215
regression guard was broken by #1273 and nobody knew — which is exactly what a suite
nobody can run is for.

**Change.** `tools/run_tests.py`, three tiers and one exit code:

| tier | needs | what it holds |
|---|---|---|
| `offline` | nothing | parsers, the DSL, the Lua chunks through `lupa`, the locales, hygiene |
| `ui` | Tk + a display | the page build, the tab contract, the dialogs |
| `live` | a running client | the acceptance probes |

Then one line in `AGENTS.md` §8 saying to run `offline` before every commit and `ui`
before every panel commit. **And fix the red test by asserting the RATIO** — every
non-EAGER tab is undrawn — so the next `in_development` change cannot break it again.

* **Win:** the cheapest quality item in this document by a distance.
* **Risk:** none. **Size:** half a day.

## 4.4 Tests that assert on source TEXT — WIN/RISK: medium

**Fact.** **27 test files open a `.py` file and read it as text.** Some of them are
legitimate and should stay — the AST guards (`test_proc_table`, `test_panel_i18n`,
`test_panel_dangling_refs`) parse rather than grep, and what they check has no runtime
form. The rest assert substrings, and the sharpest are in `test_panel_web.py`:

```python
shell = (_REPO / "panel" / "__main__.py").read_text(encoding="utf-8")
assert "gamectl.CONTROLS" in shell, "the window no longer builds its row from the table"
assert "panelctl.request" in shell, "the window restarts by some other route"
```

Both pass over DEAD code and fail on a rename. They assert that a name appears in a file,
which is not the fact anybody cares about.

**Change.** Where the fact has a runtime form, assert the runtime form — the harness
already exists (`tests/test_panel_page_build.py::_Harness` builds a real page against a
temporary profile). «The window builds its row from the table» is: build the row, compare
it to `gamectl.CONTROLS`. Keep text assertions only for what has no runtime form —
locale files, `.gitignore`, batch line endings, the AST guards (`test_proc_table`,
`test_panel_i18n`), which are a different and legitimate thing.

* **Win:** removes false green. **Risk:** none. **Size:** incremental, per test.

## 4.5 `early` / `sentinel` / patient is decided 155 times with nothing to check it

The choice belongs to the CHUNK — does its marker line carry the answer, or merely
acknowledge a request the server will answer later? — and is made at the CALL SITE, once
per caller, from a docstring — **155 call sites across `tools/`, `panel/` and `src/`**.
There is no test that can catch a wrong one; a wrong one returns an empty list silently.

**Change.** Declare it where the chunk is built (`lua_actions`), and let the call site
derive it. Then §1.2's inversion is a property of ~280 chunks instead of a decision at
155 call sites, and it becomes checkable.

* **Win:** makes §1.2 safe. **Risk:** low. **Size:** 1 day, best done as §1.2's first step.

---

# 5. The shared tree and working in parallel

## 5.1 The locale files are the collision surface — WIN/RISK: highest in this section

**Fact.** In the last 200 commits:

| file | distinct tasks that touched it |
|---|---|
| each of `panel/locales/{de,en,es,fr,id,it,pl,pt,ru,tr,vi}.json` | **37** |
| `docs/farming.md`, `docs/farming.ru.md` | 20 |
| `panel/__main__.py` | 20 |
| `panel/tabs/secret_tasks/tab.py`, `docs/panel-tabs.md`, `tools/lib/lua_actions.py` | 17 |

**85 of 200 commits (43 %) touch all eleven locale files**, because the rule — correctly —
says a key lands in every shipped locale in the same commit. With one working tree and
one index, two agents adding a key collide every single time.

**Change.** Split by TAB, not by language: `panel/locales/<lang>/<tab>.json`, merged at
load. Two agents working on two tabs then never touch the same file.
`tests/test_panel_i18n.py` keeps its guarantee word for word — it walks the loaded table,
not the file.

* **Win:** removes ~43 % of the collision windows in the tree.
* **Risk:** low — a loader change plus a one-shot migration script.
* **Size:** half a day.

The `farming.md` pair is the same problem without the same cure (they are prose). The
cheap half: make the progress bar a GENERATED artefact so
`tools/farming_progress.py --write` cannot be the thing two commits fight over.

## 5.2 A worktree per agent is the right answer, and something small blocks it

**Fact, measured.** `git worktree add` run from WSL writes `gitdir: /mnt/p/…` into the
worktree's `.git` file. The Windows interpreter that runs the tests cannot resolve it:

```
fatal: not a git repository: /mnt/p/…/.git/worktrees/audit1279
```

Three checks in `tests/test_repository_hygiene.py` shell out to `git` and therefore FAIL
inside a worktree while passing in the main tree — which makes «give each agent its own
worktree» look broken when it is not.

**Change.** Either create worktrees with Windows git at a Windows-visible path, or make
those three checks locate the repository by walking up from `__file__` rather than by
asking `git`. The second is one function and fixes it for every future runner.

* **Win:** unblocks the only real cure for a shared index — and everything in §5.1 and
  §5.3 becomes much less urgent once agents are not in one tree.
* **Risk:** low. **Size:** an hour.

## 5.3 Authorship cannot be attributed after the fact

**Fact.** All 200 of the last commits carry ONE author — the project's shared identity —
and 188 of them carry a `Co-Authored-By` naming the model rather than the worker. So
«somebody else's edit landed in my commit» cannot be detected, only remembered.

**Change.** Set `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` per worker session, or add a
`Worker: #<task>` trailer. Costs nothing, and makes the next audit of this possible.

* **Win:** the failure becomes visible. **Risk:** none. **Size:** minutes.

---

# 6. What to measure continuously

One tool — `tools/dev/bench.py` — writing one JSON line per run, so a regression is a
diff and not a complaint. Nine numbers, with today's values as the baseline:

| # | number | today |
|---|---|---|
| 1 | `import panel.__main__` | 0.99 – 1.39 s |
| 2 | first page build / warm page build | 1667 ms / 414 ms |
| 3 | undrawn-tab RATIO (not a count — §4.3) | 4 of 7 (all non-EAGER) |
| 4 | one chunk round trip, warm daemon, `settle=0`, no marker; log `Time.deltaTime` beside it | floor is ~2 client frames — 33 ms at 60 fps, 75 at 21 |
| 5 | `TAP <button>` end to end with nothing to do | 191 ms (#1230, `steal_secret_task xall`) |
| 6 | time to the first `world.get.block` after a jump | whole map in ~3 s (#1265) |
| 7 | **daemon lock occupancy at idle** — lock-seconds per wall-minute | not measured yet; this is the number that says whether §1.1 and §1.2 worked |
| 8 | Tk event-loop lateness p95 / worst, N profiles open | `tools/dev/panel_load_bench.py` already prints it |
| 9 | test-suite wall time and red count, per tier | no runner yet (§4.3) |

Numbers 1–3 and 9 need no game and belong in whatever runs before a commit. 4–7 need a
live client and belong in an acceptance run. 7 is the one to add first: it is the only
one that can tell «the panel feels slow» from «the client is at 21 fps».

---

# 6a. What was carried out — task #1282

Eleven commits, in the order the table below sorts by. Every number here was taken on
this checkout the way §«How the numbers were taken» says; where an item was NOT done, the
reason is written down rather than left to be guessed at.

| § | what happened | number, before → after |
|---|---|---|
| 4.3 | `tools/run_tests.py`, three tiers (`TIER = "ui"` / `"live"` in the file, **no declaration means `offline`**), and the red guard rewritten as a RATIO — no tab that is not `EAGER` is drawn with the page | page-build file 10/11 → 11/11; baseline recorded: offline 31/37 green in 344 s, ui 40/48 in 137 s |
| 2.1 | `xml.sax.saxutils` (and `urllib`/`ssl`/`http.client` behind it) and `panel.debug_sender` (`zipfile`) moved into the functions that use them | `autostart` 54.5 → 20 ms, `diag` 33 → 0.6 ms, `import panel.__main__` 240–306 → 197–212 ms warm |
| 1.2 step 1 | `early=True` on the tools' reads that log their whole answer in one line — ghost `read_status` / `queue_set` / the per-tile `can_steal` probe, secret-task `queue_set` and the detail read-back | ghost `--queue-only`: 1.6 s of sleep → ~30 ms per line |
| 5.2 | `tools/lib/repo_git.py` — the git directory resolved and spelled for whichever platform asks (`/mnt/p/…` ⇄ `P:\…`) | hygiene in a WSL-made worktree 4/6 → 6/6, and the `check-ignore` check no longer reads git's 128 as «not ignored» |
| 5.1 | `load_locale` merges `panel/locales/<lang>.json` with `panel/locales/<lang>/<tab>.json`; `tools/dev/split_locales.py` migrates a prefix at a time | reading half only — see below |
| 5.3 | a `Worker: #<task>` trailer, written into `AGENTS.md` §8 | — |
| 4.2 | `panel/kept.py` — no `clear()` at all, removals name `EXPIRED` / `GAME_SAID_GONE` / `PERSON_ASKED`, each store declares which it accepts, `merge()` only adds | 11 tests; no store migrated onto it yet — see below |
| 4.1 + 1.3 | `verify_lua` on `Button`: the before-value read in the same chunk as the press, then polled, and `wait` becomes the DEADLINE on that poll. A press that changed nothing fails the recipe | mechanism + 8 tests; **no button declares one yet**, so no recipe changed |
| 4.4 | the two source-text assertions in `test_panel_web.py` replaced by building the page and pressing the button; `_Runtime` given the real `recovery` / `panic` it had fallen behind | 55/69 → 69/69 |
| 1.4 | `collect` advances a byte cursor and splits only what is new; a partial last line is held back until its newline | up to 200 full re-reads of a 200-line answer → each byte read once; and a half-written line can no longer be returned as an answer |
| 6 | `tools/dev/bench.py` — numbers 1, 2, 3 and 9, one JSON line per run into `results/bench.jsonl` | today: import 0.135 s, first page build 1.04 s, warm 0.359 s, 3 of 7 tabs drawn and all three EAGER |

**What the runner found the moment it existed.** Twelve test files are RED on clean
`HEAD` (checked in a throwaway worktree at `c06cf51`, so none of it is somebody's
uncommitted work), and not one of them needs a game: `test_game_primitives` 46/63,
`test_rally_create` 7/16, `test_panel_web` 55/69, `test_panel_command_post` 20/21,
`test_panel_daemon_port` 7/8, `test_panel_multi_profile` 22/26, `test_panel_profile_compat`
and `test_secret_missions` crashing outright, `test_game_port_detection` 12/14, the two
street-run files, and the page-build guard. Two of them were fixed here (`test_panel_web`,
`test_lua_settle` — whose stand-in had fallen behind #1272 and silently went looking for a
live client). The rest are what a suite nobody could run looks like after a while, and
they are now visible instead of theoretical.

## What was deliberately NOT done, and what each one is waiting for

* **1.1, the lock off the settle.** The design is unchanged from §1.1 and the cheapest
  form is not the nonce but a per-CALL answer file — one path per call, no cross-talk to
  disambiguate, `collect` outside the lock. What stops it landing here is not the code: it
  changes when a second chunk may be INJECTED, and the hijack parks the game's main
  thread. Nothing offline can tell a working version from one that wedges the client, and
  the acceptance run (`tools/dev/check_answer_channel.py`) needs a live game. It goes in
  with a client running, and is the first thing to measure afterwards (§6, number 7).
* **1.2 step 2, inverting the `early` default**, and **4.5, declaring the answer shape on
  the chunk.** Step 1 is in; the inversion is a property of ~280 chunks in
  `tools/lib/lua_actions.py`, which was being edited by another worker throughout this
  task. It is one file, one worker, one sitting — not something to interleave.
* **3.3, one raidable predicate**, for the same reason: it spans the decoder, the Lua
  reads and the secret-task tab, and the tab was under active edit (#1272, #1280).
* **2.3, caching the phone's view.** The cache is easy; the INVALIDATION is the design,
  and doing it per tab means editing every tab that has a `web_view`. Doing it by a short
  max-age instead would make a card stale for exactly as long as it saves, which is the
  one thing §2.3 says not to do. It wants the person's call on which tabs may lag and by
  how much, and it wants the tabs to be quiet.
* **3.1 (the shell, one block per task) and 3.2 (settings out of the widgets).** Days
  and «large» respectively, both across files several tasks touch at once. Neither is a
  thing to start in the same hour as eleven other changes.
* **5.1, the locale migration itself.** The reader takes both layouts and the migration
  tool is written and dry-runnable, but the move rewrites all eleven files in one go and
  another worker had locale edits in flight for the whole of this task. Run
  `tools/dev/split_locales.py <prefix>` per prefix when the tree is quiet — `log` (188
  keys), `web` (95), `secrettasks` (81), `vsduel` (81) first.
* **4.2's first customer and 4.1's first button.** Both mechanisms are additive by
  design and both first customers live in files that were being edited: the ★ list
  (`panel/tabs/secret_tasks/tab.py`) and any button whose `count_lua` would be its
  verifier. Each is a small, separate change with a live check behind it.

---

# 7. Sorted by win / risk

| | item | win | risk | size |
|---|---|---|---|---|
| 1 | §4.3 test runner with three tiers, and fix the red guard as a ratio | highest | none | ½ day |
| 2 | §2.1 defer the `autostart` / `diag` imports | 0.35 s off every start | low | 1 h |
| 3 | §1.2 step 1 — `early=True` in the tools' status/queue reads | 1.6 s off the ghost robbery | low | 1 h |
| 4 | §5.2 unblock worktree-per-agent | removes the shared index | low | 1 h |
| 5 | §5.1 locales split per tab | −43 % of collision windows | low | ½ day |
| 6 | §5.3 per-worker authorship | makes the failure visible | none | minutes |
| 7 | §4.2 a store type whose removals name a reason | a class of data loss | low | 1–2 d |
| 8 | §4.1 `verify_lua` on buttons | a class of false «done» | low-med | 1 d + per button |
| 9 | §1.3 `wait` becomes a deadline (same edit as 8) | halves a recipe | medium | 1 d |
| 10 | §1.1 the lock off the settle | background reads stop blocking presses | medium | 1 d |
| 11 | §4.5 declare the answer shape on the chunk | makes 12 safe | low | 1 d |
| 12 | §1.2 step 2 — invert the `early` default | most of 164.8 s | med-high | 1–2 d |
| 13 | §3.3 one raidable predicate | one edit instead of three | medium | 1–2 d |
| 14 | §2.3 cache the phone's view | the phone stops being a loop tenant | low-med | ½ day |
| 15 | §1.4 `collect` reads only what is new | ms, where answers are biggest | low | 1 h |
| 16 | §3.1 the shell, one block per task | the top collision file shrinks | med-high | days |
| 17 | §3.2 settings out of the widgets | a class of quiet loss | high | large |

---

# 8. What NOT to do, and why

1. **Do not rewrite `panel/__main__.py` in one go.** It is the boot path and twenty
   different tasks touched it in the last two hundred commits; a big refactor is
   guaranteed to meet somebody else's edit. One block per task or not at all (§3.1).

2. **Do not chase one hijack instead of two.** #1230 costed it: 33 ms → 16 ms at 60 fps.
   That is below anything a person can feel, and the price is live shellcode in a process
   somebody is playing in. The research file already lists it as «left on the table»; it
   should stay there.

3. **Do not remove the ghost robbery's spawned child «because the secret-task one
   worked».** Measured here: the spawn is 0.21 s and the sleeping is 1.6 s. Do §1.2 step 1
   first, re-measure, and only then decide whether the child is worth removing.

4. **Do not tune the polling granularity of the hijack park.** Already measured under
   #1230: five times finer sampling gave the same 2.06 frames, because the wait is for the
   frame and not for us to look — and each sample suspends the render thread. It was
   reverted once; do not revert the revert.

5. **Do not fix the next three data losses with three fixes.** There have already been
   three in one day and #1272 said it in so many words: three fixes leave a fourth
   waiting. The invariant goes into a type (§4.2).

6. **Do not add another test that greps the source.** They pass over dead code and fail on
   renames; there are 24 files' worth already (§4.4).

7. **Do not switch settles off globally with one flag.** Some chunks log an
   ACKNOWLEDGEMENT and the answer arrives with a later server reply; cutting those short
   returns an empty list and says nothing. This is why `early` is opt-in and why §1.2 has
   two steps rather than one.

8. **Do not adopt pytest for its own sake.** The self-running scripts work and the
   conventions are built around them. What is missing is a runner and tiers, not a
   framework (§4.3).

9. **Do not «split the locales by language» — they already are.** The cut that helps is by
   TAB; anything else leaves all eleven files in every commit (§5.1).

10. **Do not treat the eleven-locale rule as the problem.** It is why the tables are
    complete — 1 323 keys, zero missing in any of the eleven, checked during this audit.
    The cost is the FILE LAYOUT, not the discipline.

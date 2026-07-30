# Control panel — UX audit

What the panel is like to *use* as the front end of a bot that farms an account
every day: what is missing, what is awkward, and what should be rebuilt rather
than patched. Read against `panel/__main__.py`, `panel/timers.py`,
`panel/profile.py`, `tools/lib/game_buttons.py`, `tools/lib/lua_actions.py` and
the ability list in [`farming.md`](farming.md).

Every item says what happens **now**, what it **costs** the person running the
bot, and what the **fix** looks like. Nothing here is a bug report about the game
side — the engine calls work; this is about the surface in front of them.

> **Status.** Every item of §5 has been implemented (task #1120), and with them
> everything in §2 and §3 they cover, plus the first four bullets of §4. The text
> below is kept as written — it is the reasoning behind each change, and the
> "what happens now" tense describes the panel *before* the work. What is **not**
> done is called out where it stands: the tab split (§4, first bullet), the
> button-driven action queue (§4), and «нечего играть сессию» end to end (2.1)
> beyond what the timer editor now makes possible. Nothing here has been proven
> in a live session yet — see the marks in [`farming.md`](farming.md).

---

## 1. What already works well

Worth naming, because the gaps below should not undo it.

* **One action = one file.** Every ability is a `src/lastwar_bot/actions/*.md`
  script the picker lists, the editor edits and Run executes — adding an ability
  needs no panel change.
* **The schedule is honest.** Per-account clock that survives a restart, one
  worker thread so two errands never drive the game at once, a failed run is not
  counted as a run, and nothing fires with the game closed (`panel/timers.py`).
* **Everything is per profile.** Settings, logs, the timer catalogue and its
  clock all live under `panel/profiles/<name>/`, and a switch re-points the
  running monitors too.
* **The log is the record.** Mirrored to `panel.log` line by line, copyable under
  any keyboard layout, and every coordinate in it is a clickable jump.

---

## 2. Missing — the gaps that matter for a real bot

### 2.1 Nothing plays a session

`farming.md` says it outright: the panel repeats one chosen action and keeps a
couple of errands to their own clocks, but no routine runs end to end. In
practice the daily list (collect → donate → gifts → help → hospital → survivors →
skills → ministry) is a person clicking Run eight times or hand-editing
`timers.json` eight times.

**Fix.** The schedule is already the right machine for this — what is missing is
its editor (2.2) and a "morning routine" entry that is a list of steps. Once a
timer can be created from the UI, "play the session" is one timer with ten steps
and a period of an hour.

### 2.2 Timers can only be edited by hand

The Timers tab shows a switch, a period, last/next run and Run-now — and that is
all it can write back (`_save_timers`). Adding an errand, changing what it runs,
its arguments or its title means opening
`panel/profiles/<name>/timers.json` in an editor and pressing ⟳. The tab's own
hint tells the user to do exactly that.

**Cost.** The one feature that makes the bot unattended is gated behind hand-editing
JSON per account.

**Fix.** Add / duplicate / delete a row; edit scenario steps (a picker over
`list_actions()` plus a free-text step for inline DSL), args and title inline. The
file format already supports all of it — only the UI is absent.

### 2.3 Rally: the alert goes nowhere

The rally monitor prints into the shared log; `actions/join_rally.md` can join
with named squads; the Settings → «Авторалли» page saves which squads may go and
who carries the banner — and **nothing reads that page** (its own docstring says
so). A rally is worth minutes, and the log line scrolls past.

**Fix, in order:** (a) wire the autorally config into `join_rally`'s `squads`
argument so the page stops being dead; (b) surface the alert — a toast / tray
notification / sound, not just a log line; (c) an "auto-join" switch that fires
the recipe on the alert, and a one-click Join on the alert itself.

### 2.4 No liveness, no recovery

`_refresh_status()` runs at start-up, after an action and when ↻ is pressed —
there is no periodic poll. The game is crash-prone (it is why `launch_game`
exists), so the panel can sit for an hour showing "running (pid …)" over a dead
client, with every timer tick failing into the retry hold. There is no
restart-the-daemon button either: if `lua_daemon` wedges, the only route is
killing it outside the panel.

**Fix.** Poll status on a timer (every 5-10 s is free — it is a process-list
scan); an optional "relaunch the game when it dies" watchdog (the recipe is
already written, `actions/dev/watchdog.md`); a Restart button beside the daemon
indicator.

### 2.5 Multi-account is only half there

Profiles switch panel settings, logs and schedules — but not the client they
drive. A second instance needs its own Windows session and
`LW_DAEMON_PORT=47655` (`tools/rdp_instance.py`); the panel hardcodes the default
port through `lua_client` and knows nothing about instances. So two profiles
still drive one game.

**Fix.** Make the daemon port (and optionally the instance to bring up) a profile
field, thread it through `DaemonClient` and every `WIN_PYTHON` child launch. That
turns "two profiles" into "two accounts farmed at once", which is the point of
having profiles at all.

### 2.6 Chat is read-only

`chat_send.py`, `tools/lib/chat_share.py` and `actions/send_chat_message.md` all
exist; the Chat tab has no input box. Answering a mate, or sharing a coordinate,
means leaving the panel.

**Fix.** A message box per channel tab (text / emoji / sticker / coordinate),
running the existing recipe.

### 2.7 Coordinates in chat are not clickable

`coords.parse` turns coordinates into jump links in the log, but
`_render_msg_line` inserts chat text raw. Chat is where coordinates actually
arrive — a rally target, a treasure, a base to hit.

**Fix.** Reuse the log's link path in the chat renderer.

### 2.8 No day counters, no account dashboard

Everything that happened is prose in one log. How many robberies are left today,
whether the base was collected, how many donations went in, how many mates are
waiting for help — none of it is on screen, and the daily budgets are exactly the
numbers a person needs before deciding to intervene.

The galling part is that **every one of those readings is already written**, as a
one-line Lua expression the buttons use for `xall`:
`secret_task_steals_left()`, `ghost_recon_steals_left()`,
`alliance_donate_rest()`, `alliance_help_waiting()`, `hospital_wounded_count()`,
`hospital_healed_ready()`, `visitor_recruit_pending()`, `visitor_gift_pending()`,
`occupation_skills_ready_count()`, `queues_needing_help()`, `free_build_queues()`,
`treasure_queue_len()`, `rally_joins_pending()`. They are only ever evaluated
*inside* a press, and the answer is thrown away.

**Fix.** A dashboard strip that polls them through the warm daemon every 30-60 s:
"кражи 3/5 · донат 12 · раненых 681 · ждут помощи 4 · выживших у ворот 2 · навыков
готово 3". That single view is what tells the person whether today needs them at
all — and it is a display, not new game logic.

### 2.9 The map has to be panned by hand for the secret-task scan to see anything

The capture is a passive pcap: it only learns tiles from the map responses the
client sends while the map is *moving*. The panel says so when the monitor starts
("двигай карту, иначе трафика не будет"), and the auto-loot watcher repeats it
("включи «Мониторинг» секреток и подвигай карту").

**Cost.** «Автолут ★» is sold as a standing order but is only as autonomous as the
person dragging the map. In daily use this is the single most manual thing left in
an otherwise headless bot.

**Fix.** A panning driver: walk the camera over a rectangle of tiles around the
base on a timer (the coordinate jump already exists — `jump_to_coord` / `GotoWorldPos`
is exactly the primitive), so a scan sweep is a checkbox rather than a wrist. Or
read the tiles the way the environment reader already does off the Lua VM and drop
the pcap dependency for this feature entirely.

### 2.10 No quick command line for the button catalogue

Thirty-odd named presses exist (`tools/lib/game_buttons.py`), and the only way to
fire one from the panel is if some `actions/*.md` happens to wrap it. Pressing
"collect the trucks" or "close the window" once, by hand, is not possible without
writing a file first.

**Fix.** A one-line command box under the log: type `TAP collect_trucks xall` or
`LUA …`, press Enter, it runs through the same interpreter. Same field also makes
debugging a recipe interactive instead of edit-save-run.

### 2.11 Abilities that exist but cannot be reached from the panel

`tools/street_run_bot.py` (Street Run, the most finished autonomous piece in the
repo), `tools/find_treasures.py` / `dig_treasure.py`, `tools/attack.py`,
`tools/scan_players.py`, `tools/dispatch_tasks.py` have no `actions/*.md` and so
never appear in the picker. `actions/dev/*` is deliberately hidden, which also
hides `work_treasure.md` and `collect_trucks.md`.

**Fix.** Either a thin recipe per tool, or a "show dev scripts" checkbox on the
picker so the dev folder is one click away instead of a code change.

### 2.12 The button catalogue is invisible

`tools/lib/game_buttons.py` is the vocabulary `TAP` speaks — 30-odd named
presses, each with its own `xall` count and caps. A person writing a recipe in
the panel's own editor has no way to see the list without opening the source.

**Fix.** A reference pane (name · label · has `xall` · what it needs open) beside
the editor, or completion on `TAP ` — and it pairs with the command box in 2.10.

### 2.13 No validation before a recipe is saved or run

The editor writes the file a second after the last keystroke, whatever is in it.
A typo is discovered when the run fails — and the file has already replaced a
working recipe, with only in-session Tk undo to get back.

**Fix.** Parse on save and show the first error inline (the DSL parser is already
there); keep a `.bak` of the previous text per file.

### 2.14 Ghost recon has no standing order

Secret tasks have «Автолут ★» — a watcher that robs the moment a target appears.
Ghost recon has the same five-a-day budget, the same perishable targets and the
same finished tool chain, but only a manual recipe.

**Fix.** The same watcher, pointed at the ghost-recon capture.

---

## 3. Awkward — friction in what already exists

* **The log has no timestamps.** `panel.log` on disk gets
  `%Y-%m-%d %H:%M:%S` per line; the widget the person actually watches gets none
  (`_insert_line`). So "когда собралась база?", "давно ли пришёл этот запрос
  помощи?", "сколько назад упал захват?" all mean opening the file. One line of
  code, and it is the first thing missed in daily use.
* **The scenario list is in English while the UI is in Russian.** `list_actions()`
  takes the first `#` line of each `.md`, and those are written in English
  ("Claim the alliance gifts — ordinary and premium"). The Timers tab localises
  its two built-in rows properly, so the same errand reads one way there and
  another way in Scenarios. *Fix: a locale key per action, or a Russian title line
  the loader prefers.*
* **The log is one undifferentiated stream, and it never stops growing.** Six
  producers (`[secret] [rally] [help] [chat] [action] [timer]`) write into one
  Text widget with no severity colouring, no per-tag filter, no search and no
  Clear. Nothing trims it either — an overnight session grows the widget until
  the panel is slow. *Fix: tag colouring (error / warning / ok), a tag filter
  strip, Clear, and a hard cap on retained lines.*
* **The panel's own log is Russian-only.** ~74 hardcoded Russian strings in
  `_log_put` calls against 158 fully mirrored locale keys — pick English and the
  UI switches while everything the bot says stays Russian. *Fix: move them into
  the locale files; it is mechanical.*
* **The Scenarios tab forgets everything on restart.** The selected script, the
  args JSON and the repeat interval are not in `_collect_settings()`, so every
  launch starts on the first row with an empty args box. *Fix: persist them per
  profile.*
* **The auto-loot rule hides inside display filters.** «уровень от/до» is both the
  log filter and the rule that decides which star gets one of the day's five
  robberies (the code comments record a level-6 star costing a level-7 one). Two
  different decisions on one pair of entries. *Fix: give auto-loot its own level
  row inside its own frame; leave the filters to filtering.*
* **Two Settings sub-tabs are placeholders while real knobs are constants.**
  «Общие» and «Игра» say "Скоро", yet `WIN_PYTHON`, `AUTOLOOT_LIMIT`,
  `AUTOLOOT_SPENT_PAUSE`, `AUTOLOOT_POLL`, `TRACE_FILTER`, `SNIFF_READY_TIMEOUT`
  and the game paths are all edit-the-source. *Fix: fill the two tabs with them.*
* **The `system` chat bucket has no tab.** `_chat_msgs` carries `system`, the tab
  list does not — those messages are counted and never shown. *Fix: add the tab
  or drop the bucket.*
* **No unread marks on chat tabs.** A DM that arrives while another tab is open
  is silent.
* **The main tab does not breathe.** Fixed-height blocks stack above a log that
  gets whatever is left; at the 640×500 minimum the log is a few lines. There is
  no sash to give the log more room, and the window size is not remembered. *Fix:
  a `PanedWindow` between the controls and the log; save geometry per profile.*
* **No panic button.** Stopping everything at once — monitors, watchers, a running
  scenario, the schedule — is five separate clicks across three tabs. *Fix: one
  "stop everything" control, which is also what you want when the game misbehaves.*
* **The jump has no memory.** X/Y/server is one triple; there is no history and no
  favourites, though jumping between a handful of known tiles is routine.
* **Run-now cannot be taken back.** A queued or running errand has no cancel — the
  Scenarios tab has Stop, the Timers tab does not, and the scheduler's `pending()`
  is never shown.
* **Deleting a profile deletes its logs without saying so.** The confirmation
  names the profile, not the `rmtree` of its history.

---

## 4. Rework — structural, not cosmetic

* **`panel/__main__.py` is 3200 lines and five features.** Navigation, capture
  monitors, auto-loot, sniffers, scenarios, timers, settings and chat all live in
  one class. Every new ability lands in the same file. *Split into
  `panel/tabs/*.py` with the shared log/busy plumbing in a small core — the tab
  builders are already independent, so this is mostly moving code.*
* **Four copies of "spawn a child, stream it into the log, untick the box when it
  dies".** Secret, rally, help and chat monitors each repeat ~40 lines
  (`_start_*` / `_*_reader` / `_stop_*`), and `_spawn_sniffer` is a fifth partial
  copy. *One `ChildMonitor(cmd, tag, var)` helper, and the differences become
  three arguments.*
* **The busy flag is claimed two different ways.** `_act`, `_run_md_action` and
  `_run_timer_action` go through `_claim_busy()` under the lock; `_jump()` reads
  and sets `self._busy` bare (lines 1886-1889). A coordinate click and a timer
  firing in the same instant can both proceed into the game VM. *Route `_jump`
  through `_claim_busy` — one line, and it closes a real race.*
* **Busy is a boolean, not a queue.** Anything that arrives while the flag is up
  is refused with "занят" and lost (except timer errands, which requeue). *Give
  button-driven actions the same single-file queue the scheduler already has —
  then "collect the base" pressed during a rally join simply waits.*
* **The panel writes `panel.log` by reopening the file for every line.** Fine at
  today's volume, wasteful once a tracer is streaming. *Keep the handle.*
* **Header comments have drifted.** The module docstring points at
  `tools/lua_actions.py` (it is `tools/lib/lua_actions.py`) and at `actions/*.md`
  (it is `src/lastwar_bot/actions/`). Small, but this file is where a newcomer
  starts.

---

## 5. Suggested order

Ranked by what a person running the account every day gets back per hour spent.
All twelve are done (#1120); what each turned into is noted after it.

1. **Timestamps in the log** (§3) — minutes of work, and it is the thing missed
   every single session.
   ✅ `%H:%M:%S` per line, in its own grey tag.
2. **Account dashboard from the existing `count_lua` expressions** (2.8) — the
   readings are written; this is a display over them, and it answers "does today
   need me at all".
   ✅ `panel/dashboard.py` — thirteen readings, ONE game-VM call, polled every
   30 s. A budget stays on the strip at zero, a queue drops off it, and an
   unreadable one shows `?` rather than passing for a zero.
3. **Timer editor** (2.2) — unlocks the unattended routine (2.1) with no other work.
   ✅ Add / copy / edit / delete a row, steps + args + title, a picker over the
   action scripts, a master switch for the schedule, and «✕» to take a queued
   errand back off the queue (`TimerScheduler.cancel`).
4. **Automatic map sweep for the secret-task scan** (2.9) — turns «Автолут ★» from
   half-manual into the standing order it claims to be.
   ✅ `panel/mapsweep.py` — a serpentine walk over a box around a centre, driven
   through the same `_jump` a clickable coordinate uses. The box, the step, the
   dwell and the rest between passes are Settings → «Игра».
5. **Status polling and a game watchdog** (2.4) — everything below assumes a live
   client, and today a crash is silent.
   ✅ An 8-second poll; a crash is announced whether or not the watchdog is on;
   the watchdog needs two consecutive dead readings and keeps a 5-minute cooldown.
   A ⭮ beside the daemon indicator restarts it.
6. **Log: colouring, tag filter, Clear, retention cap** (§3) — the panel's only
   feedback channel.
   ✅ All four, plus the file handle kept open instead of reopened per line.
7. **Wire autorally + surface the rally alert** (2.3) — the settings page is
   already written and read by nothing.
   ✅ The page's `squads` list IS `join_rally`'s argument now; the alert is a
   log line the colouring picks out plus a bell, deduplicated by `teamUuid`;
   «Присоединиться» and an auto-join switch beside it.
8. **Quick command box** (2.10) + button reference (2.12) — makes the 30 existing
   presses reachable without authoring a file.
   ✅ One DSL line through the same interpreter a recipe runs on, with Up/Down
   history, and a «Справочник TAP» window that drops `TAP <name>` into the box.
9. **Chat input + clickable coordinates** (2.6, 2.7).
   ✅ A box per open tab (the target room is shown, never guessed), a 📍 that
   shares the jump fields as a map pin, and the log's own link path in the chat
   renderer. The `system` bucket got its tab, and the tabs carry unread counts.
10. **Daemon port per profile** (2.5) — the step that makes two accounts real.
    ✅ A Settings knob threaded through `DaemonClient` and `LW_DAEMON_PORT` in
    every child's environment.
11. **Refactor**: `_jump` under the lock (a one-line race fix), child-monitor
    helper, tab split (§4).
    ✅ `_jump` goes through `_claim_busy`; `panel/childmon.py` replaced the four
    copies. ❌ **The tab split is NOT done** — `panel/__main__.py` is still one
    class, and it grew with this work.
12. **Recipe validation** (2.13), ghost-recon watcher (2.14), Russian action
    titles (§3).
    ✅ The editor parses before it writes and keeps a `.bak`; ghost recon got its
    own standing order (it needs no capture at all — the client knows the squad
    list, so it is a poll of the game rather than of a pcap checkpoint); a script
    may carry a `# ru:` title line and the picker prefers it.

### Still open after #1120

* **The tab split** (§4) — the one structural item, deliberately last, and still
  the right thing to do next.
* **A queue for button-driven actions** (§4) — busy is still a boolean, so a press
  that arrives during a running errand is refused with «занят» rather than waiting.
* **A routine that plays the whole session** (2.1) — the timer editor makes it
  *buildable* by hand now; nothing ships one.
* **Bringing up the second instance from the panel** (2.5) — the port is a profile
  field, but `tools/rdp_instance.py --bring-up` is still a shell step.

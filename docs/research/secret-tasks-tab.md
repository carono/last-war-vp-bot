# The «Secret Tasks» tab, step by step

What this tab actually does, in the order it does it, including everything it does
without saying so: the reads it fires on its own, the background loops and their
periods, who holds the game lease and for how long, what is written to disk and when,
what it subscribes to on the wire, and which of the five tables each rule belongs to.

Written off the code, not off memory. Every step names the file and the function that
performs it, so a claim here can be checked in one jump.

**Scope.** The ★ page (the working raid list) is the subject; the four other pages are
described where they cost a read, a redraw or a disk write. The protocol behind the
robbery itself is [`secret-task-steal.md`](secret-task-steal.md); the help command is
[`secret-task-assist.md`](secret-task-assist.md); the map lap is
[`map-sweep-zoom.md`](map-sweep-zoom.md).

## 0. The parts

| File | What it owns |
|---|---|
| `panel/tabs/secret_tasks/tab.py` | The tab: the ★ model (`_rows`), all timers, the two actions, the coordinate bar, the checkpoint, the phone screen |
| `panel/tabs/secret_tasks/grid.py` | The table itself — columns, colours, sort keys, countdown arithmetic, the tree diff, and `TaskGrid` (the base of the four other pages) |
| `panel/tabs/secret_tasks/capture.py` | One pcap child: spawn, line filter, findings log, the debounce that nudges the list |
| `panel/tabs/secret_tasks/autoloot.py` | «Автолут ★» — the poll, the push listener, the rule, the state line |
| `panel/tabs/secret_tasks/autoassist.py` | «Автопомощь» — a slow poll that plays `actions/assist_secret_task.md` |
| `panel/tabs/secret_tasks/alliance.py` | The alliance mirror page (and, drawn inside it, the «Автопомощь» controls) |
| `panel/tabs/secret_tasks/ghost.py` | The three ghost-recon pages |
| `panel/tabs/secret_tasks/shared.py` | «Уже поделились» — the file-backed share marks |
| `src/lastwar_bot/actions/steal_secret_task.md` | The robbery, as a scenario: park, spam, drop, confirm |
| `src/lastwar_bot/actions/scan_map.md` | The map lap («Обойти карту») |

Five pages, in notebook order: **0** ★ (the working list), **1** Секретки альянса,
**2** Операция Призрак, **3** Призрак — альянс, **4** Призрак — карта.

## 1. Start-up, in order

### 1.1 Panel boot — `ensure_loaded()` (tab.py:501)

The tab declares `EAGER = True`, so this runs at panel start whether or not anybody
opens the tab. It starts **only the standing orders the profile asked for** and reads
nothing from the game:

1. `monitor_var` ticked → `Capture.start()` for the ★ sniffer (index 0,
   `tools/secret_task_capture.py`);
2. `ghost_map.monitor_var` ticked → `Capture.start()` for the ghost sniffer (index 1,
   `tools/dev/secret_mission_capture.py`);
3. `autoloot_var` ticked → `AutoLoot.start()`;
4. `autoassist_var` ticked → `AutoAssist.start()`.

Each is idempotent. The list's own seed is deliberately **not** here — it is a game
round trip and belongs to `on_show`, or every profile would pay one at boot for a list
nobody has looked at.

### 1.2 What `Capture.start()` hides (capture.py:108)

Split across two threads on purpose:

* **On the Tk thread** the command line is built: interpreter, script path, and the
  checkpoint switch. The ★ capture gets `--json <profile>/tasks.json`. The ghost capture
  gets `--json <profile>/ghost.json` **and** `--shared-json <profile>/secret_shared.json`.
  `--interval` is added when `interval_var` is a positive integer (default `"1"` second —
  there is no box for it any more; a profile may still set `monitor_interval`).
  Deliberately **no `--all-tcp`**: it widens the BPF to bare `tcp` and npcap's ring
  overflows on a busy adapter.
* **On a worker thread** (`_launch`, capture.py:167) three further things happen that
  nothing on screen announces: if the game is up, `rt.game.current_server()` is read
  through the daemon and passed as `--seed-server` (so the child prints a real server on
  its first line); the child is spawned through `rt.children.spawn`; and its pid is
  logged. A failed spawn **unticks the box** (`_untick`), as does the child exiting.

`_starting` guards the gap before `_proc` is set — without it, two presses inside the
second the game takes to answer would be two captures.

### 1.3 First time somebody LOOKS at the tab — `build()` then `on_show()`

`build()` (tab.py:802) only draws: the title bar with «Обновить» / «Очистить список» /
the status label, the coordinate bar, the hint, then the notebook with its five pages.
The action strip («Перейти», «Показывать исчерпанные», «Поделиться», «Собрать») is
packed **first, against the bottom**, so a short window clips the table and never the
buttons.

`on_show()` (tab.py:522) runs once (`self.loaded`) and fires, in this order:

1. `_load_persisted()` — a **file read** of `<profile>/secret_tasks_state.json`. Rows
   restored here go straight onto the screen (`_render` + `_update_status`), so the table
   is not empty while the game reads are still in flight. The keys restored are kept in
   `_restore_pending` — the set the next successful VM read reconciles against.
2. `ghost_map.restore()` — the same for the ghost-map page's own checkpoint.
3. `_start_clock_sync()` — measures the game's clock now, and arms `secret_clock`
   (`CLOCK_MS` = 5 min).
4. `_start_ticking()` — arms `secret_tick` (1 s).
5. `_prime_own_server()` — **thread**; learns the account's own server id (§3.1).
6. `_snapshot()` — **thread**; the one-time VM seed of the ★ list.
7. `_roster()` — **thread**; the alliance mirror (the tab's slowest round trip).
8. `_ghost()` — **thread**; one read that fills all three ghost pages.

Four background threads are therefore in flight within milliseconds of the first look,
plus whatever the standing orders are already doing.

### 1.4 What `_load_persisted` throws away (tab.py:2374)

A restored record is dropped, silently, when any of these holds:

* it is not a dict / has no integer `uuid`;
* `expires_at` is set and already past **on the game's clock** (`game_clock.now_ms()`,
  which answers from the last measured drift and needs no read);
* `completed_at` is missing/zero — such a row can never mature, so it is not a target;
* it is not starred: `starred` when the record carries it, else `_starred_cfg(cfg_id)`
  (the digits) for a checkpoint written before #1267.

A record with `robbed: true` is restored **and** its uuid is added to `_collected`, so a
later capture cannot re-add an unmarked copy.

## 2. The steady state — every loop, with its period

| Chain / loop | Period | Where | Costs a game round trip? |
|---|---|---|---|
| `secret_tick` — model pass | 1 s | `_tick` (tab.py:3197) | no |
| `secret_live` — countdown repaint | 250 ms (`LIVE_MS`) | `_live_tick` (tab.py:3173) | no |
| `secret_poll` — ready-row verify | 3 s (`POLL_MS`) | `_poll_tick` (tab.py:3264) | **yes**, one chunk |
| `secret_clock` — game clock | 5 min (`CLOCK_MS`) | `_sync_clock` (tab.py:3135) | **yes**, one line |
| `secret_nudge` — checkpoint re-merge | 800 ms debounce (`NUDGE_MS`) | `Capture._nudge` | file read + one cfg-rank chunk |
| ★ capture flush | 1 s (`DEFAULT_INTERVAL`) | child process | no (pcap) |
| «Автолут ★» poll | 0.5 s (`autoloot_poll`) | `AutoLoot._loop` | only once it has a fresh target |
| «Автолут ★» listener | event-driven | `secret_share_autoloot.py` child | its own daemon calls |
| «Автопомощь» poll | 300 s (`autoassist_poll`) | `AutoAssist._loop` | plays a scenario each tick that passes its gates |

Both fast chains are **gated**: `secret_live` is armed only while some row on the tab has
a clock (`_has_countdown`), `secret_poll` only while `_state_targets()` is non-empty. An
idle tab wakes nothing.

### 2.1 The once-a-second pass — `_tick`

1. `_refresh_timers()` → `shared.apply(self._rows)` first: `SharedMarks.apply` does an
   `os.stat` of `<profile>/secret_shared.json` and re-parses it **only when mtime/size
   moved**, then stamps `row["shared"]`. So a share pressed in the game shows up within a
   second, and a quiet tab costs one `stat` per second.
2. `grid.refresh_timers` (grid.py:230) recomputes, against `game_clock.now_ms()`:
   expiry (row goes), `ready` (`completed_at` set and past), `soon` (< 10 min from
   whatever the row waits on next), and writes each row's state text.
3. Expired keys are popped — `THE_LIST_RULE` clause 1.
4. If anything expired or a flag flipped → full `_render()` + `_update_status()`;
   otherwise only `_paint_timers()` (state cell only).
5. Only an **expiry** triggers `_persist_rows()`; a flag flip does not, because the
   checkpoint does not carry flags.
6. The two standing-order label lines are refreshed, but only if their text really
   changed (`_refresh_autoloot_line` / `_refresh_assist_line`).
7. `_maybe_start_poll()` and `_maybe_start_live()`.
8. `alliance.tick()`, `ghost.tick()`, `ghost_allies.tick()`, `ghost_map.tick()` — one
   chain for five tables.

### 2.2 The four-times-a-second pass — `_live_tick`

`grid.repaint_countdowns` and each page's `repaint()`. It **only draws**: no expiry, no
`ready` flip, no re-sort, no read. A row with neither clock is skipped whole, and a cell
is written only when its text changed — in the steady state three passes out of four make
no Tk call at all.

### 2.3 The ready-row verify — `secret_poll`

`_state_targets()` picks the rows that are `_raidable` (ready, or within
`AUTO_EARLY_MS` = 2.5 s of maturing, and takeable), readiest first. `_poll_work` runs
`steal_secret_task._vm_all_alliance_tasks(ev)` on a thread; `_poll_apply` refreshes
`expires_at`/`completed_at`/`loot_count` for what came back and drops what did not —
**gated by `_answerable`** (§5). A failed read (`live is None`) changes nothing.
`_persist_rows()` runs at the end of every apply.

### 2.4 The wire nudge

`Capture.on_line` (capture.py:255) runs on the child's reader thread for **every** line:

* a line with a parseable coordinate, or the periodic «… on timer» progress line, arms
  `secret_nudge` (800 ms) → `tab.refresh()`;
* the nudge is independent of the display filter — a tile hidden from the log is still on
  the map;
* `passes()` then decides whether the line reaches the log: non-findings always pass;
  a finding must be starred (`_starred`, by cfgId family, `99` excluded) and inside
  «Фильтры: уровень от / до»;
* a finding that passes is appended to `<profile>/secret.log.jsonl`
  (`{"ts": …, "line": …}`);
* nothing at all happens if the tab has never been opened (`tab.loaded`).

## 3. The hidden actions, one by one

### 3.1 Reading the player's own server, and priming it

`own_server()` (tab.py:1745) caches `_self_ids(ev)` — one Lua chunk reading
`ChatInterface.getPlayerUid()` / `getSelfServerId()` / `getUserData(uid).allianceId`,
`settle=1.0`. **Not** the server on screen: an auto-loot run walks the camera abroad all
day. `0` means «unreadable» and is never treated as «nothing is home».

`_prime_own_server()` asks for it once per profile off the Tk thread, then redraws — so
`_visible_rows` (which runs on every repaint) can consult the **cached** `_own_server`
and never go to the game itself.

The same read backs the chat room ids (`country_<srv>` / `alliance_<srv>_<aid>`), cached
in `_ids`, cleared on a profile switch.

### 3.2 The feed's own gate: `_abroad_only` (tab.py:2156)

Both feeds pass through it before anything else. Every tile on the account's own server is
**dropped at the door**, and when the own server cannot be read the feed returns an empty
list and says so once (`log.secret.no_own_server_feed`). This is a gate on the MODEL, not
a display rule: a raid at home is forbidden outright.

### 3.3 The model's other door: `_merge` (tab.py:2226)

Before anything is added: `tasks = [t for t in tasks if t.completed_at]` — a tile with no
finish time never enters the model.

Then, in order:

* **verify pass** (only when `_restore_pending` is non-empty and the read succeeded):
  a restored key present in the read is refreshed in place; one absent is dropped **only
  if** `_answerable(row, answered, source)` and the row is not `robbed`;
* **existing rows are refreshed, not skipped**: `loot_count = max(old, new)` (the count
  only ever rises), `completed_at` / `expires_at` filled if they were `None`, `seen_at`
  stamped. Panel-only facts (`robbed`, `shared`, `source`) are left alone;
* **new rows** are inserted unless the uuid is in `_collected`. A new row is born
  `starred: True` (both feeds are starred-only), with its `source`, a fresh countdown
  variable and `ready`/`soon` false.

Then `_render()`, `_update_status()`, `_maybe_start_poll()`, `_persist_rows()`.

### 3.4 The wire feed: `_fetch_scan` (tab.py:2110)

1. `proto.load_fresh_tasks(<profile>/tasks.json, max_age_seconds=None)` — **the whole
   checkpoint**, no freshness window (the capture is a source; ageing rows out is the
   list's business).
2. `steal_secret_task.apply_cfg_rank(ev, tasks)` — **a hidden game round trip**: one
   chunk asking the client's `lw_dispatch_tasks` for every *distinct* cfgId on the
   checkpoint, because a pcap child has no client and wrote the cfgId's digits. Failure
   leaves the digits. A non-zero fix count is logged (`log.secret.cfg_reranked`).
3. keep `t.starred`, then `_abroad_only`.

### 3.5 The VM feed: `_fetch_vm` (tab.py:2188)

`steal_secret_task._vm_all_alliance_tasks(ev)` → every live task in
`DataCenter.ActDispatchTaskDataManager.allianceTask` that is not expired and has a free
slot, done or still counting down. Keeps the starred ones, then `_abroad_only`.

Two things ride along with this read, unannounced:

* the chunk emits `ACT NOW=<seconds>`, so **every VM read re-measures the game clock**
  (`_read_vt` → `game_clock.note`);
* a read that comes back with no usable clock raises `NotLoggedIn`, which the tab catches
  as «the read failed» — and a failed read never reconciles anything.

### 3.6 «Обновить состояние» — `refresh_state` (tab.py:1402)

The one button that asks the server about tiles rather than about lists. Only rows that
are `_raidable` are asked about; with none, it logs `log.secret.state_none` and stops.
On a thread (`_state_work`, tab.py:1456):

1. `_vm_all_alliance_tasks(ev)` — the only reading that carries a **loot count**;
2. `lua_actions.secret_task_detail_probe(tiles)` — one `world.get.detail.new` per tile
   **plus a control tile** taken from the client's own alliance table, `settle=0.6`,
   sentinel `detail_asked`;
3. `_read_details` polls the read-back every 120 ms up to 2.2 s, stopping as soon as
   every asked tile has a **non-zero** uuid (`uuid=0` means both «nothing there» and
   «nothing back yet», so it never ends the wait early).

`_state_landed` then: refreshes counts/clocks from the alliance table where it answered;
counts a tile whose detail matches as «still there» (`seen_at` only); counts
`unconfirmed` when the probe never ran for it **or** when the control point did not come
back; and drops the row only when the tile answered as absent **and** the control proved
answers were arriving **and** the row is not `robbed`. Logs
`checked / updated / gone / unconfirmed`, redraws, persists.

Holds the game lease for the duration (the two chunks plus the read-back loop).

### 3.7 «Обойти карту» — `_sweep_once` (tab.py:1592)

Plays `actions/scan_map.md` through `rt.play_async` with `{"zoom": height, "step": step}`
taken from the «Зум» box (`lua_actions.zoom_level`). Hidden parts:

* if neither sniffer is running it says so first (`log.coord.sweep_unwatched`) — a lap
  nobody is listening to writes nothing;
* it **claims the game lease** and holds it for the whole lap: the scenario's `SWEEP_MAP`
  schedules all waypoints inside the game and then **sleeps `span + 2` s**
  (`script_engine._do_sweep_map`), ~8 s at the default 90-tile step;
* the lap does **not** empty the list (it did for exactly one commit, and that cost the
  operator their finds);
* a second press is «Остановить» → `lua_actions.fast_map_sweep_stop()`, which bumps the
  run token every pending closure checks. See §7.2 for why the button rarely says so.

### 3.8 Who holds the daemon lease, and for how long

| Action | Claim? | Roughly how long |
|---|---|---|
| «Обойти карту» | yes (`rt.play_async`) | one lap + 2 s (~8 s default) |
| Robbery (hand or auto) | **no** — `rt.actions.play` direct | up to ~9 s of spam per target, ×6 targets max |
| «Автопомощь» | no — `rt.actions.play` direct | the scenario's own length |
| «Обновить состояние» | no — raw evaluator | ≤ ~2.2 s + two chunk settles |
| Ready-row poll / snapshot / roster / ghost | no — raw evaluator | one chunk each (~1.1 s settle) |
| Clock sync | no | one line, and skipped while `rt.game.busy` |

The two standing orders deliberately bypass the claim: their interlock is «one run at a
time» (`_proc` / `_running`), and a claim wrapped round a press would invent a refusal in
the middle of a robbery whose targets were chosen a moment ago.

### 3.9 What is written to disk, and when

| File | Written by | When |
|---|---|---|
| `<profile>/secret_tasks_state.json` | `_persist_rows` (tab.py:2343) | after every structural change: `_merge`, `_poll_apply`, `_state_landed`, `_drop_gone`, `_collect_done(ok)`, an expiry in `_tick`, `_clear` |
| `<profile>/tasks.json` | ★ capture child | every flush tick (1 s default) |
| `<profile>/ghost.json` | ghost capture child | every flush tick |
| `<profile>/secret_shared.json` | ghost capture (`--shared-json`), `secret_share_autoloot.py`, and `SharedMarks.mark_panel` | on every decoded share / on a successful panel share |
| `<profile>/secret.log.jsonl` | `Capture.append` | per finding line that passes the display filter |
| profile `config.json` | `config()` / `persist_vars()` | on every settings change |

`_persist_rows` keeps exactly the fields `_load_persisted` needs: `uuid, server, x, y,
level, cfg_id, loot_count, expires_at, completed_at, starred, source, robbed`. The
countdown variable and `ready`/`soon` are UI state and are recomputed.

### 3.10 Push subscriptions

`TRIGGERS` (tab.py:289) declares two, registered by `panel/runtime/schedule.py:register`
and served by one shared wire ear per profile (`rt.wire.subscribe`, not a process each):

* `alliance.share.mission.add` → `refresh_live()` → `refresh()` (checkpoint re-merge) +
  `_snapshot()` (VM read). The roster is deliberately **not** re-read.
* `push.ghost.recon.alliance.single` → `refresh_ghost_allies()` → re-reads the client's
  **local** ghost list; the server is asked nothing.

Both do nothing while the tab has never been opened. A trigger is only live while the
profile has it enabled in its trigger catalogue.

### 3.11 What the two watchers hide

**«Автолут ★»** (`AutoLoot.tick`, autoloot.py:249), every 0.5 s, in order of return:
a run in flight → `robbing`; inside the pause window → `paused HH:MM`; own server
unreadable → `no_own` (refuses, says so once); the list empty → `no_source` (once);
otherwise it takes `rob_candidates()`, reports the count, subtracts `_seen`, and only
**then** — with something to fire at — asks the game `game_clock.session_ready(ev)`;
a client at the login screen gives `no_login` (once). Fresh uuids are logged, added to
`_seen`, and handed to `run()`.

Starting it also spawns the **listener** `tools/secret_share_autoloot.py` with
`--star-max --limit <autoloot_limit> --shared-json <…> --skip-own-server` and
`--level-min <min>` when the box has a number. It is the one robbery here that does not
choose out of the tab's list — it fires on the push itself — and it is re-spawned
(debounced 1.5 s, `RESTART_MS`) whenever the rule changes, because a subprocess carries
the rule it was started with.

**«Автопомощь»** (`AutoAssist.tick`) every 300 s: run in flight → `helping`; paused →
`paused HH:MM`; `session_ready` false → `no_login` (once); otherwise it plays
`actions/assist_secret_task.md` with `{"level": level_min() or 0}` and reads
`assist_sent` / `no assists left today` out of its output. It reads nothing from the game
itself — the scenario re-reads the alliance list and gates on its own budget.

### 3.12 Who redraws the table

| Trigger | Path | What it costs |
|---|---|---|
| merge / collect / clear / sort / filter box / state read / poll drop | `_render()` | `grid.sync_tree` — a **diff**: only changed cells are written, only new rows inserted, only re-sorted rows moved |
| a second passing with no state change | `_paint_timers()` | one `tree.set` per row, state cell only |
| 250 ms repaint | `grid.repaint_countdowns` | a `tree.set` only where the text moved |
| language change | `on_language_change` | headings, notebook labels, both hint lines, then a full `_render` of all five pages |
| page switch / selection change | `sync_actions()` | button enable/disable only |

`_update_status()` writes «секреток: N · скрыто фильтрами: M» plus «скрыто своего
сервера: K», and `sync_page_counts()` rewrites every notebook label to
`«Имя · shown+hidden»`.

## 4. Where each field of a ★ row comes from

`W` = wire (capture checkpoint) · `V` = VM read (client's own `allianceTask`) ·
`C` = checkpoint (`secret_tasks_state.json`) · `P` = the panel's own bookkeeping ·
`S` = the per-tile server answer (`world.get.detail.new`).

| Field / cell | First source | Refreshed by | Notes |
|---|---|---|---|
| `uuid` | W / V / C | never | the row's identity, the tree `iid`, and what the robbery is sent with. Not shown |
| `x`, `y` (coordinate cell) | W / V / C | never | drawn as `coords.fmt`; glyphs (💰, 📣) are prefixed but the token stays parseable |
| `server` | W (`server_id`) / V / C | never | its own column; `0` = «the row never said», which excludes it from robbery |
| `level` | W: cfgId digits, **re-asked** of the client's config in `_fetch_scan`; V: the config's `level` column | a later merge (`max` does not apply — level is not re-written) | `proto.task_rank` — config wins, digits are the fallback |
| star (`starred`) | V: `is_special`; W: family digits, corrected by `apply_cfg_rank` | — | on this list it is always `True` by construction; the glyph is drawn only where the game draws one |
| `loot_count` (n/3) | W: length of the tile's looter list (`f10.f4`); V: the task's own count | `_merge` (`max(old, new)`), `_poll_apply`, `_state_landed` (alliance table only) | **the per-tile server read cannot move it** — see §7.1 |
| `completed_at` | W: tile `f10.f3`; V | `_poll_apply`, `_state_landed`, `_merge` (only when it was `None`) | the countdown target; a row without one never enters the model |
| `expires_at` | W: tile `f10.f8`; V | same as above | the only clock that removes a row by itself |
| `ready` | P — derived every second from `completed_at` vs `game_clock.now_ms()` | `grid.refresh_timers` | never restored from disk |
| `soon` (yellow) | P — < 10 min (`SOON_MS`) from the next thing the row waits on | `grid.refresh_timers` | |
| «Собрать» cell | P — `_collectable(row)` | every render | ready, or within 10 s (`EARLY_MS`), and takeable |
| `robbed` (💰) | P — set by `_collect_done` on a server-confirmed robbery | C (survives a restart) | takes «Собрать» away, keeps «Поделиться» |
| `shared` (📣) | file `secret_shared.json` — written by the panel's own share, by the ghost capture and by the autoloot listener | `SharedMarks.apply`, once a second, mtime-gated | not in the row checkpoint; re-derived from the file |
| `source` (`vm`/`wire`) | P — which feed inserted the row | C | decides which read may remove it |
| `seen_at` | P — stamped when a feed or a read touched the row | `_merge`, `_poll_apply`, `_state_landed` | drives the «видели N мин назад» suffix after 15 min |
| `owner_name` | — | — | always empty on the ★ page; only the alliance mirror has names |
| the state cell text | P — composed by `grid.state_text` from the above | every 250 ms | «готово через …» / «готово к сбору · истекает через …» + «уже поделились» + «уже ограбили» + «видели N мин назад» |

The alliance page's rows come whole from `dispatch_tasks.alliance_roster(ev)` (owner name,
rank/colour, level and star from the config row) and are **replaced wholesale** on every
read — that page keeps no checkpoint, because the game is its checkpoint.

## 5. Why a row disappears — and the full list of display filters

### 5.1 Removal: two reasons, and nothing else (`THE_LIST_RULE`, tab.py:240)

1. **The task is over.** `expires_at` has passed on the **game's** clock — `_tick` via
   `grid.refresh_timers`. The only removal that needs no answer from anybody.
2. **The game said the tile is not there.** An answer *about that tile*:
   * `_drop_gone` — the recipe reported `steal_done uuid=… how=gone`, i.e. the server
     raised one of `dispatch_des040` / `041` / `042` / `043`;
   * `_state_landed` — the per-tile read came back with no detail **and** the control
     point proved answers were arriving;
   * `_merge` (verify pass) and `_poll_apply` — a read that *could* have carried the row
     and did not, i.e. `_answerable(row, answered, source)` is true.

`_answerable` (tab.py:2203) is two rules: a read may only testify about rows of its **own
source** (the VM read walks my alliance's tasks; a stranger's tile the capture found is
outside its scope), and an **empty** read testifies about nothing at all.

A row we robbed ourselves obeys clause 1 only: every clause-2 site skips `row["robbed"]`.

Two things that are **not** exceptions to the rule: «Очистить список» (`_clear`) is a
person asking in so many words, and a **profile switch** moves to another account's map —
the old rows stay in the old profile's checkpoint and come back with it.

Nothing else empties the list: not opening the tab, not a lap of the map, not starting or
stopping a monitor, not a failed read, not an empty one, not a restart.

### 5.2 Filters — what merely hides a row

On the ★ page (`_visible_rows`, tab.py:3010):

1. **«Фильтры: уровень от / до»** (`_in_range`) — inclusive, a blank box is no bound. The
   *same* pair filters the capture's log lines (`Capture.passes`), so the log and the
   table are one set.
2. **«Показывать исчерпанные»** — off by default; a 3/3 tile (`_spent`,
   `loot_count >= proto.MAX_LOOTERS`) is hidden unless ticked.
3. **«Скрывать со своего сервера»** — on by default; hides rows whose server equals the
   cached `_own_server`. With an unreadable own server (0) it hides nothing.
4. A **robbed** row is shown regardless of rule 2 — it is on the list to be shared.

Also hiding, though they are not boxes: a robbed row has no «Собрать» cell; a row outside
`_raidable` is not asked about by the state read or the poll.

On the capture's **log** (not the table): a non-starred finding is dropped outright — it
is not a setting.

Filters that aim the ROBBERY rather than the eye (`rob_candidates`, tab.py:2869):
`_raidable` (ready or ≤ 2.5 s out, not 3/3, not robbed by us), starred, level ≥
«минимальный уровень» (`_in_rob_range`), uuid not in `_collected`, and server known **and
not home**. An unreadable own server makes this list empty, never unfiltered. It is
deliberately **not** filtered by what the table happens to show.

The other pages carry their own level range plus «UR» / «Звезда» (alliance page) —
display only.

## 6. The robbery, end to end

### 6.1 A target appears

* the ★ capture decodes a `world.get.block` tile while the map moves (only then), writes
  it to `tasks.json` on its flush tick, and prints a finding line;
* `Capture.on_line` arms the 800 ms nudge → `refresh()` → `_fetch_scan` → `apply_cfg_rank`
  → `_abroad_only` → `_merge` → the row appears with a real countdown;
* or the VM snapshot / the share push puts it there;
* or it was restored from the checkpoint at `on_show`.

### 6.2 The two windows before maturity — 10 s and 2.5 s

They are **different on purpose**.

* **`EARLY_MS` = 10 s — the HAND.** `_collectable` offers «Собрать» while the tile is
  still counting down, because a raidable star is taken in the first instant it exists and
  a button that appears exactly at maturity is one nobody can have a finger over. Pressing
  inside the window does **not** throw an early robbery: `_collect` computes
  `hold = min(max(left − AUTO_EARLY_MS, 0), EARLY_MS)` and the worker **sleeps** it out,
  logging `log.secret.collect_armed`. `_pressing` keeps a second press from arming a
  second run at the same instant.
* **`AUTO_EARLY_MS` = 2.5 s — the MACHINE.** `_raidable` is what «Автолут ★» and the
  ready-row poll aim by. Ten seconds of a machine pressing seven times a second would be
  seventy round trips a tile cannot answer yet. It is a *pick* window: the watcher's poll
  and the run's start sit between noticing and pressing.

### 6.3 The press — `actions/steal_secret_task.md`

Both paths (`_collect` on the tab, `AutoLoot._spend`) call
`rt.actions.play("steal_secret_task", {"queue": "{uuid=…,server=…},…"})`. The recipe:

1. **parks** the queue on `DataCenter.ActDispatchTaskDataManager.__lw_steal_queue`,
   stamps `__lw_steal_mark` (today's steal count for the head) and `__lw_steal_run` (the
   count for the whole run), and installs a one-time pass-through hook over
   `UIUtil.ShowTipsId` so refusals are readable;
2. `IF targets == 0` → says so and presses nothing;
3. **spams**: `TAP steal_secret_task xall` — `wait=0.05` s, `max_taps=60` (~9 s of
   pressing at ~7–8 presses/s through the warm daemon). Each press is one
   `SFSNetwork.SendMessage(MsgDefines.DispatchSteal, uuid, server)`, gated on the daily
   budget so a spent account never puts a doomed frame on the wire. The loop's gate stops
   on: the counter moving (`secret_task_taken`), the server saying the tile is gone
   (`secret_task_gone`), or the cap;
4. `TAP drop_steal_target` — pops the head, emits
   `ACT steal_done uuid=<u> how=<taken|gone|unanswered> tip=<…>` and re-arms the mark on
   the next target. `WHILE targets > 0 LIMIT 6`;
5. `TAP dismiss_steal_reward` — closes `UIDispatchTaskReward`;
6. reports `steal_taken` when `GetTodayStealNum()` rose over the run, and `steals_spent`
   when `cap − used == 0`.

**Terminal refusals.** `STEAL_GONE_TIPS` (lua_actions.py:1366) —
`dispatch_des040` «задание выполнено, украсть нельзя», `dispatch_des041` «срок истёк»,
`dispatch_des042` «задание уже взято», `dispatch_des043` «больше не доступно». All four
mean *there is nothing there*: the spam stops and the target is dropped as `gone`.
Notably the family contains **no «ещё не готово»** — an early press is answered with
silence, which is what makes pressing early free. An unrecognised tip leaves the loop
pressing.

Out-of-reach is a different refusal (tips `458632`, «не в том же секторе») and is **not**
terminal: the spam runs out its cap on that tile and moves on.

### 6.4 What counts as success

Only the **server's** counter moving. `steal_taken` comes from
`GetTodayStealNum()` having risen — the number is the server's and reaches the client only
on the success branch of `DispatchStealMessage:HandleMessage`. A `steal_sent` line proves
a frame left the client and nothing more, and is deliberately not the mark.

### 6.5 Afterwards

* `_collect_done(key, ok=True)` → `_collected.add(key)`, `row["robbed"] = True`,
  `alliance.mark_robbed(key)`, `_render`, log, `_update_status`, `_persist_rows`. **The
  row is never removed** — it stays so it can still be shared, wearing 💰 and without
  «Собрать».
* `how=gone` on any target (either path) → `_drop_gone(uuid)` on the Tk thread, unless we
  robbed it.
* `steals_spent` → «Автолут ★» pauses for `autoloot_pause_min` (30 min default) and shows
  `paused HH:MM`.
* Failure logs `secrettasks.collect_fail`; nothing is spent and nothing is removed.

### 6.6 The share, for completeness

`_share(row, scope)` on a thread: `_room_id` (from the cached self-ids),
`chat_share.task_attachment({x, y, srv, uuid, cfgId, name:"", abbr:""})`,
`chat_share.share_point`. On success `SharedMarks.mark_panel(uuid)` appends to
`secret_shared.json` **and** caches it in memory, then both tables redraw immediately.

## 7. Where it does not do what a person expects

Honest list, from the code.

### 7.1 n/3 moves only when the map is driven past the tile

For a stranger's tile — which is most of this list — the loot count lives in exactly two
places: the client's own alliance table (which holds **my** alliance's tasks only) and the
map tile itself (the stealer list rides `world.get.block` and is decoded by the passive
capture). The per-tile read «Обновить состояние» uses carries **neither** — 45 fields, of
which `reward` is the only list — and the game's own marker does not draw n/3 at all.

So: «Обновить состояние» can confirm *the tile still exists* and can refresh clocks and
counts **only for my own alliance's tasks**; for everything else the count moves when a
**lap of the map** runs with the ★ monitor on. `_state_landed` says so in its own comment
and reports `checked` separately from `updated`.

### 7.2 The lap's button forgets it is running

`_live_tick` (tab.py:3192–3195) ends with two lines that belong in `__init__`:

```python
self._sweeping = False
self._sweep_btn = None
```

They run **every 250 ms** while anything on the tab is counting down. Consequences: the
«Обойти карту» button never stays «Остановить» (and after the first live tick
`_retitle_sweep` is a no-op, because the button reference is gone), and a second press
does not stop the lap — `_sweep_once` sees `_sweeping == False` and tries to start
another, which the game claim then refuses with «занято». Stopping a lap in practice
means waiting the ~8 s out. *(Left as found — this document changes no code.)*

### 7.3 The lap goes to the server the client's manager reports, not to the box

`SWEEP_MAP` → `lua_actions.fast_map_sweep`, whose waypoints are handed
`srv = current_server_expr()` — `WorldFavoDataManager.curServerId` or
`WarFlagDataManager.curServerId`, falling back to `HOME_SERVER`
(`LW_DEFAULT_SERVER`, **0** unless the machine sets it). It is evaluated once, inside the
sweep chunk, when the lap is scheduled. It is **not** the number in «Сервер» on the
coordinate bar, and if neither manager answers the lap walks server `0`. In practice this
reads as «обход идёт по сохранённому серверу вместо текущего».

### 7.4 There is a delay before the camera moves

Nothing in the path sleeps deliberately before the lap, but a press has to get through:
the game claim, the scenario being resolved and parsed, the engine's own start-up, then
one VM round trip (80–135 ms warm; ~5 s if the daemon is cold and a local evaluator has to
be built) before `TimerManager` starts walking. The log line «Обхожу карту …» is printed
*before* all of that, so the gap between the message and any movement is real.

### 7.5 The ★ sniffer does not write share marks

`Capture.start` passes `--shared-json` only on the **else** branch — i.e. to the **ghost**
capture. The ★ capture gets `--json` alone. So «уже поделились» off the wire arrives only
while the ghost sniffer or the auto-loot listener is running, even though
`shared.py`'s own docstring names `secret_task_capture.py` as one of the two producers.
A profile running the ★ monitor alone will see marks from its own shares and nothing else.

### 7.6 The table no longer blinks — but a page can still jump

`grid.sync_tree` (a diff) replaced the delete-all/insert-all draw, so a refresh keeps the
scroll position and the selection, and a poll that confirms what was already there writes
nothing at all. What still moves is **order**: a row that flips to ready re-sorts, and
`tree.move` puts it at the top of the default ordering under the hand that was on it.

### 7.7 Other rough edges worth knowing

* **A failed read is silent by design.** No daemon, no game, or a client at the login
  screen leaves the tab exactly as it was; nothing on screen distinguishes «the read said
  nothing» from «there is nothing». The standing orders do say so (their state lines).
* **`_collected` is per session.** «Очистить список» forgets it, so a task robbed earlier
  can be re-listed by the next scan.
* **The restore is not verified while the game is down.** `_restore_pending` survives a
  failed snapshot, so the actuality check happens whenever a read next succeeds — which
  may be minutes after the rows are on screen.
* **The listener robs outside the list.** `secret_share_autoloot.py` fires on the push
  before any table has the tile, with the rule it was *started* with; a level typed while
  it runs takes 1.5 s + a re-spawn to reach it.
* **The phone reads and does not rob.** `web_press` carries «Обновить», «Обновить
  состояние», the zoom cycle, «Обойти карту», the two monitors, the display toggles,
  «Очистить список» and «Автопомощь» — but no «Ограбить». The reason written beside
  `WEB_SCREEN` is that the robbery «still spawns a tool first to PARK the chosen tiles»,
  and that has not been true of the secret-task robbery since #1272: both paths now hand
  the queue to the recipe as an argument. The GHOST robbery still spawns, so the omission
  is defensible, but the comment states a reason that no longer applies to this list.

# «Secret Tasks» tab — timers, updates, buttons

Three tables: what runs on a clock, what refreshes each cell, and what every press does.
Read off the code. `W` = wire (capture checkpoint), `V` = VM read, `S` = per-tile server
answer, `P` = panel-only, `F` = file.

## 1. Timers

| Chain | Period | What it does | Reads | Lease | Armed | Stops |
|---|---|---|---|---|---|---|
| `secret_tick` | 1 s | stamp share marks, recompute timers, drop expired, flip `ready`/`soon`, render or repaint state cell, persist on expiry, refresh both order lines, re-arm poll + live, tick 4 other pages | `F` (`stat` of `secret_shared.json`, parse only on mtime change) | no | `on_show` → `_start_ticking` | `shutdown()` only |
| `secret_live` | 250 ms | rewrite the state cell where its text changed — draw only, decides nothing | nothing | no | `_tick` → `_maybe_start_live` while any row has a clock | when no row on the tab has a clock |
| `secret_poll` | 3 s | re-read raidable rows: refresh `loot_count`/clocks, drop what a read that could see it did not carry | `V` `_vm_all_alliance_tasks` | no | `_maybe_start_poll` while `_state_targets()` non-empty | when nothing is raidable |
| `secret_clock` | 5 min | re-measure game-vs-PC clock drift | `V` one line, skipped while game down/busy | no | `on_show` → `_start_clock_sync`, self re-arms | `shutdown()` |
| `secret_nudge` | 800 ms one-shot debounce | re-merge the capture checkpoint into the list | `F` `tasks.json` + `V` cfg-rank chunk | no | every capture finding line / «on timer» line | fires once per burst |
| `autoloot_push_restart` | 1.5 s one-shot | re-spawn the push listener with the new rule | nothing | no | level box typed while «Автолут ★» on | fires once |
| «Автолут ★» loop | 0.5 s (`autoloot_poll`) | pick targets out of `rob_candidates()`, fire the robbery scenario | `V` only when a fresh target exists (`session_ready`) | no | checkbox on | checkbox off; pauses 30 min on spent budget |
| «Автопомощь» loop | 300 s (`autoassist_poll`) | play `assist_secret_task.md` | nothing itself (the scenario reads) | no | checkbox on | checkbox off; pauses 60 min on spent budget |
| ★ capture child | 1 s flush | decode `world.get.block`, rewrite `tasks.json`, print findings | pcap | no | «Мониторинг ★» on / boot | checkbox off, child exit |
| ghost capture child | 1 s flush | same for ghost tiles + writes `secret_shared.json` | pcap | no | ghost monitor on / boot | checkbox off, child exit |

| Chain | File:function |
|---|---|
| `secret_tick` | `tab.py:_tick` / `grid.py:refresh_timers` |
| `secret_live` | `tab.py:_live_tick` / `grid.py:repaint_countdowns` |
| `secret_poll` | `tab.py:_poll_tick` → `_poll_work` → `_poll_apply` |
| `secret_clock` | `tab.py:_start_clock_sync` → `_sync_clock` |
| `secret_nudge` | `capture.py:on_line` → `_nudge` → `tab.py:refresh` |
| `autoloot_push_restart` | `autoloot.py:range_changed` → `restart_push` |
| «Автолут ★» loop | `autoloot.py:_loop` → `tick` → `run` → `_spend` |
| «Автопомощь» loop | `autoassist.py:_loop` → `tick` → `_play` |
| capture children | `capture.py:start` → `_launch`; `tools/secret_task_capture.py` |

Boot (`tab.py:ensure_loaded`, tab is `EAGER`) starts only the four standing orders.
First open (`tab.py:on_show`) runs: restore checkpoint → restore ghost map → clock sync →
`secret_tick` → prime own server (thread) → VM snapshot (thread) → alliance roster
(thread) → ghost read (thread).

## 2. What refreshes each cell

| Cell / field | Refreshed by | How often | Source | File:function |
|---|---|---|---|---|
| coordinate `X:… Y:…` | never after insert | — | `W`/`V`/`F` | `tab.py:_row_values` |
| server | never after insert | — | `W`/`V`/`F` | `tab.py:_merge` |
| level + star | insert only; wire values corrected once by the client's config on each checkpoint merge | per merge | `W` digits → `V` config | `steal_secret_task.apply_cfg_rank` |
| **`n/3` (loot count)** | `secret_poll` (3 s), «Обновить состояние», checkpoint merge — **all three only for tasks of my own alliance or a freshly captured tile** | see note | `W` tile stealer list, `V` alliance table | `tab.py:_merge` (`max`), `_poll_apply`, `_state_landed` |
| state text «готово через …» / «готово к сбору · истекает через …» | `secret_live` | 250 ms | `P`, computed from `completed_at`/`expires_at` vs game clock | `grid.py:state_text` |
| `ready` (green) | `secret_tick` | 1 s | `P` | `grid.py:refresh_timers` |
| `soon` (yellow, < 10 min) | `secret_tick` | 1 s | `P` | `grid.py:refresh_timers` |
| `completed_at` / `expires_at` | `secret_poll`, «Обновить состояние», merge (only if they were empty) | 3 s / press / merge | `V` | `tab.py:_poll_apply`, `_state_landed` |
| «Собрать» cell | every render | on any change | `P` — ready, or ≤ 10 s to maturity, and takeable | `tab.py:_collectable` |
| 💰 robbed | server-confirmed robbery | on the answer | `P`, kept in the checkpoint | `tab.py:_collect_done` |
| 📣 shared | `secret_tick` re-stats `secret_shared.json` | 1 s | `F` — panel share, ghost capture, autoloot listener | `shared.py:apply` |
| «видели N мин назад» | `secret_live`, appears after 15 min | 250 ms | `P` `seen_at` | `grid.py:_stale_minutes` |
| owner name | never on the ★ page (always empty) | — | — | `grid.py:COLUMNS` |
| row order | full render (merge, poll drop, sort click, filter, ready flip) | on change | `P` | `grid.py:sort_rows` + `sync_tree` |
| counters «секреток: N · скрыто: M», notebook labels | every render | on change | `P` | `tab.py:_update_status`, `sync_page_counts` |

**Never updates without a lap of the map, for a stranger's tile:** `n/3`. The count lives
only in the map tile (`world.get.block`, decoded by the capture) and in my own alliance's
table. The per-tile read behind «Обновить состояние» does not carry it, so that button can
only confirm the tile still exists. Same for level/star corrections of a tile that stopped
being re-captured, and for any tile that has left the checkpoint.

Alliance page rows are replaced whole by each roster read; ghost pages by each ghost read.

## 3. Buttons and events

| Press / event | Steps | To the game | Effect on the list | On screen | File:function |
|---|---|---|---|---|---|
| **Обойти карту** | claim game lease → play `scan_map.md` with zoom/step → scenario schedules all waypoints in one Lua call → sleeps `lap + 2 s` (~8 s) | 1 chunk: `GoToUtil.GotoWorldPos` per waypoint via the game's own timer; ~121 `world.get.block` | nothing directly; the capture writes what the lap uncovers, then the nudge merges it | log «обхожу карту, ~N с»; warning if no sniffer is running; rows appear ~1–2 s later | `tab.py:_sweep_once`, `lua_actions.fast_map_sweep` |
| **Остановить** (same button) | bumps the sweep run token; every pending waypoint closure returns | 1 chunk | none | log «обход остановлен» | `tab.py:_sweep_stop`, `lua_actions.fast_map_sweep_stop` |
| **Обновить состояние** | pick raidable rows only → read alliance table → send one `world.get.detail.new` per tile + one control tile → poll answers every 120 ms up to 2.2 s | `V` alliance table + `S` per tile | refresh `n/3`/clocks for my own alliance's tasks; drop a tile the server answered as absent while the control point answered; nothing otherwise | log «проверено N · обновлено N · пропало N · без ответа N» | `tab.py:refresh_state` → `_state_work` → `_state_landed` |
| **Собрать** (cell, double-click, menu, strip) | guard `_pressing` → if the tile is still counting down, sleep down to 2.5 s before maturity → play `steal_secret_task.md` with `{queue}` → recipe parks, spams `xall` (0.05 s, ≤ 60 presses ≈ 9 s), pops the target, closes the reward window | `hero.dispatch.steal {uuid, targetServer}`, repeated until the server answers | success → row marked 💰, stays on the list, loses «Собрать», uuid added to `_collected`; `how=gone` → row removed | log «нажму через N с», then «ограблено» or «не удалось» | `tab.py:_collect` → `_collect_done` / `_drop_gone` |
| **Поделиться → альянс / мир** | read cached self ids → build room `alliance_<srv>_<aid>` or `country_<srv>` → build attachment → send | chat message with the tile attachment | row gets 📣, mark appended to `secret_shared.json` | log «отправлено в …» or «не удалось» | `tab.py:_share` → `_share_done`, `shared.py:mark_panel` |
| **Очистить список** | wipe `_rows`, wipe `_collected`, wipe pending restore, render, persist | nothing | list empty, checkpoint empty; the alliance page is untouched | empty table + «нет звёздных секреток» | `tab.py:_clear` |
| **Перейти / клик по координате / история** | validate boxes → `rt.game.jump(x, y, server)` → remember in per-profile history | game's own coordinate jump (`GotoWorldPos`), no height passed | nothing | log «перешёл на @[x,y\|srv]» | `tab.py:_goto_coord`, `_jump`, `_jump_to_row` |
| **↻ сервер** | thread → read the server the client is looking at → fill the box | 1 chunk | nothing | log «текущий сервер N» | `tab.py:_load_current_server` |
| **Автолут ★** (checkbox) | on: spawn push listener with the rule + start 0.5 s loop; off: kill both | listener sniffs and robs on its own; the loop plays the steal scenario | rows it robs get 💰 via the same path as «Собрать»; `how=gone` rows removed | state line under the box: выкл / сторожит / целей N / грабит / пауза до HH:MM / нет своего сервера / нет источника / не в игре / ошибка | `autoloot.py:toggle`, `tick`, `_spend` |
| **Автопомощь** (checkbox) | on: start 300 s loop; each tick plays `assist_secret_task.md` | `hero.dispatch.assist` (5/day), targets chosen by the scenario | none — it helps the alliance, does not touch the ★ list | state line: выкл / сторожит / помогает / помог N / пауза до HH:MM / не в игре | `autoassist.py:toggle`, `tick`, `_play` |
| **Мониторинг ★** (checkbox) | build command on the Tk thread → thread: read current server as `--seed-server`, spawn the pcap child with `--json tasks.json --interval 1` | nothing (passive) | fills the checkpoint; each finding arms the 800 ms nudge | log «запускаю … pid N», findings that pass the level filter | `capture.py:start` → `_launch` → `on_line` |
| **Зум** (combo / phone cycle) | store the level, log height+step | nothing | nothing | log «зум: N, шаг M» — affects **only** «Обойти карту», not jumps | `tab.py:_on_zoom_choice`, `_cycle_zoom` |
| **Фильтры: уровень от / до** | save, render, update counters | nothing | hides rows only; the same pair also filters the capture's log lines | count line moves, table narrows | `tab.py:_on_display_filter_change`, `capture.py:passes` |
| **Показывать исчерпанные** | save, render | nothing | shows/hides 3/3 rows | table + count change | `tab.py:_on_show_spent` |
| **Скрывать со своего сервера** | save, render | nothing | hides rows on the account's own server (nothing if it is unreadable) | «скрыто своего сервера: K» | `tab.py:_on_hide_own_change`, `_hidden_at_home` |
| **Минимальный уровень** (Автолут) | save, redraw the rule line, debounce 1.5 s → re-spawn the listener | nothing | aims robberies only; hides no row | rule line under the box | `tab.py:_on_level_filter_change`, `autoloot.py:range_changed` |
| **UR / Звезда** (alliance page) | save, refilter | nothing | hides rows on that page only | count on that page | `alliance.py:narrow` |
| **Обновить** | checkpoint merge + VM snapshot + alliance roster + ghost read, four independent flags | 3 reads | adds rows; reconciles restored rows against the VM read | «загрузка…» then counts | `tab.py:refresh_both` |
| **event: push `alliance.share.mission.add`** | shared wire ear → `refresh_live()` → checkpoint merge + VM snapshot | 1 read | new rows may appear | rows appear | `tab.py:TRIGGERS`, `refresh_live` |
| **event: push `push.ghost.recon.alliance.single`** | re-read the client's local ghost list | 1 read, no server request | ghost-allies page redrawn | that page changes | `tab.py:refresh_ghost_allies` |
| **event: capture finding line** | arm 800 ms nudge → `refresh()` → load checkpoint → correct level/star against the client's config → drop own-server tiles → merge | 1 cfg-rank chunk | rows added; existing rows get `max(loot_count)` and a fresh `seen_at` | new rows, log line if it passes the filter | `capture.py:on_line`, `tab.py:_fetch_scan`, `_merge` |
| **event: robbery answer** | `steal_taken` → counted as success; `steal_done how=gone` → drop that row; `steals_spent` → pause the standing order | — | 💰 or removal | log lines from the recipe | `tab.py:_collect_done`, `_drop_gone`, `autoloot.py:_spend` |

A row leaves the list for **two** reasons only: `expires_at` passed on the game's clock,
or the game answered about that tile that it is not there (`dispatch_des040/041/042/043`,
an absent per-tile detail with a live control point, or a read that could see the row and
did not carry it). Everything else hides, not removes. Robbed rows are never removed by
clause 2. «Очистить список» and a profile switch are the only wipes.

## 4. Known defects

- `_live_tick` ends with `self._sweeping = False; self._sweep_btn = None` (tab.py:3192) — runs every 250 ms, so «Обойти карту» never becomes «Остановить» and a second press starts a new lap instead of stopping the running one (refused by the game claim).
- The lap walks `WorldFavoDataManager.curServerId`, falling back to `LW_DEFAULT_SERVER` (0 by default) — not the number in the «Сервер» box.
- «Обновить состояние» cannot move `n/3` for a stranger's tile; only a lap with the ★ monitor on can.
- The ★ capture is spawned without `--shared-json`; 📣 marks off the wire arrive only while the ghost capture or the auto-loot listener runs.
- No delay is coded before a lap, but the claim + scenario parse + one VM round trip (80–135 ms warm, ~5 s cold daemon) sit between the log line and the first camera move.
- A failed read is silent on the ★ page: «the game said nothing» and «there is nothing» look identical.
- `_collected` is per session — after «Очистить список» a tile robbed earlier can be listed again.
- The auto-loot listener robs with the rule it was **started** with; a typed level reaches it 1.5 s later, after a re-spawn.
- `web_press` has no «Ограбить»; the reason written beside `WEB_SCREEN` (a parking tool is spawned first) stopped being true for this list in #1272.

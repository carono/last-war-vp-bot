# What an errand can say about itself for free — and where we are blind (#2019)

«Таймеры» draws a block per errand. Since #2019 a block may carry two things beside its
switch: the **game's own picture** for what it does, and **one live line** saying what it
is for right now — «+377 023 ждёт сбора» under «Сбор ресурсов».

This file is the survey behind the second half, and its point is the second column: a
dozen blocks on a polled page must not become a dozen readings, so a line is drawn ONLY
where the panel already knows the answer. Everything else is left blank on purpose, and
what a blank costs is written down here rather than quietly filled in with a poll
(`CLAUDE.md`, «Read once, then LISTEN — and nothing runs in the background unasked»).

## The rule the providers obey

`panel/runtime/errand_stats.py` may read:

* **this profile's database** — the `blobs` table and the tables beside it, which the
  panel writes anyway;
* **a checkpoint a capture child writes** — a file, read with its mtime as its age;
* **a cache another page already fills**, through a door that raises no ear and books no
  refresh (`BaseResources.cached`, added for exactly this).

It may not play a scenario, take the link, subscribe to anything, or arm a clock. The
test that pins this is `tests/test_panel_errand_stats.py`.

**One exception exists and it was granted, not taken.** The truck's bubble has no push
and nothing caches it, so the choice was «a reading or a blank» — the person's answer was
«Ок, делай», with five conditions: read when the PAGE IS OPENED, at most once a minute,
only while somebody is really looking, below the bot's own work, and skip the tick when
the link is busy — with the age shown beside the number.
`panel/runtime/errand_reads.py` is those five rules and nothing else: it has no clock, and
a read can only be booked from inside `look()`, which the two errand routes call.

The reading taken is `read_daily_checklist.md` WHOLE rather than the truck alone, because
the cost of a play is the round trip and not the work inside it — so the approved cost
buys the truck and gives eight more lines away for nothing.

## Every card says something now (#2579)

The person asked for the other half of the other half: «карточки должны быть живыми,
чтобы было видно, что работа идет», with seven rows named one by one. Nothing about the
rule above changed — no new poll, no new clock, no reading that was not already being
taken — and three things were added instead:

1. **Four more fields in the ONE granted reading.** `read_daily_checklist.md` is a single
   round trip whose cost is the trip and not the work inside it, so `tavern_free`,
   `radar_free`, `radar_helpable` and `ministry_post` are four more `put(...)` lines in a
   chunk that was already being asked for. They cost nothing measurable and they answer
   four cards that had been listed as blind below.
2. **The panel's own record of its own runs.** `LastRunStore` writes down how many times
   each errand succeeded since the SERVER's midnight (`panel/timers.py`, `run_day` /
   `runs_today`). It is not a reading at all — the file is rewritten on every mark
   anyway — and it is what answers «сколько раз был министром сегодня», which the game
   keeps no counter for.
3. **A blank is now a SENTENCE.** `of()` never returns `None`: a row with no reading and
   no record says «живого показания нет». The blindness is still the deliverable — it is
   just said out loud, because an empty line under a card is indistinguishable from a
   card whose reading is broken.

The order is strict and it matters: a real reading always wins, the day's count is the
consolation, and the sentence is the last resort. «Сколько осталось» is what a person
acts on; «сколько раз запускали» is only proof the row is alive.

**One card is not drawn at all**: «Перезапуск игры» (`HIDDEN_TIMERS` in
`panel/web/api.py`). «Состояние» already carries the client's three lifecycle presses,
and the person's words were «карточку перезапуска игры скрыть, это дубль на основной
странице». The row itself is untouched — the schedule owns it, it still fires, and
`/api/timers/set` still answers for it.

## What is free today

| Errand | Line | Where it comes from | Age |
|---|---|---|---|
| `collect_base_resources` | what is standing uncollected — or, until the stock has been read, how many buildings are ready | the stock cache the front page fills and `push.resource.item.update` keeps current; `base_ready` out of the granted reading as the fallback | yes, from whichever answered |
| `resource_tracker` | (the same line) | as above | yes |
| `rally_auto_join`, `rally_monitor` | rallies joined today | `rally_counts` in `panel.db` | «today» — no clock |
| `firework_collect`, `firework_watch` | gifts taken today | `firework_state` in `panel.db`, written by the ear | «today» — no clock |
| `secret_autoloot`, `secret_autoassist`, `secret_tasks_day` | ★ targets ripe now, of the list | `secret_tasks_state` in `panel.db` | yes — off `checked_at` (game ms) or `seen_at` (PC seconds), each on its own clock |
| `ghost_autoloot` | ghost squads ripe now, of the list | `ghost_map_state` in `panel.db` | yes, same two clocks |
| `treasure_auto` | chests on the map | `world_treasures.json`, the capture's checkpoint | yes, the file's mtime |
| `collect_truck_resources` | trucks waiting on the base | the granted reading (below) | yes, from the reading |
| `send_trucks` | dispatches left of today's cap | the same reading | yes |
| `alliance_help` | how many are waiting for help | the same reading | yes |
| `donate_alliance_tech` | donations left of the 30 | the same reading | yes |
| `upgrade_decorations` | upgrade steps banked | the same reading | yes |
| `collect_visitor_gifts` | gift bearers waiting, and runs today | the same reading | yes |
| `recruit_survivors` | survivors waiting, and runs today | the same reading | yes |
| `heal_units` | wounded, or a finished heal standing uncollected | the same reading | yes |
| `occupation_skills` | profession skills off cooldown | the same reading | yes |
| `secret_tasks_day` | robberies left of the day's cap, and how many were taken | the same reading | yes |
| `ghost_recon_alliance` | the same two halves — or «сегодня не проводится» on the six days it is dark | the same reading | yes |
| `tavern_free_pull` | free pulls the banners are offering, and runs today | the same reading (`tavern_free`, #2579) | yes |
| `apply_ministry_interior` | whether a post is held, and how many applications took today | the same reading (`ministry_post`) + the panel's own record | yes |
| `do_radar_tasks`, `do_radar_marches`, `radar_full_cycle` | room on the board and errands needing no march | the same reading (`radar_free`, `radar_helpable`) | yes |
| `mail_gifts` | attachments still waiting in the Mail | the same reading | yes |
| `perform_arms_race` | chests the day has paid, and the phases behind the «i» | the day's own book (`panel/runtime/arms_book.py`), written when a reading lands | yes, the newest entry's |
| `resource_tracker` | the pile standing uncollected | the stock cache | yes |
| `explorer_chests` | chests the keys buy, with the purse beside it | the same reading | yes |
| anything else that is a TIMER | how many times it ran today | `timers_last_run.json`, the panel's own record | «today» — no clock |
| anything else at all | «живого показания нет» | — | — |

«Ripe» is the three clauses both robbers already apply — finished, not expired, not ours
and not taken, a loot slot free. The LEVEL rule is deliberately not applied: that is the
standing order's own knob and it can be moved while nobody is looking, whereas this line
answers «есть ли вообще что брать».

## Where we are blind, and what each would cost

Nothing below has a READING, and none of them got one — since #2579 they draw the
panel's own count of today's runs instead, or the sentence saying there is nothing:

| Errand | What a person would want | Why it is not free |
|---|---|---|
| `collect_alliance_gifts` | gifts uncollected | a per-type reading; the tab reads it only when opened |
| `alliance_train_board` | is a conductor appointed | the events card reads it on demand; nothing writes it down |
| `exchange_treasure_pieces`, `piece_exchange` | offers on the board | the board is read when the page is opened; no store |
| `attack_codename_daily` | attacks left today | the manager is empty until asked (`docs/research/codename.md`) |
| `sweep_star_servers` | zones whose star day is today | not derivable from the launch date — see the section below |
| `session_kick`, `inventory_refresh`, `leaderboard_collect`, `secret_task_share` | — | nothing a number would add; they are listeners, so they have no run count either and say «живого показания нет» |

## The star day: the launch-date formula does NOT reproduce our observations

The person's proposal was «день звезды вообще можно считать на лету, там же от даты
запуска сервера учет» — compute it rather than store it. **Measured against what this
profile has already seen, it does not come out.** The evidence and the arithmetic:

* the book of observations (`secret_days`, 200 rows) holds **36** days marked as the star
  day, one marked plain, and 163 laps whose star share was recorded;
* the launch date of every warzone is already on the machine (`cache/servers.json`:
  `open_ms`, and the game's own day counter `day`);
* if the day were a function of the launch date, the marked days would pile up on one
  residue. They do not — `game_day % 7` came out **{5:7, 2:6, 6:6, 3:5, 0:4, 4:4, 1:4}**,
  and `(observed_day − launch_day) % 7` came out **{4:7, 1:6, 3:5, 5:5, 2:5, 6:5, 0:3}**.
  Flat, on both keyings, and on periods 4, 5, 10 and 14 as well;
* the independent signal says the same. Across 140 laps of more than 200 tiles, the mean
  star share by `game_day % 7` is 0.047–0.109 with no bucket standing out, and by
  `(day − launch) % 7` it is 0.044–0.106. A real star day shows as a share several times
  the ordinary one, not as a tenth of a point.

So the fitted book stays what it is (`tools/lib/secret_day.py`), no store was added, and
no formula was written. **This is «не сходится», not «невозможно»**: our evidence is thin
and uneven — 78 warzones over 10 days, most rows `unknown` — and it is one account's laps.
If the game shows a schedule somewhere we have not read, that beats all of the above.

`sweep_star_servers` therefore still has no line.

## The picture

`tools/data/errand_icons.json` maps an errand to a sprite stem; the sprites are the
client's own, pulled out of its bundles by `tools/extract_errand_icons.py` into
`results/errand_icons/` (git-ignored — the art never leaves the machine that owns the
game), resolved by `tools/lib/errand_icons.py` and served by `/api/errandicon`, the
fourth route of the same shape as `/api/avatar`, `/api/itemicon` and `/api/chatsprite`.

An errand with no sensible sprite is left out of the map and draws no picture: this
client has nothing that means «перезапустить клиент» or «бесплатный герой в таверне», and
a wrong icon is worse than none. A panel that never ran the extractor has no pictures at
all and draws exactly what it drew before.

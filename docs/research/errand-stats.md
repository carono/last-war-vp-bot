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

## What is free today

| Errand | Line | Where it comes from | Age |
|---|---|---|---|
| `collect_base_resources` | what is standing uncollected | the stock cache the front page fills and `push.resource.item.update` keeps current | yes, from the reading |
| `resource_tracker` | (the same line) | as above | yes |
| `rally_auto_join`, `rally_monitor` | rallies joined today | `rally_counts` in `panel.db` | «today» — no clock |
| `firework_collect`, `firework_watch` | gifts taken today | `firework_state` in `panel.db`, written by the ear | «today» — no clock |
| `secret_autoloot`, `secret_tasks_day` | ★ targets ripe now, of the list | `secret_tasks_state` in `panel.db` | yes, off the rows' own `seen_at` |
| `ghost_autoloot` | ghost squads ripe now, of the list | `ghost_map_state` in `panel.db` | yes, same |
| `treasure_auto` | chests on the map | `world_treasures.json`, the capture's checkpoint | yes, the file's mtime |

«Ripe» is the three clauses both robbers already apply — finished, not expired, not ours
and not taken, a loot slot free. The LEVEL rule is deliberately not applied: that is the
standing order's own knob and it can be moved while nobody is looking, whereas this line
answers «есть ли вообще что брать».

## Where we are blind, and what each would cost

Nothing below has a line, and none of them got one:

| Errand | What a person would want | Why it is not free |
|---|---|---|
| `collect_truck_resources` | is the truck's bubble up | `lw.pve.idle.reward` in read mode — a round trip per look; nothing caches it |
| `collect_visitor_gifts` | how many visitors are waiting | two client queues, readable only in the CITY scene (`docs/research/visitor-recruit.md`) |
| `recruit_survivors` | is the recruit ready | a client reading, no push, nothing cached |
| `donate_alliance_tech` | attempts left of the 30 | one Lua call, but it is a call |
| `collect_alliance_gifts` | gifts uncollected | a per-type reading; the tab reads it only when opened |
| `alliance_help` | how many can be helped | the gate needs two readings (`docs/research/alliance-help.md`) |
| `alliance_train_board` | is a conductor appointed | the events card reads it on demand; nothing writes it down |
| `exchange_treasure_pieces`, `piece_exchange` | offers on the board | the board is read when the page is opened; no store |
| `do_radar_tasks`, `do_radar_marches`, `radar_full_cycle` | free radar slots | `RadarCenterDataManager` — a live read |
| `upgrade_decorations` | spare duplicates | a bag reading |
| `tavern_free_pull` | is the free pull up | a client timer, read on demand |
| `attack_codename_daily` | attacks left today | the manager is empty until asked (`docs/research/codename.md`) |
| `apply_ministry_interior` | is the post free | a live read |
| `secret_autoassist` | how many stars are being helped | the assist's own budget is read when it runs |
| `sweep_star_servers` | zones whose star day is today | derived from the season plan — free in principle, needs a store |
| `send_trucks` | trucks out / idle | a live read |
| `restart_game`, `session_kick`, `inventory_refresh`, `leaderboard_collect`, `secret_task_share`, `ghost_recon_alliance` | — | nothing a number would add |

Two of these are worth a conversation rather than a poll, and neither was done here:

* **`sweep_star_servers`** — the star day per warzone comes out of the client's own config
  tables (`docs/research/client-config-tables.md`), which are read once and never move.
  A stat would need somewhere to keep them; that is a store, not a reading.
* **`collect_truck_resources`** — the truck bubble is the one blind spot a person asks
  about daily. It is one press-sized read, and the honest options are «read it when the
  page is opened, at most once a minute» or «leave it blank». That is the person's call,
  not an agent's.

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

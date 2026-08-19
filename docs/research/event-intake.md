# Every receiver in the panel, and what it does with what it is handed (#1523)

**The report:** «Обход карты работает, но не все монстры добавляются в грид, события
проглатываются и не обрабатываются. Это вообще повсеместная проблема.»

**The verdict:** a class, not a page. Four of the panel's receivers began with the same
line — `if not self.loaded: return` — and threw away everything they were handed while
nobody happened to be looking at the tab. #1476 took that line out of the ★ tiles and
left it standing on the other four doors.

This file is the audit: every place an event can reach the panel, whether it had the
fault, and what happens there now. The counters behind it are
[`panel/runtime/intake.py`](../../panel/runtime/intake.py); the test that pins the class
is `tests/test_panel_intake.py`.

---

## The rule

**An accepted event is processed or queued, never discarded.** #1416 wrote it for the
sending half — a refused gate parks the fire and asks again — and this is the same rule
for the receiving half.

A receiver may legitimately *decline* an event. What it may not do is fail to handle one
and say nothing. So every door records four numbers:

| number | meaning |
|---|---|
| **принято** (`seen`) | reached this receiver's door |
| **взято** (`kept`) | merged into a model, a store or a table |
| **отброшено** (`dropped`) | declined ON PURPOSE, with a reason **about the event** — a plain tile among starred ones, a row on our own server, a push carrying no gain |
| **потеряно** (`lost`) | accepted and then thrown away for a reason that is **not** the event's — the tab was shut, the reader raised, the checkpoint was torn |

`lost` must stay at zero. Every other verdict on «Занятость» is a threshold; this one
fires at a count of one, because there is no ordinary number of thrown-away events.

### Re-readable is not the same as one-shot

The distinction that decides whether a skip is a bug:

* **Re-readable** — the state can be asked for again (a bag, a squad list, a chat store).
  Skipping the re-read while nobody is looking is legitimate, because opening the tab
  reads it fresh. It is still counted, so «ничего не пришло» can be told from «мы
  отказались».
* **One-shot** — the observation is the only copy. A sniffer announces a tile once per
  state; the client draws monsters where the camera is and forgets them when it moves.
  Skipping one of these destroys data, and no later read recovers it.

Every receiver below is labelled with which it is.

---

## The measurement that named the loss

Taken on the live panel (profile with the client online, warzone read off the wire), one
lap of the map at height 600:

| step | number |
|---|---|
| map responses the server sent | **155** |
| tiles decoded out of them | **25 563** |
| mines in the checkpoint after the lap | **7 994** |
| trucks | **62** · trains **0** |
| **monster reads issued during the lap** | **0** |
| lines about monsters anywhere in 200 MB of `panel.log` | **0** |
| rows on the monster page | **37**, of which 11 within the freshness window |
| monsters one read of the client actually yields | **0–1** (12 ms per read) |
| `WorldScene` present while the client sat in the base | **no** — so nothing drawn, nothing readable, and nothing said |

Read together: the wire-fed pages were being filled and the monster page was not being
fed at all — not «fed badly». The receiver was silent in **all four** of its failure
modes (client in the base, daemon not answering, scenario failed, map genuinely empty),
which is why the report could only be phrased as «события проглатываются».

---

## The receivers, one by one

### Had the fault, fixed

| receiver | kind | what it was | what it is now |
|---|---|---|---|
| `refresh_world` — mines / trains / trucks off the capture's checkpoint | re-readable | `if not self.loaded: return`. A lap driven from «Состояние», from the phone or by a schedule wrote 7 994 mines into the checkpoint and merged **none** of them while the tab was shut | merges headless; only `WorldGrid.render` skips. A torn checkpoint is a `lost` with the reason `torn`; a file that was never written is **not** a loss — nothing was offered |
| `refresh_ghost_map` — the ghost-recon tiles | re-readable | same line, plus a bare `except: return` that swallowed a missing file and a broken one alike | merges headless; an unreadable checkpoint is `lost: unreadable` |
| `_read_monsters` — the client's own memory | **one-shot** | same line. The one page on the tab whose source leaves nothing on disk, so a read dropped while the tab was shut was the only copy there was. And every empty outcome was silent | runs headless; says `log.monsters.read` with the count, or `log.monsters.unread` with WHY (`no_game` / `read_failed` / `no_answer`), once per changed answer. A second read while one is in flight is `dropped: already_reading` |
| `StatsTab.track` — the resource tally | **one-shot** | `if not current: return`. The push says a balance MOVED; the amount only exists in the reading taken right after, so a failed read takes the gain with it | `lost: no_reading`. A push carrying no gain (the session's baseline read) is `dropped: no_gain` |

### Did not have the fault

| receiver | kind | why it is sound |
|---|---|---|
| `tile_seen` / `_tiles_land` — ★ tiles | **one-shot** | fixed in #1476: the buffer is drained headless and `_ensure_model` restores the model without a window. Now also counted at the door (`no_uuid`, `not_starred`, `home_server`) |
| `area_seen` / `_areas_land` — the regions the server answered about | **one-shot** | never had the gate. Now counted (`malformed`, `no_server`) |
| `WireHub._on_line` — the one ear every push pattern rides | pass-through | dispatches per pattern under its own lock, counts what it heard, and a subscriber that raises is **logged**, not swallowed. A dead ear tells every subscriber once (`callback(None)`) |
| `ChatTab._on_chat_line` | one-shot, already durable | the record goes into a queue that `_pump_chat` drains **into SQLite first**, before anything is drawn — so a message is durable the moment it arrives. The reader child is only ever started from `ensure_loaded`, which runs after `build`, so the queue cannot fill with no drain behind it |
| `RallyTab.refresh_squads` | re-readable | hands off to `rt.squads.refresh_async()`, which coalesces concurrent reads (`if self._reading: return`) and delivers through the bus. The reading is re-askable, so a coalesced one loses nothing |
| `DataTab.refresh_live` (inventory and friends) | re-readable | `if self._loaded` is deliberate and documented: an unopened tab reads fresh when first shown, so the push is equivalent to the read that will happen anyway |
| `Schedule.run_errand` | — | a busy game returns `False` and the errand goes **back on the queue** (#1416); a shut gate parks it and re-asks every 10 s for 10 minutes. This is the sending half of the same rule and it was already right |

---

## The pace of the lap IS the monster page — measured

The operator's second reading was the one that moved this on: «монстров на всей карте
тысячи, никак не несколько десятков». Two hypotheses came with it — the lap is too fast,
and it needs intermediate zoom stages — and both were put to a live client rather than
argued about.

**The pace.** One lap of a 1000 × 1000 warzone, height 600, step 90, 121 stops, counting
distinct monster tiles, with the camera sampled at every stop:

| seconds a stop | monsters | clock |
|---|---|---|
| 0.05 (the ★ lap's pace) | **22** | 6 s |
| 0.30 | 27 | 36 s |
| 0.60 | 33 | 73 s |
| **1.20** | **972** | **147 s** |
| 2.50 | 1 059 | 302 s |

**It is a cliff, not a slope.** Somewhere around a second the client's region loader
starts keeping up, and the same lap over the same ground goes from tens to a thousand.
Everything below it is a lap that looks like it worked and collects almost nothing —
which is exactly what «монстров тысячи, а в гриде десятки» was. Above it the curve
flattens at once: 2.5 s buys another nine per cent for twice the clock. So the default is
**1.2 s**, and it is a setting because the two ends of that table are genuinely different
jobs.

Confirmed on the shipping path, pressed from the phone: **one lap, 147 s, 897 monsters
into the page, every one of them with a real level** (1 … 31+) and a species name — from
21 rows before it.

**The heights.** How many monsters are drawn at once does depend on the height — at one
view, 105 → 12, 300 → 24, 600 → 25, 1199 → 20 — while the ground one stop covers grows
with it, so a low lap sees more per stop and needs more stops. Neither end dominates,
which is why the heights are a LIST the operator owns rather than a number: a page that
wants the map covered twice says `300, 600` and gets two laps.

What is NOT worth walking: a lap at 900 with the step that belongs to it (135) collected
**5** monsters against the same pace's 27 at 600 — the higher the camera, the fewer
objects the client bothers to draw, and the bigger step does not make up for it. 600 is
the default for the same reason it is the ★ lap's.

**And the settle time is not the same thing as the pace.** A single view saturates almost
at once — 0.3 s → 9 drawn, 1.3 s → 10, 3.3 s → 10, 8.3 s → 10 — so standing longer at ONE
place buys nothing. What the extra second per stop buys is the client keeping up with a
STREAM of view changes, which is a different bottleneck and the reason the curve above is
shaped the way it is.

## What a lap can and cannot do for the monsters

Worth writing down, because «обход не наполняет грид» reads like a bug in the lap and is
not:

* **Everything else on the map is on the wire.** A lap moves the camera, the client asks
  the server for each region, and the passive sniffer decodes the answers. That is why
  one lap fills the mine page with eight thousand rows.
* **Monsters are not on the wire at all** — measured across pans, a full district load,
  the login snapshot and a server switch, ~2000 unique tiles and zero monster objects
  (`docs/research/protocol.md`). Placement is computed client-side, so the only copy is
  the client's own memory.
* **The client only draws what the camera is on.** One read yields 0–1 clones; a lap
  throws the camera across the whole server in about eight seconds, far too fast for the
  client to instantiate anything at each stop. So a lap contributes **nothing** to that
  page, and a page filled by walking and re-reading is as wide as where the camera has
  actually stopped.

So a lap that only READS at the end can never do better than one view, and that is what
the monster page had. **The answer is to sample at every stop and to give the camera a
second to draw** — `SWEEP_MAP … HARVEST` and the table above. The reading is a 1 ms walk
of `World/dynamicObj` (the node every drawn monster hangs on, found live) against the
10–12 ms a scan of the whole object table costs, so it fits between two waypoints.

The client's own area query — `WorldScene:GetMonsterListInArea(centre, radius, ids, out)`
— is NOT that source and was checked: it is a config-id whitelist and answers for INVASION
monsters only (world-monsters.md, Findings 6 and 10), which is why #1519 can count golden
zombies with it and this page cannot count the map with it.

---

## Where the numbers are read

«Разработка» → «Занятость» → **«Приёмники»**: one row per receiver, the four numbers, the
reasons, and how long since anything arrived. Beside it the **«Слушатели»** grid, which
answers the other half — the two were never the same question:

> a capture reporting 25 563 tiles and a table that grew by nothing are two perfectly
> healthy-looking listener rows.

A single `lost` also raises a line in «признаки затора» (`busy.jam.lost`), naming the
loudest receiver and its reasons.

The block is window-only: «Разработка» declares `WEB_SCREEN = False`, which is an agreed
divergence recorded in `CLAUDE.md` and pinned by `tests/test_panel_web_screens.py`.

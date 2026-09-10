# Is anything leaking past us between the wire and the panel? (#2740)

The operator's report, in their own words: «сбор сущностей с карты, монстры, шахты,
секретки, все, максимально стабильным, чтобы ничего мимо нас из провода не утекало,
сейчас 100% есть косяки, но в чём они, или мы пропускаем, или занята панель, или хук
вешается, я не знаю».

Three named hypotheses, and this is what each of them turned out to be.

## 1. The method: two counts of the same ground

The question could not be answered before, because there was only ever ONE count.
Everything the panel knows about the map arrives through a passive pcap child, and a
child that misses frames looks exactly like ground with nothing on it.

So there are two counts now, of the same box at the same moment:

* **the WIRE's** — `MapIndex.tile_kinds`, a Counter of every `f2` the capture decodes. It
  has existed since the class was written and was printed in exactly one place: the
  summary a capture writes when it EXITS. A capture the panel started never exits, so
  nobody had ever read it. It travels as `##KINDS##` on every tick it moved, is drawn as
  a row on each card, and names each kind once in the log.
* **the CLIENT's** — `AUDIT_MAP [BOX n] INTO <var>`, which walks `WorldScene.PointManager`
  over a box and counts by kind. The kind is the CLASS NAME of what `GetPointInfo`
  returns: `pointType` reads `nil` through this bridge and reflection over the object's
  properties comes back empty, while `GetType().Name` answers.

`actions/audit_map_intake.md` is the walk in front of it: `VISIT_MAP` to one named
waypoint at the task-carrying height, then the count. It presses nothing and spends
nothing.

**The client's store is what makes or breaks the comparison.** `PointManager` holds
ground the client loaded EARLIER — so a box the camera has already visited this session
holds tiles from before the capture's census started, and comparing the two there says
nothing. Two of the readings below are contaminated exactly that way and are kept here
because the mistake is easy to repeat: only a stop on ground untouched since the capture
child started is evidence.

## 2. What was measured (live, 2026-09-10, warzone 8128, profile `default`)

**Frame loss: none.** Five named waypoints produced five map responses; six produced six.
The client does not debounce map requests, so one stop is one request is one answer, and
the sniffer saw every one.

**One stop on ground untouched this session** — @[850,450|8128], census restarted first,
box 81×81:

| kind | wire (this answer) | client (box) | verdict |
|---|---|---|---|
| mine | 115 | 47 | wire ≥ box — the response rectangle is bigger than the box |
| secret_task | 5 | 1 | same |
| base | 1 | 0 | same |
| alliance_city | 2 | see below | — |
| `f2=61` | 2 | — | **nothing here decodes it** |

The panel's own ledger over the same run: **seen 127, kept 10, dropped 117
(`not_starred`), lost 0.** The 117 are the ★ list being starred-only, which is what it is
for; `lost` is the number that must stay at zero, and it did.

**A contaminated reading, for the record.** @[200,800|8128] answered `secret_task 56` on
the wire while the client's box held 103 dispatch points — which reads as a 47-tile leak
and is not one: the camera had walked that ground a minute earlier, before the capture was
restarted, and the client had kept it.

**`AllyCityPointInfo` is 196 in every box, everywhere.** At 200,800, at 300,700, at
700,200, at 100,100 and at 850,450 — the same number, which no per-box count of distinct
tiles can be. It is the warzone's own alliance-city registry answering, not map data, and
it must be left out of any comparison.

## 2a. The control run, by kind (2026-09-10 19:03, warzone 8128)

Asked for in these words: «по ВСЕМ видам сразу, которые мы реально показываем в гридах».
The sniffer was restarted first so the census started at zero, the waypoint
(@[880,60|8128]) was ground the camera had not been on this session, and the box is 41x41
— comfortably inside one answer's rectangle.

**One map response, 255 tiles.**

| kind | X — off the wire | Y — into the store | Z — on the screen | lost | why |
|---|---|---|---|---|---|
| mine | 127 | 1128 held (all-time) | 0 of 381 | **0** | the page's own «уровень от 10» — see below |
| base / player | 72 | 75 players | its own screen | 0 | — |
| secret_task | 38 | 3 kept | 82 rows, 22 ready | 0 | 36 `not_starred` — the ★ list is starred-only |
| treasure | 11 | 11 | its own screen | 0 | — |
| alliance_city | 6 | names only | — | 0 | nothing farms one |
| truck / train | 0 | 0 | 0 | 0 | they ride the march stream, not blocks |
| monster | not on the wire at all | 521 | 500 drawn (page cap) | 0 | 1 `game_busy`, and it came back |
| `f2=61` | 3 | — | — | — | **ignored on purpose** |

`lost` is zero on every row, which is the number that matters: the ledger's `lost` counts
an event accepted and then thrown away for a reason that is not about the event.

**The one screen loss, and it was real.** «Шахты» held 381 rows and drew NONE — that page's
own level range started at 10 and a seasonal warzone's mines are all below it. Nothing was
lost; what made it a fault is that the card carried neither box, so from the phone the page
read as «ничего не нашли» with no way to find out otherwise. Every table's level range is a
field on its own card now (#2740), and clearing it live turned «0 показано, 381 скрыто»
into 127 rows on screen.

**Monsters are not a wire kind and never were** (`world-monsters.md`): placement is computed
client-side, so their X is the client's own register rather than anything on the map stream.
They are in the table because they are a grid the person reads, and the answer for them is
the same shape: 521 read, 521 kept, 0 lost.

## 3. The three hypotheses

**«ПРОПУСКАЕМ» — true, and it is KINDS rather than frames.** No map response was missed
at any pace tried. What IS being thrown away is whole tile kinds nothing in this
repository has a reader for. Two showed up within a minute of the census first being said
out loud, both on the seasonal warzone 8128, and both carry the alliance-structure
sub-message `f101`:

```
f2=11   f1 f100 f101{f1,f2,f21,f3,f4,f8,f9} f102 f103 f2
f2=61   f1 f100 f101{f1,f10,f11,f2,f3,f7,f8} f102 f103 f2
```

Field NAMES only — the values are somebody's account and never reach a log. They are not
given names in `TILE_KIND_NAMES`, deliberately: a name there means «something here decodes
this», so leaving them as numbers keeps the census flagging them until somebody does.

**«ЗАНЯТА ПАНЕЛЬ» — true, and fixed.** #2711 made the monster follow step aside whenever
anything holds the client, on the grounds that «the next block of ground will bring it
back». That holds only while the map is MOVING — and the last answer of a walk is exactly
the one most likely to land while a robbery or an errand has the link. After it the map is
still, no more ground is asked for, and the reading is gone for good; «занята панель» then
reads as «монстров нет». It is offered again now, at most `MONSTER_BUSY_TRIES` times on
the same named booking a ground answer re-arms, and fresh ground clears the count. A
client held all day costs a handful of claim lookups and no round trip at all.

**«ЗАНЯТА ПАНЕЛЬ», live, after the fix.** On the boot of 19:07 a dozen readers were
queuing for the one link. The follow fired, found a holder, dropped once (`game_busy: 1`)
— and the register answered at 19:08:28 with no lap running and no further ground asked
for, which is the retry doing exactly what it was written for. `lost` stayed 0 throughout.
The bounded shape is pinned by three tests: it re-offers, it stops after
`MONSTER_BUSY_TRIES`, and fresh ground clears the count.

**«ХУК ВЕШАЕТСЯ» — not found.** `_monster_follow_sync` refuses to subscribe twice
(`if want == bool(self._monster_offs)`), and the live listener board carried 30 rows with
no duplicate and exactly one `secret_task_capture.py`. Six capture children were hearing
on one interface at the time — the starvation shape of 044c19f — and none of them was
starved: every reading above has wire ≥ client.

**A fourth, which nobody had named and which was the actual complaint.** The clause-2
removal was deleting live rows on a false premise; that is written up in
[`secret-tasks-tab.md`](secret-tasks-tab.md) §3. Live: 73 false removals in thirteen
minutes before, 0 after, and the ★ list went from 116 rows that would not grow to 177 in
one lap.

## 4. The losses that remain, named

| where | what | why it is not a bug |
|---|---|---|
| `f2=11`, `f2=61` | every tile of them | **decided against**, in the person's words: «объекты, которые мы не собираем в гриды прямо — можно игнорировать». `TILE_KINDS_IGNORED`, with a reason each |
| `f2=26`, `f2=42` | every tile of them | no reader YET — a lead, and the census names each with the field names of one tile |
| `not_starred` | most `f2=17` tiles | the ★ list is starred-only by construction |
| the checkpoint caps | mines past `DEFAULT_MAX_PER_KIND`, players past `max_players` | a whole-server lap finds tens of thousands; the capture says «N dropped to the cap» on every tick |
| `home_server` | tiles on the account's own warzone | a raid at home is fined by the game (#1188) |

## 5. What to do next, if this is picked up again

* `f2=11` / `f2=61` are settled: nothing farms an alliance structure, so they are named in
  `TILE_KINDS_IGNORED` and the census says «намеренно не собираем» rather than «никто не
  разбирает». **Only that difference keeps the census worth reading** — a kind nobody has
  looked at is a lead, one somebody decided against is not, and drawing them the same way
  turns every future lead into noise.
* `f2=26` (`f12{f1,f2,f3,f4,f5}`) and `f2=42` (`f19{f1..f7}`) turned up later and are still
  LEADS. Decide them the same way: look, then either write a reader or write down why not.
* The comparison is a press away and repeatable: restart the sniffer so the census starts
  at zero, play `audit_map_intake` at a waypoint the camera has not visited, read the card's
  «пришло с провода» row against what `AUDIT_MAP` said. Anything other than
  wire ≥ client-box, for a kind that rides `world.get.block`, is a leak.

## The lap that guarantees nothing (#2741, 2026-09-10)

Reported as three separate faults — «нажал обойти несколько серверов, в хедере сервер не
менялся, секреток 0 дошло» — and they are one chain, read out of `profiles/default/panel.log`:

| time | what the log says | what it meant |
|---|---|---|
| 17:04–17:11 | seven `sweep_server` laps, warzones 943 936 952 938 956 953 954, `OK` | the ability works: warzone 943 alone brought 467 tasks and 35 ★ |
| 19:21:39–19:22:00 | six × «`sweep_server` не запускается: статус не зелёный» | six presses refused for a red link, said in the log and NOWHERE on the card |
| 19:22:05 | `GAME STREAM FOUND — …:18128` | the capture latched onto the stream |
| 19:22:13 | «перезапускаю клиент рецептом restart_game…» | the client opened a NEW stream; the capture kept decoding the old one |
| 19:23:16 / 19:23:21 | started warzone 942, `INTERRUPTED (stopped by the operator)` | the next tile's press was read as «Остановить» — it started nothing |
| 19:23:29 / 19:23:34 | the same pair again | two laps cut 4 s and 5 s in |
| 19:23:45–19:24:36 | warzone 953 walked whole, `OK` | and the capture reported `server unknown yet, 0 map response(s), 0 tile(s)` |

So: the presses that were refused said nothing a person could see; the presses that landed
cancelled each other; and the one lap that ran whole was decoded by nobody, which is why the
header (the wire's last word since #2727) never moved and why no secret task arrived.

Three fixes, all in `panel/tabs/secret_tasks/tab.py`:

1. **A queue.** Only the WALKING warzone's own tile is the stop; another tile queues, a
   queued tile un-queues, and the queue drains when a lap ends. One lap at a time stays
   true of the game; it stopped being true of the presses.
2. **Every lap reports on the CARD** — warzone, map responses, tiles, secret tasks (and how
   many reached the list), ghost tiles. The counts are deltas of the two running totals the
   capture has always printed in its `##KINDS##` record (`blocks`, `tiles`) and nothing read.
   A lap that came home with nothing says WHICH of the five reasons it was: no monitor, a
   deaf monitor, a camera above the task ceiling (division 7, #2737), an empty warzone, or
   tasks filtered out by level. A refused press says the gate's own sentence.
3. **A deaf monitor is re-aimed.** `bus.GAME_READY` — the client getting into the game — is
   the moment its TCP stream is new, so a capture that has been running for longer than
   `SecretTasksTab.REAIM_AFTER_S` is restarted on that edge; and a lap that walked a whole
   warzone for `0 map response(s)` bounces it once as well. No clock is involved either way.

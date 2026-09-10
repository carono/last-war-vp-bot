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
| `f2=11`, `f2=61` | every tile of them | no reader — the census now says so every time one arrives |
| `not_starred` | most `f2=17` tiles | the ★ list is starred-only by construction |
| the checkpoint caps | mines past `DEFAULT_MAX_PER_KIND`, players past `max_players` | a whole-server lap finds tens of thousands; the capture says «N dropped to the cap» on every tick |
| `home_server` | tiles on the account's own warzone | a raid at home is fined by the game (#1188) |

## 5. What to do next, if this is picked up again

* Decode `f2=11` / `f2=61` if anything is ever to be farmed off them. The shapes above are
  the starting point; both look like alliance structures, and nothing in the bot collects
  those today.
* The comparison is a press away and repeatable: restart the sniffer so the census starts
  at zero, play `audit_map_intake` at a waypoint the camera has not visited, read the card's
  «пришло с провода» row against what `AUDIT_MAP` said. Anything other than
  wire ≥ client-box, for a kind that rides `world.get.block`, is a leak.

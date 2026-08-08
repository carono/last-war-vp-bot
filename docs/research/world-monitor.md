# Monitoring the rest of the map — mines, monsters, trains and trucks (#1289)

The panel already watched two things on the world map: the starred secret tasks and the
ghost-recon squads. Everything else the map holds went past the decoder and was thrown
away. This is the work that keeps it — and the interesting part is not the four lists but
the **question the task started with: how do you add a second listener when a second
capture does not work?**

## 1. Why there is no second capture, and how that was already known

**Two npcap captures over one interface do not share the traffic — the second one gets a
trickle.** Measured live during #1188 (044c19f): a hand-started capture reported
`20 delivered / 0 map response(s)` for a whole lap of the map while the panel's own
instance, in that same minute, was at `5117 map response(s), 918999 tile(s)`. A capture
starved like that is indistinguishable from a deaf client, and it was believed as one
twice before the two counters were put side by side.

So the rule for this task was fixed before a line was written: **the wire is read once
per client, and a listener is an INDEX rather than a process.**

`tools/lib/map_capture.py` already had the shape for it. `MapIndex` decodes every frame
and calls two hooks on its subclass — `on_blocks(payload, blocks, now)` for the map
responses and `on_response(command, payload)` for everything else — so a second consumer
costs a forwarded call and nothing else. `tools/lib/world_index.py` is that consumer, and
`tools/secret_task_capture.py --world-json PATH` is the wiring: same process, same npcap
handle, same BPF, one extra checkpoint file.

```
tools/secret_task_capture.py            ONE child process, ONE npcap reader
 ├── TaskIndex        -> secret_tasks.json      (the ★ list, unchanged)
 └── WorldIndex       -> world_map.json         (mines · trucks · trains)   ← new
```

**The ghost capture is still a second process, and that is pre-existing debt** — it runs
`tools/dev/secret_mission_capture.py`, and a profile with both switches on has exactly the
two-capture problem this section is about. Folding it in is the same three forwarded calls
and was left out of this task on purpose; it belongs to whoever next touches that page.

## 2. What is on the wire, counted rather than assumed

Everything below was measured off a recorded whole-server lap at camera height 600
(`results/lv_a600.jsonl`, git-ignored — 498 frames, 244 `world.get.block` responses):

| `f2` | tiles in one lap | what it is |
|---|---|---|
| 7 | **12 725** | resource mine |
| 6 | 6 723 | player base |
| 17 | 982 | secret task |
| 29 | 311 | ghost recon |
| 25 | 183 | alliance city |
| 11 | 152 | stronghold |
| 21 | 23 | hidden treasure |
| 35 | 10 | not decoded |
| 15 | 1 | not decoded |

**Mines are the map**, by a factor of two over bases and thirteen over secret tasks. That
one number decided most of the panel-side design (§5).

Trucks and trains are **not tiles at all** and never appear in a map block: they ride the
march stream (`push.world.march.world.get.new`, `push.world.march.new`,
`world.get.march.infos`) as marches whose `f11` is 37, carrying a `train` object.

| kind | how it is told apart | seen |
|---|---|---|
| player truck | `train.type == 1` | 36 distinct in one lap |
| alliance train | `train.type == 2` | 3 in **every** recording on disk |

### 2a. A mine is one packed number

```
f6.f1   family * 100 + level        levels 1..10 (12 during a season)
f6.f2   1 on all 12 725             no meaning read off it
f6.f3   the gathering activity uuid  ┐
f6.f8   the gathering player's uid   │ present only while it is taken
f6.f9   their server                 │
f6.f10  their alliance uuid          ┘
```

Families 0 / 1 / 2 are Food / Metal / Gold — a mapping **confirmed against the game screen
by the maintainer** and nowhere on the wire (`docs/research/protocol.md`, «Resource
mines»). A whole lap held 4 306 / 4 311 / 4 104 of the three, and **four tiles of a fourth
family, 80** (`f6.f1` = `8001`, `8004`), which parks its occupier under `f6.f7.f1` instead.
Four tiles is not enough to say what a player sees on them, so `MINE_RESOURCES` does not
name family 80 and the table says «семейство 80» rather than inventing a word for it.
`lastwar_proto.mines()` decodes them; `filter_mines()` narrows on the screen's name or the
wire's family number, deliberately both.

A mine carries **no uuid** — `tools/dev/gather.py` marches on one with `targetUuid = 0` —
so its identity is `(server, pointId)`.

### 2b. An alliance train is the truck shape with a different payload

`lastwar_proto.trucks()` skips `type = 2` on purpose: a train belongs to no player and
carries a `carriageList` of seats where a truck has an escort squad. `trains()` is the
mirror, and what it reads that a truck has no equivalent of:

```
train.alliancename / .allianceId / .icon    whose train it is
train.seasonCfgId                           the season's train, not a tier
train.completeness                          1.0 -> nothing taken off it yet
train.marchInfo.giftLv                      the reward tier it is at
train.marchInfo.carriageList[]              seatNum · passengerList[] · trainGoods · plunder[]
```

Position is interpolated along `f9`→`f10` over `f13`..`f14`, exactly as `Truck.position`
does it and for the same reason: the server describes one hop at a time, so `startPos` is
not where it is and `arriveTime` is not the leg's end.

## 3. Monsters are not on the wire, and this work did not change that

`docs/research/protocol.md` §«Monsters are not on the wire» established it across
incremental pans, a full district load, `push.world.point.update`, the login snapshot and a
server switch — roughly 2000 unique tiles, zero objects above the 1..10 mine range while
levels 12..28 were on screen throughout. Monster placement is computed **client-side**.

That was re-checked here rather than taken on trust, because the same lap contains
**22 `monster.invasion.boss.detail` frames** and the name reads like the answer. It is not:
the request is `{serverId, uuid}` and the reply is `{isProtected, ownerName, allianceUid,
allianceAbbr}` — the **protection state of a player's BASE**, asked as the camera crosses
it. No monster, no level, no tile.

So the monster list is read out of the client's own memory, and the ability is a scenario
like every other: `src/lastwar_bot/actions/read_world_monsters.md`, one `READ_LUA` line
into one variable. Two sources, in order:

* `ActivityMonsterInvasionDataManager.monsterInvasionData.selfMonsters` / `aliMonsters` —
  the invasion event's own lists, which carry a config id and therefore the game's own
  answer for the kind and the level. Empty between waves, which is not a failure. (The
  same lists the rally budget's classifier already reads, #1281.)
* the drawn `WorldMonster…(Clone)` objects, found through their own
  `TouchObjectEventTrigger` — the handle the no-click attack uses
  (`world-monsters.md` Finding 10). Tile from the object's world position, level from the
  «ур. N» label hanging over it.

`lw_world_monster.type` turns a config id into the split the player reads off the screen:
**7** the zombie line, **8** the Doom line («Роковая Элита»).

**Consequence, and it is a real limit: the monster page is as wide as the client's VIEW,
not as wide as the map.** A lap of the map fills the sniffer's tables for every other kind
because the answers arrive on the wire; a monster only exists where the client has drawn
one, so the page fills up by jumping somewhere and pressing «Обновить».

**Not yet confirmed against a live client.** Each piece is taken from work that was proven
live, but this particular chunk has not been run beside a map with monsters on it. The part
to check first is which label belongs to which clone.

## 4. What the lap costs, and what it does not

The lap itself is unchanged — `actions/scan_map.md`, the whole 1000 × 1000 server in
**2.6 s** at height 600 (`map-sweep-zoom.md` §9). The new listener rides it: no second
sweep, no extra jump, no gesture. Replayed through `WorldIndex`, one recorded lap yields
**8 114 mines and 36 trucks** on the server being looked at (9 003 mines before the
«drop what belongs to the map nobody is looking at» rule takes the neighbours out).

Height matters the same way it always did: at 600 everything above arrives; at 1199 the
tasks and the ghost tiles stop while bases and mines keep coming, which is what makes the
wide level a **better** setting for a mine census than the narrow one.

## 5. Nine thousand rows is not a table

A whole-server lap finds about nine thousand mines. Two caps follow, and both are said out
loud rather than applied quietly:

* **the checkpoint** keeps `--world-max` per kind (default 5000), ranked so the highest
  level and the freshest survive, and the capture prints how many it dropped;
* **the page draws 500** (`world.MAX_SHOWN`) and counts the rest into «скрыто» beside the
  counter — the same line the level filter's hidden rows land in, so «показано 500 ·
  скрыто 8503» is a sentence a person can act on and «500» is not.

The second cap is not cosmetic. A row costs a Tk variable and a `tree.insert`, and the one
event loop every open profile shares is what the panel runs out of first (#1226). The two
pages with no countdown (mines, monsters) therefore do not take Tk variables at all — they
hand `grid.new_row` a plain stand-in, because there is nothing to redraw four times a
second.

## 6. When a row leaves

Every list on the «Секретки» tab follows the same rule: **the monitor only FILLS the
tables; a row leaves by its own deadline or by an explicit answer from the game.**

| page | its deadline |
|---|---|
| trucks, trains | `arrive_at` — the moment the run ends and it leaves the map |
| mines, monsters | **the age of the sighting**, 15 min, the capture's own freshness window |

A vehicle counts down to ARRIVING rather than to being ready, and it says so: «прибудет
через …», not «готово через …», which would promise a button that does not exist.
`grid.state_text` grew one branch for that (`row["until_key"]`).

**Only ONE of the four pages keeps a checkpoint of its own.** The mines, the trucks and
the trains are re-read from `world_map.json`, which the capture rewrites every tick and
which survives a restart by itself; a second copy of five thousand mines, written again
on every finding, is a megabyte of disk per nudge and nothing gained. The MONSTER page
does keep one, because a read of the client leaves nothing on disk behind it and the page
would otherwise start empty every session.

A mine has no other clock, and this is not a shortcut: its occupancy changes under it, so a
forty-minute-old row claiming «свободна» is a lie in the one place the list is read for.
The state cell says «видели N мин назад» before the row goes (`grid.state_text`), which is
the honest halfway house.

## 7. What shipped

* `tools/lib/lastwar_proto.py` — `mines()` / `filter_mines()` / `Mine` / `split_mine_value`
  / `MINE_RESOURCES`, and `trains()` / `Train` / `TRAIN_TYPE`.
* `tools/lib/world_index.py` — the second listener, fed by the first one's hooks.
* `tools/secret_task_capture.py` — `--world-json`, `--world-max`, and the world line on the
  progress tick.
* `src/lastwar_bot/actions/read_world_monsters.md` — the one list no capture can fill.
* `panel/tabs/secret_tasks/world.py` — the four pages; `grid.py` — the column set and the
  sort keys became per-page instead of a module constant.
* `panel/profile.py` — `world_json()` and `world_state_json(page)`.
* Eleven locales, and the four cards on the phone.
* `tests/test_world_monitor.py` — the decoders, the listener, the caps, the parser.

## 8. What is left

* **The monster read wants one live run** (§3).
* **The ghost capture is still a second process** (§1).
* **`f2 = 35` and `f2 = 15` are undecoded** — ten and one tile in a whole lap. The 35 tile
  carries an alliance name, a player name and two timestamps; the 15 tile an alliance tag
  and a `f11` sub-message. Neither was chased.
* **Nothing here presses anything.** Gathering a mine, attacking a monster and robbing a
  truck are all marches, and none of them is an ability this repository has yet — the
  no-click pieces exist (`tools/dev/gather_direct.py`, `world-monsters.md` Finding 17) but
  are not scenarios. When one becomes one, the button appears in the window and on the
  phone in the same commit.

## 9. Three things the pages got wrong, and what each of them looked like (#1298)

All three were reported as one sentence apiece by the person using the panel, and all
three are worth writing down because none of them looks like what it is.

### 9a. «Поезда: 2+6» over a page with no trains on it

The notebook label was true and about the wrong list. `SecretTasksTab._page_label`
turned a page index into a grid through a literal written when there were five pages:

```python
page = {1: self.alliance, 2: self.ghost, 3: self.ghost_allies, 4: self.ghost_map}.get(index)
shown, hidden = page.counts() if page is not None else self.counts()
```

The four world pages are indexes 5..8. They fell through `.get()` to `None`, and `None`
means «this is the ★ page» — so **every world page wore the ★ list's counter**. On a
client holding two visible raids and six filtered ones, all four of them read `· 2+6`.

The counter is the one place a person looks to tell «нашлось пусто» from «всё скрыто
фильтром», so a true count of the wrong list is worse than no count at all: it is a
confident answer to the question the counter exists for. The fix is not a longer literal
— it is registering the grid beside its label (`_add_page(frame, key, page)`), which a
tenth page cannot fall through.

**The train list itself was empty and honest.** A recorded checkpoint from that session
held `mines 42 · trucks 6 · trains 0`, which is exactly what the alliance train being an
event rather than an all-day thing looks like (§2: 3 trains in *every* recording on disk).

### 9b. «Пусто» and «не смог прочитать» were the same silence

`refresh_world` returned without a word on a missing file, on a torn one, and on a file
holding nothing. Three situations, one blank page:

* the map monitor has never run under this profile — a switch to flip;
* the checkpoint cannot be parsed — a bug;
* the map genuinely has no train on it — the answer.

It now says which, and says the per-kind counts when it parses (`log.world.*`). Once per
ANSWER, not once per nudge: `refresh` is called by the capture on every finding, so an
unconditional line would be a log nobody can read past — the memo is `_world_said`.

### 9c. A truck was drawn where it had been, not where it is

**The wire never carries a position.** §2 already said the leg is what a position is
computed from, and `Truck.position` / `Train.position` have always walked it. What was
missed is that `as_dict()` freezes the answer: it calls `position` ONCE, when the frame is
decoded, and writes the resulting `x`/`y` into the checkpoint beside the leg it came from.

The panel's two record builders then took the pair and dropped the leg:

```python
{"uuid": …, "x": item.get("x"), "y": item.get("y"), …}   # and no leg_* at all
```

So a row stood on the tile the capture had first heard about it on and did not move again
until the server happened to re-send that march. A leg runs about two minutes; a run lasts
hours. A truck was routinely drawn eight or ten tiles from where the client was drawing it,
which for a list whose whole purpose is «where do I send a squad» is the wrong answer given
confidently.

Fixed in three places, and the shape of the fix is the point:

* `lastwar_proto.march_position(leg_from, leg_to, start_ms, end_ms, now_ms=None)` — the
  arithmetic, extracted from the two properties that had a copy each;
* `world.truck_records` / `train_records` carry the four leg fields, and they are in
  `PERSIST_KEYS`, so a checkpointed vehicle goes on moving after it is read back;
* `TaskGrid.advance()` — a hook the per-second tick calls before the timers. It returns
  «did a cell change», and only `_VehicleGrid` overrides it: the other pages hold tiles,
  which do not move, and a redraw they do not need is a redraw on the one event loop every
  open profile shares (#1226).

**The clock is the GAME's** (`tools/lib/game_clock.py`), never the PC's. On a two-minute
leg the offset between them is tiles, which is the whole quantity being computed.

Measured against a live checkpoint while writing this: four trucks, stored `(x, y)`
against the position walked off their own legs at that instant — the smallest gap was
16 tiles and the largest 60. The rows had been on screen for minutes.

**Open, and NOT done here: the camera does not follow.** The person using the panel
reported that the game's own way of going to a moving target «переносится к ней и следует
за ней» — the camera tracks the vehicle rather than landing on the tile it was on when the
link was tapped. The panel's coordinate click is `rt.game.jump` → `GotoWorldPos(x, y, srv)`,
which lands and stops. With the position now live, a click lands on the right tile and the
vehicle then walks out of frame. Following it is a different ability (the object handle,
not a coordinate — `GoToUtil.OnClickWorldPoint(pid, type, uuid)` is where that would start)
and belongs to whoever takes it, as a scenario.

### 9d. And the button that emptied a list nobody was looking at

«Очистить список» stood on the tab header, over a notebook of nine tables, and emptied the
★ one. Pressed while reading «Поезда» it did nothing visible — indistinguishable from a
button that does not work. Every page carries its own now (`TaskGrid.clear_pressed`), and
each card on the phone carries its own `clear_<page>`.

This is the THIRD door into a list and the only other legal one: `THE_LIST_RULE` lets a row
go for its own expiry or for the game saying the tile is gone, and a person asking out loud
for one table is not a fourth reason to touch the other eight.

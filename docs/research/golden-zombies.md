# Golden zombies — what they are, how they are found, and how a chain of kills is driven

Task #1519. The player's «золотые зомби» are the invasion event's small monster: the
yellow ones sitting on piles of gold coins. This is what identifies one, what a kill
costs, how a whole list of them is read out of the client without a single tap, and which
part of the chain is proven live and which is not.

Companion to [`world-monsters.md`](world-monsters.md), which is where the no-click select
and the launch primitive were worked out over seventeen findings. Nothing here re-opens
those; it uses them.

Everything below marked **live** was measured against a running client on 2026-08-19,
through the panel's own web API (`docs/research/panel-web.md`) because Windows interop
was down that day and the daemon could not be reached from WSL directly.

## 1 — the identity is a config id, and only a config id

**live.** `LocalController.instance():getLine('lw_world_monster', 1030000)`, every column
it carries:

| column | value | what it means |
|---|---|---|
| `id` | `1030000` | the whole identity — this is what the whitelist below is keyed on |
| `level` | `10` | the «10» tag drawn over it on the map |
| `type` | `7` | the zombie line (`8` is the Doom line — the same split `join_rally.md` sorts banners by) |
| `special` | `9` | `WorldMonsterSpecialType.MonsterInvasion` — it belongs to the invasion event |
| `size` | `1` | one tile |
| `recommend_power` | `670000` | what the popup shows as the recommended power |
| `expire` | `720` | it disappears by itself after twelve minutes |
| `is_stop` | `1` | it does not roam |
| `speed` | `0.75`, `attackRange` `6`, `deadTime` `30` | the rest of its behaviour |
| `worldmap_icon` | `…_huang0` | «huang» is yellow — the gold in the name is real, and it is the last thing to identify one by |

The name is loc key `2901011` («Вторгшиеся Зомби» / "Invading Zombies") and the
description `2901027` — the one that jokes about preferring gold coins to brains.

**So the recipe matches on `1030000` and never on the icon, the model or the label.** A
re-skin would break a picture match and cannot break this one;
`tests/test_golden_zombies.py` fails if `worldmap_icon`, `pic_name` or `huang` ever
appears in the scan.

## 1b — the PREFAB name is how a drawn one is recognised, and the level lives in the config

The operator's own hint, and it was the right way in: on the panel's monster grid a golden
zombie already shows up as **`WorldMonster_General_invasion`** — with the level column
reading **0**, which is what sent this section looking.

**The prefab name is a column of `lw_world_monster`.** `pic_name` of config 1030000 reads
`world_monster_general_invasion`: the clone's own name, bar the case and the underscores.
So normalise both (lower-case, drop everything but letters and digits) and the drawn
object is a key into the config.

**Is the name enough on its own? Yes, for this one.** Census of every `pic_name` in the
table, live — 12 115 rows, 107 distinct prefabs:

| prefab | rows | levels | type |
|---|---|---|---|
| `world_monster_general_invasion` | **3** | **10, and only 10** | 7 |
| `world_monster_boss_invasion` | 30 | 5 … 75 | 7 |
| `world_monster_boss_invasion_1` | 10 | 80 … 100 | 7 |
| `world_monster_boss_invasion_2` | 10 | 105 … 150 | 7 |
| `world_monster_boss_iron` | 35 | 1 … 35 | 1 |
| `world_monster_boss_coin_2` | 35 | 1 … 35 | 5 |
| … | | | |

So `WorldMonster_General_invasion` **is** the golden zombie and nothing else: the event's
boss is a DIFFERENT prefab (`world_monster_boss_invasion*`, `special = 10` against the
general's `9`). The three rows behind it — 1030000, 1030001, 1030002 — agree on level,
type and special, so all three go into the enumerator's whitelist. The first version of
the scan tested «the clone's name contains `invasion`», which is also true of a level-75
boss; that is fixed.

**The rule is unanimity.** A prefab whose rows agree on a field answers it; one whose rows
disagree answers nothing and the reading falls back to the level label drawn over the
monster, and to «nobody could say» when there is no label either. Caught live doing
exactly that: `WorldMonster_Boss_invasion_2` in view resolved to `type = 7` (all ten rows
agree) and `level = nil` (they span 105…150). A level guessed for something that could be
105 or 150 is the same lie the column already had.

### The level column showed 0, and 0 is a lie

Every scene-read monster had come back `type=0 level=0` since the page existed, because a
drawn clone carries no config id and the label over it is not always readable. Zero is the
worst possible answer — it is a NUMBER, so the column drew it, and «уровень 0» over a
level-10 zombie sends a person hunting for a bug in the game. The reading now answers
**`-1` for «nobody could say»**, the grid draws that as **«—»**, and a row saved by an
older panel (a literal 0) is drawn as «—» too.

### Two traps that made the fix look like it had failed

Both cost a full round of «restart, re-read, still wrong», and both are general:

* **A panel restart does NOT clear the game's Lua globals.** The prefab map is built once
  and parked in `_G`; the panel was restarted onto a fixed builder twice and went on
  answering from the EMPTY map the broken one had left behind, because the game VM had
  not gone anywhere. Anything cached in the VM now carries the version of the code that
  built it (`MON_MAP_VERSION`) and is rebuilt when they disagree. This is the mirror image
  of the restart rule in `CLAUDE.md`: restarting the panel is necessary and is not always
  sufficient.
* **A recipe embeds a COPY of any helper it uses.** The DSL has no include, so
  `read_world_monsters.md` carries the text of `monster_prefab_lookup()` inside its
  `READ_LUA`. The module was fixed and the copy was not, so every level still read `-1`
  while the module was right. `tests/test_golden_zombies.py` now fails when the two drift.

And one dead end worth not repeating: **`getTable(name).index` is not the way to the
column numbers.** `getTable` does answer `{index = …, data = <id -> row>}` and `data` is
exactly what is wanted — a plain Lua table, 12 115 rows, keyed by config id, each row
keyed by column NUMBER. But `index[<column name>]` hands back a little table whose shape
we could not pin down, every lookup through it was nil, and the walk built an empty map in
silence. The column numbers come from `getLine(id):getMetaData()` instead, which is the
reading this repository has used since #1281.

## 2 — the price of one attack, and the purse

**live.** `MarchUtil.GetCostStaminaByTargetType` has the signature
`(type, rallyType, formationUuid, destroyTimes, isEmptyDesert)` and answers **10** for
`MarchTargetType.ATTACK_MONSTER` (`= 1`). It answers `0` for `CROSS_ATTACK_MONSTER` and
for `DIRECT_ATTACK_ACT_BOSS`, so it is asked with the ordinary attack type and the answer
is used for both.

The purse is **`LuaEntry.Player.stamina`** — a float, 120 on a full account, so twelve
attacks. `LuaEntry.Player:GetCurStamina()` answers the same number and is asked second,
for builds where the field is absent. `ArmyFormationDataManager:GetCurStaminaByUuid(uuid)`
answers the same number for every formation, so it is NOT a per-squad allowance — there is
one purse per account.

There is no per-day quota on these: `MonsterManager:GetRestKillBossNum()` counts BOSS
kills and has nothing to do with the small ones. The energy is the whole gate.

## 3 — reading a list of them with no tap at all

`WorldScene:GetMonsterListInArea(centre, size, cfgIdWhitelist, out)` — Finding 6 of
world-monsters.md, and it is **invasion-only** (Finding 10), which is exactly what is
wanted here: golden zombies ARE invasion monsters (`special = 9`). It answers
`uuid -> tile`, and the uuid is the one thing a march cannot be sent without.

Three things about it were measured because guessing them all cost a run each:

* **it filters a list the client already holds, and the `size` is a plain filter.**
  `centre = (500,500), size = 2000` returns everything the client knows; `size = 300`
  around a corner of the map returns the ones in that corner. So one call with a wide
  size is «tell me everything», and that is what the recipe asks.
* **it is as wide as what the client has LOADED, not as wide as the map.** Straight after
  entering the world: **11**. After one lap of the server (`scan_map.md`): **135**, and
  143 by the end of the run. The lap is therefore load-bearing and not decoration.
* **the camera matters only through what it has loaded.** The centre argument is honoured
  independently of where the camera is standing — but a lap ends with the camera in a far
  corner, and a scan centred on `CurTilePos` there queues 79 zombies that are all 400
  tiles from the base. Centre the scan on HOME.

The second source, for anything the enumerator misses, is the drawn clones —
`WorldMonster…invasion(Clone)` objects around the camera. A clone knows its tile and NOT
its uuid, so one is completed by `TouchObjectEventTrigger:OnClick()` (opens the point
popup, the server hands over the uuid), read off `Ctrl.uuid` / `Ctrl.pointId` /
`Ctrl.serverId`, and closed with **`Ctrl:CloseSelf()`** — never `DestroyAllWindow()`,
which destroys the HUD for good (world-monsters.md, Finding 16).

## 4 — where home is, and the wrong turn taken over it

The first target of the chain is the nearest one to the SQUAD, and before the first march
the squad is standing in the base. **`SceneUtils.TileDistanceToMyHome(pointIndex,
serverId)` answers that, correctly, and is what the recipe uses.** Live: `0` at the base
tile, `49` at a tile 49 away, `492` at one 492 away, the same with the server id passed
and with it left off.

It is written up at length because a whole afternoon went into disbelieving it. The
symptom was a first pick 492 tiles from the base, which reads exactly like a broken
distance function — so it was replaced with «the tile under the camera when the world
opens», which is the base *only if the scene was just entered*. A client the panel keeps
on the map has its camera wherever the last lap of `scan_map` left it, and the run that
took that for home measured every distance from a corner of the world.

**The 492 tiles were real.** Of the 134 golden zombies the client knew about, the nearest
one to the base was 492 tiles out: they cluster in their own region of the map and not
around anybody's alliance (the «golden vein» of world-monsters.md, Follow-up 5). That is
precisely the argument FOR the chain rather than against it — the walk out is paid once,
and every kill after it is a few tiles.

The lesson is the one this repository keeps re-learning: a reading that looks wrong is
checked against a value you can compute yourself before it is replaced. One probe of
`TileDistanceToMyHome` at the base tile would have answered it, and it answers `0`.

`GoToUtil.GotoCityPos()` is NOT a way back to the base: called with no argument it put the
camera on tile (48,48). `GoToUtil.MoveToWorldPoint(pointId)` is the tile-accurate mover
(world-monsters.md, Finding 9) if one is ever needed. Neither is needed here: the scan
asks for a radius wider than the map, so the centre it is given does not matter.

Tile index arithmetic is never done by hand here: `ws:TilePosToIndex(tile)` and
`SceneUtils.IndexToTilePos(pid)` are inverses of each other and disagree by one with the
`y * 1000 + x` rule of thumb (`TilePosToIndex(600,500) = 500601`,
`IndexToTilePos(500600) = (599,500)`), which is exactly the sort of off-by-one that puts a
squad on the wrong tile.

## 4b — the fast approach: ride out on a GATHER order, attack from beside the target

The operator's idea, and the game's own arithmetic backs it. `MarchUtil` prices a march
per ORDER, not per distance:

```lua
MarchUtil.CalcMarchSpeedByConfig(targetType, formationUuid, nil, nil)
```

Live, same formation, same call:

| order | speed | |
|---|---|---|
| `ATTACK_MONSTER` (1) | **0.765** | what a kill costs to reach |
| `ATTACK_CITY` (11) | 0.815 | |
| `COLLECT` (2) | **1.930** | **×2.52** |
| `DETECT_TREASURE` (50) | 1.930 | |

Two separate bonuses stand behind that rather than one — `GetFormationSpeedAddByIndex`
and `GetFormationCollectSpeedAdd` are different numbers on the same squad — so the ratio
is an account's own and the panel shows it rather than assuming it.

**The unit is tiles per second, and the stopwatch says so.** A plan for a live target 704
seconds away by attack march priced the ride at 285 s; the COLLECT march was then really
sent and the game's own march object answered `endTime − now = 271 s`. Take off the last
twelve tiles at attack speed (16 s) and the prediction was 269 against the server's 271 —
**two seconds apart**.

**What it is worth.** Across the live queue of 80 golden zombies, the farthest was 680
tiles out: **888 s marched straight there against 361 s ridden — 527 s saved**, on one
target. That is the case the feature exists for; the zombies live in their own region and
the haul out is most of the cost of a kill.

**When it is NOT taken.** Only when the direct march is over the caller's threshold AND
the two-leg route is actually shorter:

```
direct  = dist(squad -> target) / speed_attack
two-leg = dist(squad -> mine) / speed_collect + dist(mine -> target) / speed_attack
```

Live, a target 22 s away was correctly left alone (`why=short`), and one 11 s away was
still left alone by the arithmetic even with the threshold forced to zero — until a mine
close enough turned up, at which point `direct=11 via=7`.

**Finding the mine.** `WorldScene.PointManager:GetPointInfo(pid)` answers `ResPointInfo`
with `pointType = WorldResource: 7` for a mine and `BuildPointInfo` / `PlayerBuilding: 6`
for somebody's base — the same `f2` split as the wire (`world-tiles.md`). Two traps, both
paid for:

* **`pointType` is an ENUM, not a number.** It prints as `WorldResource: 7` and
  `tonumber` on it is `nil`, so the first version found «no mine» on a map covered in
  them. The digits at the end of its own name are the value.
* **`HasPointInfo` only knows the districts the CLIENT has loaded**, and the target is
  usually one it has never been to — the mines are on the wire and in the panel's own
  map, and the client still says nothing. So the camera is put on the target first
  (`GoToUtil.MoveToWorldPoint`), given a beat, and only then is the ring scanned.

**«Has it arrived» is answered by the march's clock, never by the squad's state.**
Measured: a ride the server timed at 271 seconds left the formation reading `state = 1`
at 485 seconds and counting, because a squad that has landed at a mine is GATHERING and
the client draws no distinction between «on the road» and «at work». So every wait in the
chain is on the newest own march's `endTime` — the server's own arrival stamp, and the
one that came within two seconds of the prediction. This corrects §5 below: the state
reading tells «out» from «at home» and nothing finer.

### It DOES finish — and the diagnosis below was ours, not the game's (#1702)

**Everything from here to the end of this section was wrong, and it is kept because the
way it was wrong is the lesson.** The attack issued from beside the mine was refused over
and over, and that was written down as a rule of the game. The operator — who plays this
account by hand — said plainly that they attack from a mine and from the road every day.

They were right. The uuid of a monster is a C# `Int64` the enumerator hands over, and the
queue was keeping a REFERENCE to it; by the time a chain's second target was sent,
`tostring()` on it answered `<invalid c# object>`. Nothing was being refused, because
nothing was arriving: the send carried a dead reference. The queue keeps the TEXT of the
uuid now and the live object is fetched again at the moment of the send.

Proven live on 2026-08-20, with the ride threshold lowered so short hops would plan one:
three rides, two attacks launched from beside the mine (`launched = 1`, the game holding
the march), one zombie confirmed gone, and four stale targets dropped without an order
being wasted on them.

The lesson is the one this repository keeps paying for: **a refusal that cannot be
reproduced by hand is a bug in the sender, not a rule of the game.** Ask the person who
plays it.

### The old reading — And it does not finish — measured, not feared

The whole manoeuvre was run end to end: a ride was planned, sent, waited out, and then
the attack was issued from the mine. **The server did not take the energy** — fourteen
seconds of polling, `charged: 0`, with the squad landed (`state = 1`), the purse at 98
and the target parked. So a bare `SendCreateMarchMessage` does not move an army off a
resource node: a squad that has arrived at a mine is GATHERING, and the game holds it
there.

That is the same missing step the chain's second kill needs — a march issued from where
the squad stands rather than from home — and this feature inherits it exactly. **So the
switch ships OFF.** Turning it on today would send the squad on a fast ride to a mine and
leave it there having bought nothing.

What is missing is one call: how the game takes an army off a resource node without
walking it home. `MarchUtil.OnBackHome` exists and is the wrong shape (it walks it home,
which is what the chain is built to avoid). Nothing else was tried, and nothing should be
guessed at — the last three times a march primitive was guessed at in this repository it
returned `true` and did nothing (`world-monsters.md`, Findings 11 to 16).

**The ride itself is free**, which is why the machinery is kept rather than deleted:
`GetCostStaminaByTargetType(COLLECT)` is **0** against 10 for an attack, so the failed
attempt cost travel time and not one point of the day's purse — and the recipe still
proves every attack by the energy the server takes, which is exactly what caught this.

## 4c — the base's OWN TILE, out of the same oracle (#1702)

Live, 2026-08-20. There is no call that hands the player's own tile over: `SceneUtils`
carries exactly one home-flavoured function and it answers a distance
(`pairs(SceneUtils)` matching `Home|Self|My` → `TileDistanceToMyHome`, and nothing else;
`LuaEntry.Player` exposes no tile at all, `GoToUtil` no `*Home*`).

It does not need to. **The distance field is plain Euclid** — measured, a tile 64 east of
home reads `64.0` — so three readings solve it:

```
d0 = d(C)      d1 = d(C + (a, 0))      d2 = d(C + (0, b))
u  = (d0² - d1² + a²) / 2a      v = (d0² - d2² + b²) / 2b      H = C + (u, v)
```

with a 7×7 sweep around the rounded guess to place it exactly, and the answer refused
unless the winning tile reads under 1.5. Live check with the camera parked at home:
`d0 = 0, d1 = 64, d2 = 64 → guess (564,468), d at guess = 0`, and the sweep found nothing
nearer. `golden_arm` parks it as `p.home`, so the FIRST pick compares a tile against a
tile exactly as every later one compares against the last kill — one metric for the whole
chain instead of one call for the first pick and arithmetic for the rest.

## 4d — «the nearest» is only as near as what the CLIENT has loaded (#1702)

The operator's report was «ближайший берётся в 5 минутах пути, хотя рядом полно зомби»,
and §4 above is what made it worth a second look: the 492 tiles of #1519 were real, so a
far pick is not by itself evidence of anything.

This one was. `WorldScene:GetMonsterListInArea` answers out of the client's own loaded
tiles, not out of the server — and the recipe scanned once, straight after a lap of
`scan_map`, which leaves the camera at the far end of the warzone with the districts
around the base long since evicted. The list handed to the pick then genuinely has no
near zombie in it, and «the nearest» is the nearest of the far ones.

Measured on 2026-08-20, one account, minutes apart:

| when | camera | golden zombies the enumerator knew | nearest to home |
|---|---|---|---|
| camera sitting on the base | (566,473) | 188 | 27 tiles |
| after the client had been walked elsewhere | (564,471) | 0 | — |
| straight after re-entering the world scene | — | 0 | — |

Same account, same warzone, same invasion. The fix is one press with nothing sent:
`golden_look_from` puts the camera on the ORIGIN of the next pick — the base before the
first kill, the last kill afterwards — the recipe waits a beat and scans again, and only
then picks. `GoToUtil.MoveToWorldPoint(pid)` is the tile-accurate mover (§4).

The general lesson, and it is not about zombies: **any reading taken through
`GetMonsterListInArea`, `HasPointInfo` or `GetPointInfo` is a reading about the CLIENT's
memory, and a camera that has moved is a different memory.** A sweep of the map fills it
and evicts what it filled it with an hour ago.

## 4b — the registry: one lap, and then the map keeps it honest (#1702)

The operator's model, and the shape the chain has now: **one brisk lap of the map gives
the list of targets; from the first march onwards the list is checked against the map
rather than trusted, and the expensive re-look happens on a threshold rather than on a
clock.** A row leaves the list only where the map SAID it is gone — the secret tasks'
THE_LIST_RULE (#1272), applied to monsters.

### What the lap does and does not give

A lap moves the camera every 0.05 s. That is far faster than the client's region loader,
so the lap gives the FAR picture and leaves the ground near the base blank. Measured live
on 2026-08-21, standing 488 tiles from home after a lap:

| what was asked | answer |
|---|---|
| `GetMonsterListInArea(home, 300)` right after the lap | **0** golden zombies |
| the same call after 13 camera stops around home (~14 s) | **17**, the nearest **14** tiles away |

The ground was never empty. It was never loaded — and neither was the district the pick
was measured from, which is why the chain's first choice came out 488 tiles away twice in
a row. **One wide look at the lap's own height does not fix it**: tried, and the first
pick still came out 488. Only dwell loads a district.

So the run opens with a short ring — `GOLDEN_REFRESH_STOPS` stops on one ring of
`GOLDEN_REFRESH_RING` tiles plus the origin, on the game's own timer, the enumerator read
at each stop, about nine seconds. That is the same press the chain uses later, and it
replaced an eighteen-stop, twenty-second sweep that ran before every first pick.

### Reaping: what takes a row out

`golden_scan` used to only ever ADD, and a queue that only grows is a queue of corpses:
live, a chain with `queued = 164` walked down it dropping dead target after dead target —
20 tiles, 23, 37, 50 — at about eight seconds each, discovering one death at a time, at
the moment of the send.

Every scan now records what the enumerator actually returned (`present`) and drops a
queued target that is missing from it — **but only where both halves of «we looked» hold**:

* the target is within `GOLDEN_SEEN_REACH` tiles of the camera (the window the client
  draws), and
* `WorldScene:HasPointInfo(pid)` says the client holds that tile's district.

Anything else — a far target, an unfetched district, an oracle that will not answer, or a
read that raised — is «nobody looked there», and the row stays. The asymmetry is
deliberate: a row wrongly kept costs one refused send, while a row wrongly dropped is a
zombie the chain can never come back to, because nothing re-adds what the scan cannot see.
`golden_here`, the last check before a send, obeys the same rule — an unread district can
no longer answer «gone».

### The threshold

`p.since_refresh` counts PROVEN disappearances and `GOLDEN_REFRESH_AFTER` (3, the middle
of the operator's «2–5» band, overridable per run with `refresh_after`) is what buys the
ring. Below it nothing flies anywhere: the camera already stands on the kills, so the
ordinary scan after each one is a current picture nearly all the time. `refresh_after = 0`
switches the redraw off and leaves the run on the opening lap and the reaping alone.

This replaced a camera flight to the candidate and a re-pick after EVERY kill — 4 seconds
of «first choice» → «target» on every single lap of the chain, whether or not anything had
changed.

## 4c — a squad that will not take an order, and the three ways it happens (#1702)

Every «залипание» this task chased turned out to be the same shape: an order given to a
squad the game was never going to accept one from. The reading that ended the guessing is
one press — `actions/dev/golden_squad_state.md` — and it says everything at once:

```
squad1 state=1 canMarch=false soldiers=0
squad2 state=1 canMarch=false soldiers=0
squad3 state=0 canMarch=false soldiers=0
marches=2 [left=4082s left=-…]
rally_squads=1,2,3
```

### `canMarch` never answered this at all — the gate reads `state` and `IsFree()`

**This is the correction, and it is the whole of «в логи пишется, что ОТРЯД ЗАНЯТ, но это
НЕ ТАК».** The gate above was built on `canMarch`, and `canMarch` is a **red herring**:
it is recomputed by the real dispatch render (`UIFormationSelectListV2`) and by nothing
else, so a headless session reads whatever the flag was last left at. This was already
written down — [world-monsters.md, Finding 11](world-monsters.md) — and the golden family
asked it anyway.

Measured live, one press apart, on a squad standing **at home with a full army**:

```
squad=2 state=0 free=1 soldiers=2631 status=- march=- team=0     ← read_squad_state.md
squad2 state=0 canMarch=false soldiers=2631                      ← the old golden gate
```

Both readings are of the same squad, in the same second. The player saw squad 2 sitting
in the base; the panel said «отряд занят» and sent nothing. The same read showed
`squad1 state=1 canMarch=false` — genuinely marching — so `canMarch` was `false` for the
busy squad and the free one alike, and it distinguished nothing.

The rest of this repository never had the bug: `create_rally.md`, `read_squad_state.md`
and `panel/tabs/rally/limits.py` all ask **`state == 0` together with the game's own
`IsFree()`**, which is what `ArmyFormationDataManager:IsAnyWorldFormationOutside()` is
built out of. `_SQUAD_FREE` in `tools/lib/lua_actions.py` is now that same question, and
every golden brick asks it through `golden_squad_free()` / `golden_send_now()`.

### «No army» is still a separate fact — and it is asked FIRST

A squad the client holds **no soldiers** for is standing at home and answers `state = 0`,
`IsFree() = true`: free by every reading the game has. The old order of the checks hid
that behind `canMarch`, which happened to be false for it too. So the order matters —
the soldier count is asked **before** the free flag, or an empty formation is sent at a
zombie and refused by the server:

| answer | means | what to do |
|---|---|---|
| `1` | the squad is in the base, idle, and holds an army | send |
| `0` | marching, gathering, or on dirty ground | wait, bounded |
| `-2` | the client holds no army for it (#1285) | ask for it, then re-read |
| `-1` | the squad cannot be found | ask again |

### The launch proof asks the FORMATION, not the account

The other half of the same press had the mirror-image fault. A send was confirmed by any
march that had appeared in `GetOwnerMarches()` since it went out — and that list is every
squad of the account. An auto-join raising a **second** squad inside the four seconds the
panel waits confirmed an order that had been refused.

`GetOwnerFormationMarch(uid, formation, allianceId)` answers for our formation alone, and
a march standing in a banner (`teamUuid ~= 0`) is not the order we gave: from outside the
two look alike, both carrying `endTime = 0`.

### A mine is a trap with a long clock

A ride is a **gather** order, so a squad that lands on a mine starts working it. Measured
live the moment after a ride landed: `canMarch = false` with the march's own `endTime`
**109 minutes** away, and on a later run **4 082 seconds** still to go. Every attack sent
into that window is refused in silence, and the old chain proved it the expensive way —
ten seconds of launch polling, a target written off, the next one tried — for as long as
the run lasted. The wait that followed then sat in front of the same clock.

Two rules answer it. A march whose clock is further out than `GOLDEN_WAIT_CEILING` is not
this hunt's and the squad is recalled rather than waited on; and the first ride that ends
in a gather blows a fuse (`golden_no_ride`) that switches riding off for the rest of the
run.

**What the numbers do NOT say.** It is tempting to conclude the ride never works. Counted
over the whole log: 22 rides, 4 followed by a confirmed attack. But the plain attack march
scores the same — 129 sends, 23 confirmed — so the ride is not distinctly worse; what was
failing was the SEND, on both paths, for the reasons in §4d. The fuse is the measured
safeguard; condemning the ride is not supported by this data.

### The squads may not be the hunt's to use

`rally_squads=1,2,3` is the auto-join's own list, and the account has exactly three
squads. A banner therefore takes the hunt's squad within seconds of it coming home, over
and over, and the hunt spends its laps waiting for a squad standing in somebody's rally.
That is a **setting**, not a fault: the chain says so once, in words, and carries on. The
squad the rally may use and the squad the hunt uses have to differ, and only the person
can decide which is which.

## 4d — the launch proof, and «меняет маршрут, когда уже идёт на зомби»

The march list belongs to the client, and the client lists a march when it gets round to
it. A send that WAS accepted but had not been listed yet read as a refusal: the chain
wrote the target off, chose another and ordered the squad there — re-routing a squad that
was already walking, which is exactly what the operator saw.

The proof now takes either half: a march that was not there before, **or** the game
answering `canMarch = false` for our formation. The second is instant, and it is only
sound because of the rule above — the chain never sends unless the squad is free, so
«busy now» can only be the order just given.

The old post-send «is the squad stuck» branch is gone with it. It asked the same question
with the opposite meaning (`canMarch = false` → dirty ground), which is how one reading
came to mean both «the order was taken» and «the order was impossible».

## 4g — the opening pick, measured: median 47 tiles, tail 569 (#1702)

With the pick's diagnostic printing again (§4f), 207 live picks over a day answer what
the chain's design was only claimed to do:

| measured from | n | median | mean | max | within 25 tiles |
|---|---|---|---|---|---|
| the base — the FIRST pick of a run | 76 | **47** | 111 | 569 | 30% |
| the anchor — every pick after it | 130 | **11** | 13.6 | 50 | **88%** |

So the chain itself is doing exactly what §5 says: 88% of continuations are within 25
tiles and the median hop is eleven. **The expensive pick is the opening one**, and the
ratio of the two counts says why it mattered so much — 76 openings against 130
continuations means runs were ending after about 1.7 kills, so nearly every kill was
paying an opening march.

The opening ring covers about 160 tiles — its own radius (`GOLDEN_REFRESH_RING`) plus
what the enumerator reads at each stop — and an answer beyond that is «the nearest of the
ones the client happens to hold» rather than «the nearest one there is». That is the same
loading effect the ring exists for, one size up: standing 488 tiles out, the client
answered `0` within 300 tiles of the base and, thirteen dwell stops later, `17` — the
nearest of them 14 tiles from the front door.

So a far opening answer now buys another ring instead of a march: `golden_widen_ring`
doubles the run's own ring (up to `GOLDEN_RING_MAX`), the refresh walks the wider one at
the same cost per stop, and the queue is re-read. Twice at most, and only while the answer
is still beyond `GOLDEN_FIRST_FAR`. The arithmetic it rests on: at the attack speed the
game quotes, 569 tiles is over ten minutes of marching, and a ring is nine seconds.

## 4h — where a kill's time actually goes, and the one shortcut the game refuses (#1702)

Two squads hunting on the test account, twenty minutes, split per kill:

| segment | side A | side B |
|---|---|---|
| squad free → order away (judge, pick, uuid check, send) | **5 s** | **5 s** |
| order away → squad free again | **115 s** | **64 s** |

**Our own overhead is five seconds and it is not where the time is.** Everything the
recipe does between kills — judging the last one, choosing the next, re-fetching the
uuid, the readiness gate, the send — costs five seconds together. The minute and a half
is the squad, and it is not the march either: a squad that had just killed reads

    squad=2 state=1 free=0 soldiers=2570 status=STATION march=NORMAL team=0
            point=467403 arrive=0

STANDING on the tile it cleared, which is exactly what `back = 0` asks for so that the
next hop is three tiles instead of a march from the base. The gate calls that BUSY,
because `state == 0` plus `IsFree()` is the reading a RALLY needs — a banner is raised
from the base — so the hunt walks the squad home and pays the round trip on every kill.

**The obvious shortcut was written down as impossible, and that was our bug — see §4i.**
The gate was widened to accept a landed, banner-free march and the sends were refused in
silence: two orders at a stationed squad at 01:27:51 and 01:28:01, and the purse unmoved,
1941 before and 1941 three minutes later. The reading taken from it — «the game refuses
to redeploy an army that has arrived» — held for a day and was wrong. A bare
`SendCreateMarchMessage` creates a march FROM THE BASE; the door for a squad already out
is `MarchUtil.SendChangeMarchToServer`, and it works.

### And the measurement that decided where to aim next

Twenty-one laps, each row a kill: how far the target was from the last corpse, how far it
was from the BASE, and how long from the order to the squad reading free again.

    home_dist  anchor_dist   order->free      2*home_dist/0.765
        22          5            57 s              58 s
        26          9            64 s              68 s
        25          3            55 s              65 s
        53         17           126 s             139 s
        54          4           130 s             141 s

**The cost tracks the distance from HOME and ignores the anchor entirely.** A target two
tiles from the corpse and twenty-five from the base costs sixty-five seconds, because the
squad walks home and out again. That is the whole of the chain's «nearest to where the
squad is» idea undone by one measurement: the squad is not where it killed by the time
the next order can be given, it is at the base.

**That table prices a chain that walks home between kills, and it is the reason §4i was
worth looking for.** For one day the conclusion drawn from it was «measure every pick
from HOME», which is correct arithmetic over a wrong premise: the squad walked home only
because our send could not use it where it stood. With the redeploy call the anchor is
the origin again and the second column is the one that is paid.

What that left, in order of what it would buy — and the first line is now done:

* **the redeploy call itself** — the whole 60–115 s, and the only route to the operator's
  own four attacks a minute. Found: §4i;
* nothing in the five seconds. Cutting our own checks in half would buy 2.5 s of a
  70-second cycle, which is 3%, and every one of them is a bug already paid for.

## 4i — the redeploy door: `SendChangeMarchToServer` (#1702)

**A squad that has landed is re-aimed where it stands. Proven live on 2026-08-22.**

`MarchUtil` has three names shaped like the answer, and this client still allows
`string.dump`, so their constant tables were read without opening a window:

    MarchUtil.OnChangeSingleFormation(formationUuid, targetMarchUuid, realPointId)
    MarchUtil.OnChangeSingleMarch(marchUuid, targetMarchUuid, realPointId)
    MarchUtil.SendChangeMarchToServer  ->  SFSNetwork.SendMessage(
        MsgDefines.WorldMarchChange = "world.march.change",
        {marchUuid, targetType, targetPoint, targetUuid, backHome, targetServerId,
         destroyTimeIndex, marchInfo{posStart, status, startPos, endPos, startPointId,
         endPointId, path, curWorldId}, cardSkillUseInfoList})

`debug.getinfo(f, 'u')` says `nparams = 7` for the sender and `3` for the two wrappers.
The sender builds `marchInfo`, the world id (`GetCurWorldId`) and the card list
(`PopFormationViewCardSkillUseCache`) itself, so the seven are the first seven fields of
the payload. The target type is chosen out of `MarchTargetType` inside it, which is why
this is «change what this army is doing» and not an attack special case: the same door
sends a standing squad to a mine.

Three shapes were tried at one squad, in order, with the purse read between each:

| attempt | call | purse | march |
|---|---|---|---|
| A | `SendChangeMarchToServer(march, ATTACK_MONSTER, pointId, monsterUuid, 0, server, 0)` | **1871 → 1861** | `STATION: 0` → `MOVING: 1`, target on the new tile |
| B | the same, with a tile POSITION where A had the index | no further change | already moving |
| C | `OnChangeSingleMarch(march, monsterUuid, pointId)` | no change | already moving |

A is the call. The squad was reading `state=1 status=STATION: 0 pos=440462 end=0` — out,
landed, no clock — and the new target was 23 tiles away with no step homewards.

Two things the caller has to get right:

* **the march uuid is the squad's own**, and `GetOwnerFormationMarch` cannot always be
  relied on to hand it over (§4c). The chain keeps the uuid of the march it put out
  (`p.own_march`, written the moment `golden_launched` sees it) and asks for the march by
  name when the first question comes back empty. Never «the only march the account has»:
  with the pair driver two squads are out at once.
* **a redeploy makes no new march.** The uuid does not change — the status turns MOVING
  and `targetPos` becomes the tile asked for — so the ordinary proof, «a march that was
  not there before», can never come true for one. The proof is that the run's own march
  now points at the very tile of the send.

The wrappers are the screen's, not ours: `OnChangeSingleFormation` was called with a
monster uuid in its `targetMarchUuid` slot and the server did nothing at all — purse
unmoved, march unchanged.

**And the lesson is the one this file already carries once, in §4b:** a refusal the
person playing by hand cannot reproduce is a bug in the sender, not a rule of the game.
The operator says plainly they never attack from the base — «ухожу далеко, атакую сразу
с поля» — and that sentence was the whole of the evidence needed to keep looking.

### …and the chain rarely gets to use it, because the squad is home by then

The door works. Six kills of one chain, measured live straight afterwards, say the chain
does not reach it: every march the server priced after a kill was priced FROM THE BASE.

| pick | from | hop | tiles from home | eta the server gave | `home / 0.765` |
|---|---|---|---|---|---|
| 1 | home | 46 | 46 | 58 s | 60 s |
| 2 | anchor | 14 | 60 | 76 s | 78 s |
| 3 | anchor | 10 | 70 | 89 s | 91 s |
| 4 | anchor | 48 | 119 | 149 s | 155 s |

The eta tracks the distance from the BASE every time, never the hop. A squad that has
killed a zombie is normally home again by the moment the next order can be given — the
`STATION` reading §4h was built on is a squad that has LANDED, which lasts the length of
the fight and no longer.

**Measuring from an anchor the squad has left is worse than useless.** It chases the
neighbours of the last corpse and pays the distance from the base for each, so the chain
drifts outwards: 46, 51, 60, 70, 78, 84, 119 tiles from home over six kills, each march
longer than the one before.

So the origin is ASKED and never assumed (`_origin` in `tools/lib/lua_actions.py`): the
anchor while the squad genuinely still has a landed march to be re-aimed, the base
otherwise. The report counts `redeploys` beside `attacks` for exactly this reason — the
difference between them is the number of kills that cost a walk home, and it is the only
number that says whether the door is being reached at all.

**And the window it needs does not exist for a zombie kill — measured (#1702).** Every
pick now prints one word saying what the squad's own march looked like when the origin
was decided (`stand=`), and the finder behind it asks three ways: the formation, the uuid
the run remembers, and the SLOT the march was sent with (`armyInfo.f4`, which always
holds). On the account being hunted, lap after lap, after a confirmed kill it reads

    stand=nomarch   from=home   attacks=1

— the squad has no march at all by the time the next target is chosen. The reading is not
a blind spot in the finder: on the other account, at a squad genuinely standing out, the
same expression answers `stand=station from=anchor dist=2 home_dist=119` in the same
minute.

So the game brings a squad home when its monster fight ends, and `back = 0` does not
change that; the `STATION` states this task kept finding are squads that had LANDED but
whose order had been cut, or whose fight had not resolved. **There is no moment between
the kill and the walk home in which an order can be given**, and the cost of a kill is
therefore `2 * home_dist / speed` for as long as the target list is what the client can
see. The redeploy stays what the measurements make it: the answer for a squad standing
for some OTHER reason — a mine above all — and not a way to chain kills.

### The MINE is the other half, and it works — «залипание на шахте» answered

The operator's own case is a squad standing on a mine, re-aimed by hand with no pause.
That reads `COLLECTING: 3` with hours on the clock, not `STATION` with none, so it is a
different question and it was asked separately. Live, 2026-08-22, on the test account and
free of charge — a GATHER order costs no energy, so the proof here is the march itself:

    ride  ->  march=…915 status=MOVING: 1     target=425441 end=…085552
    land  ->        status=COLLECTING: 3      target=425441 end=…559485   (5.6 h out)
    change ->       status=MOVING: 1          target=420470 end=…107976   (22 s out)

**Same march uuid, new target, straight off the ore.** No walk home, no second march, and
the squad was working a node with five and a half hours left on it.

So the gate accepts a gathering squad too — **but only when the march is the RUN'S OWN**
(`p.own_march`). The hunt's ride puts a squad on a node itself and may take it off again;
a squad the PLAYER sent to gather is theirs, and pulling it off the ore to hit a zombie is
not a decision this recipe gets to make. A march still MOVING is never touched at all:
re-aiming one is «меняет маршрут, когда уже идёт на зомби», which §4d already cost us.

### The capture that was supposed to settle this caught nothing, and why

Two attempts were recorded while the operator attacked by hand from a mine, and neither
produced a `world.march.change`. The reason is structural rather than bad luck:
`tools/wire_event_monitor.py` **watches the DOWN direction only** — it is the ear for
push-driven triggers — so a message the CLIENT sends can never appear in it. What its log
holds is `push.world.march.new` from other players, which is what the down direction of a
march looks like.

It did not matter. The arguments were read off the client instead (`string.dump` for the
names and the payload's field order, `debug.getinfo` for the arity) and then confirmed by
sending them: a call that moves the purse and turns the march is not a guess. **A capture
is one way to learn a message and not the only one — and for an OUTGOING message on this
client it is the harder one.**


## 4j — the window is REAL, and §4i's «it does not exist» was our own wait (#2390)

**Recorded on the wire, from the operator playing by hand, 2026-09-02.** The capture
§4i said had caught nothing was taken again with `tools/secret_task_capture.py --dump`
(the DOWN-only ear was the reason the first one was empty — see the end of §4i), and the
chain the person drives with their thumb is right there in it: **five
`world.march.change` in a row over ONE march uuid**, no `world.march.formation.new`
between them, no walk home.

    22:31:07  world.march.change  uuid=…688152  path "255735;258738"  targetUid=…712809
    22:31:14  world.march.change  uuid=…688152  path "255738;268740"  targetUid=…029177
    22:31:31  world.march.change  uuid=…688152  path "267740;295742"  targetUid=…712813
    22:32:07  world.march.change  uuid=…688152  path "291742;303744"  targetUid=…712826
    22:32:22  world.march.change  uuid=…688152  path "302744;306745"  targetUid=…452080

The uplink payload, in full, is seven fields and nothing else:

```json
{"uuid": 1412337042108688152, "targetServer": 935, "autoBackHome": true,
 "targetUid": 1412337037230712813, "path": "267740;295742",
 "worldId": 0, "target": 1}
```

Read against our own `world.march.formation.new`, line by line:

| field | the chain by hand | our send |
|---|---|---|
| message | `world.march.change` | `world.march.formation.new` |
| march | `uuid` of the march already out — the SAME one all five times | none: a new march, a new `teamUuid` every kill |
| start | `path` opens on the tile the squad is standing on (`267740`) | `path "37715;39704"` — the BASE tile, every time |
| squad | not sent at all | `formationUuid` + `formationParam.heroInfos[6]` + `soldierType` + `waitTimeIndex` + `clientCreateUuid` |
| `target` | `1` | `6` |
| `autoBackHome` | `true` | `true` |

**`autoBackHome` is `true` in the operator's chain too, and the squad still never went
home.** That kills the last of the flag theories, including this task's own (§4 and
`lua_actions.golden_send`): the flag is not what keeps a squad in the field. The re-aim
is. A march that is re-aimed never reaches the state in which «come home» applies.

### What the window actually is, in seconds

The reply to each `change` carries the leg's own clock (`f13` start, `f14` arrival), so
the gap between «the previous leg landed» and «the next order left» is measurable:

| change at | previous leg landed | gap |
|---|---|---|
| 22:31:14.969 | 22:31:13.378 | **1.6 s** |
| 22:31:31.355 | 22:31:31.272 | **0.08 s** |
| 22:32:07.720 | 22:32:04.316 | **3.4 s** |
| 22:32:22.470 | 22:32:22.920 | **−0.45 s** (sent while still moving, and the kill still landed) |

So the window is a few seconds wide and the client will take an order inside it — and
§4i's conclusion, «there is no moment between the kill and the walk home in which an
order can be given», was a description of OUR OWN LAP rather than of the game. The lap
waited for the march to disappear from `GetOwnerMarches()` and for the formation to read
free, which is a squad that has finished walking home; by then, of course, there was
nothing to re-aim. The reading `stand=nomarch` is true — it is just taken ninety seconds
too late.

### What changed in the chain

* **the wait ends at the arrival**, not at «the squad is free». When the run's own march
  is still there (`golden_reaimable`), `golden_wait_for_the_march` stops right after the
  landing and the rest of its gates — the march clock, the parked check, the two
  free-squad loops — are skipped;
* **the gate on the redeploy door is our own march, in ANY status** (`_reaim` in
  `tools/lib/lua_actions.py`), banner-free. `_landed` — «standing still with no clock» —
  is the reading a MINE gives and it is never what a march looks like a second after a
  zombie fight;
* **the order goes out before the kill is judged.** Judging costs two scans and a camera
  move, which is the whole window; so the lap sends first and looks afterwards, and the
  zombie of the previous order is parked in `p.judge` for the looking. The chain counts
  kills one lap behind, and the last order of a run is judged after the loop when its
  march is already over;
* **a missed window is counted, not hidden**: `fallbacks=` in the run report is the number
  of laps that had to make a new march out of the base, beside `redeploys=` which is the
  number that did not.

### …and the first cut at it missed the window by ten seconds

Widening the gate and skipping the walk-home wait was not enough, and the measurement
that says so is worth keeping: over five laps of one run the chain saw the landing, read
`reaimable = 1` — the march really was still there — and the order left **ten seconds
later**, by which time it was not. The report was unambiguous: `attacks=5 redeploys=0
fallbacks=5`, five new marches out of the base.

Where the ten seconds went, one round trip at a time: «is it re-aimable» in the wait,
the same question again inside the send, «is the squad free», «is this the last march» —
each 0.2 s at the VM and about a second and a half by the time the player has logged it.
Against a window of 0.08–3.4 s that is not a delay, it is the whole of it.

`golden_reaim_now` is the answer and it is the same shape as `golden_send_now` (§4f):
ONE call that finds the march, re-aims it, and parks everything the lap after it reads —
the anchor, the pending target, the zombie set aside for judging, the marches that
existed before the order. «Home on the last march» is decided inside it too, because a
second question would cost exactly what this exists to save. The wait plays it the moment
the landing shows; the send either watches an order it did not give, or makes the
ordinary march out of the base and counts a `fallback`.

## 4k — the chain works the fullest SQUARE of the map, not the nearest zombie (#2390)

The operator's instruction, in their own words: **«ищи сектор, где полно зомби и иди
туда»**. The measurement behind it is one line of a live run — `found=1 … queued=0
energy=215`: the invasion wave had moved off the base, so «the nearest zombie» was one
lone target two dozen tiles out with nobody beside it, and a chain with one link in it is
not a chain. Every re-aim §4j bought is worth nothing when the next target is a minute's
flight away.

So the pick is made in two steps instead of one:

1. **the queue is cut into squares of `cluster` tiles** (`ARGS cluster = 50`, `0` restores
   the old plain-nearest behaviour). Each live target — not used, not already somebody's —
   falls into the square `math.floor(x / step) * step, math.floor(y / step) * step`;
2. **the fullest square wins**, ties broken by which of them is nearer the squad. It is
   then held in `p.crowd` and **every pick is made INSIDE it** until nothing live is left
   there, at which point the next fullest square is chosen.

The flight to the first zombie of a square is the ride over, and the point of the shape is
that it is paid **once for the whole square** rather than once per kill. `reach` — the
limit that stops a chain walking all morning for ONE kill — is deliberately not applied to
a target inside the chosen square (`if step > 0 and p.crowd ~= nil and _incell(...) then
reach = 0`): a ride into a crowd is not the thing that limit exists to refuse.

`p.crowd` is dropped wherever the run's other orders are dropped — «Вернуть отряд»
(`golden_unstick`) and a recorded miss (`golden_note_miss`) — so a chain that was sent
somewhere by hand does not keep working a square it was taken out of.

**The pick's own log line says which square it is working and how full it was**:

    crowd=650,700+50x9@37

— the square with its corner at `650,700`, 50 tiles a side, **9** live zombies in it, its
centre **37** tiles from where the squad stands; `crowd=-` when the cutting is off or the
queue is empty. So a run that is walking rather than chaining says so, in one word, on
every lap.

## 4f — the hunt recalled its own attack, one second after ordering it (#1702)

The worst kind of bug: every part of it had already been thought about, and the fix was
sitting in the module while the recipe went on running the old line.

`GOLDEN_WAIT_CEILING` (180 s) exists so the chain does not sit in front of a mine being
gathered or a rally somebody else's press sent the squad into. `golden_eta_left()` in
`tools/lib/lua_actions.py` therefore opens with `if p.pending ~= nil then return -1 end`:
a march THIS hunt ordered is never measured against the ceiling, because applying it to
our own order would cancel an attack in flight.

The recipe's copy of that expression did not have the line. The DSL has no include, so
`READ_LUA … INTO eta_left` in `golden_wait_for_the_march.md` was a COPY made before the
guard existed, and `eta_left` was not in the `tools/lib/golden_sync.py` table that keeps
the copies honest. Live, on a target 53 tiles from the base:

    22:39:32  READ_LUA launched = 1                    <- our own attack goes out
    22:39:33  READ_LUA eta_left = 200                  <- the server's arrival stamp
    22:39:33  IF eta_left > 180 -> True
    22:39:33  «not this hunt's; recalling it rather than waiting»
    22:39:33  TAP golden_unstick                        <- our own attack, cancelled

Then the chain re-picked the same zombie and did it again. Ten energy a lap, no kills,
and from outside it looks like «the bot marches for five minutes and never hits
anything»: every target more than three minutes out — which is every FIRST target of a
run, because the squad starts at the base — was ordered and then unordered.

Two things came out of it besides the sync entry:

* **the line printed the wrong number, and it was the number people reasoned from.** It
  said «-1 more seconds» while the reading two lines above had answered 200: a `{name}`
  in a `LOG` is filled in from the values the recipe was CALLED with, so any reading
  taken inside the recipe prints a lap late. The line names the FACT now and no number;
* **`golden_choose_a_target.md` printed the pick's diagnostic as Lua SOURCE** — the
  `LOG "target: …"` line carried a pasted copy of the expression instead of
  `{pick_report}`. That is the one reading that answers «how far is the target, and what
  was the distance measured FROM», so for as long as it was broken the question could
  not be answered from the log at all. With it back:

      target: at=511,464 dist=53 from=home origin=564,468 home_dist=54 queued=118 attacks=0
      target: at=582,413 dist=12 from=anchor origin=582,425 home_dist=58 queued=158 attacks=1

  which is the chain doing exactly what section 5 says it should: the first pick measured
  from the base, every one after it from the last kill, twelve and thirteen tiles apart.

## 4e — what the night's rebuild measures (#1702)

The chain is four scenarios — `golden_wait_for_the_march`, `golden_judge_the_kill`,
`golden_choose_a_target`, `golden_send_the_squad` — and `attack_golden_zombies.md` only
assembles them. Each runs from the picker on its own, which is the whole point: a hunt
that stumbles is pressed one brick at a time instead of debugged inside a loop.

Measured live, same account, same warzone, over the same evening:

| | before | after |
|---|---|---|
| from a march landing to the next order leaving | 9 s (8, 9, 9, 10, 10, 10) | **6 s** (4, 5, 5, 6, 6, 9) |
| camera flights to the candidate, per lap | 1 — always | **0** unless the sums ask |
| the opening walk before the first pick | 36 s, of which 20 was a ring of 18 stops | **27 s**, ring of 7 |
| how far the first target was | 488–569 tiles | **15–62 tiles** |
| sends that became marches | 23 of 129 over the day | **3 of 7**, and 6 zombies counted gone |
| the longest thing the hunt would wait for | `march_wait` — 109 minutes, seen | **3 minutes**, then the squad is recalled |

The patience that came down did so because the proof went up: the squad going busy is
`canMarch = false` the instant the game accepts an order, so a poll that used to wait ten
seconds for the client to list a march now answers in two — and everything past that is
time spent on orders that were REFUSED, which live is about half of them.

## 5 — the chain: why the squad does not go home in between

Every march but the last goes out with `autoBackHome = 0`, so the squad stands on the tile
it has just cleared and the next pick is measured from there. The last one goes out with
`1`, because a squad left standing on the world map when a run ends is a squad somebody
else can hit. The alternative — nearest-to-base, every time — walks the same ground over
and over for the same twelve kills, which is the thing the task was raised to avoid.

Reading whether the squad is free again turned out to be the fiddly half:

* **`WorldMarchDataManager:GetOwnerFormationMarch` is not usable.** Its real signature is
  `(ownerUid, formationUuid, allianceUid)` and it answered `nil` for every combination we
  could give it — including the formation's own `ownerUid` — while the account genuinely
  held four marches (`GetOwnerMarches().Count = 4`, `IsHaveMarchInWorld() = true`).
* **the squad's own `state` is.** `ArmyFormationDataManager.ArmyFormationList[i].state`
  reads `0` for a squad standing in the base and `1` for one that is out. Live, with two
  squads gathering and one at home: `idx=1 state=1, idx=2 state=1, idx=3 state=0`, which
  matched what the player could see.

**Whether a squad that STAYS on the map after a `back = 0` kill reads `0` again is not yet
known** — every attempt at the chain ran on an account whose squads were all out
gathering. The recipe waits a bounded number of beats and then stops and says so, rather
than sending an order nobody can carry out.

## 6 — the proof that an attack happened is the energy, not the send

`MarchUtil.SendCreateMarchMessage(...)` returns cleanly whether or not the server honoured
it — the whole of world-monsters.md Findings 13 and 16 is about that trap, and #1519 fell
into a fresh version of it: a run reported an attack for a send that never left, because
the squad it chose was already out on the map.

What the server cannot fake is the charge. **Live: the purse went 55 → 45 across one
send** — the price of exactly one attack — and stayed at 46 across a send that was
refused. So the recipe reads the purse before the send, polls it afterwards, and moves its
tally only when the difference is there. Nothing else counts an attack.

The send itself is the usual one and the usual rule:

```lua
TimerManager:GetInstance():DelayInvoke(function()
  MarchUtil.SendCreateMarchMessage(formationUuid, MarchTargetType.ATTACK_MONSTER,
                                   pointId, uuid, 1, backHome, false, serverId, nil)
end, 0.5)
```

Scheduled on the main thread, because a cold send from the hijack thread is built and then
dropped (world-monsters.md, Finding 17). `CROSS_ATTACK_MONSTER` (`= 147`) when the target
is on another warzone.

## 7 — what is proven live, and what is not

**Proven on 2026-08-19, against the running client:**

* the config read of `1030000` and every column above;
* the prefab map: 12 115 rows walked, **107 distinct prefabs**, no error, and
  `world_monster_general_invasion` resolving to ids 1030000/1/2, level 10, type 7,
  special 9;
* the unanimity rule, caught doing its job on a monster that was actually on screen —
  `WorldMonster_Boss_invasion_2` answered `type = 7` and refused a level, because its ten
  rows span 105…150;
* a clone whose prefab is not a `pic_name` at all (`WorldMonster_Boss01`) reading as
  «nobody could say» rather than as level 0;
* the energy purse and the price of one attack (10);
* the squad lookup by slot, and the `state` reading that says whether it is free;
* the enumerator: 11 golden zombies before a lap of the map, **135 after one**, each with
  a uuid and a tile;
* the pick, and the whole `arm → scan → pick` chain of presses;
* **one send** — the server charged the ten energy for it.

* **the whole thing played from the phone** — `POST /api/screen/press` with
  `hunt_golden` on the events screen: the chain ran, reported
  `found=134 attacks=1 spent=10 energy=41 squad=3`, the panel filed it in `panel.db` and
  re-read the board afterwards.

**Not proven:**

* **the chain past the first kill.** The first march was 492 tiles and the wait ran out
  at four minutes (80 beats of three seconds), so the run stopped and said so honestly;
  the default is now ten minutes. What is untested is specifically: whether a squad reads
  free again while standing on the map after a `back = 0` kill, and whether the second
  pick lands a few tiles from the first as the arithmetic says it should.
* **the clone fallback.** Every golden zombie the live account had came from the
  enumerator with its uuid attached, so `golden_touch` / `golden_grab` never ran against a
  real one. The pieces they are made of are proven elsewhere (world-monsters.md, Findings
  16 and 17); the wiring is not.
* **a golden clone in view at the moment of a read.** The map resolves its prefab and the
  clone's name was read off the map live — but the two were never observed in the same
  second, because the things live twelve minutes and respawn elsewhere. The hop between
  them is a table lookup on a key seen live on both sides.

## 7b — the lap, measured, and what «очень медленно» actually was (#2390)

The report was «отряд должен от зомби к зомби передвигаться с минимальными задержками», and
the first thing done about it was a stopwatch rather than a guess. Everything here is off
one live account, 2026-09-02, six kills before and six after, timed from the panel's own
`debug.log` (millisecond stamps on every statement).

### The cost of asking the game anything

Twenty trivial `READ_LUA (1)` in one recipe: **4 165 ms — 208 ms a round trip.** A `WAIT 1`
measured 1 003 ms. That is the unit every number below is built out of: a lap that takes
twenty readings has spent four seconds before it has done anything.

### Where a lap went, before

Six laps, order to order: **188 · 72 · 188 · 200 · 262 · 312 s**. One of them broken down:

| phase | seconds | ours or the game's |
|---|---|---|
| the send press, the confirm and the eta | 1.8 | ours |
| `WHILE far` — the flight out, 79 tiles | 83.9 | the game's |
| `WHILE arrived`, one-second beats | 3.0 | ours |
| `WHILE marching` | **90.5** | **the walk home** |
| judging the kill | 2.0 | ours |
| choosing the next target | 1.6 | ours |
| sending — of which 3.4 s is a camera flight to a far district | 4.4 | ours |

**Our own waiting was thirteen seconds of a hundred and eighty-eight.** Everything else
was travel, and half the travel was the squad walking home: `redeploys = 0` in every
report this repository has ever filed, so the «chain» in §4b had never once happened.

### `back = 0` does not keep a squad out, and neither does `false`

The chain parks `__lw_gold_back = 0` meaning «stay», and `autoBackHome` is a C# bool that
xLua fills with `lua_toboolean` — where **every number, `0` included, is true**. That was
found, fixed (`home = (back ~= 0)`, a genuine Lua boolean, with the numeric form kept as a
fallback), and **it changed nothing**: measured live afterwards, the squad fought, and two
and a half minutes later a fresh march appeared with 154 seconds on it, aimed home. So an
attack march on a monster returns home whatever this flag says, and the only way the squad
stays out in the invasion's corner is the gather ride of §4b.

The fix is kept because it is what the code MEANT, and because the fallback costs nothing.

### What made the lap short

Three changes, and the last one is the one that mattered:

1. **The next target is chosen while the current march is in the air.** The pick is made
   once before the loop and then at the END of each lap, not at the start of the next one.
   The camera flight to a far target's district went with it — that is `golden_look`, two
   seconds of settle plus a scan, and it had been sitting between «the fight is over» and
   «the next order is away».
2. **The beats came down** where they are on the hot path: arrival 1 s → 0.4 s, the march
   1 s instead of 2 s, and «is the squad free» became two loops — a quick one at 0.4 s for
   the ordinary case and the patient two-second one, unchanged, for a squad something else
   is holding.
3. **`_origin` answers for a squad that is STILL FLYING.** It used to hand back the base
   unless the march had landed, so a pick made mid-flight measured from home and the hunt
   walked back and forth across the map. A march of ours carrying nobody's banner is going
   to the anchor — that is the only place this chain ever sends it — so the anchor is the
   origin whether it has landed or not. (The march object's own destination field was
   tried first: reflection over a march answers nothing at all under xLua, so the anchor
   the send parked is the honest source.)

### …and the ride abandoned itself on its first live beat

Turning §4b's «быстрый подход» on for the first time since it was written, the ride was
planned correctly (`direct=154 via=75`) and then **abandoned 3.5 seconds later** with «the
zombie died while we were riding to it», which switched the ride off for the rest of the
run. The zombie was alive. The check was the plain there/not-there reading, asked while
the camera sits over the MINE — so the client is not holding the target's ground and
answers «not there» about everything. It is the three-way reading now
(`golden_confirm_current`: 1 alive, 0 gone, **-1 nobody could say**), and only a definite
`0` abandons a ride.

### Where a lap went, after

Six laps: **26 · 31 · 40 · 66 · 74 · 105 s**, one ride taken and not abandoned, and picks
of 4, 7 and 15 tiles reading `from=flying` — a squad hopping between neighbours instead of
commuting from the base. **The part that is ours — from the march ending to the next order
leaving — went from 6–8 s to 3.2–3.6 s.**

Two honest caveats. The invasion wave had moved nearer the base between the two runs
(nearest target 79–126 tiles before, 4–61 after), so the TRAVEL numbers are not comparable
and only the tail is. And the run still costs one walk home per kill: until an attack march
can be made to stay, the ride of §4b is the only lever left on the travel half.

The run says its own lap now: `lap=` (the average) and `laplast=` in the closing report,
counted on the game's clock between two confirmed orders, and drawn on the phone as
«Секунд на зомби».

## 7c — the lap on a LIVE panel: 61 % of it is not ours (#2390)

§7b's laps — 26 · 31 · 40 · 66 · 74 · 105 s — were measured on a panel doing nothing
else. The same chain, run on the account's ordinary evening with every timer, trigger and
rally join switched on, kills a zombie every **304–462 s**. Nothing about the recipe
changed between the two; what changed is who was holding the client.

The run: `attack_golden_zombies` (limit 40), started 23:20:18, killed by the client
disappearing at 23:36:45 — **1010 s, three confirmed attacks, two re-aims, no walk home
and no fallback**. Every line below is counted off `panel.log` between those two stamps.

### Where the 1010 s went

| | seconds | share |
|---|---|---|
| parked — the game belongs to somebody else | **620** | **61 %** |
| our own statements (294 of them, median gap 0 s, mean 0.8 s) | 113 | 11 % |
| the rest — marches in the air, waits the recipe asked for | 277 | 28 % |

Sixty-six parks, median **7 s**, longest 40 s. Who took it:

| owner | seconds |
|---|---|
| `default/timer` | 227 |
| `default/poll` | 204 |
| `default/web` | 101 |
| `default/game` | 88 |

`default/web` is this session's own probing and is not part of an ordinary evening; the
other three are.

### What that says, and what it does not

**The recipe is no longer the slow part.** 294 statements cost 113 s between them — a
median gap of zero seconds, which is what a lap looks like when the VM answers in 0.15 s
and nothing is queued behind it. The flight was not the slow part either: the picks were
8, 40 and 11 tiles, ten to fifty seconds of marching.

**The slow part is the priority the chain is deliberately given.** `DETACH` puts it below
an ordinary errand (docs/dsl.md), so every rally join, every timer and every poll takes
the client off it at the next statement boundary and keeps it for a median seven seconds.
Three hundred seconds a kill on a busy account is the chain being a good citizen, not the
chain being broken — and the honest way to shorten it is to have fewer neighbours asking,
not to raise the hunt above a rally join.

So the two levers left are, in order of what they are worth:

1. **Fewer questions from the neighbours.** `default/poll` alone held the client for 204 s
   of the window — a fifth of it — and that is the rule this repository already has
   («Read once, then LISTEN»). Every poll retired is a fifth of a kill given back.
2. **Fewer statements per lap.** 98 statements a kill is 98 chances to be parked. Folding
   the reads that always travel together into one call — the way `golden_land_or_reaim`
   folded «has it landed» and «re-aim it» into one round trip (§4j) — cuts the exposure
   without touching anybody else's priority.

### The re-aim window itself is caught

The thing §4j went in to fix is fixed: **two landings, two re-aims, zero walks home**
(`reaimed = 1` both times, and the first send of the run reads `reaimed = 0` because there
was no march to re-aim yet). The order left 12 s after the landing on the last lap, inside
a window §4j measured at 0.08–3.4 s of slack — the beat that finds the landing is the beat
that sends the order, and it holds under live contention.

## 8 — where the code is

* the ability — `src/lastwar_bot/actions/attack_golden_zombies.md`
* the reading — `src/lastwar_bot/actions/read_golden_zombies.md`
* the presses — `golden_*` in `tools/lib/lua_actions.py`, catalogued in
  `tools/lib/game_buttons.py`
* the board and the squad picker — the «Золотые зомби» group of `panel/tabs/events/`
* the day's tally — `panel/golden_zombies.py`, a row in `panel.db`'s `blobs` table
* the tests — `tests/test_golden_zombies.py`, `tests/test_panel_events.py`

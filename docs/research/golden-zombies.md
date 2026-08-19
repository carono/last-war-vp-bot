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

**The risk, plainly.** A squad that lands at a mine is GATHERING, and issuing the attack
from there is the same move the chain's second kill already needs: a march from where the
squad stands rather than from home. That is not proven live yet and this feature inherits
it exactly. What IS known: **the ride is free** — `GetCostStaminaByTargetType(COLLECT)`
is **0** against 10 for an attack — so a plan that turns out to be impossible costs travel
time and not one point of the day's purse, and the recipe still proves every attack by the
energy the server takes.

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

## 8 — where the code is

* the ability — `src/lastwar_bot/actions/attack_golden_zombies.md`
* the reading — `src/lastwar_bot/actions/read_golden_zombies.md`
* the presses — `golden_*` in `tools/lib/lua_actions.py`, catalogued in
  `tools/lib/game_buttons.py`
* the board and the squad picker — the «Золотые зомби» group of `panel/tabs/events/`
* the day's tally — `panel/golden_zombies.py`, a row in `panel.db`'s `blobs` table
* the tests — `tests/test_golden_zombies.py`, `tests/test_panel_events.py`

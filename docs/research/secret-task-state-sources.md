# Keeping the ★ list true: what can answer, and what cannot (task #1484)

The ★ list holds strangers' secret-task tiles found across the map. Two things about a
row go stale: **how many times it has been robbed** (`n/3`) and **whether the tile is
still there at all**. This file is the audit of every way those could be re-read, each
one measured on the live client rather than reasoned about, because three of the four
turned out not to exist.

The short version: **there is no background source.** What keeps the list true is what
already arrives — the sniffer hearing tiles off laps somebody was making anyway — plus
the server's own answer when a robbery is attempted.

## Where the number lives at all

`n/3` is on the map tile (`world.get.block`, field `f10.f4` / `stealInfoList`) and in the
client's own alliance task table. It is **not** in the per-tile answer a marker tap gets:
`world.get.detail.new` returns 45 fields and no stealer list. That is why the button that
asked it reported «обновлено 0» in 716 consecutive log lines over ten days.

## 1. Passively, off the wire — NO

The panel already runs a pcap sniffer on the client's own socket. If the server announced
a change to a tile we know about, the sync would be free.

**Measured:** five minutes with the client logged in and online, camera still, no errand
running, sniffer up.

| | |
|---|---|
| `world.get.block` responses in five minutes | **0** |
| tiles handed to the panel | **0** |

A stranger's tile is never re-announced on its own. `push.world.point.update` exists and
carries the same tile encoding — the treasure page is built on it — but it arrives for
points the client is subscribed to, i.e. the district it is looking at.
`push.hero.dispatch.mission.steal` is a broadcast to the OWNER's alliance, so it says
nothing about anybody else's tile.

## 2. Asking without moving the camera — NO

This is the one that should have worked, and the API is exactly the right shape. Read out
of the live VM by reflection:

```
WorldScene.SendViewRequest(Vector2Int tilePos, Int32 viewLevel, Int32 serverId)
WorldScene.UpdateViewRequest(Boolean isForce)
WorldScene.SetFirstViewRequestFlag(Boolean)
WorldScene.GetHeroDispatchTaskPointInfoByIndex(Int32 pointIndex) -> HeroDispatchMissionPointInfo
```

…and the record it returns carries everything wanted:

```
Int32 cfgId | Int64 completionTime | List`1 stealList | List`1 heroList | Int32 rewarded
Int64 actEndTime | List`1 accList | String allianceId | Int64 expiredTime | Int32 pointIndex
Int32 mainIndex | WorldPointType pointType | String ownerUid | Int32 tileSize | Int64 uuid
Byte[] extraInfo | Int32 serverId | Int32 srcServerId | Int32 worldId | …
```

**Measured, three ways, and it does not work:**

| what was done | what happened |
|---|---|
| 20 × `SendViewRequest` spread over a foreign warzone | response counter unchanged — **nothing was sent** |
| 16 × `SendViewRequest` on the warzone the client was already hearing | response counter unchanged |
| the same 16 with `SetFirstViewRequestFlag(true)` in front of each | 3 responses arrived — **and the world came down**: the `WorldScene` object died and the client came back on its home warzone |
| `GetHeroDispatchTaskPointInfoByIndex` for 60 tiles the client demonstrably knows (its own alliance's tasks) while the camera was on another warzone | **60 misses, 0 hits** |

So the reader answers only for points loaded in the world currently on screen, the
request is gated behind the camera's own view state, and forcing it past that gate is a
way to break the client rather than a background read. The AOI numbers, for whoever tries
again: `kBlockSize = 500`, `kBlockCount = (2, 2)`, `_USE_LW_AOI = true`.

`WorldGetBlockMessage` exists as a class with `Send(Object[])` / `CSSetData(Object[])`,
so building the frame by hand is not obviously impossible — but the parameter order is
not in the dump and would have to be found by guessing against the wire.

### What a TAP on a secret task actually does — nothing, on the wire

Traced live (`клик по секретке`, 2026-08-18, 4347 lines): the operator tapped a star on
the map and the client made **no server round trip at all**. Not one `SendMessage` in the
whole trace, and the only frames that came in while the panel was open were three
unrelated alliance pushes.

What the tap does is open the window with the answer already in hand:

```
EventManager.DispatchCSEvent  781, 415435          -- the tap, by pointId
EventManager.Broadcast        731, 415435
UIManager.OpenWindow          UIWorldPoint, <uuid>, 415435, "", 22, 0
```

— the uuid travels INTO the window, so the client had it before the tap; the pointId
`415435` is tile (435, 415), and the warzone (945) comes off the same call chain.

This is the same fact as §2 seen from the other side: for a point the client has LOADED,
everything the panel draws — including the stealer list — is already in
`HeroDispatchMissionPointInfo`, and the game never re-asks. It also refines the note in
[`protocol.md`](protocol.md), which has a marker tap firing `world.get.detail.new`: that
was captured while a task was being ROBBED, and a tap on a freshly-loaded dispatch tile
fires nothing.

(The pcap side of that run recorded 0 bytes, so the wire itself is unrecorded. It does not
change the reading — nothing was sent, so there was nothing to answer — but a run that
needs the wire should check the capture file is not empty before being believed.)

## 3. Off the alliance table — 0 % of this list

`ActDispatchTaskDataManager.allianceTask` carries `stealInfoList` and needs no map at all.
It is also the wrong scope.

| | |
|---|---|
| alliance tasks held by the client | **200** |
| of them on a warzone other than home | **0** |

The ★ list drops the home warzone on the way in (#1188, robbing at home is forbidden), so
the table answers for none of it. It is still read every three seconds by the ready-row
poll, and where it *does* answer it now stamps the row as verified — it costs nothing and
on another account, with an alliance spread across warzones, it would cover more.

### …and it DOES have a state read of its own, asked of the server (#2780)

The scope verdict above is unchanged; what the first pass of this file did not say is that
the shared table is not a cache anybody has to hope is fresh. `ActDispatchTaskDataManager`
has `GetAllAllianceTasksFromServer()`, and wrapping `SFSNetwork.SendMessage` for the
length of one call names what it puts on the wire. Measured live, 2026-09-11:

```
share_wire sent=[hero.dispatch.alliance.list] count_after=154
```

One message, one reply, the table went 153 → 154 entries. Nothing is robbed, no window
opens and the camera does not move — this is the per-id read's missing half, for the rows
it covers.

**And unlike the per-id detail, a row here carries STATE.** The fields of a live row:

```
uuid  pointId  targetServer  ownerId  allianceId  cfgId  cfg=<table:6>
completionTime  actEndTime  rewarded  followCount  heroList  assistInfo
stealInfoList=<table:N>
```

`stealInfoList` is the `n` of `n/3` and it is filled: of 153 rows one carried an entry,
and the entry is the whole robbery — `uid`, `name`, alliance `abbr`, `time`, the avatar.
`completionTime` says when it became raidable and `actEndTime` when the event closes.
That is every number the ★ grid draws, for a row that is in this table.

Which rows are: measured on the same account, `targetServer` counted across all 154 —
**153 on the home warzone, 1 elsewhere.** So the scope verdict holds and the read is
worth having anyway: it is what keeps `n/3` honest for the home warzone, and on an
account whose alliance is spread out it would answer for the ★ list too.

The point this task was opened about is in neither table: `pointId=<pid>` is absent from
all 154 alliance rows after a fresh server read, and `GetSingleTaskByPointId(<pid>)`
answers `nil` against the 10 tasks of our own. That is stronger than the per-id silence
and it is still not a denial — the table holds what the ALLIANCE shared, never every tile
on the warzone.

### On READY rows the table answers in full — and still about the wrong warzone (#2784)

The measurement #2780 could not make: the operator emptied the ★ list and waited for
secret tasks to come due, so that «is it ready» and «how many are already taken» could be
asked of the shared table while there were ready rows to ask about. Four server reads on
2026-09-11, 16:50–16:53, through a throwaway recipe under `actions/dev/` (that tree is git-ignored; the read is
`ActDispatchTaskDataManager:GetAllAllianceTasksFromServer()` with `SFSNetwork.SendMessage`
wrapped for the length of the call, exactly as #2780 did it) — one
`hero.dispatch.alliance.list` each, nothing robbed, no window, the camera still:

| read | rows | home / elsewhere | ready | pending | `stealInfoList` non-empty |
|---|---|---|---|---|---|
| 16:50:05 | 138 | — / — | 51 | 87 | 1 |
| 16:51:28 | 132 | 131 / 1 | 46 | 86 | 1 |
| 16:52:20 | 132 | 131 / 1 | 46 | 86 | 1 |
| 16:52:53 | 132 | 131 / 1 | 46 | 86 | 1 |
| 16:53:50 | 132 | 131 / 1 | **49** | 83 | 1 |

(The first read reports no home warzone: `PlayerDataManager:GetServerId()` raises, and
`LuaEntry.Player.serverId` is what answers. It is why that row has no split.)

**Readiness and `n/3` are both in the row, and neither costs a robbery or a camera.**
«Ready» is `completionTime > 0 and completionTime <= now` against the game's own clock
(`UITimeManager.Instance:GetServerTime()`), and `actEndTime` says when the event closes —
`endsIn=50991s` on every live row of this read, i.e. one shared deadline, not a per-tile
expiry. A worked row:

```
pid=<y*1000+x> srv=<warzone> steals=1/3 doneAgo=15994s endsIn=50991s cfg=<cfgId>
```

So the answer to «видно ли, что секретка готова и сколько с неё взяли» is **yes, from one
message**: 46 of 132 rows named themselves ready, and the one row carrying a robbery named
it as `1` with the robber's uid, name, alliance tag and time. The table is live, too —
138 rows fell to 132 and 51 ready to 46 inside 83 seconds, and three pending rows came
due between 16:52:53 and 16:53:50 — 46 ready became 49 with no camera anywhere and
nothing pressed. That is the finding this task was opened for: **a task COMING READY is
visible in the shared table, by itself, for the price of one message.**

**And it is still the wrong list.** Against the ★ store read out of `panel.db` at the same
minute:

| | |
|---|---|
| ★ rows held | **168** — three warzones, none of them home (161 / 6 / 1) |
| alliance rows held | **132** — home (131), one other (1) |
| rows in BOTH | **0** |

Zero overlap, so nothing the server said about readiness could be checked against what the
panel calls ready: the two lists do not describe the same tiles at all, by construction —
the ★ list drops the home warzone because robbing at home is forbidden (#1188), and the
alliance table is almost entirely home. The verdict of §3 is unchanged and now has a
second, independent measurement behind it.

**Our own dispatches are a third list again.** `singleTask`: 10 rows, all 10 ready,
`stolen_from_me=0`, and every one of them carries `pointId=0` — an own task is not a point
on the map for the client holding it. Nothing here answers the ★ list either.

**What to do with it, and what not.** A pre-pass for «Сверить» is cheap and honest — one
message, a reply inside the six-second settle, no map — and it should stamp the rows it
covers and hand the rest to the camera walk unchanged. On THIS account it would stamp 0 of
168 and save nothing; on an alliance spread across warzones it is the only state read that
costs nothing. So it is worth wiring as a first step that can only add confirmations, never
as a replacement for the walk, and never as a reason to drop a row it did not carry
(THE_LIST_RULE clause 2 — the table holds what the alliance shared, never every tile).

### The read takes NO arguments, and aiming it is ignored (#2784)

The obvious next question — if the table has a server read of its own, why not call it with
our own arguments: another warzone, a point id, a list of uuids we care about — measured on
2026-09-11, 17:07–17:10, with `SFSNetwork.SendMessage` wrapped so that the payload itself is
printed rather than guessed:

```
hero.dispatch.alliance.list (nil)        <- GetAllAllianceTasksFromServer()
hero.dispatch.list          (nil)        <- GetAllSingleTasksFromServer()   (our own tasks)
get.alliance.share.mission.list (nil)    <- SendGetMarkList()               (the marks)
```

**All three send an empty payload.** There is no warzone field, no point field, no filter and
no list of ids to ask about: the scope is the caller's alliance and the server decides it.

Aiming it anyway, by sending the same name with fields of our own
(`{targetServer=<a foreign warzone>, serverId=<same>, srcServer=<same>}`) and counting how
often the reply applier `UpdateAllAllianceTasks` runs, so that «no change» can be told from
«no reply»:

| | plain call | aimed at a foreign warzone |
|---|---|---|
| replies applied | **1** | **1** |
| rows after | 130 | **130** |
| rows off the home warzone | 1 | **1** |

So the server **answers** — it does not refuse, it does not error — and the answer is the
same alliance-scoped table. The extra fields are dropped on the floor. That is the fact to
quote: not «the server said no», but «the server ignored the aim and re-sent its own scope».

**The steal gate cannot fetch either — it is arithmetic, not a question.**
`ActGhostreconManager:GetPointStealType(cfgId, completionTime, stealList)` classifies state
the caller ALREADY HAS. Measured with the wire wrapped for the length of the call:

```
GetPointStealType(<a ghost cfgId>, <finished a minute ago>, {}) -> 2   (CanSteal)
GetPointStealType(<a ghost cfgId>, <finishes in 10 min>,     {}) -> 4   (UnShow)
wire during both calls: []          <- nothing was sent
```

Nothing goes out, so nothing comes back: given a `completionTime` we do not have, it has
nothing to classify. `ActDispatchTaskDataManager` has no such method at all.

The marks are not a back door either: `GetMarkList()` held **0** rows on this account at the
time of the measurement, and its read is the third empty-payload message above.

## How a tile is learned to be GONE — the reply's own rectangle

The question nothing above answers: the operator jumps to a coordinate the list calls
«готово к сбору» and finds empty ground, and the row stays. How does the CLIENT know?

**It is told about ground, not about tiles.** A `world.get.block` reply is a set of
blocks, and each block carries the rectangle it accounts for:

| field | meaning |
|---|---|
| `leftBottom` / `rightTop` | the corners, packed `y * maxAreaSize + x`, **server-local** — not the packing the REQUEST uses (protocol.md §7) |
| `maxAreaSize` | the warzone's side, 1000 on every one measured |
| `viewLvl` | the height it was asked at |
| `points` | everything standing inside that rectangle |

So a tile inside the rectangle and absent from `points` is not on the map. That is how
the client finds out — it draws what the reply carries and drops what it does not — and
it is the only mechanism there is: no per-tile push, no per-tile question, and a tap
sends nothing (above).

Verified against a recording before a line was written: for every block, the tasks the
existing decoder yields inside the rectangle are exactly the `f2 = 17` points that block
carried. The map **wraps horizontally**, and a block that runs off the right edge comes
back with `x0 > x1` — measured, `(991, 0) -> (0, 111)` carrying points at x 994 and 996 —
so «is this tile inside» is one function (`proto.area_holds`) and not an inline
comparison.

`viewLvl` is load-bearing. Above the secret-task height the client keeps asking for bases
and stops asking for tasks, so a rectangle heard up there would read as «no tasks here»
about ground that is full of them. Only `viewLvl == 0` is trusted.

**Live acceptance.** One ordinary lap of one warzone, with the list holding rows found
over the previous days:

```
карта ответила про их клетки и их там нет: пропало 1
карта ответила про их клетки и их там нет: пропало 3
карта ответила про их клетки и их там нет: пропало 21
карта ответила про их клетки и их там нет: пропало 87
```

— 112 rows removed, and what was left was **114 rows on that warzone against the 114
tiles the lap actually heard there**. The rows on the warzone nobody asked about were
untouched, which is the rule working from the other side.

## 4. What is actually done

* **Every sighting counts — harvested from the checkpoint, not from the event stream.**
  The sniffer hears tiles whenever the map moves for any reason: the four-hourly star
  round, a person panning, any errand that jumps. Its EVENT stream cannot carry those,
  though, and that is worth knowing before anyone tries: the capture child announces a
  tile once per state and never again — the dedup is what stops a lap of twenty thousand
  tiles flooding the panel — so **a full lap over a warzone whose tiles are all already
  on the list prints nothing and taught the list nothing**, measured exactly that way.

  The checkpoint has them all. So the tab re-reads that file every twenty seconds
  (`secret_harvest`), on a worker, and merges it: `loot_count` rises (upwards only) and
  the row is stamped. It asks the game nothing — the template re-rank that used to ride
  along is cached, so the steady state is a file read and no round trip at all.

  **The stamp is when the MAP answered, not when the file was read.** The checkpoint is
  rewritten every tick with everything still inside its freshness window, so the same
  record is offered over and over; each carries its own `seen_at` and that is what is
  carried onto the game's clock. A newer reading moves the stamp forward, an older one
  cannot walk it back.

  Measured on the shipped build: one ordinary lap of one warzone → **98 rows stamped, 9
  of them now reading 3/3**, 2 at 2/3, 1 at 1/3 — and no game call made for any of it.
* **A region that answered takes the rows it did not carry.** The rectangle above, as
  its own machine line out of the capture (`##AREA##`), judged on the Tk thread. Three
  guards keep it an answer rather than a silence: the row must be inside the rectangle,
  the answer must be NEWER than the row's own last sighting, and a row we robbed
  ourselves is kept. A row nobody has answered about stays where it is, for ever if need
  be.
* **The robbery corrects the rest at the point of use.** `hero.dispatch.steal` answers
  «задание уже взято / больше не доступно / срок истёк» about a tile that has gone, and
  the row comes off on that answer (`_drop_gone`). A premature or hopeless press costs
  nothing: the daily counter is the server's and only moves on success.
* **The camera walk is a person's press.** «Обновить состояние» still walks the ready
  rows' squares, one warzone per run, and it is the only thing that does. It used to run
  itself every thirty seconds — holding the one game claim for seconds at a time and
  moving the map under whoever was reading it — and that is the practice this task ended.

## How to re-test any of this

The probes were dev recipes played through the panel's web API, so the client was never
touched by hand:

```
POST /api/actions/run   {"profile": "<name>", "name": "<a recipe under actions/dev/>"}
```

Reflection from Lua needs `BindingFlags` cast rather than added — `a + b` on an enum
raises, `CS.System.Reflection.BindingFlags.__CastFrom(60)` is Public+NonPublic+Instance+Static.

## 4. Asking about ONE tile by its id — it CONFIRMS, and it cannot deny (#2780)

The first cut of this section said the opposite, and the correction is written out rather
than quietly replaced: for a few hours this file claimed a silent point meant «the tile is
gone», which would have deleted most of the ★ list on the first press of a button built on
it. What follows is what the measurements actually support.

`world.get.detail.new {pointId, serverId, 0, 17, ""}` for one point, a settle, then
`WorldPointDetailManager:GetDetailByPointId(pointId)`. The recipe is
[`actions/read_secret_task_state.md`](../../src/lastwar_bot/actions/read_secret_task_state.md).

**A point answers only when the client ALREADY HOLDS IT.** That is §2 of this file seen
from the other side, and it is what makes the reading one-directional. Measured live on
2026-09-11, the home warzone, the client standing in its own base:

| asked about | answered |
|---|---|
| a point in the client's own alliance table (163 held, 162 on that warzone) | **yes** — uuid, uid, owner, alliance tag, `srcServer` |
| two tiles a camera walk had loaded 25 s earlier, in nobody's alliance table | **yes** |
| two tiles the same walk had not reached | **no** — asked twice, 25 s apart |
| five ★ rows nothing had walked over | **no** — and they were not gone: the auto-loot was still naming one of them as a target minutes later |

So the answer has two values and no third:

* `exists=1` — the game confirmed this tile. Worth having: it freshens «Сверено» and it is
  the check the robbery already makes before it presses.
* `exists=unknown` — nothing came back, which says **nothing at all** about the tile.

**No caller may take a row off a list on `unknown`** (THE_LIST_RULE clause 2). A control
point does not rescue it either — the control that answers is by definition a point the
client holds, so it proves the link and not the question.

**`pointId` is `y * 1000 + x`, server-local** (protocol.md §7) and is packed by the recipe
rather than asked for: `SceneUtils.TilePosToIndex` answers **0** while the client stands in
its base, measured on every run.

**What still has to be the map:** both halves of a stale row. `n/3` was never in the detail
(§«Where the number lives at all»), and «is it still there» is only answered by the ground
the tile stands on — `actions/verify_secret_tasks.md` walking the camera with the capture
listening. The per-id read is a confirmation, not a check.

### The cache is what answers, and a walk does not fill it (#2780, second run)

Asked again on a list the operator had just refilled, so that «the camera has been over
these a minute ago» was true of most of it. The counts are the point:

| | |
|---|---|
| rows asked, one `world.get.detail.new` each | **20** |
| of them walked over 1–2 min earlier (the home warzone) | 17 — **0 answered** |
| of them last confirmed 9 min earlier (another warzone) | 3 — answered, **out of the cache** |
| detail cache before the burst / after | **19 → 20** |
| what the one new entry was | the CONTROL — an alliance task |

`GetDetailByPointId` is a lookup in `worldPointDetailList`, which keeps every point the
client has ever had a detail for. So «it answered» has two meanings, and the cache size is
the only way to tell them apart: **twenty requests for the list's own tiles produced ONE
new entry, and that one was the alliance control.** The three that answered were already
in the cache from some earlier fetch; nothing on the wire came back for them now.

The client was in the CITY for this run (`cur_server` = home, `scene` city), which is where
a panel reading a list normally sits. An hour earlier, *while the map was up right after a
walk*, two tiles the walk had just heard did answer — so what makes a stranger's point
answerable is the world being loaded around it, and it does not survive going back to the
base. How long it lasts WHILE the map is up has not been measured.

**And there is still no state in the answer.** The full 45 fields dumped from two live
replies: `expireTime=0`, no `stealInfoList`, no `stealList`, `stage=0`, `currAssistance=0`,
`maxAssistance=0`, `maxProgress=0`, `donateProgress=0`, `remainRes=0`, `initRes=0`. What
it does carry is identity — `uuid`, `uid`, owner name, `allianceId`, `srcServer`,
`pointId`, career type and level. Nothing about `n/3`, nothing about the expiry, nothing
about whether the tile is taken.

So per-id confirmation is not a supplement to the walk either: the points it can confirm
are the ones the walk has just loaded, and only while the map is still up.


### The row this task was opened about (#2780)

The coordinate the operator named — the home warzone, X<x> Y<y> — asked from the base on
2026-09-11 at 16:35, the link green and the client talking to the game:

```
READ_LUA state = 'pid=<pid> exists=unknown'
```

`unknown`, which by the rule above says **nothing** about the tile: not that it is gone,
not that it is there. Nothing else could be compared against it either — by then the ★
store held **no such row**, on any profile (`secret_tasks_state.rows`: 0 rows on the
profile that had listed it, 1 row on another, warzone 973). So the honest report on that
one row is «не знаю», and the only thing that can answer it is the camera walk.

That is the whole finding of this task stated as a cost: **one per-id ask is one round
trip to the game (~8–10 s of settle) and it can freshen a row the client already holds —
it can never refresh a list.**

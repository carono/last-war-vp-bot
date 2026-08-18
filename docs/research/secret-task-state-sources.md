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

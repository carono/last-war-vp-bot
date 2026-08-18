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

* **Every sighting counts.** The sniffer hears tiles whenever the map moves for any
  reason — the four-hourly star round, a person panning, any errand that jumps. Those
  sightings raise `loot_count` (upwards only) and stamp `checked_at`, so the «Сверено»
  column is filled by traffic nobody paid for. A checkpoint REPEAT does not stamp: that
  would date the row by when the file was read.
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

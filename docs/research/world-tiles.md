# World-map tiles — `world.get.block` kinds, and where monsters actually live

Goal: enumerate world-map tile kinds (`world.get.block` `f2`) beyond the known
`6/7/17/29`, and find the monster tiles. Method (strict): passive sniff first
(`tools/dev/secret_task_capture.py --seconds N --dump`), then `SceneUtils.ChangeToWorld()`
via `tools/lua_goto_world.py`, then pan the map with `pydirectinput` drags to force new
`world.get.block` fetches. Three captures (120 s + 90 s wide sweep + 70 s over a
monster-containing view), 242 tiles total.

**Headline:** the only *new* block kind is **`f2=25` = alliance city**. Roaming
**monsters are NOT `world.get.block` tiles at all** — they are a separate world-entity
system on their own streams. The task's guess (monsters at `f2=8/9/10`) conflated the
wire `f2` with the *client* `LWWorldMonsterType` enum (below), which is numbered
differently.

## `world.get.block` response shape

`down world.get.block` → `serverPointArr[] → points[]`, each point a protobuf tile:

| field | meaning |
|---|---|
| `f1` | packed world point id (the map coordinate; `x = p % 1000`, `y = p // 1000` per `lastwar_proto`) |
| `f2` | **tile kind** (see table) |
| `f102`, `f103` | serverId (935 here) |
| kind-specific sub-message | the entity's attributes — **`f3` (base) / `f6` (mine) / `f10` (task) / `f101` (city)**, not a fixed `f14` |

There is **no top-level `f14`**; the "attributes in `f14`" are inside the kind's
sub-message (e.g. a base's `f3.f14` is the owner's name).

## Tile kinds seen (242 tiles, 3 captures)

| `f2` | count | kind | attribute sub-message (key fields) |
|---|---|---|---|
| 6 | 96 | **base** (player city) | `f3`: `f3`=HQ bId (`10100000`), `f4`=base level (35), `f14`=owner name (`"armaca"`), `f15`=alliance abbr (`"TLou"`), `f7`=alliance uuid, `f2`=player uuid, `f13`=10000 |
| 7 | 97 | **mine / resource node** | `f6`: `f1`=amount/level, `f2`=1 |
| 17 | 47 | **secret_task** (raidable SecretTask) | `f10`: `f2`=cfgId (`400703`), `f8`=expiry ms, `f9`=alliance uuid, `f100`=tile uuid |
| 25 | 2 | **alliance city** ⟵ NEW | `f101`: `f10`=alliance name (`"The New Dawn"`), `f5`=alliance tag (`"CIan"`), `f4`=owner uid, `f7`=alliance uuid, `f15`=server, `f19`=`{uuid,pos,state,…}` |

(`f2=29` = ghost_recon is known from prior work but did not appear in this area.)
Example new-kind tile:
```json
{"f1":499600,"f2":25,"f100":1356530359877216252,
 "f101":{"f1":1670,"f4":1779285600,"f5":"CIan","f7":"c14a…","f10":"The New Dawn",
         "f15":935,"f19":{"f1":"1356530359877216252","f3":499600,"f4":3,"f9":1},"f20":"6"},
 "f102":935,"f103":935}
```

## Monsters are a separate system (not block tiles)

The world view visibly has monsters — `results/world_view.png` shows two roaming
monsters tagged **lvl 19** and **lvl 22**, and the chat ticker names a **lvl 130
Zombie-Boss** — yet none of the 242 captured tiles is a monster. Panning back and forth
over the monster-containing view (3rd capture) still yielded only `6/7/17/25`. So
monsters are fetched/pushed independently of `world.get.block`.

### The client world-entity enum — `LWWorldMonsterType` (from Lua)

`DataCenter` exposes the display-type enum for all world entities (read live via
`tools/lua_eval.py`):

```
ResMetal=1  ResFood=2  Boss=3  City=4  ResGold=5  Radar=6  MonsterInvade=7
RunningMonster=8  ResObsidian=9  ResFlint=10  FlowerCar=13  S4Tank=14  S4Airplane=15
S4Missile=16  S4Boss=17  S4TankBN=18  S4AirplaneBN=19  S4MissileBN=20  S4BossBN=21
S4RunningBoss=22  Lockhart=1001
```

Monsters are **`Boss=3`, `MonsterInvade=7`, `RunningMonster=8`** (plus the seasonal
`S4Boss/S4RunningBoss`). **This is a client enum and does NOT equal the wire `f2`** —
e.g. wire `f2=6` is a base but `LWWorldMonsterType 6` is `Radar`; wire `f2=7` is a
resource mine but the enum `7` is `MonsterInvade`. Do not map one onto the other.

### Monster streams and managers observed

| message / manager | role |
|---|---|
| `push.running.boss.del` (and `.new`/`.add`) | roaming boss lifecycle (the lvl-19/22 "running monsters") |
| `monster.invasion.boss.detail` | per-boss detail query → `{uuid, ownerName:"ofbi", allianceUid, allianceAbbr:"TLou", isProtected}` |
| `push.al.zombieRushPoint.change` | alliance zombie-rush spawn points → `{zombieRushPoint, allianceId}` |
| `push.world.march.new` / `push.world.march.world.get.new` | marches (some target monsters; blob carries name, coords `x;y`, difficulty `"Normal"`, hero squad) |
| `surprise.point.get.info` | event/surprise points (empty this run) |
| Lua: `DataCenter.MonsterManager` | kill-boss counters / max attackable level (`GetCurCanAttackMaxLevel`) |
| Lua: `DataCenter.MonsterTemplateManager` | monster config templates (level → attributes) |
| Lua: `WorldPointDetailManager` | per-point detail cache (`GetDetailByPointId`) |
| Lua: `KillZombieCtrlManager`, `MonsterProtectionManager`, `MonsterLockDataManager`, `LWZombieRushManager`, `LWBerserkBossManager`, `S0/S4/Season BossDataManager` | specific monster/boss subsystems |

The roaming-monster **list** was already resident when the world loaded (like the base
cold-load in `city-protocol.md`) and is maintained by `push.running.boss.*`; it is not
re-sent on a pan, which is why the sniff never caught it as a tile. To capture the list
fresh, sniff across a cold world-enter or a `monster.invasion`/running-boss query, or
read it live from the managers above.

## Artifacts (git-ignored under `results/`)

- `results/world_tiles_capture.jsonl`, `world_tiles_capture2.jsonl`, `world_monsters3.jsonl` — the three decoded captures.
- `results/world_view.png` — world map screenshot showing the lvl-19/22 roaming monsters absent from the block tiles.

## Sending a GATHER march to a mine — no-click (tools/dev/gather.py, gather_direct.py)

Same main-thread-timer mechanism as the solo monster attack (docs/research/world-monsters.md
Finding 17), but for resource tiles ("mines"). Confirmed live: `IsHaveMarchInWorld()` false→true,
`GetOwnerMarches()` 0→1, HUD untouched.

Mines render as **`CollectResourceWood_world(Clone)` / `CollectResourceStone_world(Clone)`**. Unlike
monsters, a resource tile has **`uuid=0`** — it is identified by `pointId` alone. The march type is
**`MarchTargetType.COLLECT` (2)**. Two scripts, mirroring the monster pair:

- **`tools/dev/gather.py`** — MODE 1 (OnClick): find a `CollectResource*_world(Clone)` via its
  `TouchObjectEventTrigger` → `trig:OnClick()` → read `pid` from the popup `Ctrl` (its `uuid` is 0) →
  **`Ctrl:CloseSelf()`** (close ONLY the popup; NEVER `UIManager:DestroyAllWindow()`, which kills the
  HUD) → main-thread send.
- **`tools/dev/gather_direct.py`** — MODE 2 (fully no-click): resource tiles need no server uuid-fetch, so
  skip OnClick entirely — read `pid` straight from the clone's world position and send:

```lua
-- in World, mine in view:
local pid = SceneUtils.WorldToTileIndex(mineClone.transform.position)   -- e.g. CollectResourceWood_world(Clone)
TimerManager:GetInstance():DelayInvoke(function()
  MarchUtil.SendCreateMarchMessage(formationUuid, MarchTargetType.COLLECT, pid, 0, 1, 1, false, serverId, nil)
end, 0.5)
-- MarchTargetType.COLLECT = 2 ; targetUuid = 0 (resource tile) ; send runs on the MAIN THREAD
-- (a send from the SafeDoString hijack thread is dropped by the server).
```

Both proven live: mine `CollectResourceWood_world(Clone)` pid=497565, uuid=0,
`MarchTargetType.COLLECT`(2) → `om` 0→1. Other collect-family `MarchTargetType`s: `COLLECT=2`
(own resource node), `ATTACK_ARMY_COLLECT=10`, `ALLIANCE_RESOURCE_COLLECT=75`,
`COLLECT_ALLIANCE_BUILD_RESOURCE=35`. Compare monsters, which need the real server-fetched uuid
(Finding 17) — resource tiles never do.

## Programmatic coordinate jump — no UI (tools/dev/goto_coord.py)

The in-game magnifier ("лупа" → enter X/Y → jump) is `UISearchCtrl:OnJumpClick(server, x, y)`, which
internally calls **`GoToUtil.GotoPos(worldPos, zoom, time, onComplete, serverId, worldId)`**. Captured
the exact worldPos it passes: for tile (X, Y) it is **`Vector3(X*2+1, 0, Y*2+1)`** (TileSize=2, +1 =
tile centre) with `zoom=105`. So the coordinate jump needs no window at all:

```lua
GoToUtil.GotoPos(CS.UnityEngine.Vector3(X*2+1, 0, Y*2+1), 105, nil, nil, serverId, nil)
```

Verified live: `WorldScene.CurTilePos` moved exactly to (X, Y) with `UIManager` stack empty
(`(588,522)→(600,550)`, `(600,550)→(650,480)`, `→(0,0)`). `tools/dev/goto_coord.py <X> <Y> [serverId]`
wraps it. (`GoToUtil.MoveToWorldPoint(SceneUtils.TilePosToIndex(Vector2Int(X,Y)))` is an equivalent
pid-based jump; `GotoPos` is what the magnifier's coordinate search actually uses.)

**Cross-server (different `serverId`) — camera moves but world data does NOT load.** On the home
server the jump loads the map fully (jumping to (563,508) on server 935 → 93 world clones appear:
bases/mines). Passing a foreign `serverId` (500, 972) moves the camera but the world stays empty
(~17 stale clones) — the client cannot fetch another server's `world.get.block` in the normal world
scene. None of these repopulate it: `SceneUtils.WorldSendGetALPointsRequest()` (+ its throttle reset
`SceneUtils.ClearLastRequestALPointsTime()`), `GoToUtil.GotoServerZone(serverId, isInMoveToState)`,
`DataCenter.WorldAllianceCityDataManager:InitAllCityDataRequest()` / `:UpdateAllCityDataRequest(type,
serverId, seasonType)`, `GoToUtil.GoToServerPreCheck(serverId)`. So `serverId` in `GotoPos` only tags
the request; it does not enter a cross-server context. The real standard cross-server switch is a
different API — `CrossServerUtil.JumpToServerByServerId(...)` — see the section below.
**Discipline for further probing: return to the home server 935 before each new hypothesis** (a
foreign-server `GotoPos` view is a stuck/empty state).

## Viewing another server's world — full load, no teleport UI (tools/dev/cross_server.py)

Goal: browse a foreign server's map (e.g. 972) programmatically, with the map fully populated and
**without** the base-relocation ("teleport") UI. Solved live — recipe below, confirmed repeatedly
(~340-390 world clones load, `UIMoveCity` closed, HUD intact).

### The two dead ends (measured, not assumed)

- **`GotoPos` with a foreign `serverId`** only *tags* the world request; it does not enter a
  cross-server context, so the camera moves over an empty map (~17 stale clones).
- **`CrossServerUtil.OnCrossServer(serverId)`** enters a *clean* cross-server mode
  (`GetLastJumpToParam()` mode `nil`, no teleport UI) but does **NOT** bulk-load the world — the map
  stays empty (~17-79). `GotoServerZone`, `WorldSendGetALPointsRequest`, `ChangeToWorld(cb,true)`,
  and re-entering the world scene do not fill it either. (A one-off 277-clone reading was **residual**
  clones left over from a prior `JumpToServerByServerId` load, not a fresh clean load.)

**Only `CrossServerUtil.JumpToServerByServerId(...)` bulk-loads a foreign world**, and outside an
active event it *always* enters **move-city mode** (`GetLastJumpToParam().mode = CrossServerMoveCity`)
— which opens the base-relocation window **`UIMoveCity`**. The mode does not depend on the `type`
argument (`BigMap3000`, `BackToSrcServerBigMap` both → move-city) nor on the enable-reason;
`JumpToKingdomAround` funnels into the same jump. So full-load and the teleport UI are bundled.

### The fix — jump, then close only the `UIMoveCity` window

```lua
-- 1) authorize the target (flips GetCrossEnableReason(serverId): -2 Disable -> positive/enabled)
CrossServerUtil.SetCrossEnableList({[0]={homeServerId}, [1]={serverId}})   -- entries are {serverId}, 0-indexed
-- 2) full bulk load (opens UIMoveCity):
CrossServerUtil.JumpToServerByServerId(serverId, MoveCrossServerType.BigMap3000, nil, 105, false)
-- 3) close ONLY the teleport window — NEVER UIManager:DestroyAllWindow() (it kills the HUD):
UIManager.Instance:GetWindow("UIMoveCity").Ctrl:CloseSelf()
-- 4) (optional) pan to fill more of the map:
GoToUtil.GotoPos(CS.UnityEngine.Vector3(X*2+1,0,Y*2+1),105,nil,nil,serverId,nil)
```

`UIMoveCity` is the window that renders the base-relocation ghost/confirm bar; closing it via its own
`Ctrl:CloseSelf()` leaves the fully-loaded foreign world and the HUD untouched. Window-name constants
live in the global `UIWindowNames` (companions: `UIMoveCityTip`, `LWUIMoveCityTip`). Return home with
`CrossServerUtil.BackToSrcServer()` + `OnBackSelfServer()`.

`tools/dev/cross_server.py <serverId> [X Y]` wraps the whole recipe; `tools/dev/cross_server.py --home`
returns to the home server. (`SetCrossEnableList` is transient — the client re-syncs and clears it
after a few seconds; the jump must follow immediately, which the tool does.)

### How the recipe was found

The move-city-vs-clean distinction and the `SetCrossEnableList` gate were caught by monkey-patching
`CrossServerUtil.*` / `SceneUtils.*` (logging args to `Player.log`) while the player performed the
normal in-game switch: the trace showed `OnCrossServer(serverId)` + `SetCrossEnableList(table)` for
the outbound view and `JumpToServerByServerId(homeServer, BackToSrcServer, pos)` for the return. The
`UIMoveCity` window was then located via the `UIWindowNames` constants and `UIManager:IsWindowOpen`.

### Near vs far / cross-season servers

A **near, same-season** server (e.g. 972 relative to home 935) loads stable and full — ~340-390 world
clones, `IsInOther=true`.

A **very far / different-season** server (tested: server 5) is still reachable — the same recipe sets
`IsInOther=true` and the world does populate — but with two caveats:

- **One-time season-data download.** On the first entry to a server on a different season the client
  shows a season-data-download popup (a `UIWindowNames` migration/loading window). It is transient;
  after the data downloads the view works.
- **Sparser, fluctuating load.** The far/cross-season world streams less predictably — clone counts
  bounced 208 → 140 → 72 across reads rather than settling at a stable full map, and
  `GetCrossEnableReason(serverId)` reverted to `-2` (the transient enable list re-cleared). The view
  is usable but do not expect the same density/stability as a near same-season server.

So the mechanism generalizes to arbitrary server ids; the limits are content-availability (season
data) and load stability, not the jump itself.

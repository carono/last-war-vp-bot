# World-map treasures — find & take (protocol)

*"Сокровища на карте"* — the named treasure chests an alliance's **Detect Event**
(radar / drone scan) drops onto the world map. Members march to the tile, dig it,
and the finisher claims the gift. This note is the protocol for **finding a
treasure's position** and **taking it**, reconstructed from one live session
(task #1107):

* trace : `results/traces/20260728_155726_сокровище_trace.log`
* wire  : `results/traffic/20260728_155731_сокровище_traffic.jsonl`

Everything below is confirmed against that capture plus the live Lua VM
(`SFSNetwork.SendMessage`, `push.world.point.update`, `push.detect.treasure.claim`,
`SceneUtils.IndexToTilePos`).

## What a treasure is on the wire

A treasure rides the same transport as every other interactable — it is a
**`world.get.block` / `push.world.point.update` tile** whose `WorldPointType`
(field `f2`) marks it as treasure. Relevant `WorldPointType` values (full enum
dumped from the live VM):

| value | name | meaning |
|---|---|---|
| **21** | `TREASURE` | the detect-event treasure captured here |
| 43 | `ACTIVITY_WORLD_TREASURE` | activity variant |
| 46 | `TreasureChest` | pick-one chest (`pick.one.start/end.request`) |
| 42 | `MONSETER_CHALLENGE_NEW_TREASURE` | monster-challenge treasure |
| 14 | `DETECT_EVENT_PVE` / 8 `EXPLORE_POINT` | other detect points |

The treasure's *sub-kind* is `WorldTreasureType`
(`RadarTreasure=1`, `SiegeTreasure=2`, `SupplyTreasure=4`, `OffSeasonDetect=11`,
`PlayerKillMonsterTreasure=9`, … 21 values total).

### The point object (find = read the position)

`push.world.point.update` (`type:"change"`) carries the treasure. Decoded blob
of the captured "Uzilla" treasure:

```
f1  = 500553                     -- pointId  →  SceneUtils.IndexToTilePos(500553) = (552,500)
f2  = 21                         -- WorldPointType.TREASURE
f11 = {                          -- the treasure record
  1  = 1397117530950313784       -- treasure UUID  (this is what you claim)
  3  = "25193"                   -- cfgId   (config tables detect_event / world_treasure id 25193)
  5  = "3d4b9dee…43089"          -- alliance uuid
  6  = "TLou"                    -- alliance abbr
  7  = "1371213785000935"        -- finisher/operator uid (once dug)
  12 = "Uzilla"                  -- treasure name
  13 = 1785322473766             -- expiry ts
  16 = { 1=<uuid>, 3=500553, 4=8 }
}
```

**Position** = `f1` (pointId) → `SceneUtils.IndexToTilePos(pointId)` → `(x,y)`.
The server id is the `…935` suffix on the ids (here server **935**). Same
`tools/lib/coords.py` / `SceneUtils.IndexToTilePos` used everywhere else applies.

Two ways to enumerate treasures already known to the client, no capture needed:

* pan the map → `world.get.block` returns the tiles (`f2 = 21/43/46/42`), exactly
  like `tools/secret_task_capture.py` does for `f2 = 17`;
* the Detect Event fetches them up front — `MsgDefines.DetectInfoGet =
  get.detect.info` / `activity.detect.list`, parsed into
  `DataCenter.ActDetectTreasureDataManager` (`.dataDict`, `.treasures_num`,
  handler `OnGetArrDataMsg`). Dormant when no detect event is running
  (`treasures_num == 0`).

## Taking it (dig → claim)

Two steps, both seen in the capture:

1. **March to the tile.** A normal `WorldMarch` to the treasure's `pointId`
   (the capture shows a dozen alliance marches — `push.world.march.new`, all
   `destTile = 500553` — converging and digging). This is the ordinary
   `SendCreateMarchMessage` path, not treasure-specific.
2. **Claim** once dug — the finisher sends:

   ```
   SFSNetwork.SendMessage("detect.event.claim.treasure",
       uuid         = 1397117530950313784,   -- PutLong  "uuid"  = f11.1 above
       targetServer = 935)                    -- PutInt   "targetServer"
   ```

   i.e. command **`detect.event.claim.treasure`**, body **`{uuid:<long>,
   targetServer:<int>}`** — the same shape as `ghost.recon.steal` and
   `hero.dispatch.steal`.

Server response:

* reward popup `UIGiftPackageRewardGet` (captured haul: *Сундук опыта героя* ×5, …);
* broadcast **`push.detect.treasure.claim { uuid, operator:{uid,name,abbr,…} }`**
  to the alliance;
* the point flips to dug (`f11.7` operator uid filled in) and a system chat line:
  *"Сокровище Uzilla, расположенное в (552,500), было раскопано!"*

The related `MsgDefines` (from the live registry, for follow-ups):
`detect.event.get.treasure.claim.info`, `receive.detect.event.reward`,
`push.detect.event.info` (treasure notification), `detect.event.put.point.in.world`
(server places the point on the map).

## Not this feature (disambiguation)

* **`DigTreasureManager`** = the in-panel *treasure-map* mini-game (hammer digs
  blocks, `MsgDefines.DigTreasureGameOpenBlock = hero.dispatch.dig.game.open.block`,
  item `771030`). Not on the world map.
* **`ExplorerTreasureManager`** = a treasure *box bubble in the base* (city),
  `hero.dispatch.explorer.treasure.open`. Not on the world map.
* **`ActDispatchTreasureManager`** = the secret-task fragment exchange.

## Lua path (DataCenter) & draft recipe — UNPROVEN

Read side (positions), no capture:

```lua
-- treasures the Detect Event has handed the client (empty when no event runs)
local m = DataCenter.ActDetectTreasureDataManager
-- m.dataDict  : keyed treasure records ; m.treasures_num : count
-- per-tile x/y for a record's pointId:
local tp = SceneUtils.IndexToTilePos(pointId)   -- e.g. 500553 -> (552,500)
```

On-map points also live in `DataCenter.WorldPointDetailManager` /
`WorldPointWaitOpenManager` and arrive as `push.world.point.update` (`f2 == 21`).

Take side (exactly what the in-game «раскопать» finish does):

```lua
SFSNetwork.SendMessage("detect.event.claim.treasure", <uuid_long>, <targetServer_int>)
-- body: PutLong("uuid", uuid) ; PutInt("targetServer", server)
```

## Primitives (built — task #1107 follow-up)

Both moves are packaged as reusable Lua chunks in `tools/lib/lua_actions.py`
(`dig_treasure_march`, `claim_treasure`, consts `MARCH_DETECT_TREASURE = 50`,
`MARCH_CROSS_DETECT_TREASURE = 182`) and driven by the standalone tool:

```
C:\Python312\python.exe tools\dig_treasure.py march <pid> <uuid> [serverId] [formation]
C:\Python312\python.exe tools\dig_treasure.py march --xy <x> <y> <uuid> [serverId] [formation]
C:\Python312\python.exe tools\dig_treasure.py claim <uuid> [serverId]
```

`march` fires `MarchUtil.SendCreateMarchMessage(formation,
MarchTargetType.DETECT_TREASURE|CROSS_DETECT_TREASURE, pid, uuid, 1,1,false,
serverId, nil)` (same/cross auto-picked from the viewed server, override
`--same`/`--cross`); `claim` fires `SFSNetwork.SendMessage(MsgDefines.
DetectEventClaimTreasure, uuid, targetServer)`.

**Validation so far:** both chunks compile in the live VM and every symbol they
touch resolves (`MarchUtil.SendCreateMarchMessage`, `MarchTargetType.DETECT_TREASURE=50`
/ `CROSS_DETECT_TREASURE=182`, `MsgDefines.DetectEventClaimTreasure=detect.event.claim.treasure`,
`SFSNetwork.SendMessage`). **Not yet fired end-to-end** — no treasure on the map
(`treasures_num == 0`); the actual dig→claim round-trip is unconfirmed until a live
detect event drops one.

### Recipe

`src/lastwar_bot/actions/dev/work_treasure.md` — "find a treasure; if still being
dug, dig; if already dug, collect." It reads the head of a parked target queue
`DataCenter.__lw_treasure_queue` (entries `{pid, uuid, server, dug, cross,
formation?}`) and, per target, presses `dig_treasure` (still digging) or
`claim_treasure` (dug). The **dug vs digging** split is the point's operator-uid
field, proven from the capture: while digging the point carries NO operator uid
(wire `f11.7` absent); once fully dug it is filled with the finisher's uid — the
finder sets `dug` from that. Buttons `dig_treasure` / `claim_treasure` /
`dismiss_treasure_reward` are in `tools/lib/game_buttons.py`; the queue helpers
(`treasure_queue_len`, `treasure_head_state`, `dig_head_treasure`,
`claim_head_treasure`) in `tools/lib/lua_actions.py`. All compile in the live VM
and the read-only helpers run (empty queue → clean no-op). It sits in `actions/dev/`
until a live treasure confirms the round-trip.

Still to come: the finder that FILLS `__lw_treasure_queue` — the chat-driven "new
treasure" detector (its push is not in any trace yet — the user will add it) or a
map scan. Until one runs, the recipe is an honest no-op.

## Status / open ends

* Position read: **confirmed** (blob decoded, pointId→(x,y) matches the in-game
  system message).
* Take command: **confirmed** on the wire (`detect.event.claim.treasure` +
  `push.detect.treasure.claim`).
* **Not yet built/proven headless:** driving march→claim from a script. The claim
  almost certainly gates on the dig being complete (a march must have worked the
  tile) and on per-day limits (`ActDetectTreasureDataManager:CheckTreasureReach
  DailyLimit`, cfg `treasureDailyLimit`). To prove end-to-end needs a live detect
  event with a treasure on the map — none was active during this analysis
  (`treasures_num == 0`).

# Resource collection on the base

How the base collects resources, reverse-engineered from two function-level traces
the user recorded (`tools/lua_trace` XSCALL logs) and confirmed live through the warm
Lua daemon. Two collection types are covered: **production buildings** ("Сбор
ресурсов") and **supply trucks** ("Сбор грузовика ресурсов").

Recipes: `actions/collect_base_resources.md` (blessed) and
`actions/dev/collect_trucks.md`. Buttons: `tools/lib/game_buttons.py`
(`collect_base_resources`, `collect_trucks`).

## Type 1 — production buildings (`ProductLineManager:SendCollect`)

The base's resource generators are **production lines**, owned by
`DataCenter.ProductLineManager`. Collecting one building is a single call —
`ProductLineManager:SendCollect(uuid)` — and the game's own "Collect All" button
does nothing more than fire that for every **ready** building. So a full base sweep is
a loop over `GetAllBuildUuids()` gated on readiness:

```lua
local plm = DataCenter.ProductLineManager
for _, u in pairs(plm:GetAllBuildUuids() or {}) do
  local ok, stor = pcall(function() return plm:GetBuildingCurrStorage(u) end)
  if ok and (stor or 0) >= 1 then pcall(function() plm:SendCollect(u) end) end
end
```

No window has to be open — the harvest is fully headless.

### The readiness gate is mandatory (task #1087)

An earlier version of this note claimed an already-empty building "simply no-ops, so no
readiness check is needed". **That is wrong.** `SendCollect` on a building with nothing
banked goes out on the wire and is rejected by the server — captured live:

```
--> building.production.collect  uuid=1267743595478371491
<-- building.production.collect  errorCode='602026' errorMsg='In production, please be patient.'
```

The client turns each rejection into a toast, so an ungated sweep of 38 buildings left
the player staring at a queue of "production still running" popups — one per not-ready
building.

**The gate:** `GetBuildingCurrStorage(uuid) >= 1`. The server bills exactly `floor()` of
the client-side storage — both captured on the wire in the same session:

| client `GetBuildingCurrStorage` | server `resNum` in the reply |
|---|---|
| `30155.124313861` | `30155` |
| `210.87499520183` | `210` |

so `floor(storage) >= 1` *is* the server's own accept condition. `>= 1` rather than
`> 0` also skips the sub-unit window right after a collect, where a continuous producer
already shows a fraction that still floors to 0.

Two shapes of building exist and both are covered by the same gate: continuous resource
generators, whose storage climbs every second (~70/s on a maxed farm), and batch "goods"
factories, whose storage stays at exactly `0` until `GetNextCollectTime(uuid)` and then
jumps by a whole `GetBuildProduceNum(uuid)`.

Not the gate, checked and rejected: `GetState(uuid)` (`1` for ready and empty alike),
`GetNextCollectTime(uuid)` (the *next production tick*, in the future even for a
building that is full and collectable) and `TryCollectRes(uuid)` (sends nothing at all —
a capture around it showed no `building.production.collect` frame).

Verified after the fix: the gated sweep sent 36 collects and got 36 successful replies,
zero `602026`.

### How this was pinned down (all confirmed live)

Each production building exposes, keyed by uuid:

- `plm:GetAllBuildUuids()` → the 38 production buildings (a plain Lua table).
- `plm:GetBuildingCurrStorage(uuid)` → the pending, uncollected amount. This is the
  ground-truth signal *and* the readiness gate: it resets to ~0 the instant a building
  is collected, and the server accepts a collect exactly when it floors to `>= 1`.
- `plm:GetNextCollectTime(uuid)` → when the next production tick lands (**not** a
  collect cooldown).
- `plm:GetBuildProduceNum(uuid)` → the per-tick production of that building.
- `plm:CanOneKeyCollectRes()` → whether anything is currently collectible.

The collectors were tested one method at a time, watching `GetBuildingCurrStorage`:

| call | effect on storage |
|---|---|
| `SendCollect(uuid)` | **drops to ~0 — collects** |
| `OnCollectClick(uuid)` | also collects (the button handler; wraps `SendCollect`) |
| `CheckOneKeyCollectAll()` | no-op (only *checks* whether to show the one-key button) |
| `TryCollectRes()` / `OnCollectClick()` with no uuid | no-op (need a uuid) |
| `CampProduceDataManager:CollectAllRes()` | no-op (a different, seasonal subsystem) |

End-to-end proof: looping `SendCollect` over all 38 buildings dropped their summed
pending storage from **~29k to ~6k (16 ready → 0)**.

### Why not `CityCollectionByItemId` (the old, retired approach)

The earlier `collect_base_resources` reconstructed the harvest from the
`20260728_171425_Сбор_ресурсов` trace's load-bearing line —
`BuildingUtils.CityCollectionByItemId(itemId, worldPos...)` — by scanning all 205
city buildings (`BuildManager:GetAllBuildData()`), filtering on `productEndTime`,
grouping by `itemId`, and resolving each instance's world position via
`GetBuildModelCenterVec(pointId, 2, 2, 0)`. That works but is far more machinery than
needed: `SendCollect(uuid)` collects a building directly, so the position math and the
205-building scan are gone.

## Type 2 — supply trucks (build bubbles)

Trace: `results/traces/20260728_171442_Сбор_грузовика_ресурсов_trace.log`. It is
dominated by UI teardown (`UICommonResItem` / reward cells) plus
`WorkerUtil.IsExistDispatchableTaylorWorker` and `Effect_Ue_GetReward` — the reward
being handed over — so the harvest itself is driven through the **build-bubble**
system rather than a single named call.

A truck surfaces on the base as a bubble in
`DataCenter.BuildBubbleManager.allBuildBubble`. Each bubble carries
`param.buildBubbleType` (a `BuildBubbleType` enum value), `param.buildId`,
`param.pos`, `param.callBack`, and the bubble object exposes an **`OnClick`** method —
tapping it is exactly `bubble:OnClick()`. Truck-relevant enum values (confirmed live):

| `BuildBubbleType` | meaning |
|---|---|
| `TruckTravelling` | truck is en route (not collectible) |
| `TruckReward` / `TruckReady` (203) | truck has arrived — tap to collect |
| `TrainCanRob` (202) | (sibling: a robbable train) |

`collect_trucks` fires `OnClick` on every `TruckReward` / `TruckReady` bubble.
Observed live: one `TruckReward` and two `TruckTravelling` bubbles present in a
snapshot; trucks come and go, so no ready truck was available to fire against during
this session — hence the recipe stays in `actions/dev/`. **Caveat:** `OnClick` on a
`ProductLineNormal` bubble *opens the production window* rather than collecting, so a
`TruckReward` `OnClick` must be verified against a live ready truck in case it, too,
opens a window (in which case switch to `DataCenter.LWGateTruckGoodsManager:DropGoods`).

`DataCenter.LWGateTruckGoodsManager` (methods `DropGoods`, `RefreshTruckGoods`,
`SetBuildObjState`, …) and `BuildManager:GetAllInBaseTruckShowBuild()` are the direct
API alternatives if the bubble path proves unreliable.

## Status

`collect_base_resources` (the `SendCollect` sweep) is **user-confirmed working live** —
run against a real base it collected every ready resource generator in a single tap.
Since #1087 it skips the not-ready ones, so the harvest no longer trails a queue of
"In production, please be patient." toasts.

## Notes for the next session

- Reading values back from the daemon uses `CS.UnityEngine.Debug.LogError("MARK|"..x)`
  + a marker (plain Lua `print` does **not** reach `Player.log` in this build).
- The base "Collect All" screenshot template already exists
  (`results/base_04_collect_all.png`) if a vision fallback is ever wanted; the Lua
  path above is preferred.

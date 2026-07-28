# Resource collection on the base

How the base collects resources, reverse-engineered from two function-level traces
the user recorded (`tools/lua_trace` XSCALL logs) and confirmed live through the warm
Lua daemon. Two collection types are covered: **production buildings** ("Сбор
ресурсов") and **supply trucks** ("Сбор грузовика ресурсов").

Recipes: `actions/collect_base_resources.md` (blessed) and
`actions/dev/collect_trucks.md`. Buttons: `tools/lib/game_buttons.py`
(`collect_base_resources`, `collect_trucks`).

## Type 1 — production buildings (`CityCollectionByItemId`)

Trace: `results/traces/20260728_171425_Сбор_ресурсов_trace.log`. The load-bearing
line is the harvest itself:

```
XSCALL BuildingUtils.CityCollectionByItemId <- 10201000, (-977.2, 501.1, 0.0), (-1388.6, 807.1, 0.0)
XSCALL UIUtil.DoFly <- ... cfm_zhujiemian_tubiao_ziyuan4.png, (-977.2, 501.1, 0.0), (-1388.6, 807.1, 0.0), ...
XSCALL DataCenter.ProductLineManager.bindProductionTimer <- 1156814232810146872
```

So tapping a ready building calls **`BuildingUtils.CityCollectionByItemId(itemId,
worldPos...)`**. The first arg is the building's config id (here `10201000`, a
resource building with 5 instances); the varargs are the **world positions** of every
ready instance of that itemId — one call harvests them all at once (the trace shows
two positions batched). `UIUtil.DoFly` is just the resource-icon fly animation and can
be ignored.

### Data model (confirmed live)

- `BuildingUtils.GetBuildListByBuildId(buildId)` → the building instances. Each has
  `itemId` / `cachedItemId` (== the buildId for resource buildings), `pointId`,
  `prodStatus`, `productEndTime`, `lastCollectTime`, `productBase`.
- `DataCenter.BuildManager:GetAllBuildData()` → all 205 city buildings; the producing
  ones carry a non-zero `productEndTime` (walls/decorations don't). Filtering on that
  narrows the sweep to ~11 resource-building kinds / ~41 instances.
- `BuildingUtils.GetBuildModelCenterVec(pointId, 2, 2, 0)` → the world position an
  instance needs as the `CityCollectionByItemId` argument (2×2 tile footprint).

### Recipe strategy

`collect_base_resources` groups the base's producing buildings by `itemId` and calls
`CityCollectionByItemId(itemId, positions...)` once per group. **No readiness check is
needed**: the server harvests whatever is ready and no-ops the rest (proven harmless
by firing it across all buildings — no error, nothing lost). Readiness helpers exist
but are unreliable for a blanket sweep: `BuildingUtils.IsCanShowCollectGreenByPoint`
returns `true` for *every* building, and `BuildManager:GetCanGetResourceBuildUuidByResourceType(rt)`
errors on most resource types — so we rely on the server's own no-op instead.

`BuildingUtils` also exposes `CollectSoldier`, `IsBuildResourceEmpty`,
`GetResourcePercent`, `GetCityBuildAllResByItemId` for finer-grained work if ever needed.

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

## Notes for the next session

- Reading values back from the daemon uses `CS.UnityEngine.Debug.LogError("MARK|"..x)`
  + a marker (plain Lua `print` does **not** reach `Player.log` in this build).
- The base "Collect All" screenshot template already exists
  (`results/base_04_collect_all.png`) if a vision fallback is ever wanted; the Lua
  path above is preferred.

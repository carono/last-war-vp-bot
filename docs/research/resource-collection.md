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

### What the sweep costs the client, and where the stutter comes from (task #1189)

The player reported the game freezing while the base is harvested. It is **not** a read
spam of ours: `collect_base_resources` is a single VM round trip, and the sweep itself is
cheap. The freeze is the client's own reaction to each collect *reply*, multiplied by the
number of buildings.

Read off `results/traces/20260802_151055_обычная_игра_trace.log` — a broad XSTRACE
(wrapped=6535, depth=2, no dedup) of one ordinary session, 86,070 traced Lua calls.
`building.production.collect` crossed the wire 61 times in six bursts. Five of them (36
requests) follow a `BuildingUtils.CityCollectionByItemId` call each — the player tapping
the HUD resource icons. The sixth, lines 56015–56207, is ours: 25 requests inside 193
lines with nothing but SFS marshalling between them and no UI call ahead of it.
`ProductLineManager` is not in the wrapped set, so the chunk is invisible in the trace;
that marshalling run is its fingerprint.

**Sending is free. Being answered is not.**

| | traced Lua calls |
|---|---|
| all 25 requests going out | 386 (~15 each) |
| each reply coming back | **~425** |
| the whole sweep, lines 56520–66210 | **9,691 — 11% of the session** |

The replies arrive one per frame, evenly spaced (424, 427, 427, 425, … lines apart), so
that is 25 consecutive frames each doing ~425 Lua calls on top of the frame's own work.
One reply expands into:

- **114 × `DataCenter.BuildBubbleManager.checkShowBubbleAction`** — every base bubble
  re-walked (42 distinct bubble objects, ~2.7 passes). Across the whole session 9,009 of
  the 9,507 bubble checks — 95% — sit behind a collect reply;
- **~30 × the building-condition sweep** — `SceneUtils.GetIsInCity` plus
  `BuildingLevelTemplate.IsPreBuildConditionValid` / `GetPreBuild` / `GetNeedResource` /
  `IsTimeConditionValid` for every building, because the balance moved and each
  building's "can I afford / unlock this upgrade" state is recomputed from scratch;
- the flying-resource animation: `UIUtil.DoFlyCustom`, `UIAnimator.Play`,
  `UIImage.LoadSprite` + `CheckPath`, `UIText.SetText`.

Taken over the session, the 61 replies account for 17,566 traced calls — 20% of
everything the VM did — for an action the player experiences as one tap.

**Our own second-order contribution.** That same burst also produced 20
`push.resource.info` and 6 `push.resource.item.update`. Three panel listeners hang off
`push.resource.item.update` — the `resource_tracker` trigger, the `inventory_refresh`
trigger, and the «Инвентарь» tab's `refresh_live` — and each one is a fresh VM round trip
(settle 0.6 s) that hijacks the main thread *while* the client is still digesting the
cascade. `TimerScheduler.submit` coalesces only what arrives while the previous run is
queued or running, so a burst spread over several seconds still costs several hijacks.
Nothing throttles them.

**Leads for a fix, none verified live yet**, best first:

1. **Do the harvest outside the city scene.** Every leg of the cascade is city UI, and
   each one asks `SceneUtils.GetIsInCity` before doing its work — 1,863 of those calls in
   the sweep's window alone. If the bubbles and the fly animation short-circuit in the
   world scene, the reply cost collapses. Cheapest to test, biggest prize.
2. **Pace the sends.** 25 requests in one chunk queue 25 heavy frames back to back; a
   short gap between them lets the client digest one reply per idle frame instead.
3. **Debounce the panel's `push.resource.item.update` listeners** so a harvest costs one
   read, not one per push that slips past the coalescer.

Note that the retired path is no cheaper: the player's 8 icon taps still produced 36
separate `building.production.collect` requests. One request per building is the game's
own shape — there is no batch collect to move to.

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

It does, however, make the client stutter while it runs — diagnosed in #1189 above, not
yet fixed.

## Notes for the next session

- Reading values back from the daemon uses `CS.UnityEngine.Debug.LogError("MARK|"..x)`
  + a marker (plain Lua `print` does **not** reach `Player.log` in this build).
- The base "Collect All" screenshot template already exists
  (`results/base_04_collect_all.png`) if a vision fallback is ever wanted; the Lua
  path above is preferred.

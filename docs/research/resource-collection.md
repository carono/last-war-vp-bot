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

## What the harvest is worth, stated before it presses anything (#2747)

The day's card «Сбор ресурсов» is built by DIFFING balances, and a balance push says only
that a number moved. Attributing a gain to the base by TIME alone therefore charges the
harvest with whatever else happened to land near it. Measured on the live panel of
2026-09-11, profile `default`:

| item | whole-day tally | base's card | what the base makes |
|---|---|---|---|
| «Запчасти дрона» (7038) | 56 | 34 | about 7 a day |
| «Сундук Компонента Дрона» (630011) | 46 | 21 | none — the base has no line for it |
| «Фиолетовый кристалл» (521050) | 90 | 90 | none |

The 34 is `20 + 9 + 2 + 2 + 1`: `collect_base_resources` ended at 08:44:37 and 08:54:07
and two arms-race prizes of twenty drone parts each landed at 08:45:44 and 08:55:50 —
outside the minute's claim (#2746e) and inside the burst chain behind it, which exists to
hold a harvest's own cascade together and therefore held those too. On the four
resources the same error is invisible: it is a percent of eleven million.

So the harvest states its own size. `actions/collect_base_resources.md` sums
`GetBuildingCurrStorage` over `GetAllBuildUuids` by what each line pays
(`GetProductRes` / `GetProductResItem` / `GetProductGoods`) BEFORE it presses anything —
the same number `read_base_resources.md` reports as `pending` — and leaves it in
`harvest_pending`. `panel/runtime/resource_book.py` arms that as a per-key BUDGET and
credits the base up to it and no further; a key the harvest never claimed gets nothing.

A harvest made with a thumb states nothing, so its budget is the last reading's own
`pending`. That only ever understates, which is the right way for this number to be
wrong.

### Verified live, 2026-09-11 09:28

```
the sweep is about to collect: 1=34129 #|# 2=25166 #|# 14=35862 #|# 10=3750 #|# 23=455 #|# i8001=54000
получено ресурсов: item:8001 +54000, metal +34129, food +36529, oil +455, gold +25594
```

The base's book moved by `metal +34129, gold +25166, food +35862, oil +455,
item:8001 +54000` — each exactly the stated size, with the 667 food and 428 gold that
arrived from somewhere else in the same window left in the whole-day tally alone. In the
same window the tally took `item:630011 +22` and `item:7038 +20`; the base's book took
neither.

The reading is exact rather than inferred: the reading of 23:55 on 2026-09-10 said 219
screws were standing, and the harvest a minute later paid exactly 219.

### A harvest made BY HAND states no size, and a stale cap is worse than none (#2747)

The person: «5 зданий для генерации опыта изготовили по 60 000, после сбора в статистике
180 000». Measured on the live panel of 2026-09-11:

* 10:04:56 — the balance rose by `item:8001 +302 400` (five lines × 60 480), and the base's
  book took **183 600**.
* No run of `collect_base_resources` was on the register: the panel's own play had been
  refused minutes earlier and the client went down at 10:08. The collect was the person's
  own thumb, which is exactly the case #2746d says must count.
* With no run to state the size, the budget came off the last READING's `pending`, which
  was minutes old — the same five lines at 36 720 each. 183 600 = 5 × 36 720.

A cap that is stale by construction loses two fifths of a real harvest, which is far
worse than what the cap is for. So a GUESSED budget is now a LIST of the keys the base was
known to be holding and never a ceiling on the amount: it still refuses a chest of drone
parts, an arms-race prize or a crystal — the keys production never pays — and it takes what
the base paid whole. A budget a RUN stated is unchanged and is still an exact cap, because
that one is read off the game one line before anything is pressed.

### Does the budget ever cut the panel's OWN sweep? Measured: no (#2747)

The person's follow-up: «ресурсы собраны все, по механике нельзя собрать часть» — so the
300 000 arrived and something on our side kept 180 000. It did, and it was the stale
fallback above. The other candidate — that the panel enumerates fewer production lines
than the base has — was checked with a census taken seventeen seconds before a sweep:

| | five lines, census 10:26:43 | budget stated 10:27:00 | gain on the wire 10:27:24 | written to the base's book |
|---|---|---|---|---|
| hero experience | 5 × 17 280 = 86 400 | **95 040** | **+95 040** | **+95 040** |
| metal | 56 548 | 61 296 | +61 563 | +61 296 |
| food | 61 529 | 66 378 | +66 379 | +66 378 |
| gold | 42 771 | 45 916 | +46 113 | +45 916 |
| oil | — | 910 | +910 | +910 |

All five lines of every kind are in the budget: it is larger than the census by exactly
the production of the seventeen seconds between them (hero experience: 95 040 − 86 400 =
8 640 = 5 lines × 4 ticks × 432). For the ITEM the three numbers are identical. So the
enumeration is complete and nothing is cut.

What IS dropped is the trickle between the budget's own read and the collects a
fraction of a second later — 1 food, 267 metal, 197 gold here, **0.0015 % to 0.44 %**. It
is left on the floor deliberately: closing it means letting a gain exceed the stated size
by some margin, and a margin is exactly the door the budget was put in to shut.

## Notes for the next session

- Reading values back from the daemon uses `CS.UnityEngine.Debug.LogError("MARK|"..x)`
  + a marker (plain Lua `print` does **not** reach `Player.log` in this build).
- The base "Collect All" screenshot template already exists
  (`results/base_04_collect_all.png`) if a vision fallback is ever wanted; the Lua
  path above is preferred.

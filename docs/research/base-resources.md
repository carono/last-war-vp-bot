# The base's resource stock: where the numbers are, and why the field names lie

Task #1990. The panel had no reading of «сколько у меня сейчас золота, хлеба, металла и
нефти» that worked, and the one it thought it had returned nothing at all. This is what
was found on a live client on 2026-08-26, what the reading is now, and what it costs.

Recipe: `actions/read_base_resources.md`. The cache the panel serves it out of:
`panel/runtime/resources.py`. The card: the phone's «Профиль» (`panel/tabs/profile.py`).

It opened on «Состояние» and moved on the person's word — «ресурсы выведи на вкладке
профиль». The move had to take the EAR with it, and that is the part worth remembering:
`BaseResources.state()` is both the reading and the subscription — asking for it is what
raises the listener on `push.resource.item.update` and what keeps it up — so the card and
the caller cannot be separated. Left on `/api/state`, the call would have held a capture
alive for every phone with the front page open, whether or not anybody was reading a
balance; drawn on «Профиль» without the call, the card would have shown a number nothing
ever updated. Both halves are pinned in `tests/test_panel_web.py`.

## 1. What was there before — a guess wrapped in `pcall`

`panel/runtime/reads.py` asked `DataCenter.ResourceManager` for `GetFood()`, then the
field `food`, then `R.resource.food`, each in its own `pcall`, and called itself
"best-effort". A live dump of that manager's metatable:

```
ResourceManager  ->  Delete GetResourceDescByType GetResourceIconByType
                     GetResourceNameByType GetResourceOutBuildingUids
                     GetResourceOutBuildings InstanceOf New …
```

Name, icon, description and which buildings produce a resource — and no amount of
anything. So every branch fell through and the function returned `{}` on every call it
ever made. The daily tally it feeds (`panel/resource_stats.py`, the «Статистика» tab) has
therefore been empty for its whole life, and nothing said so. Same lesson as
`docs/research/inventory.md`: **a `pcall` around a guessed name turns a wrong name into
silence.**

## 2. Where the numbers actually are — `LuaEntry.Resource`

Not under `DataCenter` at all. A depth-limited walk of `_G` looking for the key
`petroleum` found it in one place:

```
G.LuaEntry.Resource.petroleum = <amount>
```

The object's own fields are the whole balance:

```
money  metal  wood  petroleum  oil  water  electricity  obsidian  flint  people
honorScore  pvePoint       …plus maxMetal / maxOil / maxWater / maxElectricity
                              and metalAddSpeed / oilAddSpeed / waterAddSpeed
```

and its metatable carries the accessors that matter:

| call | answers |
|---|---|
| `GetCntByResType(type)` | how much of that resource is held |
| `GetMaxStorageByResType(type)` | the cap, where the resource has one |
| `GetResAddSpeedByResType(type)` | the per-second trickle, where it has one |
| `GetResCurrentPercentByResType(type)` | how full it is |
| `LWResourceLackUtil.GetResourceSpeedCountPerHour(type)` | the per-hour rate |

## 2a. ONE READ AT LOGIN, THEN DELTAS — measured, and now REQUIRED

**This stopped being an observation about the client and became the rule the panel is
written under** (`CLAUDE.md`, «Read once, then LISTEN»). The operator's words: «работаем в
той же парадигме как и клиент, читаем один раз, остальное слушаем изменения, никаких
активных действий просто в фоне быть не должно, все подобные моменты проговариваются
отдельно». So what follows is not merely how the GAME happens to work — it is how every
reading in this panel has to work, and a background poll is a violation whatever it costs.
Where there is no event to subscribe to, the poll is not written: the cost and the
interval are put to the person first.

The operator's hunch, and it is right: the client does not ask the server for the
balance. It is handed the numbers once and then keeps them, applying every change as it
is announced. The class carries exactly the three parts of that model —
`InitFromNet` (the one read), `UpdateResource` / `UpdateResourceCurrentValue` /
`ChangeNum` (the deltas), and `AddListener` / `__event_handlers` (the subscription).

Proved by wrapping all six writers on the class and counting:

| | `InitFromNet` | `UpdateResource` | `UpdateResourceCurrentValue` | balance |
|---|---|---|---|---|
| **45 s of an idle base** | 0 | 0 | 0 | byte-identical |
| **one `collect_base_resources`** | 0 | **25** | **25** | metal +718 326, food +763 421 |

Twenty-five is one per collect reply — the sweep sent 25 `building.production.collect`.
`InitFromNet` stayed at zero throughout: it had already run, at login.

**What follows for the panel.** A read never touches the server, so its cost is the
panel↔VM round trip and nothing else; and a balance that no event has moved CANNOT have
changed, so polling for one is either late or wasted. The panel therefore subscribes to
`push.resource.item.update` — the wire half of the same event — on the profile's shared
ear (`panel/runtime/wire.py`) and re-reads when it is told to. §7 has what that leaves.

> **A wrapper was left in the live client by this experiment.** The six writers on
> `LuaEntry.Resource`'s class still carry a counter that increments
> `DataCenter.__lw_rw` and calls through. `debug.getupvalue` and `string.dump` have been
> closed in this client since 2026-08, so the originals cannot be recovered to undo it;
> it costs one table write per resource update, it cannot fail (nothing removes the table
> it writes to), and it goes away with the next restart of the game client. **Do not
> delete `DataCenter.__lw_rw`** — the wrapper would then index a nil inside the game's own
> resource path.

## 3. **The field names do not say what the game shows.** Read by TYPE

This is the whole reason the recipe is written the way it is. The flat fields are the
engine's originals and the game has been re-skinned around them. Asked by type on a live
account, with the name coming from the client's own table
(`ResourceManager:GetResourceNameByType`):

| type | the game's own name | the field holding it |
|---|---|---|
| 1 | «Металл» | `metal` |
| 2 | «Золотые монеты» | **`wood`** |
| 14 | «Еда» | **`money`** |
| 23 | «Нефть» | `petroleum` |
| 15 | «Бриллианты» | — |
| 10 / 13 | season resources | `obsidian` / `flint` |

Reading `money` and labelling it «золото» — which is exactly what the old code was
shaped to do — prints a confident lie about the largest number on the screen. So nothing
in the panel maps a field to a word: the recipe asks per type and reports the game's own
name with it, which also satisfies `CLAUDE.md`'s rule that no word of the panel is
written in the panel.

The type ids are the client's own enum (`_G.ResourceType`), and it is itself a museum of
the same drift — `Wood = 2`, `Oil = 0`, `Food = 14`, `Gold = 15`. **The enum's names are
not usable either**; only `GetResourceNameByType` is.

### Two types can wear the same name

Type 0 is dead — the amount is always 0 — and its config row now reads «Золотые монеты»,
the same name as type 2, which is the one the player holds. Drawn together they read as
a bug («золото: 0» above «золото: 712 198 273»), so the recipe drops a zero row whose
name another non-zero row already carries. Nothing is renamed and nothing is summed.

### Which types are reported

Every type in the game's own resource table
(`ResourceTemplateManager.resourceTemplateDic` — 11 rows on this build) whose count is
above zero, or which the base has a building for
(`ResourceManager:GetResourceOutBuildings`). The rest are resources this account has
never met.

## 4. What the game does NOT report

Asked for all ten live types: `GetMaxStorageByResType` answers `200` for the season
resources (water, electricity) and **`0` for every base resource**, and
`GetResourceSpeedCountPerHour` answers **`0` for all of them**. There is no storage cap
and no hourly rate for gold, food, metal or oil in this client — so the card shows
neither rather than computing one out of `GetBuildProduceNum` and a tick length. A
derived number in a column headed «в час» would be indistinguishable from one the game
stated.

**And one of the caps it does answer belongs to something else.**
`GetMaxStorageByResType(1)` answers `200` on an account holding 71 832 543 of type 1 —
the season's own metal allowance, reached because the two share a type id. So the recipe
drops any cap that is smaller than the stock it is supposed to bound: «71 832 543 из
200» is not a fact about anything.

Two more things that look like caps and are not:
`ResourceItemDataManager.warehouseStorageMax` (`30.0`) and `freezerStorageMax` (`40.0`)
are building LEVELS, not amounts.

Dead ends, so nobody re-walks them:

* `ResourceItemDataManager:GetResourceItemTotalNumByType` counts resource PACKS in the
  bag, not the balance — it answers 0 for metal on an account holding 71 million of it.
* `ProductLineManager:GetResItemCurStorage` / `GetResItemMaxStorage` answered `0/0` for
  every type asked.
* `BuildManager:GetOutResourceNum(type)` answered `0` for every type.
* `ProductLineManager:GetResType(uuid)` does not answer for a build uuid while the
  client is out on the world map. **`GetProductRes(uuid)` does** — see §5 — and using the
  first one is why an early version of this reading reported no pending storage at all.
* `LWResourceLackUtil.GetBuildingResourceCollectionAndProduceTime` answers `0, 0` for a
  build uuid, a build id and a `:`-call alike. It belongs to the «not enough resources»
  popup and needs state that a headless read does not have.
* `LWResourceLackUtil.TryGetBuildingCanCollectResNum(type)` and
  `TryGetHangUpRewardCanCollectResNum(type)` answer `0` for every type — they are not the
  pending figure either.
* `BuildingUtils.GetBuildingCurrentProduceCount` / `GetBuildingPredictedProduceCount` do
  not resolve as globals from a headless read.

## 5. What IS stated: how much is waiting to be collected

Every production building answers two things that need no scene and no window:

| call | answers |
|---|---|
| `ProductLineManager:GetProductRes(uuid)` | `{[resourceType] = per-tick amount}` |
| `ProductLineManager:GetBuildingCurrStorage(uuid)` | how much is standing uncollected |

Summing the second by the first gives the pending stock per resource — on a live base,
44 buildings, `377 023` gold / `604 724` food / `569 647` metal / `7 735` oil waiting.
That is exactly what one press of «Сбор ресурсов» would add, it is the game's own number
per building, and the only arithmetic on it is a sum. It is the seventh field of the
reading and the card shows it beside the amount.

**Note it is `GetProductRes`, not `GetResType`.** The latter does not answer for a build
uuid while the client is out on the world map, and it is why the first cut of this
reading reported nothing.

## 6. Why there is no «в час», in detail

The client keeps a per-TICK figure per building, `GetBuildProduceNum(uuid)` — `196.35` on
the building watched — and no tick length anywhere. The length was established by
watching one building's storage across a `WAIT 20`:

```
t=0    stor = 70293.299
t=20s  stor = 71078.699      ->  785.4 in 20 s  =  39.27/s
785.4 / 196.35 = 4.0 exactly ->  GetBuildProduceNum is per FIVE SECONDS
```

which also squares with the config: `GetProductRes` says `{2 = 35}` — 35 a second of
type 2 before bonuses — and `35 x 1.122 = 39.27`, the technology multiplier.

So an hourly rate is reachable: `GetBuildProduceNum x 720`. **It is deliberately not
shown.** The `720` is this document's measurement, not the game's statement, and a
column headed «в час» carrying the panel's own constant is indistinguishable from one
the client provided. `GetResourceSpeedCountPerHour`, which IS the client's per-hour
accessor, answers `0` for gold, food, metal and oil alike — it exists for the season
trickle resources (`metalAddSpeed`, `oilAddSpeed`, `waterAddSpeed`), which are all `0`
on this account too.

## 7. What it costs

One play of `read_base_resources`, end to end through the panel's own runner, timed off
`profiles/<name>/debug.log` on the live client:

| run | open → close |
|---|---|
| 1 | 168 ms |
| 2 | 219 ms |
| 3 | 260 ms |

**The 44-building sweep for the pending figure is free**, measured after it was added:
175 / 193 / 195 / 209 ms for the whole reading. It is inside the same chunk, so the cost
is the round trip and not the work — the same lesson as the alliance-tech donate loop.

This is why the panel does not read on demand. `/api/state` is its most frequent
question — an open page asks every 2.5 s, per profile — so reading per poll would hold
the exclusive game link some 8 % of the time for as long as a phone is open, at the
expense of the schedule and the robberies.

**So the wire is the update and the clock is only a net** (§2a). `panel/runtime/resources.py`
subscribes to `push.resource.item.update` while somebody is looking, re-reads when it is
told to, and otherwise re-reads at most every **300 s**. Underneath the pushes is a
**3 s** floor, because a harvest is a burst of them — 25 collect replies — and the client
is still digesting the cascade while they arrive
(`docs/research/resource-collection.md`). The play goes in at `claims.DETACHED`, below
every ordinary errand: a stock figure is never worth making a rally join wait.

What that costs an idle evening: **nothing**. No push, no read. What it costs a harvest:
one read, ~0.2 s, a few seconds after the last reply. Measured live on the headless panel
— gold went 712 761 695 → 712 780 343 and the reading's age fell from 95 s to 4 s with
nobody pressing anything.

The ear is a capture process, shared with whatever else this profile subscribes to. It
goes up the first time the card is asked for and comes down when nobody has asked for
120 s, so a panel nobody is looking at pays for no capture either.

The tally in `panel/resource_stats.py` reads the same cache, so there is exactly one trip
to the game however many things are watching.

## 8. The login gate

A client at the login screen answers every question plausibly and wrongly — no tasks,
own server `-1`, all five robberies unspent (`tools/lib/game_clock.py`, #1227) — and
`LuaEntry.Resource` is no exception. So the recipe asks the game what time it is BEFORE
it reads anything, in the same chunk, and returns an empty string when the answer is not
an epoch (a client that has not logged in hands out its own uptime). The panel then keeps
the rows it had rather than drawing a base with nothing in it. It costs no extra round
trip.

## 9. How to ask again

```
READ_LUA (function() local R = LuaEntry.Resource
  local RM = DataCenter.ResourceManager
  return RM:GetResourceNameByType(14) .. '=' .. R:GetCntByResType(14) end)() INTO x
LOG "{x}"
```

# The base's resource stock: where the numbers are, and why the field names lie

Task #1990. The panel had no reading of «сколько у меня сейчас золота, хлеба, металла и
нефти» that worked, and the one it thought it had returned nothing at all. This is what
was found on a live client on 2026-08-26, what the reading is now, and what it costs.

Recipe: `actions/read_base_resources.md`. The cache the panel serves it out of:
`panel/runtime/resources.py`. The card: the phone's «Состояние».

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
* `ProductLineManager:GetResType(uuid)` did not answer for a build uuid while the client
  was on the world map, so per-resource PENDING storage is not in the reading.

## 5. What it costs

One play of `read_base_resources`, end to end through the panel's own runner, timed off
`profiles/<name>/debug.log` on the live client:

| run | open → close |
|---|---|
| 1 | 168 ms |
| 2 | 219 ms |
| 3 | 260 ms |

This is why the panel does not read on demand. `/api/state` is its most frequent
question — an open page asks every 2.5 s, per profile — so reading per poll would hold
the exclusive game link some 8 % of the time for as long as a phone is open, at the
expense of the schedule and the robberies. The reading is cached for 30 s
(`panel/runtime/resources.py`), which is ~0.7 %, and it is played at
`claims.DETACHED` — below every ordinary errand, because a stock figure is never worth
making a rally join wait.

The tally in `panel/resource_stats.py` reads the same cache, so there is exactly one trip
to the game however many things are watching.

## 6. How to ask again

```
READ_LUA (function() local R = LuaEntry.Resource
  local RM = DataCenter.ResourceManager
  return RM:GetResourceNameByType(14) .. '=' .. R:GetCntByResType(14) end)() INTO x
LOG "{x}"
```

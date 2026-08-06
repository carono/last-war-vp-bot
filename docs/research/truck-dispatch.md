# Sending trade trucks out («Отправка грузовиков»)

The trade station's fleet: the trucks a commander dispatches to another server,
other players rob on the way, and the initiator empties on arrival. **Not** the
supply truck that arrives at the base (`resource-collection.md`) and not the base's
idle accumulator — three different things wearing the same word.

What is done today is the **reading** behind the checklist's first group (#1249).
The dispatch itself is not automated; everything below is what the next session
needs to write it.

## The manager

`DataCenter.LWMyStationDataManager` (Lua, `LuaScripts/DataCenter/LWRailway/Station/`)
owns the fleet, the daily allowance and the formations. `DataCenter.LWMyStationManager`
is its view side (bubbles, models, camera), and `LWAllyStationDataManager` is the
alliance's stations.

Read live, and all three are already computed — nothing has to be derived from the
fleet list:

| call | what it answers |
|---|---|
| `GetDepartureCount()` | how many trucks have gone out today |
| `GetMaxDailyCount()` | today's allowance — a base four plus what the «Extra Truck» tech adds |
| `GetRealReadyCount()` | how many could go out RIGHT NOW: trucks in `TruckStationState.Ready`, capped by what is left of the allowance |
| `IsTruckFunctionLock()` | the trade station is still locked (it opens at base level 8) |
| `IsDailyCountLoaded()` | the daily counters have arrived from the server |
| `GetMyTrainList()` / `GetMySpareTrains()` / `GetMyDepartureTrains()` | the fleet, the idle ones, the ones on the road |

**Two traps, both cost a session if they are not known:**

1. These calls return MORE THAN ONE value. `tonumber(M:GetDepartureCount())` reads
   the second as a base and fails with «string expected, got number» — wrap the call
   in its own parentheses.
2. **A locked station answers `0` dispatched, exactly like an idle one.** Drawn
   straight that reads as «nothing sent yet today» on an account that cannot send
   anything at all. Every read guards on `IsTruckFunctionLock()` first and answers
   nil, which the checklist draws as «state unknown»
   (`tools/lib/lua_actions.py: truck_dispatch_*`).

## The wire

`MsgDefines`, resolved live:

| name | command | what it is |
|---|---|---|
| `GetMyStationData` | `train.data` | ask for the station's state |
| `PushMyStationData` | `push.train.data` | …and the server pushing it back |
| `DepartureTrain` | `train.send` | dispatch one truck |
| `TrainBatchSend` | `train.batch.send` | «Супер отправка» — dispatch several |
| `ChangeTrain` | `train.change` | refresh one truck's rarity |
| `TrainBatchChange` | `train.batch.change` | «Супер обновление» — refresh several |
| `CollectTrainReward` / `CollectTrainBatchReward` | `train.reward` / `train.batch.reward` | take what an arrived truck carried |
| `AttackTrain` | `train.attack` | rob somebody else's |

The checklist subscribes to `train.data`, `train.send` and `train.batch.send`, which
is what makes its counter move within seconds of a truck leaving rather than at the
next poll.

## What a dispatch needs, and why it is not a scenario yet

`TryDepartureTrain` reads (from its constants) `trainUuid`, an escorting `formation`
built by `GenerateServerHeroArray` out of the saved truck formation, the squad index,
and a chip-set id; it calls `TrySaveTruckFormation` first and refuses with a tips id
when there is no escorting squad. So a dispatch is «pick a truck, pick heroes to guard
it, save that, send» — several decisions, not one press, and each of them spends
something. Until that is one `actions/*.md` scenario the panel reads the numbers and
offers no button (`CLAUDE.md`).

## Rarity, and the setting that is waiting for it

A truck has a rarity — N, R, SR, SSR, UR — and refreshing raises it: in «Супер режим»
each non-UR truck costs Trade Contracts to bring to UR. Above UR there is the
**Reindeer Sleigh Ride** (`tech_name_13_9`, ru «Оленья повозка»), its own tech, with
its own «refresh everything to it» button (`super_trucklaunch_limit_10`).

That is where the checklist's three-way setting comes from — to UR by hand, to UR by
itself, all the way to the sleigh by itself. It is stored in the profile and drawn,
and nothing reads it yet: it is what the dispatch ability will be told to do the day
it exists.

## Windows

```lua
UIManager.Instance:OpenWindow(UIWindowNames.UILWTruckSuperDeparture)  -- dispatch / refresh
UIManager.Instance:OpenWindow(UIWindowNames.UILWTruckRecord)          -- who robbed whom
```

Enums worth knowing: `TruckStationState` (`Lock` 0, `Ready` 1, `Exhausted` 2,
`Travelling` 3, `Reward` 4), `TruckStateType` (`Safe` 1, `Robed` 2, `DefendSuccess` 3),
`TruckRecordType` (`TruckSend` 1, `TruckRob` 2, `TruckCollect` 3).

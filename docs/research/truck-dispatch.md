# Sending trade trucks out («Отправка грузовиков»)

The trade station's fleet: the trucks a commander dispatches to another server,
other players rob on the way, and the initiator empties on arrival. **Not** the
supply truck that arrives at the base (`resource-collection.md`) and not the base's
idle accumulator — three different things wearing the same word.

What is done today is the **reading** behind the checklist's first group (#1249)
**and the dispatch itself** (#1908) — `actions/send_trucks.md`, which rotates the
fleet up to a rarity you name and then sends out as many trucks as the day still
allows. The last section of this file is how that was measured; everything before
it is the reading.

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

## What a dispatch needs — and why it is the window's own two presses

`TryDepartureTrain` on the data manager reads (from its constants) `trainUuid`, an
escorting `formation` built by `GenerateServerHeroArray` out of the saved truck
formation, the squad index, and a chip-set id; it calls `TrySaveTruckFormation` first
and refuses with a tips id when there is no escorting squad. So a dispatch built from
the wire is «pick a truck, pick heroes to guard it, save that, send» — several
decisions, each of which spends something.

None of that is done by hand. **The whole ability lives in `UILWTruckSuperDeparture`,
and the state it needs is on the window's VIEW rather than on the data manager**
(measured on three live accounts, #1908):

| on `UIManager.Instance:GetWindow(UIWindowNames.UILWTruckSuperDeparture).View` | what it is |
|---|---|
| `canSelectRefreshTruckIndexMap` | which trucks the refresh may touch — already excludes one at the top rarity |
| `canSelectDepartureTruckIndexMap` | …and which may be sent. NOT quota-aware: it holds three on an account with 5/5 dispatches gone |
| `recordSelectRefreshTruckIndexMap` / `recordSelectDepartureTruckIndexMap` | the selection itself, `index -> true` |
| `selectRefreshReindeerCart` | the «all the way to the sleigh» toggle |
| `isUnlockReindeerCart` | whether this account has that toggle at all |
| `CalcRefreshTruckCost()` | …which SETS `refreshSelectTruckNeedTicketCount` |
| `refreshSelectTruckNeedTicketCount` | the price of the current selection, in Trade Contracts |
| `ownTicketCount` / `oneTicket2DiamondNum` | what is in the bag, and what one contract costs in diamonds when it is short |
| `OnTabItemClick(n)` | 1 = Refresh, 2 = Departure |
| `TrySendRefreshMsg()` / `TrySendDepartureMsg()` | the two senders |
| `truckShowDataList[i].truckData` | the truck itself: `quality`, `isSpecialURQuality`, `uuid`, `arriveTs` |

### The price, measured one truck at a time

Flat, and it does not depend on where the truck is starting from:

| selection | contracts |
|---|---|
| one truck (`quality` 1) to UR | 3 |
| one truck (`quality` 4) to UR | 3 |
| three trucks to UR | 9 |
| one truck to the sleigh | 6 |
| three trucks to the sleigh | 18 |

`oneTicket2DiamondNum` is 100, and a short bag is made up in diamonds by the game
without saying so — the same silent top-up the secret tasks were caught by (#1903), so
the recipe reads the purse again afterwards and prints the difference.

**Nothing of that table is written into the recipe.** The selection is built, the
game's own `CalcRefreshTruckCost()` is called, and the number it answers is the gate.

### Two traps in the presses themselves

1. **`OnBtnRefreshOrDepartureClick()` does not do what its name says, and does two
   different things on the two tabs.** On the Refresh tab it raises
   `UILWTruckSuperDepartureRefreshSecondConfirm` and sends nothing — the first run
   reported a successful rotation against an unchanged bag of 358 contracts. On the
   Departure tab it does nothing at all: a whole run pressed it against three trucks
   standing with five dispatches banked and left the counter at 0/5. (It presumably
   wants the button it was wired to, which a call from outside has not got.) So the
   recipe clicks for the refresh and then answers the dialog with `TrySendRefreshMsg`,
   and for the dispatch calls `TrySendDepartureMsg` directly rather than clicking at
   all — a click that MIGHT start working followed by a send that certainly works is
   two dispatches out of a five-a-day allowance.
2. **Never «select all».** The window's own select-all ticks every truck it MAY touch,
   which at the UR target includes a truck that is already UR — a press would re-roll a
   win and charge three contracts for the privilege.

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

# Sending trade trucks out («Отправка грузовиков»)

The trade station's fleet: the trucks a commander dispatches to another server,
other players rob on the way, and the initiator empties on arrival. **Not** the
supply truck that arrives at the base (`resource-collection.md`) and not the base's
idle accumulator — three different things wearing the same word.

What is done today is the **reading** behind the checklist's first group (#1249),
**the dispatch itself** (#1908) and **the round trip** (#2023) — `actions/send_trucks.md`,
which empties the trucks that have come home, rotates the rest up to a rarity you name,
sends out as many as the day still allows and books its own next turn for the moment the
nearest truck lands. The last two sections of this file are how that was measured;
everything before them is the reading.

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

## The round trip: collecting an arrival, and one truck at a time (#2023)

A dispatch is three to four hours out and comes back carrying what it earned. **Until
that load is taken the truck is `TruckStationState.Reward`** — neither `Travelling` nor
`Ready` — so it cannot be sent again, and a day's five dispatches are decided by whether
anybody collects in time rather than by the fleet's size.

Measured live on the station manager (the names it really has, `getmetatable(M).__index`):

| call | what it is |
|---|---|
| `GetTruckStationStateByTrainData(t)` | the truck's state — the only honest way to say «this one has landed». `arriveTs` is the client's clock and answers «the timer has run out», not «the server has said so» |
| `TryBatchCollectReward()` | **no arguments**, empties every arrived truck at once (`train.batch.reward`) |
| `TryCollectReward(uuid)` | one truck. Called bare it raises inside the serialiser — `bad argument #2 to 'pack' (number expected, got nil)` — which is how the signature was found |
| `GetRealReadyCountPlusRewardCount()` | ready **plus** arrived: the number a bubble is drawn from, not the one a dispatch is capped by |

So the collect is one press for the fleet (`collect_arrived_trucks`), made only when the
scan says something is home — a batch of nothing is a frame the server is asked to think
about for no reason.

**The next turn is booked, not polled.** The recipe reads the nearest `arriveTs` off the
client, hands it back as `next_run_in` (docs/dsl.md) and the schedule plays the errand
again a minute after the landing — one deferred turn per arrival. It books that turn even
when the day's allowance is spent, because the load still has to be taken; and it books
nothing at all when no truck is on the road, so the row's own period stands.

**«По одному за раз»** (`one_at_a_time`) caps the departure selection at one. The rows are
already ranked by rarity, so the truck that goes is the best one standing, and the escort
is the window's own first formation — the strongest the person has arranged. Four trucks
ticked at once spend four formations, including the weak ones, which is what the operator
asked to be able to avoid.

## Robbing somebody else's truck (#2591)

The other tab of the same event. `train.list` fills a board of trucks other players have
on the road; `train.attack` robs one; the game caps it at `MAX_DAILY_LOOT_COUNT` = 4 a
day and counts what has gone with `LWMyStationDataManager:GetRobCount()` (the field
behind it is `todayRobCount`). `IsTruckRobCountUsedUp()` is the same fact as a boolean,
and `GET_MAX_LOOT_PER_TRUCK` = 2 is how many times ONE truck may be robbed in total, by
anybody.

### The board

`UIManager.Instance:OpenWindow(UIWindowNames.UILWTrainList)` and then
`window.View:GetTrainsByTab(2)` — tab 1 is our own fleet, tab 2 the targets. Fifteen rows
at a time, refilled from the server by `train.list`. What a row carries, of the fields the
rule uses:

| field | what it is |
|---|---|
| `uuid` | the truck. **A STRING**, and `%d` will format it while `PutLong` refuses it |
| `serverId` | the warzone it belongs to — one of `matchServers`, ours plus three |
| `ownerId` / `ownerLv` / `name` | the player |
| `quality` | 1..5 for N..UR, and **10 with `isSpecialURQuality` for the Reindeer Sleigh Ride** |
| `power` | the escort guarding it, server-side, the number the rule is judged on |
| `completeness` | how far along its road it is |
| `maxLootPerTrain` | 3 |

### The frame, and the four dead ends in front of it

`SFSNetwork.SendMessage(MsgDefines.AttackTrain, uuid, heroInfo, serverId, 0, squadNo)`,
where `heroInfo` is an `SFSArray` of one `SFSObject` per hero — `PutLong('heroUuid', …)`
and `PutInt('index', …)`. Proven live: `GetRobCount()` 0 → 1, then 2, then 3.

The four fields were read off `Net.Msgs.Railway.AttackTrainMessage:OnCreate` with a
recording proxy in place of `sfsObj` (the trick this file's neighbour
`alliance-train.md` describes): `PutLong uuid` from argument 1, `PutSFSArray heroInfo`
from 2, `PutInt serverId` from 3 and `PutInt squadNo` from 5. Argument 4 is written
nowhere and goes out as 0.

Everything that looks like a shortcut to that frame is not one, and each cost an hour:

1. **`LWMyStationDataManager:TryAttackTrain(trainData, n, formation)` throws** —
   `SFSDataSerializer.lua:43: bad argument #2 to 'pack' (number expected, got table)`.
   The hook on `SendMessage` shows it forwarding five arguments with a TABLE where the
   uuid goes, so whatever the client calls it with, it is not a truck's own data table.
2. **`FormationToSFSObject(formation)` is not the `heroInfo`.** It hands back an
   `SFSArray` of 33 entries whose `heroUuid` sits under the LONG tag holding a STRING,
   and the packer refuses it with the same message. An EMPTY `SFSArray.New()` packs and
   sends, which is how the two were told apart.
3. **`trainData.uuid` is a string** (above). `pick.uuid + 0` is the fix, and without it
   the failure reads `…got string` — indistinguishable from a server refusal if the
   error is swallowed.
4. **`GetRobFormation()` / `GetAttackFormationByIndex(i)`** are the right formations —
   `f.heroes` is `heroUuid -> slot`, which is exactly what the array wants — but they
   have to be walked by hand.

### Our own strength, which the client will not compute

`ArmyFormationDataManager:GetFormationPowerByUuid` answers **0** for every formation on
the account, by uuid or by index, and there is no `*BattlePower` method anywhere in
`DataCenter` (31 managers carry a `Power` method; none of them prices a squad). Two
readings do exist:

* **the server's own**, off one of OUR trucks while it is on the road:
  `GetMyTrainList()[i].power` against `squadNo`, in the same units as a target's `power`.
  Measured: 60 077 576 for squad 1;
* **the heroes added up** — `HeroDataManager:GetHeroByUuid(uuid).power` over
  `f.heroes`. Measured: 39 797 903 for the same squad, so about two thirds of the
  server's number. Lower, which makes a rule judged on it stricter rather than looser.

`lua_actions.truck_rob_scan` prefers the first and falls back to the second, and parks
which one answered so the recipe can say it.

### What is still not measured

**Whether a LOST robbery moves the daily counter.** Every robbery run so far has been
won, so the recipe's judgement — the counter moved, therefore it worked — has only been
seen from the winning side. `TruckStateType{Safe=1, Robed=2, DefendSuccess=3}` says the
game knows the difference; `train.record.list` with `type=2` came back with no rows for
the robber, so the record book is not obviously where to read it. Finding out costs a
deliberate defeat, which costs troops, so it is a question for the person rather than a
probe to run.

### Asking for a new board

`SFSNetwork.SendMessage('train.list', true)` — what the window's own refresh button sends,
and it really does replace the rows rather than re-sort them: measured live, all fifteen
`uuid`s came back different, with different owners, rarities and escorts. Re-opening
`UILWTrainList` does the same thing and costs the six seconds the window takes, so the
recipe sends the message on its own (`lua_actions.truck_rob_refresh`). One round trip is
about four seconds.

That is the «rotation» the errand counts: a rotation is one board that came back with
nothing the rule allows. After `rotations` of them IN A ROW — a robbery resets the count —
the run books its next turn `pause_min` minutes out with `next_run_in` and stops, rather
than sleeping: a recipe waiting a quarter of an hour would hold the game claim for the
whole of it while rallies, timers and the person's own buttons queued behind it.

Counters, measured on the live account: `GetRobCount()` 0..4, `MAX_DAILY_LOOT_COUNT` 4,
and the day turns over at `UITimeManager:GetInstance():GetTomorrowZero()` — the game's own
stamp, never this machine's clock.

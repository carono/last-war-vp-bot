# The Alliance Train: the conductor, the carriages and the fare (#1993)

The trade train that stands at the alliance station. A train arrives with nobody driving
it; an R4 or R5 appoints a **conductor** and the queue opens at that moment; the rest of
the alliance take a seat in one of the carriages, and the train leaves on a clock.

**Not** the trade trucks — those are the same `LWRailway` tree and a different half of it
(`truck-dispatch.md`, `DataCenter.LWMyStationDataManager`). Two things wearing the word
«train»: the trucks a commander dispatches, and this, the alliance's shared train.

Everything below was read off a live client on 2026-08-26 with a train actually standing
at the platform. Every identifier in the examples is invented (`CLAUDE.md`).

---

## Where the state lives

`DataCenter.LWAllyStationDataManager` — the module
`DataCenter.LWRailway.Station.LWAllyStationDataManager`.

| call | what it answers |
|---|---|
| `IsTrainActivityOpen()` | the event is running on this warzone |
| `IsTrainClosed()` / `IsTrainFunctionLock()` | …and the station is not shut or locked |
| `GetPlatform(1)` | the platform row — the whole of what a passenger needs |
| `GetTrainByPlatformId(1)` | the train standing on it |
| `AlreadyThumbsUp()` | has the fare been paid for this train, by any hand |
| `GetThanksItemMin()` / `GetThanksItemMax()` | **1** and **3** — the fare's floor and ceiling |
| `RandomThanksLangIndex()` | one of the game's canned thank-you phrases |
| `TryGetAllyStationData()` | ask the server for all of it |

The platform row (`DataCenter.LWRailway.Station.PlatformData`, which also has a
`MeInQueue()` of its own):

```
platformId=1  state=2  trainUuid=<id>  readyEndTime=<server ms>
meInQueue=false  lineUp={…}  vipInvite={…}
```

`state` is the global `TrainPlatformState`:

| value | name | meaning |
|---|---|---|
| 0 | `NoTrain` | nothing at the platform |
| 1 | `TrainNoDriver` | a train, **no conductor appointed yet** — the queue is shut |
| 2 | `TrainWithDriver` | **a conductor is appointed** — boarding is open |
| 3 | `TrainWithPassenger` | passengers are aboard |

`lineUp` is the queue, **keyed by the carriage's 1-based position** and holding one entry
per queued player. The locomotive is position 1 and is the conductor's own, so the keys a
passenger sees are 2…5 — i.e. **wire carriage 1…4 is `lineUp[2]`…`lineUp[5]`**. That was
established by boarding: a `lineUp` sent with `carriageId = 1` made `lineUp[2]` grow by
one. Live numbers: 4 boardable carriages, 7 seats each, 57 players queued for 28 seats,
so a seat is a lottery and the queue is not a booking.

`readyEndTime` is server milliseconds; judge it against
`UITimeManager.Instance:GetServerTime()` and never the PC's clock (`game-clock.md`).

## The wire

Resolved off `MsgDefines` on the live client:

| name | command | what it is |
|---|---|---|
| `AllianceTrainInfo` | `alliance.train.info` | ask for the station |
| `AllianceTrainAssign` | `alliance.train.assign` | an R4/R5 appointing the conductor |
| `AllianceTrainLineUp` | `alliance.train.lineUp` | **take a seat in a carriage** |
| `AllianceTrainThumbsUp` | `alliance.train.thumbs.up` | **pay the fare** — a like, or contracts |
| `AllianceTrainRefresh` | `alliance.train.refresh` | the conductor refreshing the cargo |
| `PushAlTrainPlatformCreate` / `Update` | `push.al.train.platform.create` / `.update` | **the platform's state changed** |
| `PushAllianceTrainStartInfo` | `push.alliance.train.start.info` | the train's own start |

The two that matter are built by their own message classes, and this is what they put on
the wire (read by handing the class a recording stand-in for its SFS object):

```
alliance.train.lineUp     PutInt trainPlatformId=1   PutInt carriageId=<the one argument>
alliance.train.thumbs.up  PutInt platformId  PutInt num  PutInt index
```

So both are one line of Lua and no window at all:

```lua
SFSNetwork.SendMessage(MsgDefines.AllianceTrainLineUp, carriage)      -- 1..4
SFSNetwork.SendMessage(MsgDefines.AllianceTrainThumbsUp, 1, num, idx) -- num 0..3
```

`num` is the fare and `index` is which canned phrase goes with it. **`num = 0` is the
free «like»**; 1…3 are Trade Contracts, the game's own floor and ceiling. Proven live:
`meInQueue` went `false → true` on the first, `AlreadyThumbsUp()` went `false → true` on
the second, both with no UI open.

**One fare per train.** Once `AlreadyThumbsUp()` is true the server refuses a second
offer, so the amount is decided ONCE — which is why the recipe works out what it can
afford before it sends anything.

## The «ticket»

The fare is paid in **Trade Contracts**, item id **1520001** — the same item that
refreshes a trade truck, which is why the player calls them «билеты на грузовики». The
bag holds them in `DataCenter.ItemData.ItemInfos` (`inventory.md`), summed per stack.

**When the bag is short the game offers to buy the missing ones for diamonds.** The
operator's answer to whether the bot may take that offer is a SWITCH beside the number —
«докупать, если не хватает» — off by default, and capped by the number so a purchase can
never go one contract past what was allowed. Every purchase names itself in the log with
what it cost: an allowed spend is still a spend, and a silent one is not allowed even
with the box ticked (`CLAUDE.md`).

**The purchase itself is NOT confirmed yet, and the recipe does not guess it.** The
candidate is `alliance.train.buy` — it carries `trainPlatformId` and nothing else, and
the ally manager has `BuyCount()` and `OnAllianceTrainBuySuccess` beside it — but
`UITrainBuy` also serves the conductor's **Mega Express contract**, which is a far larger
spend, and the two cannot be told apart from the message shape alone. Sending it blind to
find out would be spending the player's money to run the experiment. So with the switch on
and a short bag the recipe says so and pays what the bag holds; one live confirmation
(a train where the bag is genuinely short, or a conductor's screen to compare against)
turns it into the purchase.

## What is NOT this

* `alliance.train.buy` (`UITrainBuy`) is the **conductor's** side — the Mega Express
  contract that calls a richer train. It carries `trainPlatformId` and nothing else, and
  is no part of boarding.
* `FlowerTrain*` is a different event entirely.
* `season.*.zone.train.*` is the warzone train, also unrelated.

## What the panel does with it

| piece | where |
|---|---|
| the reading | `src/lastwar_bot/actions/read_alliance_train.md` → one `key=value` line |
| the ability | `src/lastwar_bot/actions/board_alliance_train.md` — `ARGS carriage`, `tickets` |
| the ear | the `alliance_train_board` trigger on `push.al.train.platform` (`panel/triggers.py`) |
| the card | «События» → «Поезд Альянса», web screen (`panel/tabs/events/`) |

The two knobs — which carriage, and what fare — are read LIVE at fire time through
`Schedule.register_args`, so the card and the standing order can never disagree.

## Is the 1..3 fare the SERVER's cap or only the client's form? — NOT ANSWERED YET

The operator asked for this probe in these words: «В рамках эксперимента попробуй
заплатить 5 билетов, не знаю, даст ли игра, интерфейс не позволяет».

**It has not been run, and this section exists so that nobody re-derives it.** The probe
lives as `actions/dev/_t1993_fare5.md`, which is a git-ignored tree — so the two lines
that matter are written out here instead, and rebuilding it is a copy rather than a
re-think:

```lua
-- the send, past the client's own 1..3 form. ONCE.
local M = DataCenter.LWAllyStationDataManager
local idx = 0; pcall(function() idx = (M:RandomThanksLangIndex()) + 0 end)
SFSNetwork.SendMessage(MsgDefines.AllianceTrainThumbsUp, 1, 5, idx)

-- the judge, read before and after: the bag, not the reply.
local n = 0
for _, s in pairs(DataCenter.ItemData.ItemInfos or {}) do
  if type(s) == 'table' and tostring(s.itemId) == '1520001' then
    local c = 0; pcall(function() c = s.count + 0 end); n = n + c
  end
end
```

What it does, and why each part is there:

* **One send, never a loop.** `AllianceTrainThumbsUp(1, 5, idx)` once, past the client's
  own 1..3 form. What is wanted is the server's answer, not pressure on it.
* **The judge is the BAG, not the reply** — contracts counted before and after. A silent
  clamp to three shows up as a bag three lighter, an acceptance as five, a refusal as
  none at all. The same rule the robbery counters go by: only the reading moves.
* **A wire watch on `SFSNetwork.HandleMessage`** keeps the server's own words for any
  command carrying `train` or `error`, so a refusal is recorded verbatim rather than
  paraphrased, and the hook is put back at the end.
* **Three gates before anything is sent:** the fare on this train must be UNPAID
  (`AlreadyThumbsUp()` is `0` — one offer per train, so on a paid train the probe would
  only be measuring that rule), a conductor must be at the platform, and **the bag must
  hold at least five**. The last one is not caution about the fare — it is about
  DIAMONDS: five against a short bag is exactly the case where the game offers to make
  the difference up in diamonds, and the operator's permission was explicit that it
  covers their contracts and not their money.

**Why it did not run on 2026-08-26**, both reasons recorded because either is enough to
block it:

1. **The fare on the standing train was already paid** — the free like had gone out
   earlier the same session while the boarding was being proven, so `AlreadyThumbsUp()`
   read `1`. A second offer is refused by the server, and that refusal says nothing about
   the number five.
2. **The Lua link died** — `enum: gated hijack returned None`, then
   `LeaseLost: lease lost — it expired or was taken by nobody`, with the client online but
   silent for ~3 400 s. Every read and every send stopped landing. Eight copies of
   `panel.headless --profile default` were alive at the time and contending for the same
   client, which is the shape that error takes.

So the answer is **unknown**, and the interface keeps the operator's 0..3 either way —
that was his instruction: «Сам предел пока оставь 0..3, как он сказал». If the probe ever
comes back «five accepted», the ceiling in `panel/tabs/events/model.py`
(`TRAIN_TICKETS`) and the field's `max` are the two places that would change, and it is
his call whether they should.

## Open ends

* **The diamond purchase, above** — the one thing between the «докупать» switch and its
  job. It needs a live train and a bag short of the fare; on the account this was read
  from the bag held 92 contracts, so the case never arose.
* Whether a carriage further down the train is worth more than the one nearest the
  locomotive is not known — the reward table (`carriages[].trainGoods`) is readable and
  has not been compared.
* The VIP seats (`vipInvite`, `alliance.train.invite.vip`, `.accept.vip`) are the
  conductor's invitations — Special Guest and Guardian Defender, pick one. Read, not
  acted on.
* The conductor's own half — appointing, refreshing the cargo, the free refreshes,
  saving a GoldTrack — is untouched.

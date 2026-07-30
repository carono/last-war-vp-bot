# City visitor — recruit a survivor ("Собрать выжившего")

How a survivor knocking at the base is accepted with one message, where the visitor
queue lives, and how a recruitable survivor is told apart from the other visitors.

- Recipe: `actions/recruit_survivors.md` — one line, `TAP recruit_survivor xall`.
- Button: `tools/lib/game_buttons.py` (`recruit_survivor`); the Lua itself is
  `tools/lib/lua_actions.py` (`visitor_recruit_survivor`, `visitor_recruit_pending`).
- Source capture: `results/traces/20260729_145441_Собрать_выжившего_trace.log`
  (function trace of the player tapping the survivor and its agree button).
  `results/` is git-ignored, so this note is the durable record.

## The wire

The traffic sniffer caught nothing useful — the window closed on keepalives — but the
**function trace** holds the send whole. The player tapped the survivor, the
`UIWorkerDetailRecruit` window opened, and the agree button fired one message:

```
XSCALL UIButton.GetClickSound <- …, agreeBtn …
XSCALL SFSNetwork.SendMessage <- visitor.operate, 1397117535769569141, 1
XSCALL SFSObject.PutLong      <- …, uid, 1397117535769569141
XSCALL SFSObject.PutInt       <- …, operate, 1
```

i.e.

```
--> visitor.operate  {uid = <visitor uid>, operate = 1}
```

`MsgDefines.VisitorOperateMessage == 'visitor.operate'`. The SFSObject is exactly two
fields — a `Long uid` and an `Int operate` — so the send needs no window open once the
uid is known. `operate = 1` is accept/recruit (the button was `agreeBtn`); no other
`operate` value was observed, and no `VisitorOperate*` enum exists in the VM, so a
decline value (if any) is unconfirmed.

## The queue and the discriminator

Visitors line up in `DataCenter.CityVisitorManager`. A new arrival pushes
`push.user.visitor.change`. A queue is read with

```lua
DataCenter.CityVisitorManager:GetQueueAllVisitorData(q)   -- q = 1 or 2; 0 and 3+ raise
```

which returns a list of **wrappers**, each `{data = <visitor>, model = <view>}` — the
recruitable fields live one level in, on `.data`, not on the wrapper. `GetFristVisitorData()`
returns the front `.data` directly. A visitor's `.data` carries:

```
uid          1397117535698265960     -- what visitor.operate sends
eventType    2                       -- the kind; indexes the global VisitorType enum
visitorId    3                       -- NOT the kind: a per-arrival counter (see below)
eventId      2006                    -- the City_Visitor config row
appearCfgId  3002
name         440401
modelPath    …/City/Worker/A_Hero_nvzhuboqban01.prefab
startTime    1785295387399
line         <the config row, lazily resolved>
```

`eventType` is the kind, and it indexes the global `VisitorType` enum:

```
MERCHANT=1  GIFT=2  RECRUITMENT=3  BATTLE=4  WORKER_LOTTERY=5  NOTIFY=6  OPEN_PANEL=7
ALLIANCE_INVITE_MOVE_CITY=8  DOMINATOR=9  SeasonDayGift=10  VisitorActivity=11
ALLIANCE_INVITE=12  DOMINATOR_COCKATRICE=13  AllianceCongratulation=14  AD_REMINDER=15
SKY_BATTLE=16  PLANE_FEATURE=17  S0_ALLIANCE_BOSS=18  SURVIVOR_PACK_GiFT=19
ProtectCoverVisitor=20  SystemGift=30
```

The client keys on the same field: `AddVisitor` compares `eventType` against
`VisitorType.AllianceCongratulation`, and `GetReceiveAllGiftUidList(<VisitorType>, …)`
filters the queue on `data.eventType == <that type>`.

### `visitorId` is not the kind — the bug this note used to carry

This note first read the kind off `data.visitorId`, on the strength of one trace where a
survivor happened to show `visitorId 3` next to `RECRUITMENT = 3`. It is a coincidence:
`visitorId` is a **per-arrival counter**. A live queue read (task #1122) settled it —
four visitors numbered 3, 4, 5, 6, every one of them `eventType == 2` (GIFT):

```
i=1 uid=…240 visitorId=3 eventId=2003 eventType=2   isArrival=true
i=2 uid=…246 visitorId=4 eventId=2005 eventType=2   isArrival=true
i=3 uid=…379 visitorId=5 eventId=2001 eventType=2   isArrival=true
i=4 uid=…974 visitorId=6 eventId=2005 eventType=2   isArrival=nil   -- not spawned yet
```

So the old `visitorId == VisitorType.X` test was wrong both ways: the gift press matched
nothing at all (no queued visitor is ever numbered 2), and the recruit press fired at
whoever was the third visitor of the session, whatever kind it was. Both primitives now
test `eventType`.

### Readiness — the visitor has to have walked up

A queue entry exists before the visitor is spawned: entry `i=4` above had a bare model,
no `isArrival`. The client skips those (`GetReceiveAllGiftUidList` yields 3, not 4, on
that queue), so the gate is `model.isArrival and not model.isFinish` on top of the kind.
Both counts agreed at 3, which is how the readiness rule was checked against the
client's own list rather than guessed.

### There are TWO queues, and reading one is reading half the visitors

`GetQueueAllVisitorData` takes a queue index, and the manager keeps two of them:

```
GetQueueVisitorCount(0) -> raises (CityVisitorManager.lua:733, index a nil field)
GetQueueVisitorCount(1) -> 1        -- the gift visitor, not arrived yet
GetQueueVisitorCount(2) -> 1        -- the waiting survivor, arrived
GetQueueVisitorCount(3..8) -> raise
```

Live (task #1122, second pass): the gift visitors sat in **queue 1** and the
RECRUITMENT one in **queue 2**, with its model `CallerUnit<uid>` active in the scene —
the "?" figure walking around the base. So `recruit_survivors` was reading queue 1 only
and could not see the survivor at all: the kind test was right by then, the queue index
was the thing left hardcoded. Both primitives now scan queue 1 and queue 2, each in its
own pcall, and match on the kind wherever it turns up.

The mapping of kind → queue is not exposed: `VisitorTypeToQueue` is a module-local of
`CityVisitorManager.lua` (not on the instance) and `Const.CallerQueueList` is not a
global, so which queue a kind lands in cannot be read out of the VM. Scanning both
sidesteps the question — and the client itself takes the queue as a parameter beside the
kind, `GetReceiveAllGiftUidList(<eventType>, <queue>, <max>)`, so a kind is not tied to
one queue by construction anyway.

### …and readiness only exists in the city scene

The models are a city-scene thing, from the manager's own code:

```
BeforeReleaseCity  -> DeleteAllVisitorModel, ReleaseData     -- leaving the base drops them
OnEnterCity        -> GetIsInCity, StartCreateVisitor        -- entering starts them again
StartCreateVisitorByType -> GetIsInCity … TimerManager.DelayInvoke(delay)
```

So `model.isArrival` can only be true while the base is on screen, and even there the
spawn runs on a delay of its own. Both presses are therefore base-screen actions: run
from the world map they are a quiet no-op (nothing is lost — the queue is server-side and
the visitors keep waiting). Switching to the city and pressing straight away would not
help either; the models arrive on that timer, not on the scene change.

The queue *data* thins out too, not just the models — `ReleaseData` runs on the way out.
Read from the world map, the manager showed `queue=1 total=0`; back in the city the same
queue read `queue=1 total=1` and the survivor's queue-2 entry was there. So a visitor
reading taken outside the base is not just short of models, it is not to be trusted at
all — which is the other reason a run from the world map cannot be made to work by
loosening the readiness test.

Note `HasWorkerToRecuit()` reads **nil** even with a RECRUITMENT visitor queued — it is
a narrower check (a free worker slot / lottery worker), not "is a survivor waiting", so
it is the wrong gate. Count the queue by `eventType` instead.

## Acceptance

Live, driving the warm daemon:

```
before: pending=1  total=5
        --> visitor.operate  {uid=…, operate=1}
after:  pending=0  total=4
```

A visitor left the queue and the total dropped, both server-side (the removal came back
on `push.user.visitor.change`) — a reply applier could not decrement the server's visitor
count, and the call was a bare `SFSNetwork.SendMessage`, so this is the real wire action,
not a local state edit. What it did **not** prove is that the visitor was a RECRUITMENT
one: the pick was then `visitorId == 3`, i.e. the third arrival of the session.

Re-run on 2026-07-30 with a survivor actually knocking, after the queue scan landed:

```
before: recruit=1  total=1   -- q1: gift, not arrived · q2: survivor, arrived
        --> visitor.operate  {uid = …974, operate = 1}
after:  recruit=0  total=0   -- q2 empty, q1 untouched
```

Three independent readings, not one: the count, the server's visitor total, and the
scene — `CallerUnit…974` was gone and so was the "?" figure walking the base in the
screenshot. The gift visitor in queue 1 was left alone, as it should be: not its kind,
and not arrived either.

## Gift-bearing visitors — same command, kind GIFT (trace 20260729_151712)

A survivor can also arrive carrying gifts («Собрать подарки выжившего»). This is the
same queue mechanic — only the kind differs: `data.eventType == VisitorType.GIFT` (2)
instead of RECRUITMENT (3). Tapping the visitor and collecting the gift sends the
identical one-shot message, captured whole in trace `20260729_151712`:

```
XSCALL SFSNetwork.SendMessage <- visitor.operate, 1397117535811512114, 1
XSCALL SFSObject.PutLong      <- uid, 1397117535811512114
XSCALL SFSObject.PutInt       <- operate, 1
XSCALL UIUtil.DoFly           <- 7, 1, .../ItemIcons/icon_coinbox, …   -- reward flew
XSCALL UIManager.DestroyWindow <- UICityVisitor                        -- window closed
```

So `operate = 1` means "collect the gift" here just as it means "accept" for a recruit;
after the send the client flew a coin-box reward (reward type 7) and destroyed the
`UICityVisitor` window. The body is still exactly `{uid, operate}`, so the collect needs
no window open. Primitives `visitor_gift_pending` / `visitor_gift_collect`
(`tools/lib/lua_actions.py`), button `collect_visitor_gifts`, recipe
`src/lastwar_bot/actions/collect_visitor_gifts.md`.

### Acceptance (2026-07-30, task #1122)

The companion traffic capture for that trace was empty (0 B), so the send stayed
trace-only until the `eventType` fix made the press fire at all. Then, driving the recipe
`collect_visitor_gifts` (`TAP … xall`) against a queue of four gift visitors:

```
before: gift=3  queue=4  total=3      -- the fourth had not walked up yet
        --> visitor.operate  {uid, 1}   x3
after:  gift=0  queue=1  total=0
```

Three sends, three visitors gone, and the not-yet-arrived one left alone — the removals
came back from the server on `push.user.visitor.change`, so this is the wire action. The
count the recipe reads is the same gate the send applies, which is why `xall` drains the
queue exactly and stops.

### The client's own batch list

`GetReceiveAllGiftUidList(VisitorType.GIFT, <queue>, <max>)` returns the uids the client
itself considers claimable right now — it filters on `data.eventType`, skips a visitor
with a `dialog_type`, one already `isFinish`, and one `IsGiftUidReceiving`. On the queue
above it answered 3, the same as the primitive's count, which is what the readiness gate
was checked against. It belongs to the season "claim all" feature (`CheckUnlockReceiveAll`,
`GetBatchAllMaxCount`, `MarkGiftUidsReceiving`) — the per-visitor collect here does not
depend on that unlock, so the primitives read the queue themselves.

## Related visitor commands (seen in MsgDefines, not exercised here)

```
visitor.operate                 -- accept/operate on a visitor (this note)
finish.visitor                  -- FinishVisitor
visitor.receive.reward          -- VisitorReceiveRewardMessage
visitor.fresh                   -- VisitorFreshMessage (refresh the queue)
visitor.season.choose           -- VisitorSeasonChoose
survivor.visitor.receive.free / .score / .bubble / .info   -- the survivor-rating mini-game
push.user.visitor.change        -- queue changed (arrival / removal)
push.activity.visitor           -- an activity visitor appeared
push.alliance.congratulation.receive.visitor
```

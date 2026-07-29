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
`push.user.visitor.change`. The queue is read with

```lua
DataCenter.CityVisitorManager:GetQueueAllVisitorData(1)   -- arg 1 = the on-base queue
```

which returns a list of **wrappers**, each `{data = <visitor>, model = <view>}` — the
recruitable fields live one level in, on `.data`, not on the wrapper. `GetFristVisitorData()`
returns the front `.data` directly. A visitor's `.data` carries:

```
uid          1397117535698265960     -- what visitor.operate sends
visitorId    3                       -- the kind; indexes the global VisitorType enum
eventId      2006
eventType    2
appearCfgId  3002
name         440401
modelPath    …/City/Worker/A_Hero_nvzhuboqban01.prefab
startTime    1785295387399
```

`visitorId` is the kind, and it indexes the global `VisitorType` enum:

```
MERCHANT=1  GIFT=2  RECRUITMENT=3  BATTLE=4  WORKER_LOTTERY=5  NOTIFY=6  OPEN_PANEL=7
ALLIANCE_INVITE_MOVE_CITY=8  SeasonDayGift=10  DOMINATOR_COCKATRICE=13
AllianceCongratulation=14  AD_REMINDER=15  PLANE_FEATURE=17  S0_ALLIANCE_BOSS=18
SURVIVOR_PACK_GiFT=19  ProtectCoverVisitor=20  SKY_BATTLE=1
```

A waiting survivor is `visitorId == VisitorType.RECRUITMENT` (3). `visitor_recruit_pending()`
counts those; `visitor_recruit_survivor()` sends `visitor.operate {uid, 1}` for the
first one and is gated on the count so a quiet queue costs no round trip. Other
`visitorId`s ride the same `visitor.operate` message but are a different feature
(merchant, gift, alliance invite …) and are left alone.

Note `HasWorkerToRecuit()` reads **nil** even with a RECRUITMENT visitor queued — it is
a narrower check (a free worker slot / lottery worker), not "is a survivor waiting", so
it is the wrong gate. Count the queue by `visitorId` instead.

## Acceptance

Live, driving the warm daemon:

```
before: pending=1  total=5
        --> visitor.operate  {uid=…, operate=1}
after:  pending=0  total=4
```

The RECRUITMENT visitor left the queue and the total dropped, both server-side (the
removal came back on `push.user.visitor.change`) — a reply applier could not decrement
the server's visitor count, and the call was a bare `SFSNetwork.SendMessage`, so this is
the real wire action, not a local state edit.

## Gift-bearing visitors — same command, kind GIFT (trace 20260729_151712)

A survivor can also arrive carrying gifts («Собрать подарки выжившего»). This is the
same queue mechanic — only the kind differs: `data.visitorId == VisitorType.GIFT` (2)
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

The companion traffic capture for this run was empty (0 B), so the wire action is
reconstructed from the trace alone — not yet confirmed by a live count 1→0 the way the
recruit path was. Marked 🟡 in `docs/farming.md` until a live run confirms it.

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

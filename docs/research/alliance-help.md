# Alliance help ("Помочь всем")

How the alliance help list answers every pending request in one press, and why the
obvious data-manager call is a decoy that silently helps nobody.

- Recipe: `actions/help_ally.md` — one line, `TAP help_ally_all xall`.
- Button: `tools/lib/game_buttons.py` (`help_ally_all`); the Lua itself is
  `tools/lib/lua_actions.py` (`alliance_help_send`, `alliance_help_all`,
  `alliance_help_pending` / `alliance_help_red_point` / `alliance_help_waiting`).
- Standing order: the panel's «Авто-помощь союзникам» checkbox →
  `tools/alliance_help_monitor.py` + `tools/lib/alliance_help.py`.
- Source capture: `results/traces/20260728_232122_помощь_союзнику_trace.log` (function
  trace of the player pressing the real button). `results/` is git-ignored, so this
  note is the durable record.

## Follow-up captures carry nothing new

Two later sessions relabeled the same feature — `20260728_162518_Помощь_союзнику`
(§8.11 of `docs/skills/sniff.md`) and `20260729_145629_Помощь_союзникам` — and both
came back with **no `al.help.all` on the wire**: the traffic file holds only
keepalives plus downstream `push.lw.alliance.alert.info.remove` churn (a member's
march ending), a `push.al.sign` count bump and a `push.all.notice` ministry
appointment, and the trace is UI churn (an already-collected alliance gift, the
notice popup). Every command there is already in `docs/research/protocol.md`; the
`al.help.all` press is only visible when a request is actually pending and answered,
as in the Acceptance capture below. There is no new primitive or scenario to write —
the feature is fully covered by `help_ally_all` / `alliance_help_all` / `help_ally.md`.
Do not re-record "help allies": recapture only with a request pending and confirm the
`--> al.help.all` up-frame.

### "Always-visible button, not the separate window" (task #1111)

A follow-up worried the recipe only helps "from a separate window" because the
`20260729_145629` operator pressed the button inside the alliance-help popup. It does
not: the bot never touches a window or a button. The always-visible main-UI help
bubble and the window's "Help All" button funnel into the **same** controller method —
`UI.UILWAlliance.UILWAlHelp.Controller.UILWAlHelpCtrl:OnClickHelpAll`, whose only
network line is `SFSNetwork.SendMessage(MsgDefines.AlHelpAll, …)` (constant dump live:
`… SFSNetwork | SendMessage | MsgDefines | AlHelpAll | … can_help | helpList | curTime`).
`alliance_help_all()` sends that one `al.help.all` directly, so no on-screen button of
either kind has to exist.

The always-visible element itself is the bottom-bar bubble `HelpBubbleTip` (a live
`GameObject.FindObjectsOfType` scan found it active on the main screen with no window
open), hosted by `UI.LWMainUI.Component.UIMainBottom.MainAllianceBubbles`. And there is
**exactly one** alliance help-all up-message class in the client —
`Net.Msgs.Alliance.AlHelpAllMessage` (the only other `AlHelp*` classes are the inbound
`PushAlHelpNewMessage` / `PushAlHelpUpdateMessage`). So the bubble and the window button
have no alternative command to send: both are `al.help.all`, which the bot already
emits headless. There is no separate "HUD button" primitive to add.

Verified live with the alliance-help window **never opened this session** (cold read
via `tools/lib/lua_eval.py`):

```
DataCenter.AllianceHelpDataManager ~= nil   -> true
#GetAllianceHelpList()                       -> 6      # populated, no window ever opened
helpable (isSelf == false) / self            -> 0 / 6  # all 6 were my own requests
```

The list is readable cold, with no window ever opened, which is what mattered for the
press. The `20260729_145629` trace carried no `al.help.all` precisely because every
entry was `isSelf` (0 helpable) — the same gate the bot honours before sending. Nothing
to rework.

> **Correction (task #1113).** An earlier version of this note read that sentence as
> "the list is kept current by the `push.al.help.new` handler". It is not: that handler
> only bumps the red-point counter and never touches the list — see "Answering it
> without a human" below, which is where it matters. The cold read above proves the
> list survives without a window, not that a push fills it.

## The decoy

The first version of this recipe pressed

```lua
DataCenter.AllianceHelpDataManager:OnHelpAll()
```

It looked right — `pcall` succeeded, the pending request disappeared from the list,
`GetHelpNum()` dropped to 0 — and it helped nobody. Nothing left the client.

`OnHelpAll` is the **reply applier**, not the action. Dumping its constant table
(§ "Reading a Lua function without its source" below) gives its entire body:

```
Mgr.OnHelpAll :: otherHelpInfoList | SetHelpNum | self
```

i.e. `function M:OnHelpAll(otherHelpInfoList) self.otherHelpInfoList = … ;
self:SetHelpNum(…) end`. No `SFSNetwork`, no `MsgDefines` — it *cannot* send. Its only
caller is `AlHelpAllMessage:HandleMessage`, whose constants name it directly:

```
AlHelpAll.HandleMessage :: errorCode | UIUtil | ShowTipsId | DataCenter |
  AllianceHelpDataManager | otherHelpInfoList | OnHelpAll | accPoint |
  AllianceBaseDataManager | UpdateAccPoint | EventManager | GetInstance | Broadcast |
  EventId | AllianceHelpSever | UpdateAllianceHelpNum
```

Calling it by hand is calling the server's answer without ever asking the question —
which is exactly why the symptom was "the request vanishes but no help is sent". The
local list is the *aggregate* signal warned about in `docs/skills/sniff.md` §8.7a-3: it
looks identical for a real help and for a no-op. Only the wire tells them apart.

## The press

`UILWAlHelpCtrl:OnClickHelpAll` — its constants, in order:

```
view | helpList | table | walk | UITimeManager | GetInstance | GetServerTime |
SFSNetwork | SendMessage | MsgDefines | AlHelpAll | math | floor | UIUtil | ShowTipsId
locals: self | helpAllBtnPos | toPos | can_help | helpList | curTime
```

which reads back as: walk the view's help list, set `can_help` when an entry is not
mine, and then either

```lua
SFSNetwork.SendMessage(MsgDefines.AlHelpAll,   -- MsgDefines.AlHelpAll == 'al.help.all'
                       curTime, helpAllBtnPos, toPos, nil, true)
```

or `UIUtil.ShowTipsId(390170)` when there is nobody to help.

**The message is one field wide.** `AlHelpAllMessage:OnCreate` constants:

```
sfsObj | PutLong | cmdBaseTime | self | cmdBaseTime | helpBtnPos | toPos |
isOnlyDisperse | isOnlyShowDiff | base | _helpBtnPos | _flyToPos | _isOnlyDisperse |
_isOnlyShowDiff
```

Only `cmdBaseTime` is put into the SFSObject. `helpBtnPos` / `toPos` /
`isOnlyDisperse` / `isOnlyShowDiff` are stashed on the message as `_…` fields and used
by `HandleMessage` to fly the reward icon from the button to the resource bar. They are
pure presentation — so **the send needs no window open**, and `Vector3.zero` twice
stands in for the on-screen button position:

```lua
local Z = CS.UnityEngine.Vector3.zero
SFSNetwork.SendMessage(MsgDefines.AlHelpAll,
    math.floor(UITimeManager:GetInstance():GetServerTime()), Z, Z, nil, true)
```

## The gate

The controller only sends when at least one list entry has `isSelf == false`; my own
open requests sit in the same `GetAllianceHelpList()` and are not helpable. That gate is
mirrored in `alliance_help_pending()`, so the bot never fires a press the chunk then
declines to make and never spends a round trip on a quiet alliance (the `#1087` rule: a
speculative *network* call is not a no-op, it is a rejection with a toast).

`GetHelpNum()` is a different thing — a **server-pushed red-point number**, not the
length of the helpable list: it read 3 while exactly one helpable entry existed. As a
loop counter it is useless.

**But the list alone is not the gate either** (task #1113). It is only ever filled by
the help window's own query and by the `al.help.all` reply — never by `push.al.help.new`
— so a headless bot that has not opened that window sees nothing but its own requests in
it, and a list-only gate declines every request that arrives while the bot is running.
The red point is the half that moves: the push increments it, the reply resets it. So
the gate is `alliance_help_waiting()` = `math.max(list, red point)`, used both inside the
press chunk and as the button's `count_lua`. It terminates an `xall` loop for the same
reason it is a live signal — the reply zeroes it (5 → 0, watched on the wire). The
reasoning, and the live traces, are in "Answering it without a human" below.

## Acceptance

Live, with `tools/lib/live_tshark.py` running:

```
before: pending=6  total=12  helpNum=6
        --> al.help.all  cmdBaseTime=1785267758008
        <-- al.help.all  allianceId='<my alliance>' (+3 fields)
after:  pending=0  total=6   helpNum=0
```

The server answered, which the decoy never got. Re-running the recipe with an empty
list logs `TAP Help All (alliance) xall -> 0 press(es)` and puts nothing on the wire
(checked against a five-minute capture).

Then end to end, waiting for a real request to arrive and running `actions/help_ally.md`
itself:

```
21:54:33 <-- push.al.help.new  level=19 helpId='…'      # an alliancemate asks
         TAP Help All (alliance) (1; 1 available)
         TAP Help All (alliance) xall -> 1 press(es)
21:54:33 --> al.help.all  cmdBaseTime=1785268474380
21:54:34 <-- al.help.all  allianceId='<my alliance>' (+3 fields)
```

One request pending, one press, one message, one reply — `xall` did not spin, and the
re-read after the press saw the list cleared by the server rather than by the client.

Daily limit: helping is **unlimited**. Only the daily help POINTS are capped —
`GetAllianceHelpSliderData()` → `{todayHelpPoint = 1000, maxHelpCount = 1000}` — and the
run above went through with the cap already reached, so the cap stops the points, not
the helping.

## Answering it without a human (task #1113)

The press above is instant and unlimited, but it is worth nothing while nobody is
pressing it: a request pays help points only for as long as it is open, and the alliance
asks at whatever hour it likes. The panel therefore grew a standing order — the
«Авто-помощь союзникам» checkbox — that keeps an ear on the traffic and fires the press
the moment a request lands.

```
panel checkbox  ──►  tools/alliance_help_monitor.py   (Windows Python, scapy/npcap)
                        the ear:  LiveDecoder, down-direction push.al.help.new
                        the hand:  tools/lib/alliance_help.py -> al.help.all,
                                   through the warm Lua daemon
```

Five decisions worth keeping:

* **The wire is the trigger, not a poll.** `push.al.help.new` is the game telling us a
  request exists — and, as the next point shows, it is the *only* place the client puts
  that news that a headless bot can see in time. Polling would answer late by half the
  interval for no gain.
* **The ear never presses.** `emit` runs on the scapy callback; a daemon round trip
  there stalls the capture and npcap starts dropping frames. It sets an event, and a
  worker thread does the press.
* **The recipe's gate is blind to a fresh request.** This is the one that cost a live
  run. `TAP help_ally_all xall` gates on non-self entries of `GetAllianceHelpList()`,
  and `PushAlHelpNewMessage:HandleMessage` never puts anything there. Its whole constant
  table:

  ```
  senderId | LuaEntry | Player | DataCenter | AllianceHelpDataManager | SetHelpNum |
  GetHelpNum | EventManager | GetInstance | Broadcast | EventId | UpdateAllianceHelpNum |
  BuildManager | GetFunbuildByItemID | BuildingTypes | FUND_BUILD_ALLIANCE_CENTER |
  uuid | AllianceMemberNeedHelp | self | myAllianceCenterUuid | base
  ```

  No `otherHelpInfoList`, no insert — it does `SetHelpNum(GetHelpNum() + 1)` and
  broadcasts "somebody needs help". The *list* of other people's requests is written by
  the reply to `al.help.all` (`AlHelpAllMessage:HandleMessage` → `OnHelpAll(
  otherHelpInfoList)`) and by the help window's own query. Live, that reads exactly as
  it sounds: four `push.al.help.new` frames arrived and the non-self count stayed 0
  through all of them, so the first cut of the auto-helper logged "nobody to help" four
  times in a row.

  So `alliance_help.signals()` reads **both** — the list (what the last reply left) and
  `GetHelpNum()` (what the push just raised) — and presses when either is above zero.
  Note this was not only the auto-helper's bug: `TAP help_ally_all xall` had the same
  blind gate and therefore pressed zero times for any request that arrived while the bot
  was running, which is every request it would ever be there for. Both now go through
  `alliance_help_waiting()`.
* **The press must not re-apply the gate.** `alliance_help_all()` is the send wrapped in
  that same gate, so a caller that has already decided to help would have been silently
  turned into a no-op by it — the log said "helped 6" and nothing left the client. Python
  decides, `alliance_help_send()` (bare, ungated) sends.
* **A zero is retried, not believed.** The sniffer decodes the packet before the client
  has processed it, so both gates can legitimately read 0 for a moment after the push.
  `answer_pending` re-reads for ~1.5s before accepting "nobody is waiting".
* **A burst is one press.** One `al.help.all` answers the whole list, so the worker
  collects wake-ups for `--coalesce` seconds (0.4 by default) and presses once — then
  holds a `--cooldown` floor of 5 s before it may press again. Live, requests arrive
  ~20 s apart and the floor never binds; it is there so that a minute of alliance-wide
  building cannot turn into a stream of up-frames from us.

Only the *inbound* push triggers it: our own outgoing `al.help.all` is on the up
direction and reacting to it would be a loop. `push.al.help.update` is opt-in
(`--with-updates`) — it fires when an already-answered request changes, so by default it
would only spend gate reads. Standing up the watcher with requests already pending has
no push coming (theirs was sent before the ear opened), so it sweeps once at start-up
unless `--no-sweep` says otherwise.

The Lua is not copied anywhere: every chunk comes from `lua_actions`, so the recipe
(`TAP help_ally_all xall`) and the auto-helper send the same message behind the same
gate. Covered by `tests/test_alliance_help.py` (stub evaluator, hand-built envelopes —
no game, no capture).

### Acceptance of the auto-helper

Live, 2026-07-29, alliance server 100. The push payload in full (this is what
`push.al.help.new` carries — `senderId` is the requester, `content` the queue id):

```
15:45:09 <-- push.al.help.new
  {"helpId":"cbc455…","senderId":"1000000000017100","name":"<Player11>","level":1,
   "itemId":"1","queueType":3,"content":1163779272759051027,"nowcount":0,"maxcount":40,
   "allianceId":"<alliance-id>","updateTime":1785322740079,"helpType":1,"picVer":4,"pic":""}
   +0.1s … +6.0s   pushed helpId in GetAllianceHelpList(): no, every sample
                   list stays 6 entries, all isSelf; helpNum 5
```

The press, with the list at zero and only the red point raised — the case the old gate
refused:

```
signals before: (0, 5)            # list = 0, red point = 5
15:45:13 --> al.help.all  cmdBaseTime=1785321914743
15:45:13 <-- al.help.all  allianceId='…' accPoint=49540
signals after : (0, 0)            # only the reply can zero the red point
```

Then the whole chain, unattended, five requests in a row (`tools/alliance_help_monitor.py`,
no start-up sweep):

```
15:54:51 <-- push.al.help.new  helpId='204699c4…'
15:54:53 helped 1 request(s) (list=0, red point=1)
15:55:12 <-- push.al.help.new  helpId='060b5a55…'
15:55:14 helped 1 request(s) (list=0, red point=1)
…                                  # 5 pushes, 5 presses, ~2 s apart
```

The red point reading 1 again on every push is itself the proof that each press landed:
nothing but the server's reply resets it.

## Reading a Lua function without its source

The trick that settled this in one probe, and the reason no window ever had to be
opened: the client's Lua is compiled but **not stripped**, so `string.dump` hands back a
chunk whose constant table still holds every string the function references — field
names, globals, message ids — plus the original source path and the local-variable
names. Printing the printable runs of that dump is a poor man's decompiler, and it is
enough to tell "this function sends" from "this function applies a reply":

```lua
local function strings(f, tag)
  local ok, b = pcall(string.dump, f)
  if not ok then CS.UnityEngine.Debug.LogError('P '..tag..' dump FAILED') return end
  local out, cur = {}, {}
  for i = 1, #b do
    local c = b:byte(i)
    if c >= 32 and c < 127 then cur[#cur+1] = string.char(c)
    else if #cur >= 4 then out[#out+1] = table.concat(cur) end cur = {} end
  end
  CS.UnityEngine.Debug.LogError('P '..tag..' :: '..table.concat(out, ' | '))
end
strings(DataCenter.AllianceHelpDataManager.OnHelpAll, 'Mgr.OnHelpAll')
```

Works on any Lua (not C) function reachable from `_G` or `package.loaded`. C functions
and closures over the C boundary fail the `pcall` — that is the only failure mode.

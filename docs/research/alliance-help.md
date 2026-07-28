# Alliance help ("Помочь всем")

How the alliance help list answers every pending request in one press, and why the
obvious data-manager call is a decoy that silently helps nobody.

- Recipe: `actions/help_ally.md` — one line, `TAP help_ally_all xall`.
- Button: `tools/lib/game_buttons.py` (`help_ally_all`); the Lua itself is
  `tools/lib/lua_actions.py` (`alliance_help_all`, `alliance_help_pending`).
- Source capture: `results/traces/20260728_232122_помощь_союзнику_trace.log` (function
  trace of the player pressing the real button). `results/` is git-ignored, so this
  note is the durable record.

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
mirrored in `alliance_help_pending()` and reused as the button's `count_lua`, so
`TAP help_ally_all xall` never fires a press the chunk then declines to make and never
spends a round trip on a quiet alliance (the `#1087` rule: a speculative *network* call
is not a no-op, it is a rejection with a toast).

Note `GetHelpNum()` — the previous `count_lua` — is a **server-pushed red-point
number**, not the length of the helpable list: it read 3 while exactly one helpable
entry existed. It is a bad loop counter; count the list instead.

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

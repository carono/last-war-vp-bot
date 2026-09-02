# Hospital — healing wounded soldiers (`hospital.cure`)

Sources:

* two live sniffer runs driven by hand in the game hospital (`LWUIHospital`) —
  `20260729_152749` «лечение юнитов» and `20260729_152841` «Лечение юнитов»;
* a live read of the running Lua VM (the traces alone were misleading — see §6), including
  a read of the window's own sender and of the message class, and a series of live sends.

Neither run's `*_traffic.jsonl` holds anything but keepalives, so every wire fact below
comes from the Lua trace and from the VM, not from decoded packets.

## 1. The window

The hospital is opened from the base: the click sound is `cureBtn`, the window
`LWUIHospital` (view `LWUIHospitalView`, controller `LWUIHospitalCtrl`). It is opened
with the hospital building's uuid as its user data —
`UIManager.Instance:OpenWindow("LWUIHospital", buildUuid)`; without it the window closes
again immediately.

The window lists one row per wounded soldier type, each with a slider, and pre-fills each
slider with as many soldiers as fit the player's stored cure-time preference
(PlayerPrefs `HOSPITAL_CURE_SOLDIER_TIME`, 1931 s in the capture). None of that is needed
to heal — see §3.

## 2. The heal message

One press of the confirm button sends one message. The wire side is from the traces, the
caller side from `LWUIHospitalView.SendMessage` / `HospitalCureMessage.OnCreate`:

```lua
SFSNetwork.SendMessage(MsgDefines.HospitalCure, {        -- "hospital.cure"
    armyArray = { {armyId = "3014", count = 93}, {armyId = "3013", count = 1} },
    gold      = 0,   -- gold spent on the heal (0 = the free heal)
})
```

On the wire that is **three** keys and no more:

```
PutUtfString(armyId, 3014)  PutInt(healNum, 93)   AddSFSObject
PutUtfString(armyId, 3013)  PutInt(healNum, 1)    AddSFSObject
PutSFSArray(armyArray, …)   PutInt(gold, 0)       PutInt(worldType, 0)
```

* One `armyArray` entry per soldier type to heal. `armyId` is the soldier template id
  (`DataCenter.SoldierDataManager.soldiers`), a **string** in the message; `count` is how
  many of that type to treat.
* `HospitalCureMessage` renames `count` to **`healNum`** on the wire, which is why the
  trace reads `PutUtfString(armyId, "3014")` + `PutInt(healNum, 80)` while the caller
  passes `count`.
* `gold` is **not optional** — the serialiser packs it as an int and a missing one aborts
  the send before it leaves the client
  (`SFSDataSerializer.lua:39: bad argument #2 to 'pack' (number expected, got nil)`).
* `goldForTime`, `goldForResource` and `itemIds` are **not part of a plain heal** and must
  not be sent. They belong to the pay-to-finish path; passing them (even as `0` / `""`)
  takes `OnCreate` down that branch, which emits `itemId` and the gold fields and **skips
  `armyArray` entirely** — the server then answers `errorCode E000000` and nothing heals.
* The message also carries a `worldType`, which the message class fills in itself from
  `LuaEntry.Player:GetCurWorldType()` (0 in the base) — the caller neither knows nor
  passes it.
* No window has to be open: the message carries no window or building id, so the send is
  the whole press.

> An earlier revision of this file listed all five caller fields as mandatory and said the
> trace hid the repeats by deduping. Both claims were wrong, and they came from reading a
> trace recorded with `lua_trace --dedup`, which keeps only the FIRST call of each name.
> The 20260729_182527 re-recording (no dedup) shows the whole message, and it is three keys.
> Never reason from what a deduped trace does not contain — see `docs/skills/sniff.md` §8.5a.

### 2a. How to send it from a script

`SFSNetwork.SendMessage("hospital.cure", param)` **does not work for this message**.
`HospitalCureMessage:OnCreate` will not build `armyArray` from a param handed to it that
way: the message leaves with only `gold` + `worldType` and the server answers
`errorCode E000000`. That was verified to exhaustion — every spelling of the entry fields
(`count` / `healNum` / both, armyId as string and as number), with and without the extra
gold fields, on a freshly restarted client, with the hospital window shut and open, and
with `param` confirmed intact *inside* `OnCreate` by a trap. The cause inside `OnCreate`
was never found; the function does not raise, it simply skips the block.

What works is to let `SendMessage` do the sending and to complete the message one step
short of the wire: `SendMessage` serialises with `msg:ToBinary()`, so the message class's
own `ToBinary` is borrowed for exactly one call.

```lua
local cls = SFSNetwork.GetMsgType("hospital.cure")
local orig = cls.ToBinary                       -- inherited; `rawget` on the class is nil
rawset(cls, "ToBinary", function(self, ...)
    rawset(cls, "ToBinary", nil)                -- put back BEFORE anything can raise
    local arr = SFSArray.New()
    for _, e in ipairs(entries) do              -- e = {armyId, count}
        local o = SFSObject.New()
        o:PutUtfString("armyId", tostring(e[1]))
        o:PutInt("healNum", math.floor(e[2]))
        arr:AddSFSObject(o)
    end
    self.sfsObj:PutSFSArray("armyArray", arr)
    return orig(self, ...)
end)
SFSNetwork.SendMessage("hospital.cure", { gold = 0 })
```

`gold` still has to be in the param: the serialiser packs it as an int and a missing one
aborts the send (§2). Everything else the message needs it fills in itself.

Proven live on 2026-08-20: 692 wounded across two soldier types went to treatment in one
press — `dead` 692 -> 0, `heal` 0 -> 692, `GetHealCount()` 692.

### 2a-bis. The route that used to be here, and why it cannot come back

Until 2026-08 this note told you to read `GetMsgType` and `Network` out of
`SFSNetwork.SendMessage`'s upvalues with `debug.getupvalue` and to call
`Network:SendLuaMessage("hospital.cure", msg:ToBinary())` yourself. That worked, and it
is now impossible: **the client has closed its Lua sandbox.** Measured live on
2026-08-20 (#1702):

```
debug.getupvalue  ->  this API is disabled for security
debug.sethook     ->  this API is disabled for security
string.dump       ->  lua_dump is disabled

debug.getinfo     ->  OK
debug.getlocal    ->  OK
debug.traceback   ->  OK
```

Three closed, three still open, and the split is the useful part: what went is every way
of reading a value or a body OUT of a function (`getupvalue`, `string.dump`) and the
global call hook (`sethook`). What stayed is everything that describes a frame you are
already standing in — which is why `tools/lua_trace.py` still traces: it wraps the
functions it wants and reads `debug.getinfo` from inside the wrapper. Only its optional
`--hook` flag is dead.

`debug` is still a table and `string.dump` still a function, so both fail at the CALL and
not at the lookup — a `pcall` around them returns false with those words, and code that
swallows the failure sees nothing wrong. There is no reading a function's upvalues or its
constants from Lua any more, on any command, so anything in this repository that used to
identify a value that way has to be rebuilt out of what is still public.

What `SFSNetwork` still exposes is three names, and nothing else:

```
GetMsgType : function      HandleMessage : function      SendMessage : function
```

`GetMsgType(cmd)` hands back the message class (a table whose `ToBinary`, `NewMessage`
and `OnCreate` all come from a base through its metatable — `rawget` on the class itself
is nil, which is what makes `rawset` a clean one-call shadow). That, plus `SendMessage`,
is the whole toolkit, and it is what §2a above is built out of.

**Why this failure is worth a section of its own:** it is silent. The transport raised
into its own `pcall`, the press reported success, and the panel went on saying it had
healed for as long as anybody let it — 698 wounded stayed 698 while the log said the
button had been pressed. A closed API here does not look like an error; it looks like a
heal that did nothing.

### 2b. `errorCode 130069` — the queue is occupied

The old "building queues are full" reading of `130069` was wrong, but the code is real: it
comes back when the **hospital** queue is not free — either a heal is already running, or a
finished one is still waiting to be collected (`state=3`). Collect first, then heal.

The reply comes back through `HospitalManager:HospitalCureHandle`, which either carries
an `errorCode` (and shows the game's tip) or applies the heal: resources, gold, the queue,
the army and the hospital rows, plus a `HospitalUpdate` broadcast.

## 3. Who is wounded — `HospitalManager`, not `T11Util`

`DataCenter.HospitalManager.allHospital` is keyed by soldier template id. A row
(`HospitalInfo`) carries exactly three server fields:

```
allHospital[3014] = {armyId = 3014, dead = 365, heal = 0}
```

* **`dead`** — wounded of that type waiting in the hospital. This is the pool to heal
  (`GetDeadHospital()` is literally what the window lists, and `IsHaveInjuredSolider()`
  reads it).
* **`heal`** — how many of them are already in treatment (`GetTreatingHospital()`).

A row may also show a `curCount`, which is **not** from the server: the window stamps its
own suggested amount onto the row when it opens. It is absent on a freshly started client
and it is only ever a slice of `dead`, so a headless heal must not read it as "the
wounded count".

`T11Util.GetSelfCurSoldierData()`, which the trace shows the window calling, is a red
herring. Called live it returns exactly two fields — `{stage = 0, type = 0}`, the player's
current soldier tier, used to pick the icon. There is no wounded count in it and no name
that a heal could read, so nothing about the heal depends on it.

Read live on 2026-07-29, the same base gave:

```
3013: dead=41  heal=0
3014: dead=746 heal=0
queue state=0 endTime=0 helpNum=2     -- the hospital queue: idle
```

## 4. "Ask for help" and "collect" — the other two presses

* **Ask for help — `al.call.help`, a press of its own.** Positional arguments, not a
  table:

  ```lua
  SFSNetwork.SendMessage(MsgDefines.AlCallHelp, queueUuid, 1, 3, 1)   -- "al.call.help"
  --   PutLong(uuid, <hospital queue uuid>)   PutInt(type, 1)
  --   PutInt(qType, 3)                       PutUtfString(itemId, "1")
  ```

  `qType` is the queue kind — `3` = `NewQueueType.Hospital`, i.e. the same value that
  identifies the heal queue everywhere else — and `uuid` is that queue's uuid, so the same
  message asks for help on any queue by changing those two. The game follows it with
  `al.show.help` (a refresh of the request list), which is not part of the press.

  **`itemId` must be a string.** Passing the number `1` dies in the serialiser before the
  message leaves the client (`SFSDataSerializer.lua:55: attempt to get length of a number
  value`). The trace cannot tell `1` from `"1"` — it prints both the same way.

  **State: the queue's own `isHelped`** — `0` = no request standing, `1` = asked. It flips
  on a successful send, which is what gates the repeat. Proven live on the hospital queue:
  `isHelped 0 -> 1`, `helpNum -> 6`, and five allies answered within seconds
  («предоставил помощь, ускорив исцеление ваших раненых солдат. 1/40!»).

  Only the hospital queue is confirmed. The same message sent for the base's building
  queues (`type=0`) is accepted by the client and draws no error and no tip, but their
  `isHelped` stays `0`, so there is no evidence it registered. Treat help for anything but
  the hospital as unverified.

  Helping *others* is the separate `al.help.all` press the `help_ally` recipe already
  sends.

> This section previously stated that asking for help sends nothing and that starting a
> heal registers the request by itself. That was read off the deduped trace, where
> `SFSNetwork.SendMessage` appears once and every later message is dropped. The no-dedup
> recording has four sends in it — `hospital.cure`, `al.call.help`, `al.show.help`,
> `queue.finish` — so both "there is no such message" claims in this file were artefacts.

* **Collect the healed — `queue.finish`.** The window's receive button is
  `DataCenter.HospitalManager:CheckSendFinish(buildUuid)`, which
  gets the hospital queue (`NewQueueType.Hospital`), checks it has reached
  `NewQueueState.Finish`, checks the healed soldiers would not overflow the barracks
  (else it shows `hospital_finish_drill_ground_full_tips`), and sends
  `MsgDefines.QueueFinish` (`queue.finish`) with the queue uuid. Calling it directly is
  therefore both the press and its gate — a heal still running costs one no-op.

  The no-dedup recording has it, and it is one field:

  ```
  SFSNetwork.SendMessage <- queue.finish, <table>
  PutLong(uuid, 1156814232810146879)     -- the hospital queue's own uuid
  ```

  (The earlier note here — "neither trace contains this press" — was the dedup artefact
  again: `SFSNetwork.SendMessage` had already been logged for `hospital.cure`, so the
  collect send was never written.)

## 5. Building queues are NOT what blocks a heal

An earlier revision of this file claimed a heal takes a `NewQueueType.Default` building
queue and that a base with all of them busy gets the cure refused with `errorCode 130069`.
**That was wrong**, and the whole §5 it justified is retracted.

The player's own heal on 2026-07-29 went through from a base with `free build queues = 0`
— 93 soldiers of type `3014` left the wounded list (746 → 647) while all four Default
queues were working. Whatever `130069` was, it was not this.

`lua_actions.free_build_queues()` still counts idle Default queues correctly and the probe
still prints it; it is simply not a gate on healing, and `heal_all` must not treat it as
one.

## 6. What is proven and what is not

**Proven live, end to end (2026-07-29).** Collect then heal, both headless, both moving
real numbers:

```
collect  -> queue state=3 -> 0,  3013 heal=5 -> 0      (the healed came back)
heal_all -> reply with no errorCode
            3013 dead=34  -> 0, heal=34
            3014 dead=647 -> 0, heal=647
            queue state=2, timer running
```

Also proven: the message and every field in it (from the no-dedup recording of a real
press), the wounded list, and the three other presses of the routine.

**Not** proven: the heal *timer* running down to soldiers rejoining the army from a
bot-started heal (the collect above belonged to a heal started minutes earlier, which is
the same path), and `al.call.help`, which is understood but not yet wired to a button.

The window's own sender cannot stand in for it from a script: `LWUIHospitalView.SendMessage`
sums `curCount` over its own soldier list — not over `HospitalManager.allHospital` — and
bails out with `hospital error soldierCount 0 ----->` even after `ChangeSoliderCount` has
filled both that list and `cacheSoliderCureCount`. Replaying the press through the UI needs
a real hand on the button.

A warning about the traces, which is why §3 exists at all: the first pass read this
ability off the trace alone and got both halves wrong — `T11Util.GetSelfCurSoldierData()`
was taken for the wounded list (it is not), and the message was reconstructed from the
`SFSObject.Put*` calls as `{armyArray = [{armyId, healNum}]}` (which will not even
serialise). The trace was recorded with dedup on, so the repeated `PutInt` calls for the
gold fields never appeared in it. Read the sender out of the VM, not off the wire dump.

## 7. Code

* Lua chunks: `tools/lib/lua_actions.py` — `hospital_cure`, `hospital_heal_all`,
  `hospital_heal_portion`, `hospital_wounded_count`, `hospital_collect`,
  `hospital_healed_ready`, `hospital_wounded_probe`, `free_build_queues`, and, for the
  bill and the bag, `hospital_heal_bill`, `hospital_bill_report`,
  `hospital_open_res_packs`, `hospital_packs_report`.
* Buttons: `heal_all`, `heal_portion`, `collect_healed`, `heal_bill`, `heal_open_packs`,
  `heal_watch_on` / `_off` / `_state` in `tools/lib/game_buttons.py`.
* Primitive: `tools/lib/hospital.py`.
* Recipe: `src/lastwar_bot/actions/heal_units.md`.

## 8. A heal with a ceiling on it, and a watch that finishes it (#2085)

The person asked for four things: a portion to heal by, the sending done automatically,
the alliance asked, and the healed collected **by hook, as the treatment ends** — not by
a clock. Three of the four are here; the fourth is §9.

### 8a. The portion

`hospital_heal_portion` is `hospital_heal_all` with a ceiling read off the VM
(`DataCenter.__lw_heal_portion`, parked by the recipe because a `TAP` takes no
arguments). Zero means «all of them» and the two presses are then identical.

The ceiling is worth having because the hospital is ONE queue: everything wounded in the
base goes in as a single treatment that nothing can interrupt, and a portion is as much
as the player is prepared to wait for. It spends itself HIGHEST SOLDIER FIRST — a bigger
`armyId` is a better soldier — and fills each type up to whatever is left of the portion.

It leaves `DataCenter.__lw_heal = {want, sent, types, err}`, which the recipe reads back
so the log says what actually went rather than that a button was pressed.

### 8b. The watch — the client tells us, we never ask

`HospitalManager` carries the doors this needs, and a live read of its method table
(2026-09-01) is what settled it:

```
:OnQueueEnd  :HospitalCureHandle  :UpdateHospitalDeadInfo  :PushHospitalChangeHandle
:CheckSendFinish  :CalculateCount2CureTime  :CalculateCureTime2Count
:GetDeadHospital  :GetTreatingHospital  :GetHealCount  :GetSoldierCureValueLocal
```

* **`OnQueueEnd`** — the client's own call when the hospital queue retires. This is the
  hook «собираем, как завершается» asked for: the moment the game itself learns the
  treatment is over.
* **`HospitalCureHandle`** — the reply to a cure. Wakes the watch to ask the alliance
  over a queue that is by then working.
* **`UpdateHospitalDeadInfo`** — soldiers being hurt. Wakes it to start the next heal.

All three are wrapped on the manager INSTANCE with `rawset`, so the class is untouched
and a second arm finds the wrapper already there (`W.hooked`). Each wrapper only
SCHEDULES the real step a quarter of a second later
(`lua_actions.HEAL_WATCH_SETTLE_SEC`): every one of them is entered while the client is
in the middle of its own handler, and sending a message from inside one is asking it to
re-enter itself.

Beside the hooks there is **one alarm, and it is not a poll**: the queue's `endTime` is
a stamp the server gave us, so the exact millisecond the heal finishes is known in
advance and a single `TimerManager:GetInstance():DelayInvoke` is pinned to it. It is
re-pinned only while a heal is running, and a watch that finds nothing to do for an hour
takes itself off the game's timer — a timer in somebody else's game has to end. The
recipe arms it again on its next run, which is what the half-hour `heal_units` row is
for: not a schedule, a safety net for a client that has restarted (a fresh VM has no
hook at all) and for a watch that has idled out.

One step does the three presses in the routine's own order — collect a finished heal,
send the next portion into an idle hospital, ask the alliance over a working queue with
`isHelped == 0` — and returns after whichever one it did, because the server's answer
comes back through one of the doors and wakes it again.

The hospital queue, read live while idle, is what the step reads:

```
state=0 endTime=0 startTime=0 isHelped=0 helpNum=0 type=3
uuid=<the queue's own uuid>  funcUuid=<the hospital building>  qid=1
```

## 9. What a heal COSTS, and paying for it out of the bag (#2085)

The fourth thing the person asked for was «если требуется, открываем сундуки с ресурсами»,
and their answer to «how much does it cost» was that there is nothing to model: **«При
лечении указывается нужное количество ресурсов, нужно вычислять, сколько каких сундуков
нужно открыть»**. Both halves are readable now, and one of them turned out to be readable
in a way no amount of reverse-engineering would have found: the client works the chests
out itself.

### 9a. Which resources, and how much

**Which** is per soldier type, out of the game's own config: `lw_soldier.rescue_consume`
is an explicit `id;amount|id;amount` list — `1;577|14;577` for the tier-9 soldier,
`1;702.7|14;702.7` for the tier-10 — and the ids are rows of `aps_resources`, which
`CommonUtil.GetResourceNameByType(id)` names in the player's own language: **1 = Металл,
14 = Еда**. That settles the first of the two questions §8 left open: the window's two cells (`oreNeedResourceCell`
/ `cerealNeedResourceCell`) are metal and food, and the ids are readable with no wounded
in the hospital and no window open.

**How much the base has** is `CommonUtil.GetOwnCountByCommonCostType(1, <resource id>)`,
verified against the base's own balances. The `1` matters: `1` is a base RESOURCE
(`aps_resources` id), `2` is a resource ITEM (`itemId` 6001/7037/8001/5001…), and the two
spaces do not overlap — asking for `(2, 1)` answers 0 and looks like an empty warehouse.

**How much the heal costs** is that list times the soldiers going. Two other candidates
were measured live on 2026-09-02 and BOTH were rejected:

* `LWUIHospitalCtrl:GetHealCostResourceCount(n)` answers `ceil(0.625 × n)` — 1 → 1,
  10 → 7, 100 → 63, 1000 → 625 — and it answers the same with 1 724 wounded, with 120,
  with none at all, and on a second account. A number that does not move when the wounded
  change from tier 9 to tier 10 is not the bill for healing them. an earlier revision called it «the
  price, asked of the game» and that is **retracted**; it is printed in the run's log
  beside the real bill, so that a person with the window open can say in one sentence
  which of the two the screen shows.
* `HospitalManager:GetSoldierCureValueLocal()` is a CONSTANT — 55 059.812266213 here,
  the same with 120 wounded and with zero. A first version of the bill took it for «the
  game's own total, discounts included» and prorated by it. Also retracted.

**What is NOT settled** is whether the player's own research discounts the config price.
The only clean way to see it is a before/after reading of metal and food across one real
heal, and every attempt at one on 2026-09-02 found the hospital already empty — the watch
of §8b heals within a quarter of a second of the wound arriving, which is exactly what it
was built to do. So the question goes to the person instead (the log prints both numbers
for the same soldiers), and until it is answered the bill reads the config price, which
can only ever be too HIGH — and that is why nothing opens unless the run was told to.

### 9b. Which chests — the client answers, and it is not `para1`

the second of those questions was «which resource does a bag pack give», and the answer is that
**it does not have to be asked at all**. `LWResourceLackUtil:GetResItemsToSupplementDatas(
<resource id>, <how much is missing>)` returns the packs that would cover it, in the
numbers that would cover it — the same list the game shows a player who is short at a
shop. Live, with a million metal missing:

```
supp(1,  1000000) = {{itemId = 400102, count = 1000, rewardType = 7, quality = 2}}
supp(14, 1000000) = {{itemId = 400202, count = 899}, {itemId = 400204, count = 11}}
```

`goods.para1` was never resolved and does not need to be: 242 (food), 253 (metal), 264
(coins), 317 (stamina), 97 (diamonds) and 1253 (oil) exist in **none** of the client's 744
config tables — a full sweep with `LocalController:hasLine` found only three tables holding
both 242 and 1253, and all three (`activity_slots_group`, `lw_season`, `lw_template_property`)
are unrelated. The amount a pack gives IS readable —
`ItemTemplateManager:GetResGoodsUnitNum(id)` answers 10 000 for the 10K bread pack — but
which resource it belongs to is the client's business, and the client is willing to say.

**The trap that cost half a day: these are COLON methods.** `LWResourceLackUtil.Func(x)`
returns `nil` or `false` for everything and looks like «the client cannot answer»;
`LWResourceLackUtil:Func(x)` answers. `debug.getinfo(f, 'u').nparams` is what settled it —
`nparams = 2` for a function taking one argument means the first is `self`. `debug.getinfo`
works on this client even though `string.dump` is refused («lua_dump is disabled»), and it
also hands back the file and line a function was defined at, which is the cheapest map of
the client there is.

### 9c. What the recipe does with all that

`TAP heal_bill` parks `DataCenter.__lw_heal_bill` — one row per resource with `need`,
`own` and `lack` — and the run says it in the log whether or not anything is opened.
`TAP heal_open_packs` opens the shortfall, and only ever under three gates, each of which
refuses instead of guessing: the run has to have been told it may (`ARGS chests`, off by
default), the bill has to have been READ (a `lack` of -1 is «I could not look», never
«short»), and every item in the game's own plan has to be a resource pack
(`goods.type == 3`). What was opened, and how much of it actually left the bag, is in the
log, and the bill is read again afterwards so the line after the packs is the state they
left behind.

The watch of §8b deliberately does NOT open anything: spending somebody's inventory rides
on the errand's own run, not on a hook that fires on the client's own calls. The two fit
together — the watch heals whatever the base can pay for, and a heal it could not pay for
leaves the wounded lying there for the next `heal_units` run to find, price and fund.


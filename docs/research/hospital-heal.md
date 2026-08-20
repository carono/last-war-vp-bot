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
  `hospital_wounded_count`, `hospital_collect`, `hospital_healed_ready`,
  `hospital_wounded_probe`, `free_build_queues`.
* Buttons: `heal_all`, `collect_healed` in `tools/lib/game_buttons.py`.
* Primitive: `tools/lib/hospital.py`.
* Recipe: `src/lastwar_bot/actions/heal_units.md`.

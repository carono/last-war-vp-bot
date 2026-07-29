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
    armyArray       = { {armyId = "3014", count = 93}, {armyId = "3013", count = 1} },
    gold            = 0,   -- gold spent on the heal          (0 = the free heal)
    goldForTime     = 0,   -- gold spent to skip the timer
    goldForResource = 0,   -- gold spent to cover missing resources
    itemIds         = "",  -- speed-up items used             (empty = none)
})
```

* One `armyArray` entry per soldier type to heal. `armyId` is the soldier template id
  (`DataCenter.SoldierDataManager.soldiers`), a **string** in the message; `count` is how
  many of that type to treat.
* `HospitalCureMessage` renames `count` to **`healNum`** on the wire, which is why the
  trace reads `PutUtfString(armyId, "3014")` + `PutInt(healNum, 80)` while the caller
  passes `count`.
* The three gold fields are **not optional**. The serialiser packs them as ints, and a
  missing one aborts the send before it leaves the client
  (`SFSDataSerializer.lua:39: bad argument #2 to 'pack' (number expected, got nil)`).
  Sending `armyArray` alone was tried live, with `count` and with `healNum` — both die on
  that same `pack` error, so the four extra fields go out on every real press too. The
  trace shows them only once because it dedups by *function name*, not by argument list:
  that is why one `PutInt` line stands for four.
* The message also carries a `worldType`, which the message class fills in itself from
  `LuaEntry.Player:GetCurWorldType()` (0 in the base) — the caller neither knows nor
  passes it.
* No window has to be open: the message carries no window or building id, so the send is
  the whole press.

The five caller fields are exactly what the window itself passes: `LWUIHospitalView.SendMessage`
builds `{armyArray = {{armyId = …, count = info.curCount}, …}, gold, goldForTime,
goldForResource, itemIds}` and hands it to the same `SFSNetwork.SendMessage`. A headless
send is therefore not an approximation of the press — it is the same call with the same
argument.

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

* **Ask for help — no message of its own.** The heal queue itself carries the help state
  (`helpNum`, `isHelped`, `lastHelpTime`), i.e. starting a heal registers it for alliance
  help; there is no player-initiated "request help for my heal" send. What the 152841
  trace shows is the *inbound* half — an ally helping:

  ```
  UIUtil.ShowTips <- Vaserely предоставил помощь, ускорив исцеление ваших раненых
                     солдат. 1/40!
  ```

  Helping *others* is the separate `al.help.all` press the `help_ally` recipe already
  sends.

* **Collect the healed — `queue.finish`.** The window's receive button is
  `DataCenter.HospitalManager:CheckSendFinish(buildUuid)`, which
  gets the hospital queue (`NewQueueType.Hospital`), checks it has reached
  `NewQueueState.Finish`, checks the healed soldiers would not overflow the barracks
  (else it shows `hospital_finish_drill_ground_full_tips`), and sends
  `MsgDefines.QueueFinish` (`queue.finish`) with the queue uuid. Calling it directly is
  therefore both the press and its gate — a heal still running costs one no-op.

  Neither trace contains this press: the heal in 152841 was timed at ~32 minutes, so the
  soldiers could not possibly have come back before the capture ended.

## 5. A heal needs a free building queue

Healing occupies a building queue (`NewQueueType.Default`) on top of the hospital's own
(`NewQueueType.Hospital`). With every building queue working, the server refuses the cure
with `errorCode 130069` — «Очередь на строительство заполнена». `lua_actions.free_build_queues()`
counts the idle ones, and both the probe and the heal itself print the count, so a refused
heal can be told from a bug.

The counter was checked against the raw queue table live, and it is honest — the base at
the time held twelve queues, of which four were `type=0` (`Default`) and all four were
`state=2` (`Work`), the earliest of them finishing a day later:

```
queue[…866] type=0 state=2 endTime=…   -- Default,  working
queue[…078] type=0 state=2 endTime=…   -- Default,  working
queue[…587] type=0 state=2 endTime=…   -- Default,  working
queue[…166] type=0 state=2 endTime=…   -- Default,  working
queue[…879] type=3 state=0 endTime=0   -- Hospital, idle
free build queues = 0
```

## 6. What is proven and what is not

Proven live: the message shape (it serialises, reaches the server, and comes back through
the real reply handler), that the shape is byte-for-byte the window's own argument, the
wounded list, the collect press and its gate, and the absence of a help-request message.

**Not** proven: a heal seen through end to end. Every live attempt was refused. On
2026-07-29 the refusal was reproduced five times from a base with 0 free building queues —
all wounded at once, a single soldier, and an exact replay of the press the capture
recorded (`3014` × 80), each with the hospital window shut and with it open. Every one came
back the same way:

```
HospitalCureHandle <- {errorCode = "E000000"}    -- the ONLY field in the reply
UIUtil.ShowTips    <- Извините, произошла неизвестная ошибка…
```

`E000000` is not in the client's error table, which is why the tip is the generic one; the
earlier `130069` («Очередь на строительство заполнена») was the same base state answered
with a code the client *does* know. Since the payload has now been shown identical to the
window's own, what is left to differ is state, and the only state known to differ from the
successful capture is the four busy building queues.

The window's own sender cannot be used to check that from a script: `LWUIHospitalView.SendMessage`
sums `curCount` over its own soldier list — not over `HospitalManager.allHospital` — and
bails out with `hospital error soldierCount 0 ----->` when the list has not been through
the cells. So replaying the press through the UI needs a real hand on the button.

So the ability stays 🟡 until one heal is watched from the press to the soldiers coming
back, on a base with a building queue free.

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

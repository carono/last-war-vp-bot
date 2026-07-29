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

Proven live: the message and every field in it (from the no-dedup recording of a real
press), the wounded list, the three other presses of the routine, and that a heal is
accepted with the building queues full.

**Not** proven: a heal sent **from a script**. The headless send reaches the server and is
answered `errorCode E000000` with the generic "unknown error" tip, because the message
leaves without `armyArray`:

```
HospitalCureHandle <- {errorCode = "E000000"}    -- the ONLY field in the reply
```

The cause of the missing `armyArray` was the three extra fields (§2) — a plain heal must
send only `armyArray` and `gold`. Dropping them is the fix under test; until a scripted
heal is watched moving the wounded count, the ability stays 🟡.

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

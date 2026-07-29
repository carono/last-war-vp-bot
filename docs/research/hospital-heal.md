# Hospital — healing wounded soldiers (`hospital.cure`)

Source: two live sniffer runs, both driven by hand in the game hospital
(`LWUIHospital`):

* `20260729_152749` «лечение юнитов» — heal, then select a quantity, then ask for help.
* `20260729_152841` «Лечение юнитов» — heal, select quantity, ask for help, collect
  the healed units.

Only the **heal press** produced an up-message on the wire; the "ask for help" and
"collect" parts of the operator's description did not (see §3). What is proven below is
the heal message shape; the rest is grounded but still needs one live session to close.

## 1. The window

The player opens the hospital from the base — the click sound is `cureBtn` and the
window is `LWUIHospital`, controller `LWUIHospitalCtrl`:

```
XSCALL UIButton.GetClickSound <- ..., cureBtn ...
XSCALL UIManager.OpenWindow  <- ..., LWUIHospital
XSCALL BaseClass             <- LWUIHospitalCtrl, ...
```

The window builds a slider + an input field per wounded soldier type. The wounded list
comes from a **global util, not a DataCenter manager**:

```
XSCALL T11Util.GetSelfCurSoldierData <-           -- (no args) → the soldier data
XSCALL T11Util.IsSuperSoldier        <- 10, 1     -- soldier level 10, type 1
XSCALL UIImage.LoadSpriteAsync       <- .../ItemIcons/soldier_10
XSCALL UIScrollViewSimple...SetTotalCount <- 2    -- 2 wounded soldier types listed
XSCALL UIInput.SetText               <- 311       -- the input defaults to the MAX healable
```

`311` is the full wounded count of the shown type; the player then slid it down. So the
**default input is "heal all of this type"** — a headless "heal all" is the default press.

## 2. The heal message (PROVEN)

One press of the cure button sends exactly one message. Captured whole in both runs:

```
XSCALL SFSNetwork.SendMessage <- hospital.cure, table
XSCALL SFSObject.PutUtfString <- armyId,  3014
XSCALL SFSObject.PutInt       <- healNum, 80          -- (361 in the 152749 run)
XSCALL SFSArray.AddSFSObject  <- armyArray, {armyId, healNum}
XSCALL SFSObject.PutSFSArray  <- armyArray, [ ... ]
```

i.e. the message is

```
hospital.cure  {
  armyArray = [ { armyId = <string>, healNum = <int> }, ... ]
}
```

* `armyId` is a **UtfString** (`"3014"`), `healNum` an **Int**. `SFSNetwork.SendMessage`
  takes a plain nested Lua table and serialises it (string→UtfString, number→Int,
  array-of-tables→SFSArray of SFSObjects), so the send is just:

  ```lua
  SFSNetwork.SendMessage("hospital.cure", {armyArray = {{armyId = "3014", healNum = 80}}})
  ```

* `armyArray` carries **one entry per soldier type that has a non-zero heal count** — in
  both captures the player healed a single type, so one entry went out even though the
  list showed two.
* `armyId == "3014"` is the **same value in both runs** (healNum differed: 80 vs 361),
  so `armyId` is a stable soldier-type/config id, not a per-session record id. It is one
  of the ids inside `T11Util.GetSelfCurSoldierData()`.

After the send the client stamps `HOSPITAL_CURE_SOLDIER_TIME` into PlayerPrefs, destroys
`LWUIHospital`, and the reply drives `QueueInfo.ParseData` + `HospitalInfo.UpdateInfo`
(the heal queue/timer refresh). No window need stay open.

## 3. "Ask for help" and "collect" — NOT separate up-messages

The operator's description mentions asking allies for help and collecting the healed
units, but **no second up-message was captured** for either — the only `SendMessage` in
both traces is `hospital.cure`.

* **Ask for help.** Healing is sped up through the *alliance help* system, which is
  already covered by `help_ally` / `al.help.all` — the same "Помочь всем" press allies
  use. In the 152841 trace we see the **inbound** side of it, not a request send:

  ```
  XSCALL UIUtil.ShowTips <- <color=#54c4f2>Vaserely</color> предоставил помощь,
                            ускорив исцеление ваших раненых солдат. 1/40!
  XSCALL AllianceHelpInfo.SetNowCount <- 40
  ```

  So starting a heal registers it for alliance help automatically (the client filed an
  `AllianceHelpInfo` with cap 40); there is no distinct player-initiated "request help
  for this heal" message on the wire. The bot's `help_ally` recipe already answers such
  requests for allies; a heal of our own is helped by *them* the same way.

* **Collect the healed units.** No up-message was captured. In this game a completed heal
  returns the soldiers on the heal-queue timer without a per-unit "collect" send (the
  reply that refreshes `HospitalInfo`/`QueueInfo` does it). This is the least-certain
  part — if a "collect" press exists it did not fire in these two runs. Confirm live.

## 4. Open questions to close live (see `tools/scratch/_hospital_probe.lua`)

1. **The shape of `T11Util.GetSelfCurSoldierData()`** — which field is the `armyId`
   (`"3014"`) and which is the wounded count that becomes `healNum`. Needed to build
   `armyArray` headlessly for *all* wounded, not just a hardcoded type.
2. Whether a **"collect healed"** press/message exists after a heal finishes.
3. Whether `T11Util.GetSelfCurSoldierData` is the only source or the hospital also reads
   `DataCenter.HospitalManager` (it exists) for the queue state.

Until (1) is confirmed, `tools/lib/hospital.py` can send a heal for a **known**
`armyId`/`healNum` (proven), and its `heal_all` reads `GetSelfCurSoldierData()`
best-effort with a positive-wounded gate — a safe no-op when the field names differ.

## 5. Code

* Lua chunks: `tools/lib/lua_actions.py` — `hospital_cure`, `hospital_heal_all`,
  `hospital_wounded_probe`.
* Button: `heal_all` in `tools/lib/game_buttons.py`.
* Primitive: `tools/lib/hospital.py`.
* Recipe: `src/lastwar_bot/actions/heal_units.md`.
* Live probe: `tools/scratch/_hospital_probe.lua`.

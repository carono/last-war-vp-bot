# Raising a rally («Стягивание») on a world monster

The CREATE side of a rally, confirmed live. The JOIN side (walking a squad onto a banner someone
else raised) is [`rally-join.md`](rally-join.md); finding the target is
[`rally-elite-search.md`](rally-elite-search.md). Everything here runs out-of-process through
xLua `SafeDoString` ([`xlua-state.md`](xlua-state.md)), in **World**.

This supersedes the old guess. A rally create is **not** `SendCreateMarchMessage` fired at the
monster from nowhere: it is the game's own three-window flow, and each window has to be *there*
before the next thing is pressed.

## What it is not

The earlier implementation read the monster's popup, **closed it**, and then sent
`MarchUtil.SendCreateMarchMessage(formation, 6, pid, uuid, …)` from a `DelayInvoke`, warming the
formation first with an `OnClickStartMarch` it closed again with `GoToUtil.CloseAllWindows()`.
Nothing ever went out, and what the player saw was exactly the two halves of that: the monster
came up and vanished with no button pressed, then the squad screen flashed open and was shut
before a squad was on it.

Both parts were wrong:

- `6` is `JOIN_RALLY` — the type for joining an **existing** rally, which needs a `teamUuid` in
  the `targetUuid` slot. Creating one on a monster is `RALLY_FOR_BOSS = 7`. The game agrees:
  `MarchUtil.IsRallyMarch(7)` is `true`, `IsRallyMarch(6)` is `false`.
- The formation "warm" step *was* the rally screen. `OnClickStartMarch` ends in
  `UIUtil.OpenFormationSelectUI(...)` — closing it is closing the very screen the launch button
  lives on.

## The flow

### 1. The target's popup

Search brings it up by itself (`rally-elite-search.md`): the reply runs
`GoToUtil.MoveToWorldMarchAndOpen`, which flies the camera in and opens `UIWorldPoint`. Poll for
it — and for its data, which lands a beat after the window:

```lua
local w = UIManager.Instance:GetStackTopWindow()     -- w.Name == "UIWorldPoint"
local c = w.Ctrl
local md = c:GetMonsterData(c.uuid)                  -- md.level, md.canAttack
c.pointId, c.uuid, c.serverId
```

**Which button the popup carries is the reliable test**, better than `canAttack`:

```lua
c:GetPointBtnEnumName(w.View.btnList[1])   -- "RallyBoss" on a rally target
```

`View.btnCount` is the number of action buttons and `View.btnList` holds their enum ids; a rally
target has exactly one and it names itself `RallyBoss`. A soloable monster names itself
`AttackMonster` instead, and nothing turns that into a rally.

### 2. Press it

The popup's button dispatcher is `UI.UIWorldPoint.Component.UIWorldPointBtn:OnBtnClick`; its
`RallyBoss` branch (past an `IsOpenAttackMonsterByLevel` check and, on some targets, a
`TryCheckRallyDist` distance confirm) ends in a callback holding just `point` and `uuid`:

```lua
MarchUtil.OnClickStartMarch(MarchTargetType.RALLY_FOR_BOSS, pointId, uuid)
```

Two arguments, the rest defaulted. **The popup must still be the top window.** Full signature,
for the other callers:
`OnClickStartMarch(targetType, pointIndex, uuid, index, backHome, rallyType, targetServerId, targetWorldId, monsterSpecialType, ignoreNotice)`.

### 3. The squad screen

`OnClickStartMarch` ends in `UIUtil.OpenFormationSelectUI`, which opens
`UIWindowNames.UIFormationSelectListV2` — or `UIFormationSelectListNew` when the
`formation_v2_switch` config is off. Wait for it; it comes up already carrying the target:

| `Ctrl` field | read live on a level-35 elite |
|---|---|
| `targetType` | `7` (RALLY_FOR_BOSS) |
| `targetPoint` / `targetUuid` | the monster's tile and uuid |
| `targetServerId` | `935` — filled in by the screen, not by the press |
| `timeIndex` | `5` — the rally wait, via `ServerIndex2Time` (`{[5]=1, [1]=5, [2]=10, [3]=30}` minutes) |
| `autoBackHome` | `1` |
| `selectFormationUuid` | the squad last used, remembered in `FORMATION_SELECT_HISTORY` |

Useful `Ctrl` methods: `SetSelectFormationUuid(uuid)`, `CheckCanBattle(formationUuid)` (**the
formation uuid is required** — calling it bare answers `false` and means nothing),
`GetFormationPowerByUuid(uuid)`, `SetTimeIndex(showIndex)`, `NeedTakeArmy()`, `OnEditClick`.

### 4. Pick the squad, then launch

```lua
w.View:OnSelectClick(formationUuid)        -- the tap: repaints the cells and the cost
c:SetSelectFormationUuid(formationUuid)    -- what the tap records
-- read c.selectFormationUuid back before going on
c:OnCheckTime(formationUuid, nil)          -- the launch button
```

`View:OnCreateClick(uuid, destroyTimeIndex)` is the button's own handler and it just forwards to
`Ctrl:OnCheckTime(uuid, destroyTimeIndex)` (via `OnChangeMarchInGuide` while in the city).
`OnCheckTime` runs the game's pre-checks — rally-cap tips, wait-time and transport warnings, the
`GetConfirmFlag` second-confirms — and then calls `OnCreateClick`, which sends:

```lua
MarchUtil.SendCreateMarchMessage(formationUuid, targetType, targetPoint, targetUuid,
                                 timeIndex, autoBackHome, NeedTakeArmy(), targetServerId,
                                 destroyTimeIndex)
```

The screen closes itself afterwards.

`OnCreateClick` can also stop at a second-confirm dialog ("add more heroes / soldiers",
`SHOW_ADD_HERO` / `SHOW_ADD_SOLDIER`, tips `121006`/`121007`) whose OK re-sends; whether it
appears depends on the account's "do not show again" flags. It did not appear on this account.

### 5. What proves it

Not the press — the game's own answer. A raised banner shows up as a **new own march with a
non-zero `teamUuid`**:

```lua
DataCenter.WorldMarchDataManager:GetOwnerMarches()   -- enumerate; count teamUuid ~= 0
```

Live, on a level-35 «Роковая Элита»: own rally marches `0 → 1`, the new march reading
`uuid=…566, teamUuid=…567` — `teamUuid == uuid + 1` is the **leader**'s numbering
(`rally-join.md`), i.e. the rally is ours. `IsHaveMarchInWorld()` alone proves nothing: it is
already true whenever any unrelated march is out.

## Calling it off

`MarchUtil.CancelRallyByLeader(teamUuid)` only pops a confirm dialog; its OK sends
`MsgDefines.AllianceWarCancel`, so send that straight:

```lua
SFSNetwork.SendMessage(MsgDefines.AllianceWarCancel, teamUuid)
```

Verified: the own march's `teamUuid` goes back to `0` and it turns for home. (The member-side
leave is `alliance.team.retreat` — `rally-join.md`.)

## Where the waits go

Every step above is a state, not a delay, and the two places this flow used to fail are the two
handovers between them:

1. **popup → press.** Poll until `UIWorldPoint` is on top *and* `GetMonsterData` answers; never
   close it before the press.
2. **press → squad → launch.** Poll until the formation window is on top, pick the squad, read
   `selectFormationUuid` back, and only then launch. A launch on a screen that is not holding
   the wanted squad is the "no squad was selected and it all ended" the player saw.

Tool: [`tools/rally_create.py`](../../tools/rally_create.py) — `find_target()` (search, leaves
the popup open), `raise_rally()` (press → wait → pick → launch → confirm), `create_on_level()`
(both, per squad). `python tools/rally_create.py --find --level N [--type monster|boss]` reports
what the search returns and which button it carries, without pressing anything.

# Opening UI panels programmatically (Lua) — UIManager, UIWindowNames, GoToUtil

Goal: open the alliance menu without a physical click, by analogy with
`SceneUtils.ChangeToWorld()`. Driven out-of-process via `XLuaManager.SafeDoString`
(`tools/lua_eval.py`, docs/research/xlua-state.md §12). Two working layers were found and
proven with screenshots.

## The UI framework

`_G` search (`SafeDoString` + Player.log markers) surfaced:

- **`UIManager`** — the UI singleton. Instance via **`UIManager.Instance`** (not
  `GetInstance()`). Methods: `OpenWindow`, `DestroyWindow`, `GetWindow`, `HasWindow`,
  `IsWindowOpen`, `IsPanelLoadingComplete`, `GetWindowConfig`, `PushStackWindow`,
  `GetStackTopWindow`, `GetStackWindowCount`, …
- **`UIWindowNames`** — table of **2221** window-name constants (key == value == the
  window's string id), e.g. `UIWindowNames.UISettingSet`, `UIWindowNames.UIAllianceDetail`,
  `UIWindowNames.UIAllianceShop`. ~120 of them are alliance windows (grouped in the API
  reference below). (Separately, 96 `_G` globals contain "alliance" — mostly enums/data types.)
- **`GoToUtil`** — the high-level navigation util (the UI analogue of `SceneUtils`):
  `GoMainUIBtn`, `GotoOpenView`, `GotoAllianceShop`, `GoToAllianceMemberBase`,
  `GoToNewAllianceSkill`, `GoToAllianceFurnace`, `OpenScienceTree`, `MoveToWorldPointAndOpen`,
  `JumpToWorldPoint`, … `UIMainFunctionInfo.Alliance = 5` is the alliance main-HUD button id.

## Layer 1 — direct `OpenWindow` (works for data-independent windows)

```lua
UIManager.Instance:OpenWindow(UIWindowNames.UISettingSet)
```
**Proven:** this renders the full Settings panel (`results/settings_test.png`). So the
mechanism works out-of-process — no click needed. Good for self-contained windows
(settings, simple popups) that don't need server data on open.

## Layer 2 — `GoToUtil.Goto*` (full flow: fetch data → open → render)

For panels that need server data, the dedicated `GoToUtil` functions run the whole flow
(request + open), exactly like `SceneUtils.ChangeToWorld()` does for scenes:

```lua
GoToUtil.GotoAllianceShop()
```
**Proven:** this opens and renders the **Alliance Shop** («Магазин Альянса» — tabs, item
cards, honor currency, refresh timer) — `results/alliance_shop_open.png`. This is the
alliance menu opened programmatically. Siblings: `GoToAllianceMemberBase`,
`GoToNewAllianceSkill`, `GoToAllianceFurnace`.

## Why the bare alliance *main* window fails (and how to fix it)

`UIManager.Instance:OpenWindow(UIWindowNames.UIAllianceDetail)` registers the window
(`IsWindowOpen` briefly true, `GetWindowConfig` resolves `PrefabPath =
Assets/Main/Prefabs/UI/Alliance/UILWAllianceDetail.prefab`) but it **auto-closes within ~2 s
and never renders**. Player.log gives the exact reason:

```
SFSDataSerializer.lua:55: attempt to get length of a nil value (local 'val')
    UIAllianceDetailView.lua:186: in function 'OnCreate'
Open window failed UIAllianceDetail
```

`UIAllianceDetailView:OnCreate` deserializes **alliance-detail data** (SFS-serialized) that
is `nil` when the window is opened cold → it throws and the framework discards the window.
Passing the alliance uid or the `AllianceBaseDataManager:GetAllianceBaseData()` object as an
`OpenWindow` arg does **not** help — the view needs the *detail* payload the button fetches
from the server first. `GoToUtil.GoMainUIBtn(UIMainFunctionInfo.Alliance)` runs (`ok=true`)
but does not open the panel by itself either.

**Takeaway / recipe**
- Data-independent window → `UIManager.Instance:OpenWindow(UIWindowNames.<Name>)`.
- Alliance / data-driven panel → use the high-level **`GoToUtil.Goto*`** entry (proven:
  `GotoAllianceShop()`), which performs the server request + open. The main alliance detail
  (`UIAllianceDetail`) needs its alliance-detail request sent before `OpenWindow` — the
  `GoToUtil`/button flow is the reliable path; a bare `OpenWindow` aborts in `OnCreate`.
- All of this is driveable out-of-process via `tools/lua_eval.py`
  (`GameEntry.get_Lua() → XLuaManager.SafeDoString`).

## Artifacts (git-ignored under `results/`)

- `results/settings_test.png` — `OpenWindow(UISettingSet)` rendering the Settings panel.
- `results/alliance_shop_open.png` — `GoToUtil.GotoAllianceShop()` rendering the Alliance Shop.
- `results/alliance_panel_open.png` — bare `OpenWindow(UIAllianceDetail)` (no render; aborts in OnCreate).

---

# UI interaction API reference (captured this session)

All lists below are from the live `_G`/method dumps captured during the alliance-open work (via `tools/lua_eval.py`), plus the docs. **Completeness flags** are explicit: the game was not re-probed for this write-up (user in-game), and `results/il2cpp_dump.json` holds only assembly names + class counts (no method tables), so anything marked *partial* needs a live dump to finish.

## `UIManager` — window manager (complete method list)

Singleton: **`UIManager.Instance`** (a `mt:GetInstance` also exists). Grouped:

- **Open / close windows:** `DestroyAllWindow`, `DestroyViewList`, `DestroyWindow`, `DestroyWindowByLayer`, `OnDestroyWindow`, `OpenWindow`
- **Query window state:** `CheckIfIsMainUIOpenOnly`, `GetWindow`, `GetWindowConfig`, `HasWindow`, `HasWindowByLayer`, `IsInWindowStack`, `IsNeedReorder`, `IsPanelLoadingComplete`, `IsWindowOpen`
- **Window stack:** `GetStackTopWindow`, `GetStackWindowCount`, `PopStackWindow`, `PushStackWindow`, `ReorderWindow`
- **Layers:** `BgLayerClickBack`, `BgLayerSetActive`, `DeleteAllLayer`, `GetLayer`, `IsLastLayerForChatPanel`, `SetLayerActive`
- **Animation / main-UI / FPS:** `ChangeFPSToHighFPS`, `ClearFPSLockInfo`, `GetUIMainAnim`, `PlayMoveInAnim`, `PlayMoveOutAnim`, `PlayUIMainShowAnimation`, `SetUIMainEnable`
- **Chat split-panel:** `GetChatSplitClickInRect`, `GetChatSplitPanelModeSetting`, `GetChatSplitPanelRatio`, `IsChatSplitPanelModeOn`, `ResumeChatSplitPanelMode`, `SetChatSplitPanelMode`, `TempCloseChatSplitPanelMode`, `UpdateClickOnSplitPanel`
- **Scene camera:** `CheckNeedHideSceneCamera`, `CheckNeedShowSceneCamera`, `IsSceneCameraDisable`, `ShowSceneCameraIfAnyHideCameraWindow`, `StopWorldCameraMove`
- **Lifecycle / input / misc:** `AddListener`, `AndroidNavigationGestureEscape`, `Delete`, `Description`, `DisableInteractionBlocker`, `EditorProfile`, `EnableInteractionBlocker`, `GetScaleFactor`, `GetUIContainerRect`, `InstanceOf`, `IsDisableLuaAddComponentAssert`, `KeyCodeEscape`, `New`, `OnAndroidNavigationGestureEscape`, `OnKeyCodeEscape`, `OnUpdate`, `RemoveListener`, `ResetAllAdjustForPC`, `SetNewTMProFontMaterial`, `Startup`, `UpdateHideBack`

## `GoToUtil` — high-level navigator (PARTIAL — log truncated)

The UI analogue of `SceneUtils`; `Goto*` functions run the full fetch+open flow (proven: `GotoAllianceShop`). Captured so far (the live dump was truncated after `GotoDr…`, so this is not the full set):

`GetBuildState`, `GoCheckBuild`, `GoMainUIBtn`, `GoToAllianceFurnace`, `GoToAllianceMemberBase`, `GoToNewAllianceSkill`, `GotoAllianceShop`, `GotoFinishedBuilding`, `GotoMainBuildPos`, `GotoOpenView`, `GotoOpenViewOpenOptions`, `GotoOpenView_BattleReturnOpt`, `JumpToMarchByUuid`, `JumpToWorldPoint`, `MoveToWorldMarchAndOpen`, `MoveToWorldPointAndOpen`, `OpenScienceTabPanel`, `OpenScienceTree`, `RequestAllianceMemberBasePoint`

Groups: **alliance** `GotoAllianceShop`, `GoToAllianceMemberBase`, `GoToNewAllianceSkill`, `GoToAllianceFurnace`, `RequestAllianceMemberBasePoint`; **build** `GoMainUIBtn`, `GoCheckBuild`, `GetBuildState`, `GotoMainBuildPos`, `GotoFinishedBuilding`; **science** `OpenScienceTree`, `OpenScienceTabPanel`; **world/march** `MoveToWorldPointAndOpen`, `MoveToWorldMarchAndOpen`, `JumpToWorldPoint`, `JumpToMarchByUuid`; **generic view** `GotoOpenView`, `GotoOpenViewOpenOptions`, `GotoOpenView_BattleReturnOpt`.

## `SceneUtils` — scene switch (from docs/research/xlua-state.md §12.2)

`ChangeToWorld()`, `ChangeToCity()` (proven), `CreateWorld()`, `CreateCity()` (build only — no view switch), `GetIsInWorld()`, `GetIsInCity()`, `CheckCanGotoWorld()`. Higher-level `GoToUtil.TryJumpToWorld()` runs but no-ops without a target. The C# `SceneManager` (Assembly-CSharp) mirrors these statically (`get_CurrSceneID`, `IsInWorld`, `IsInCity`, `ChangeScene`, `CreateWorld/City`) but does NOT render — always use the Lua `SceneUtils` path.

## `UIWindowNames` — window-name constants (total **2221**; only the 120 alliance ones captured)

Key == value == the window's string id. The full 2221 were counted but not dumped; below is the **complete alliance group** (captured), sub-grouped by function:

- **Alerts:** `UIAllianceAlertDetail`
- **Alliance boss (S0):** `UIS0AllianceBossBuild`, `UIS0AllianceBossBuildRecord`, `UIS0AllianceBossChallengeRecord`, `UIS0AllianceBossRank`, `UIS0AllianceBossRewardPreview`, `UIS0AllianceBossSelect`
- **Alliance star:** `UIAllianceStarBook`, `UIAllianceStarBookTip`, `UIAllianceStarMain`, `UIAllianceStarOrderTimePop`, `UIAllianceStarReward`
- **Congratulation / thumbs-up:** `LWAllianceCongratulationListPop`, `LWAllianceCongratulationPopView`, `LWAllianceThumbsUpPopView`
- **Digging event:** `DiggingLevelAllianceCView`, `DiggingLevelAllianceView`, `OffSeasonDiggingLevelAllianceView`
- **Flag:** `UIAllianceFlag`
- **Ghost parkour event:** `UIGhostParkourAllianceRewardView`
- **Help / gift / shop / task / storage:** `UIAllianceEveryDayTask`, `UIAllianceGift`, `UIAllianceGiftInfo`, `UIAllianceHelp`, `UIAllianceShop`, `UIAllianceStorage`, `UIAllianceTask`, `UIGhostreconAllianceTask`, `UIIdleGameTaskEventAllianceHelp`, `UILWAllianceGift`, `UILWAllianceGiftInfo`, `UILWAllianceShop`
- **Join / create / invite:** `UIAllianceApplyList`, `UIAllianceInvite`, `UIAllianceInviteList`, `UIAllianceInviteTip`, `UIChatAllianceInviteScoreTipView`, `UICreateAlliance`, `UICreateSetAlliance`, `UIJoinAlliance`, `UIJoinOrCreateAlliance`, `UILWAllianceApplication`, `UILWAllianceFirstJoin`, `UILWAllianceInvite`, `UILWAllianceInviteShare`, `UILWAllianceInviteShareConfirm`, `UILWAllianceInviteShareNew`, `UILWAllianceList`, `UILWChangeEnterAllianceCondition`, `UILWSeasonMakeFriendsSearchAlliance`
- **Main / info:** `UIAllianceChangeLanguage`, `UIAllianceDetail`, `UIAllianceIntro`, `UIAllianceQa`
- **Management / settings / notice:** `LWUIAllianceNoticeDetail`, `UIAllianceChangeAbbr`, `UIAllianceChangeAnnounce`, `UIAllianceChangeName`, `UIAllianceChangeRestriction`, `UIAllianceKirovPlanTime`, `UIChangeAllianceCityName`, `UILWAllianceLeaveTips`, `UILWAllianceLog`, `UIPostAllianceNotice`, `UISettingAlliance`, `UIUpgradeAllianceNotice`
- **Members / roles / careers:** `UIAllianceCareerEdit`, `UIAllianceCareerEffectTip`, `UIAllianceMemberDetail`, `UIAllianceMemberTip`, `UIAllianceOfficeSelect`, `UIAllianceRankSelect`, `UIAllianceSelectRole`, `UISeasonAllianceSelectMember`
- **Military pay:** `AllianceMilitaryRewardPreviewView`, `AllianceMilitaryRewardUpgrade`, `LWAllianceMilitaryPayMainView`
- **Rally:** `UIAllianceAutoJoinRally`, `UIAllianceRally`
- **Ranks / rewards:** `AllianceMilitaryPayRank`, `LWSeasonAllianceRank`, `LWSeasonAllianceRankRewardInfo`, `LWSeasonAllianceScoreDetail`, `UIAllianceRankDetailList`, `UIAllianceRankTable`, `UIGhostParkourAllianceRewardRankView`, `UILWAllianceRank`, `UISeasonAllianceReward`, `UISeasonAllianceRewardDisplayDetail`, `UISeasonAllianceRewardDisplayMain`
- **Science / skills:** `UIAllianceCommonSkill`, `UIAllianceCommonSkillInfo`, `UIAllianceCommonSkillRecord`, `UIAllianceCommonSkillSelect`, `UIAllianceCommonSkillUseTip`, `UIAllianceGovernmentSkill`, `UIAllianceGovernmentSkillHistory`, `UIAllianceGovernmentSkillHurtList`, `UIAllianceScience`, `UIAllianceScienceInfo`, `UILWAllianceSkill`
- **Seasonal (Queen of Blood):** `UIQueenOfBloodAllianceListPop`
- **War / compete / season events:** `LWUIAllianceCompeteProtectTip`, `LWUIZoneMobilizationAllianceRank`, `S5AllianceExpeditionConditionPopup`, `SeasonAllianceWarTimeChangeConfirmView`, `SeasonAllianceWarTimeSetConfirmView`, `SeasonAllianceWarTimeSetInfoView`, `SeasonAllianceWarTimeSetView`, `SeasonAllianceWarTimeStateTipsView`, `UIAllianceCompeteMain`, `UIAllianceCompeteNew`, `UIAllianceCompeteRank`, `UIAllianceCompeteReward`, `UIAllianceCompeteSchedule`, `UIAllianceWarDetail`, `UIAllianceWarMainTable`, `UILWSurfingAllianceSumRankView`, `UILWSurfingBattleAllianceRewardView`, `UILeagueMatchAlliances`

Partial **settings** group also captured: `BankSetting`, `LWUIMigrationSetting`, `OfficialCDSetting`, `UIChatAISetting`, `UIGroupChatSetting`, `UILWAlSetting`, `UIPaymentPreferenceSetting`, `UIPlayerDownloadCenterSetting`, `UISettingBlock`, `UISettingChangeUid`, `UISettingChooseURL`, `UISettingCusto`, `UISettingFlag`, `UISettingRedemptionCode`, `UISettingSet`, `ValentineSendGiftSetting` (list truncated at `UISettingCusto…`). A full grouped map of all 2221 (battle, resources, heroes, buildings, shop, events, …) needs a live `for k in pairs(UIWindowNames)` dump — deferred while the user is in-game.

## Other UI enums / managers (from `_G`)

- **`UIMainFunctionInfo`** — main-HUD function ids: `Alliance=5`, `AllianceTaskShare=20` (rest not dumped). Used by `GoToUtil.GoMainUIBtn(id)`.
- **`MainUITipType`** — `Alliance=7` (red-dot/tip ids; rest not dumped).
- **`GuideOpenPanelType`** — exists (guide-driven panel opens); values not captured (no alliance key).
- Other UI globals seen: `UIWindow`, `UIBaseView`, `UIModelView`, `UIScrollView`/`UIScrollViewSimple`, `UILoopGridView`/`UILoopListView2`/`UILoopListViewSimple`/`UIUnlimitedScrollView`, `UIComponentPoolManager`, `UITimeManager`, `TroopHeadUIManager`, `WorldBuildHeadUIManager`, `WorldMarchTileUIManager`, `UIViewSkinBridge`, `UIChatSplitPanel`. (Open-type enums: `UIMailOpenType`, `TrainUIOpenType`, `AlarmUIOpenType`, `UISeasonCallBackInfoOpenType`, `UIDetectSlotBoxPanelType`.)


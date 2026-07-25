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

## Worked example — the Shop (`UICommonShop`): open → switch tabs → close

The generic in-game **Shop** («Магазин») is `UIWindowNames.UICommonShop`. It is
data-independent enough to open cold via `OpenWindow` (unlike the alliance *detail* panel
below), it carries the full tab bar, and it closes via `CloseSelf`. Full flow verified live
with screenshots (`results/shop_*.png`); driven out-of-process through the warm Lua daemon
(`tools/lib/lua_client.get_evaluator()`), reusable script `tools/dev/ui_shop.py`.

### 1. Open

```lua
UIManager.Instance:OpenWindow(UIWindowNames.UICommonShop)
```

Renders the Shop on the diamonds tab. Confirm with
`UIManager.Instance:IsWindowOpen("UICommonShop")` → `true` and
`UIManager.Instance:IsPanelLoadingComplete("UICommonShop")` → `true` (both true ~2 s after).

### 2. Switch tabs

The window object exposes the view at `w.View`. Tabs are keyed by a **shop-type** number,
not an index:

- `w.View.curShopType` — the currently shown tab (starts at `1`).
- `w.View.shopTabTypeList` — ordered list of tab types: `{1, 2, 7, 8, 100, 200, 150, 10}`.
- `w.View.togglesTb[<type>]` — the toggle sub-view for each type; each holds `shopType`,
  `selecting`, the `__onvaluechanged` callback, and the real `unity_uitoggle` (a
  `CS.UnityEngine.UI.Toggle`).

Read a tab's display name programmatically from its toggle sub-view — the title is a
TextMeshPro component wrapped at `txt_title.unity_tmpro`:

```lua
w.View.togglesTb[<type>].txt_title.unity_tmpro.text
```

The full tab map (read live via that path — the numbers are the `shopTabTypeList` order):

| # | type | title |
|--:|--:|---|
| 1 | 1   | Магазин бриллиантов (diamonds) |
| 2 | 2   | VIP-магазин |
| 3 | 7   | Магазин Альянса (honor) |
| 4 | 8   | Магазин чести |
| 5 | 100 | Магазин Экспедиции |
| 6 | 200 | Магазин Сезона |
| 7 | 150 | Магазин обликов |
| 8 | 10  | Магазин купонов |

> **Encoding gotcha:** on this install `Player.log` is written in **cp1251**, so Cyrillic
> logged via `Debug.LogError` comes back mojibake through `lua_eval` (which decodes UTF-8).
> To read Unicode strings cleanly, have Lua write straight to a file as UTF-8 —
> `CS.System.IO.File.WriteAllText(path, text)` — and read that file (this is how the table
> above was captured).

**Faithful switch — drive the real toggle** (fires the registered `onValueChanged`, which
changes the visible content + top-bar currency and updates `curShopType`):

```lua
local w = UIManager.Instance:GetWindow("UICommonShop")
w.View.togglesTb[7].unity_uitoggle.isOn = true   -- -> Магазин Альянса
```

`onValueChanged` runs on the **next frame**, so `curShopType` reflects the new tab only on a
*subsequent* call — reading it in the same `SafeDoString` chunk still sees the old value
(verified: separate-chunk reads returned `7` then `100` correctly). There is also a direct
view method `w.View:ChangeShowType(<type>)`, but it updates `curShopType` later still (a
server round-trip) and does **not** mark the toggle selected — prefer
`unity_uitoggle.isOn = true` for a click-equivalent switch.

### 3. Close

```lua
UIManager.Instance:GetWindow("UICommonShop").Ctrl:CloseSelf()
```

`w.Ctrl:CloseSelf()` is the base-controller close (inherited — `pairs(w.Ctrl)` only shows
`__ctype`/`_class_type`, but `type(w.Ctrl.CloseSelf) == "function"`). After it,
`IsWindowOpen("UICommonShop")` → `false` and the view returns to the city. Do **not** use
`DestroyAllWindow` (kills the HUD, see [[feedback_no_destroyallwindow]]).

## Left panel buttons

The vertical button column on the left edge of the **city** view drives several data-heavy
features. Entry points were resolved live with the warm Lua daemon
(`tools/lib/lua_client.get_evaluator()`); probe/inspect helpers are `tools/scratch/_ui_probe.py`
(open + screenshot) and `tools/scratch/_ui_inspect.py` (open + dump the window's on-screen TMP
text to a UTF-8 file — works even when the Windows session is locked and BitBlt screenshots
fail). Every entry below opens and renders from the city. **A ready-made launcher is
`tools/dev/ui_left_panel.py`** (`--list`, `--open <button>`, `--close`, `--close-all`).

Which icon is which was pinned down by reading the `UnityEngine.UI.Image` sprite names on the
`UIMain` HUD buttons (the buttons' GameObjects are generically named `btn`; the sprite name
carries the feature). Left-column sprites → feature:

| sprite (Image on the button) | feature | entry point |
|---|---|---|
| `zyf_chengjian_rukou_icon` | 城建 city-build queue entrance | build UI |
| `lyp_..._kejishu` | 科技树 tech/science queue entrance | `GoToUtil.GotoScience()` / `OpenScienceTree()` |
| `lrb_chengjimaoyi_...` | 城际贸易 inter-city trade | **trucks** → `TradeStationCity` (below) |
| (radar / secret-missions / quest icons — generic sprites) | radar / ghost recon / quests | see below |

Summary of the verified feature windows (all `IsWindowOpen` → `true`):

| button | Lua | window |
|---|---|---|
| Radar / recon | `GoToUtil.GoRadarProbe()` | `UIDetectEvent` |
| Secret missions (ghost recon) | `OpenWindow(UIWindowNames.UIDispatchTaskMain)` | `UIDispatchTaskMain` |
| Trucks (Trade Station) | `OpenWindow(UIWindowNames.TradeStationCity)` | `TradeStationCity` |
| — truck dispatch | `OpenWindow(UIWindowNames.UILWTruckSuperDeparture)` | `UILWTruckSuperDeparture` |
| — truck rob log | `OpenWindow(UIWindowNames.UILWTruckRecord)` | `UILWTruckRecord` |
| Quests | `OpenWindow(UIWindowNames.UILWQuestList)` | `UILWQuestList` |

### Radar (satellite-dish icon) — `GoToUtil.GoRadarProbe()`

```lua
GoToUtil.GoRadarProbe()
```

Opens **`UIWindowNames.UIDetectEvent`** — the radar mission map («задания радара»: a scatter
of task pins over the mini-map, a stamina cost, «Через HH:MM:SS восстановится N заданий
радара», «Действуйте быстро»). Visually confirmed (`results/lp_01_radar_goradarprobe.png`).
A bare `OpenWindow(UIWindowNames.UIDetectEvent)` is *not* the reliable path — use the
`GoToUtil` route, which runs the fetch+open flow. Close with
`UIManager.Instance:GetWindow("UIDetectEvent").Ctrl:CloseSelf()`.

### Secret missions / ghost recon / «Операция Призрак» — `UIDispatchTaskMain`

```lua
UIManager.Instance:OpenWindow(UIWindowNames.UIDispatchTaskMain)
```

Opens the **«Секретный командный пункт»** (Secret Command Post) — this is the ghost-recon
secret-missions hub (see [[project_ghost_recon_missions]]). Opens cold via `OpenWindow`
(`IsWindowOpen` → `true`). On-screen text confirms it: tabs **«Индивидуальные Задания»**,
**«Задания Альянса»**, **«Задания других»**; mission cards («Спасти учёного», «Разрушить
энергосистему» …); **«Секретный мобильный отряд — Отправляйте героев выполнять секретные
задания…»**; **«Операция Призрак»**, **«Скрытые Сокровища»**, «Грабить других», «Записи».
Close with `GetWindow("UIDispatchTaskMain").Ctrl:CloseSelf()` (or `GoToUtil.CloseAllWindows()`).

### Trucks / Trade Station (truck icon) — `TradeStationCity` + truck sub-windows

The truck feature is the Trade-Station convoy system whose trucks are the ones tracked by
`tools/dev/scan_trucks.py` and the `can_loot` rule ([[project_can_loot_rule]]). Three
windows make it up; all open cold via `OpenWindow` and were text-confirmed:

```lua
UIManager.Instance:OpenWindow(UIWindowNames.TradeStationCity)          -- trade-post hub
UIManager.Instance:OpenWindow(UIWindowNames.UILWTruckSuperDeparture)   -- dispatch a truck
UIManager.Instance:OpenWindow(UIWindowNames.UILWTruckRecord)           -- rob / robbed log
```

- **`TradeStationCity`** — the trade-post overview: **«Ваш торговый пост: 0/5»**, a grid of
  posts by coordinate (`#935 X:49 Y:349`, «Ещё не открыт», «Ур.1…4»).
- **`UILWTruckSuperDeparture`** — the truck-dispatch panel: tabs **«Супер режим / Супер
  обновление / Супер отправка»**, the truck fleet as `No.1 … No.4` each with a countdown
  and a haul value. (Renders "super" mode when a super buff is active.)
- **`UILWTruckRecord`** — the battle log of trucks robbed / robbing others («Победа
  атакующей стороны», «Поражение в бою с #946 [OTER]…», «Nч назад»). Detail:
  `UILWTruckRecordDetail`. Rewards/insurance popups: `UILWTruckRewardGet`,
  `UITruckRewardInsurance`, `UITruckRewardInsuranceTips`. Data manager:
  `DataCenter.LWGateTruckGoodsManager`.

### Quests (task-list icon) — `UILWQuestList`

```lua
UIManager.Instance:OpenWindow(UIWindowNames.UILWQuestList)
```

Opens **«Задание»** — the quest list with **«Основные задания»** (main) and **«Дополнительные
задания»** (side) sections («Улучшить "Хижина строителя" до 30-го уровня (0/1)», «Вперёд» …).
Opens cold via `OpenWindow`; text-confirmed.

Note (2026-07-25): screenshots for the secret-missions, trucks and quest windows are pending —
the Windows session locked mid-session (`OpenInputDesktop`→0), which kills BitBlt capture while
leaving the Lua daemon fully functional; identification of those is by each window's rendered
on-screen text (radar additionally by screenshot). Re-run `tools/dev/ui_left_panel.py --open
<button>` + `tools/scratch/_ui_probe.py` once the desktop is unlocked to capture them.

### Nearby "other buttons" mapped along the way (guard against confusables)

- **«Экономика» (city building index)** — `GoToUtil.GoBusinessCenterWindow()` (also
  `UIWindowNames.UIBusinessCenter`, but that one needs the fetch flow). Renders the building
  catalogue («Производство еды», «Железный рудник», «Хранилище», «Учебная база» …). This is
  **not** the trucks/Trade-Center panel despite the "Business Center" name.
- **Battlefield teleport** — `UIWindowNames.UILLWorldMapTransport` («Телепортироваться»,
  «перемещение на поле боя», «центральная зона»). Opens cold but is the season/battlefield
  teleport, **not** a transport/trucks window — the name is a trap.

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
- `results/lp_01_radar_goradarprobe.png` — `GoToUtil.GoRadarProbe()` rendering the radar mission map (`UIDetectEvent`).

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


---

# Full enumeration — complete live dump (supersedes the partial lists above)

Dumped from a fresh login via `SafeDoString` writing straight to disk (`CS.System.IO.File.WriteAllText`, bypassing Player.log truncation). Raw dumps in `results/*.txt` (git-ignored); **grouped machine-readable copies committed under `docs/research/ui-open-data/*.json`**. Counts: **UIWindowNames 2221, GoToUtil 147, SceneUtils 77, DataCenter 464, GuideOpenPanelType 1**.

## `GoToUtil` — 147 methods (complete)

The full high-level navigator. Every `Go*`/`Goto*`/`Jump*`/`Move*`/`Open*`/`Request*` runs a fetch+open flow (proven: `GotoAllianceShop`). Grouped:

- **Alliance** (5): `GoToAllianceFurnace`, `GoToAllianceMemberBase`, `GoToNewAllianceSkill`, `GotoAllianceShop`, `RequestAllianceMemberBasePoint`
- **Build/city/resource** (47): `CheckSeasonResourceStatus`, `GetBuildState`, `GetHighestLevelBuild`, `GetSourceByResourceItem`, `GoBarracks`, `GoBuildOpenUpgrade`, `GoBusinessCenterWindow`, `GoCheckBuild`, `GoCityCollect`, `GoConnectBuild`, `GoEnergy`, `GoFactory`, `GoFactoryWork`, `GoGarageUpgrade`, `GoGarbage`, `GoHospital`, `GoToCityBuildByQuest`, `GoToCivilizationSparkBuild`, `GoToCurObstacle`, `GoToGarageRefit`, `GoToSeasonCityList`, `GotoBuildListByBuildId`, `GotoBuildListRobotByRobotId`, `GotoBuildRoad`, `GotoCityByBuildId`, `GotoCityByBuildUuid`, `GotoCityByCondBuildId`, `GotoCityPos`, `GotoCityTroopAndPointToGarbage`, `GotoColdStorage`, `GotoDabenPos`, `GotoDragonBuildPos`, `GotoFarm`, `GotoFarmGet`, `GotoFastBuildList`, `GotoFinishedBuilding`, `GotoMainBuildPos`, `GotoNearestCity`, `GotoNearestCityStronghold`, `GotoPasture`, `GotoPastureByUuid`, `GotoResourceBuild`, `GotoWorldBuildAndOpenUI`, `GotoWorldResource`, `OpenInCity`, `RequestNearestTradeStationWithLord`, `RequestNearestTradeStationWithoutLord`
- **Generic window/view** (12): `CloseAllWindows`, `GoMainUIBtn`, `GoToByQuestId`, `GoToWindow`, `GotoOpenView`, `GotoOpenViewOpenOptions`, `GotoOpenView_BattleReturnOpt`, `GotoTWSkillChipView`, `GotoTWView`, `GotoWorkerRecruitView`, `OpenChatView`, `OpenMinTrainTimePanel`
- **Hero/formation** (14): `GoFormation`, `GoHeroBag`, `GoHeroDetails`, `GoHeroDetailsByItemId`, `GoHeroStation`, `GoHeroStationScores`, `GoHeroTrust`, `GoHeroUniqueWeaponPreview`, `GoToCareerSelect`, `GoToPlayerCareer`, `GotoHeroAwaken`, `GotoHeroHonorWall`, `GotoHeroUniqueWepaon`, `GotoTrainSolider`
- **Monster/combat/PvE** (13): `FindMonster`, `GoAttackMonster`, `GoLandLockById`, `GoLandPve`, `GoLockMonster`, `GoPveLevel`, `GoSearchEnemy`, `GoTriggerPve`, `GoUnlockedTile`, `GoUnlockedTile_Newbies`, `GotoBossMonsterBetweenLv`, `GotoMonsterReward`, `LookAtFirstCanUnlockLandLockByPve`
- **Other** (15): `CheckCrossWar`, `DoPlayerAssistance`, `GoBagPackUseItem`, `GoLWParkourBattle`, `GoToByTypeAndParam`, `GoToCostTrainSpeed`, `GoToPlayerLevel`, `GoToServerPreCheck`, `GotoAnySpeed`, `GotoBattlefield`, `GotoDragonPos`, `GotoEffectLack`, `GotoPos`, `GotoPosForDragon`, `PersonalArmsGoto`
- **Science/upgrade** (9): `GoToCampScience`, `GoToCivilizationSparkBattle`, `GoToCivilizationSparkUpgrade`, `GoToMilitaryCampPromotion`, `GotoScience`, `OpenSciencePanel`, `OpenScienceQueue`, `OpenScienceTabPanel`, `OpenScienceTree`
- **Season/activity** (7): `CheckActIdInOffSeasonViewAndOpen`, `GoActWindow`, `GoActWindowDontClose`, `GotoSeasonActivityView`, `GotoSeasonBiuBiuActivity`, `GotoSeasonSnowStormActivity`, `OpenActivityCommonGroupWindow`
- **Shop/pay/reward** (11): `GoGiftMall`, `GoToMonthCard`, `GoToStorageShop`, `GotoActShopWindow`, `GotoActShopWindowMission`, `GotoGiftPackView`, `GotoGuluBox`, `GotoMigrationTicketShop`, `GotoPay`, `GotoPayTips`, `GotoSeasonWeekCardView`
- **World/map/march** (14): `GoRadarProbe`, `GoToCountBattleMap`, `GoToCurWorldPoint`, `GotoCurrMonopolyCell`, `GotoMarchCurPos`, `GotoServerZone`, `GotoWorldPos`, `JumpToMarchByUuid`, `JumpToWorldPoint`, `MoveToWorldMarchAndOpen`, `MoveToWorldPoint`, `MoveToWorldPointAndOpen`, `OnClickWorldPoint`, `TryJumpToWorld`

Highlights: monster nav `GoAttackMonster`, `FindMonster`, `GoLockMonster`, `GotoBossMonsterBetweenLv`, `GotoMonsterReward`; building `GoBarracks`, `GoFactory`, `GoHospital`, `GotoCityByBuildId`; hero `GoHeroBag`, `GoHeroDetails`, `GoFormation`; science `GotoScience`, `OpenScienceTree`; generic `GoToWindow`, `GotoOpenView`, `CloseAllWindows`, `GoMainUIBtn`.

## `SceneUtils` — 77 methods (complete)

Not just scene switching — it also holds the world-map **coordinate math** used elsewhere in these docs (city-navigation / world-tiles). Grouped:

- **Alliance points** (6): `CheckNewAllianceMemberSwitch`, `ClearALMemberPoints`, `ClearLastRequestALPointsTime`, `TryFastJoinAlliance`, `TryJoinAlliance`, `WorldSendGetALPointsRequest`
- **Audio/effects** (9): `PlayCityAMBSound`, `PlayCityBGM`, `PlayGuideSceneBgMusic`, `PlayWorldAMBSound`, `PlayWorldBGM`, `PlayWorldEffect`, `PlayWorldSceneBGMusic`, `TryPlayDarkneesSeasonBloodyNightBGM`, `TryPlayQueenOfBloodWorldBgm`
- **Coordinate/tile conversion** (19): `BigIndexToStandardIndex`, `BigIndexToTilePos`, `DecodeWorldPos`, `EncodeWorldPos`, `IndexToTilePos`, `TileIndexToWorld`, `TilePosToIndex`, `TileToUniqueTile`, `TileToWorld`, `TileXYToIndex`, `UniqueTileToWorld`, `WorldToClosestGridWorld`, `WorldToTile`, `WorldToTileFloat`, `WorldToTileFloatXY`, `WorldToTileIndex`, `WorldToTileXZ`, `WorldToUniqueTile`, `WorldXYToUniqueTileXY`
- **Geometry/distance/path** (13): `AxisAlignRectIntersectAxisAlignSegment`, `AxisAlignRectIntersectSegment`, `CalcMoveOnPath`, `CreatePathSegment`, `GetBlackLengthByStartEnd`, `GetIndexByOffset`, `GetIndexByOffsetX`, `GetIndexByOffsetY`, `GetNinePalacesOffset`, `GetNinePalacesOffsetByIndex`, `ManhattanDistance`, `TileDistance`, `TileDistanceToMyHome`
- **Land/zone/camp** (10): `GetCampIdByPointIndex`, `GetCampIdByPosId`, `GetCityMetaByPointIndex`, `GetOccupyServerIdByPosId`, `GetZoneIdByPosId`, `IsBlackLandActive`, `IsInBlackLand`, `IsInBlackOrYellowLand`, `IsInBlackRange`, `IsInYellowLand`
- **Other/sync** (5): `CheckNeedSyncCityBuildIdName`, `GetMarchCurPos`, `IsInCityField`, `IsIndexInWorld`, `SyncCityBuildIdName`
- **Pooling** (3): `RefreshUsePool`, `ReturnPoolV2`, `ReturnPoolV3`
- **Scene control** (12): `ChangeToCity`, `ChangeToWorld`, `CheckCanGotoWorld`, `CreateCity`, `CreateWorld`, `GetIsInCity`, `GetIsInPve`, `GetIsInWorld`, `GetSceneLuaArray`, `SceneDescription`, `SetIsInCity`, `UnInitSceneLuaArray`

Note the coordinate helpers `EncodeWorldPos`/`DecodeWorldPos`, `WorldToTile`/`TileToWorld`, `TileDistance`/`ManhattanDistance`/`TileDistanceToMyHome`, `BigIndexToTilePos` — a ready-made API for the point↔tile packing reverse-engineered in `world-tiles.md`.

## `UIWindowNames` — 2221 windows, grouped (full list: `docs/research/ui-open-data/ui_window_names.json`)

| group | count | examples |
|---|--:|---|
| Other | 580 | `BirthdayDataSetPanel`, `BountyHunterExchange`, `BountyHunterRules`, `BountyHunterSpecialEvent`, `BuyDiamondPackTips`, `CommonTipConfirm`, `CompleteImmdiatelyPanel`, `CrazyRockGame` … (+572) |
| Battle/war/rally | 503 | `ActLotteryBigRewardSpecialShow`, `ActLotteryPreOpenReward`, `AllyDuelScoreGacha`, `AllyDuelScoreGachaRules`, `ArmyFormationDetailPowerTips`, `ArmyFormationPowerTips`, `AttackCityS0RadarEventPopView`, `BanquetAttackMonsterFinRewardGet` … (+495) |
| Season/event/activity | 280 | `ActLotteryDraw100Result`, `ActLotteryDrawResult`, `ActMonopolyItemUse`, `AllyDrillUpdateBoss`, `DiggingLevelSingleView`, `KillZombieAlChallengeRank`, `KillZombieBoxUpgrade`, `LWActMeteoriteFlyTip` … (+272) |
| Hero/weapon/chip | 198 | `ActCitySkinExchangeItemUse`, `ExchangeHeroSuccess`, `HeroAwakenSkillPreview`, `HeroAwakenSkinPreview`, `HeroAwakenUpgradeStarEffect`, `HeroExchangeGuide`, `HeroExchangePreview`, `LWEffectOverviewHeroDetail` … (+190) |
| Building/city/base | 150 | `BankCity`, `BankCityHistory`, `CampSelectHistory`, `CampSelectHistoryS6`, `CampSelectList`, `CampSelectListS6`, `CityGiveUpPopup`, `CityProtectTimeTips` … (+142) |
| Alliance | 124 | `AllianceMilitaryPayRank`, `AllianceMilitaryRewardPreviewView`, `AllianceMilitaryRewardUpgrade`, `DiggingLevelAllianceCView`, `DiggingLevelAllianceView`, `LWAllianceCongratulationListPop`, `LWAllianceCongratulationPopView`, `LWAllianceMilitaryPayMainView` … (+116) |
| Shop/pay/gift/reward | 95 | `AccuRechargeOverlapDisplay`, `BankDepositInfo`, `BankHelp`, `BankHistory`, `BankReport`, `BankSetting`, `FirstPayGetExpClickTipsView`, `FirstPayGetExpHistoryPopView` … (+87) |
| Chat/social/mail | 89 | `LWUIActEasterEggChat`, `LWUIActEasterEggMessage`, `LWUIActEasterThumbsUpGlory`, `LWUIActMeteoriteRankChangedNotice`, `LWUIChatCommonShare`, `LWUIChatOperation`, `LWUIFriendsCircleSetting`, `LWUIMeteoriteConditionNotice` … (+81) |
| Setting/system/guide | 65 | `LWGuideMask`, `LWStatusSettingsView`, `LWUIMigrationChangeWord`, `LWUIMigrationGuide`, `LWUIMigrationPlayerMark`, `LWUIMigrationRequest`, `LWUIMigrationRequestConfirm`, `LWUIMigrationResult` … (+57) |
| Resource/production | 58 | `GoldBrickStoreConfirmPop`, `GoldTreePrayShow`, `GoldTreeRank`, `GoldTreeResult`, `GoldTreeRule`, `LWTradeStationRecord`, `LWUIActEasterEggYesterdayCoin`, `LWUIBagResourceOverview` … (+50) |
| Map/world/detect | 36 | `LWUIMasterySkillUseInWorld`, `LWUIWorldTrend`, `UIDetectCaveExploration`, `UIDetectEvent`, `UIDetectEventLevelUp`, `UIDetectEventPowerUpgrade`, `UIDetectSlotBoxOpen`, `UILLWorldMapTransport` … (+28) |
| Rank/leaderboard | 32 | `CrossOccupyRankDetail`, `LWCommonScoreDetail`, `LWUISheepRank`, `S6MilitaryEliteScoreTipsView`, `ScratchOffRankPage`, `TorchRelayRank`, `UIALChallengeRank`, `UIAllyDrillRank` … (+24) |
| Science/research | 11 | `LWSeasonVirusResearchLevelUp`, `UILWScienceDetail`, `UILWScienceInfo`, `UILWScienceMain`, `UILWScienceQueue`, `UILWScienceTree`, `UILWTrainDepartureScienceTips`, `UIScience` … (+3) |

## `DataCenter` — 464 managers, grouped (full list: `docs/research/ui-open-data/datacenter.json`)

`DataCenter.<X>` are the Lua data managers (each a singleton-ish table with getters). Grouped:

| group | count | examples |
|---|--:|---|
| Other | 141 | `AccountListManager`, `AccountManager`, `AirDropGarbageManager`, `AllyDrillDataManager`, `AllyDuelScoreGachaManager`, `BackGestureManager`, `BoardManager` … (+134) |
| Build/City/Decoration | 56 | `ActEpidemicZoneManager`, `BaseExpansionTemplateManager`, `BuildBubbleManager`, `BuildBubbleManagerHelper`, `BuildCanUpgradeEffectManager`, `BuildConnectEffectManager`, `BuildEffectManager` … (+49) |
| Activity/Season/Event | 54 | `ActCommunityLinkManager`, `ActConcertDataManager`, `ActDispatchTaskDataManager`, `ActDispatchTreasureManager`, `ActDragonManager`, `ActFrontBreakSundayDataManager`, `ActGhostreconBubblePosManager` … (+47) |
| Hero/Equip/Card | 42 | `BuildHeroCountdownManager`, `BuildHeroManager`, `BuildingDisplayCardManager`, `CommonEquipDataManager`, `CommonEquipTemplateManager`, `DominatorCockatriceUnlockManager`, `DominatorGuideManager` … (+35) |
| Alliance | 38 | `ActGhostreconAllianceManager`, `AllianceAlertDataManager`, `AllianceAutoInviteManager`, `AllianceBaseDataManager`, `AllianceCareerManager`, `AllianceCityLogManager`, `AllianceCityTemplateManager` … (+31) |
| Battle/War/March/Troop | 32 | `ActBattlePassData`, `ActChampionBattleManager`, `ActDispatchTaskFakeMarchManager`, `ActMeteoriteBattleManager`, `ArmyFormationDataManager`, `ArmyManager`, `BattleFieldAnimManager` … (+25) |
| UI/Guide/Template/RedDot | 30 | `AdaptiveBoxTemplateManager`, `AllyDuelConditionTipManager`, `AppearanceTemplateManager`, `DailyTaskTemplateManager`, `EffectNumberTemplateManager`, `GoldBrickTemplateManager`, `GovernmentTemplateManager` … (+23) |
| Shop/Pay/Reward/VIP | 17 | `CommonShopManager`, `CumulativeRechargeManager`, `DailyPackageManager`, `DailyPackageTemplateManager`, `FirstPayManager`, `GiftDetailShowDataManager`, `GiftSystemManager` … (+10) |
| Resource/Trade | 16 | `CollectResourceManager`, `CollectResourceTemplateManager`, `EventCollectManager`, `GatherResourceTemplateManager`, `LWGateTruckGoodsManager`, `LWResourceLackManager`, `MineCaveManager` … (+9) |
| World/Map/Point | 14 | `ActDetectTreasureDataManager`, `BirthPointTemplateManager`, `CanUnlockFogManager`, `CommonRedPointManager`, `DetectResultDataManager`, `LWWorldTrendDataManager`, `NextGarbagePointManager` … (+7) |
| Monster/Boss/Zombie | 11 | `ActBossDataManager`, `ActivityKillZombieManager`, `ActivityMonsterInvasionDataManager`, `LWBerserkBossManager`, `LWSeasonBossLoginDataManager`, `LWZombieRushManager`, `LWZombieRushPlanInfoManager` … (+4) |
| Chat/Social/Mail | 9 | `ChatCacheMsgManager`, `ChatEmojiManager`, `ChatEmojiTemplateManager`, `ChatPrivateDataManager`, `ChatPrivateSearchDataManager`, `GroupChatSetTemplateManager`, `LWChatPinManager` … (+2) |
| Science/Tech | 4 | `CampScienceDataManager`, `LWSpreadResearchDataManager`, `ScienceDataManager`, `ScienceTemplateManager` |

## `GuideOpenPanelType`

Only one value: **`Common = 1`** (the guide system's panel-open kind is not an alliance-style enum).


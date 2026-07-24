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
  `UIWindowNames.UIAllianceShop`. 96 alliance windows exist.
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

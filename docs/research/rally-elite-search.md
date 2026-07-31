# Searching a Fatal Elite via the world-map «лупа» (`UISearch`)

How the CREATE side of a rally finds its target. The wrong way (superseded) was a
**clone-hunt**: enumerate every `WorldMonster*(Clone)` on screen, `:OnClick()` each to open
its popup, and keep the first whose level matches. That scans whatever monsters happen to be
loaded (including ones others are attacking) and depends on what is visually on screen. The
right way is the game's **own search** — the magnifier a player presses — which resolves a
monster of the wanted level server-side and opens its popup by itself.

Driven out-of-process through xLua `SafeDoString` (docs/research/xlua-state.md), in **World**.

## The window: `UIWindowNames.UISearch` (`UISearchCtrl`)

`UIManager.Instance:OpenWindow(UIWindowNames.UISearch)` opens the world-map search panel
(the «лупа»). Its `Ctrl` (`UISearchCtrl`) methods of interest:

- `SetCurNumBySearchType(type, num, subType)` — set the **search level** (`num`) for a search
  kind. Persists via `SearchPanelDataManager:RecordUserSearch`.
- `GetCurNumBySearchType(type, subType)` — read it back (clamped to `GetMaxNumBySearchType`).
- `GetMaxNumBySearchType(type)` — the max level for a kind (`Monster` → 30, `Boss` → 35).
- `OnSearchClick(type, subType)` — **press the magnifier**: builds and sends the server request.
- `OnSearchEnd(pointId, uuid)` — the **response handler** (see below).
- `OnJumpClick(server, x, y)` — the unrelated X/Y coordinate jump (docs/research/world-tiles.md).

### `UISearchType` enum (read live)

```
None=0  Monster=1  Oil=2  Metal=3  Water=4  Boss=5  Resource=6  WorldDesert=7
```

Field monsters (incl. the red «Роковая Элита» behemoths) are searched under **`Monster`**;
event bosses under **`Boss`**. `Oil/Metal/Water/Resource/WorldDesert` are resource points.

## The flow

```lua
UIManager.Instance:OpenWindow(UIWindowNames.UISearch)
-- (one frame later)
local c = UIManager.Instance:GetStackTopWindow().Ctrl   -- w.Name == "UISearch"
c:SetCurNumBySearchType(UISearchType.Monster, LEVEL, 0) -- pick the level
c:OnSearchClick(UISearchType.Monster, 0)                -- press the magnifier
```

`OnSearchClick(type, subType)` branches on `type`:

- `Monster` → `SFSNetwork:SendMessage(MsgDefines.FindMonster, {type, pos, level, subType, pointId})`
- `Boss`    → `MsgDefines.FindMonsterBoss`
- `Resource`→ `MsgDefines.FindResourcePoint` (and desert/obsidian/flint variants)

then `GoToUtil.CloseAllWindows()` + `SearchPanelDataManager:RecordUserSearch`. `pos` is
`LuaEntry.Player:GetMainWorldPos()` (search near me). **The subType arg is required** — a nil
subType trips `SearchPanelDataManager` / `MonsterTemplateManager` with a "table index is nil".
`0` is the default sub-tab and works.

Confirmed live: with the daemon, `OnSearchClick(UISearchType.Monster, 0)` fired a
`SFSNetwork:SendMessage` with `msgId 471568` — the request goes out.

### The reply opens the popup itself

The server answers with `{pointId, uuid}`; the game's handler runs `OnSearchEnd`, which calls
`GoToUtil.MoveToWorldMarchAndOpen(GetSelfServerId, pointId, uuid)` — this **flies the camera to
the monster and opens its `UIWorldPoint` popup**, then closes the search panel. No tap. So the
top window flips `UISearch → UIWorldPoint` once the reply lands.

Read the popup the usual way (docs/research/world-monsters.md Finding 8 — the uuid arg is
required):

```lua
local w = UIManager.Instance:GetStackTopWindow()        -- w.Name == "UIWorldPoint"
local c = w.Ctrl
local md = c:GetMonsterData(c.uuid)                      -- md.level, md.canAttack
-- c.pointId, c.uuid, c.serverId
c:CloseSelf()                                            -- never DestroyAllWindow (kills the HUD)
```

`canAttack == 0` → rally-only «Роковая Элита» (raise «Стягивание»); `canAttack == 1` → a
soloable monster (not a rally elite — treat the level as "no rally elite found").

## Open ends

- **A monster must exist to be found.** On an idle account the search fired but no
  `UIWorldPoint` came back within ~10 s — the server had nothing of that level to return. This
  is inherent to the feature (the «лупа» locates/produces an elite; it does not conjure one from
  nothing). Whether a search literally *spawns* a Fatal Elite or only navigates to an existing
  one still needs a live session where one comes back.
- **Monster vs Boss tab — resolved: `Boss`.** A live search for a level-35 Fatal Elite was
  captured going out under `Boss` (`SFSNetwork.SendMessage("find.monster.boss", 35)`); the server
  answered and `MoveToWorldMarchAndOpen(pointId, uuid, server, 0)` opened its `UIWorldPoint`
  popup. The `Monster` tab sends `find.monster` (ordinary field monsters, no elite) and clamps
  the level at 30, so a level-35 elite is unreachable there — searching it returned nothing. The
  tool now defaults to `Boss` (`RALLY_ELITE_SEARCH` in `tools/rally_create.py`); `--type monster`
  still forces the other tab.
- **The CREATE wire is still UNPROVEN** (docs/research/rally-join.md, world-monsters.md
  Finding 17). Searching brings up the elite; raising the actual «Стягивание» banner
  (`MarchUtil.SendCreateMarchMessage` with `RALLY_CREATE_TARGET`) has no live capture yet.

Tool: `tools/rally_create.py` (`spawn_elite` drives the search; `create_on_level` searches then
raises). `python tools/rally_create.py --find --level N [--type monster|boss]` reports what the
search returns without raising anything.

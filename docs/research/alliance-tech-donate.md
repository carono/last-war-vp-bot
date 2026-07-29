# Alliance tech: donate to the priority technology

Reverse-engineered from the labelled trace
`results/traces/20260728_151312_жертва_альянсу_trace.log` (recorded while the player
walked Alliance → Alliance Tech → clicked the priority tech → pressed "Donate 1000"
several times) and then confirmed live via the warm daemon
(`tools/lua_daemon.py` + `tools/lib/lua_client.py`), game running. All calls go through
the game's own Lua VM (`SafeDoString`, see `docs/research/xlua-state.md`); the resource
donate path spends no diamonds and touches no pixels.

Consumers: the CLI `tools/alliance_donate.py` (via the shared core
`tools/lib/alliance_science.py`); the DSL action
`src/lastwar_bot/actions/donate_alliance_tech.md`, now a **one-line** `TAP` recipe
(`TAP donate_1000 xall`) whose button is defined in `tools/lib/game_buttons.py` and
whose Lua lives in `lua_actions.alliance_donate_batch`; runnable from the panel's
Scenarios tab. Raw Lua recipe: `actions/alliance_donate.lua`. Wire command:
`al.science.donate` (up/down, `tools/known_commands.txt`).

**No window needed.** `string.dump` of `UIAllianceScienceInfoCtrl.OnResDonateClick`
shows a body of three statements — the resource check
(`LuaEntry.Resource:GetCntByResType`, else `ShowTipsId` + `LWResourceLackUtil.GotoResLack`),
the attempts check (`GetResDonateRestCount`), and
`SFSNetwork.SendMessage(MsgDefines.AlScienceDonate, …)`. No `self` field is touched
(`self`, `btnPos` and `techPointPos` are unused parameters — the last two only anchor
the reward-fly animation). So the press is `require(<the ctrl module>)
.OnResDonateClick(nil, scienceId, res, resNum)`, sent with nothing open. Confirmed
live with `GetStackTopWindow() == nil`: attempts 14 → 13. `OnGoldDonateClick` has the
same shape (`LuaEntry.Player.gold` gate, then `MsgDefines.AlScienceGoldDonate`, no
`self` access); it is written the same way but has not been fired — it spends gems.

**Freeze pitfall (important):** the remaining-attempts count (`GetResDonateRestCount`)
only drops AFTER the server replies to `al.science.donate`. A tight in-Lua
`while rest>0 do OnResDonateClick() end` therefore never sees it fall, spins on the
main thread and **freezes the client**. Never wait for the server inside a chunk.

**Pacing — a whole quota is ONE call.** That same lag is what makes batching work: a
donation in flight lowers neither counter until the reply lands, so `n` presses inside
one chunk all pass the client-side gates and all reach the server. Since nothing in
the chunk waits, the freeze pitfall does not apply — the loop counts to a **fixed**
`n`, never to a condition. The caller reads the real count, spends exactly that many,
pauses, and re-reads to confirm; the count is still the stop condition, just not once
per press.

Measured live (warm daemon, `tools/lua_daemon.py`): a round trip into the VM is
~0.15 s, and the Lua loop inside it is free — 10 iterations cost the same as 1. One
chunk with `n=5` took attempts 13 → 8 in 0.21 s; the next, with `n=8`, emptied the
quota in 0.21 s. So a full 30-attempt quota is ~1 s including the confirming read,
against ~30 s for one press per call.

The knobs: `Button.batch_lua` / `Button.wait` in `tools/lib/game_buttons.py` for the
DSL, the `settle_after` argument of `press_donate` for the CLI. A round that fires
nothing ends the loop in both, so a count that refuses to fall cannot spin.

The batch cannot overshoot the quota — it is sized by a fresh count read — and it
stops early if the resources run out (the same gate the controller applies, checked
before each press inside the chunk). That gate lags the server by a round trip too,
so it catches "already broke", not "broke on this press".

## What the trace shows

The captured log is the **window-opening** half of the flow (the actual "Donate" presses
were deduped away — the trace ran with `dedup=True`). It nails down the data model:

- The alliance-tech list is `UIAllianceScienceCell.prefab` cells, each with a progress
  `Slider` (`ScienceBg/Slider`) and a **long-press donate button** — the tip string
  `alliance_science_longpress_tips_01` (a `UILongPressTrigger`) is the "hold to donate
  repeatedly" affordance. One press = one donation.
- Cell data is `AllianceScienceData.ParseData(...)`; a science is keyed by `scienceId`
  (the trace shows `SFSObject.PutInt(scienceId, 10011800)`).
- `SeasonUtil.HasAllianceScienceData()` gates whether the feature is available.

The trace alone does **not** contain the donate send. Everything below was recovered by
enumerating the loaded Lua modules (`package.loaded`) and class methods on the live VM.

## The data layer — `DataCenter.AllianceScienceDataManager`

| call | meaning |
|------|---------|
| `GetCurRecommendScience()` | **the priority tech** — the science the server recommends. Returns an `AllianceScienceData` object (fields below). This is how you pick the tech programmatically; no need to read the "recommended" banner off the screen. |
| `GetShowRedScienceId()` | scienceId currently carrying a red-dot (may be `nil`). |
| `GetResDonateRestCount()` | **resource** ("Donate 1000") attempts **left today**. |
| `GetResDonateMaxCount()` | daily cap on resource donations (observed `30`). |
| `GetGoldDonateRestCount()` | diamond-donate attempts left (observed `999999999` ≈ unlimited). |
| `GetGoldDonateMaxCount()` | diamond-donate cap. |
| `GetCanDonate()` | master gate — `false` when the resource quota is spent, no alliance, etc. |
| `GetOneAllianceScienceById(id)` / `GetAllianceScienceListByTab(tab)` | fetch a specific / a tab's worth of sciences. |

### The recommended-science object (`GetCurRecommendScience()`)

Live sample (scienceId `10021500`, mid-donation):

| field | value | meaning |
|-------|-------|---------|
| `scienceId` | `10021500` | the tech id (argument to the donate call) |
| `res` | `2` | **resType** — which resource the "Donate 1000" button spends |
| `resNum` | `1000` | resources per press — the number printed on the button |
| `maxNum` | `30` | daily resource-donation cap (matches `GetResDonateMaxCount`) |
| `goldNum` | `2` | diamonds per gold-donate press |
| `curLevel` / `maxLevel` | `9` / `10` | current / max tech level |
| `currentPro` / `needPro` | `6367950` / `8000000` | progress toward the next level |
| `state` | `1` | 1 = researchable/active |
| `name` / `description` | `454020` / `alliance_tech_desc_02_02` | text ids |

**"How many attempts are accumulated"** = `GetResDonateRestCount()` (of `GetResDonateMaxCount()`
= 30). Each resource press consumes one; you press until it hits 0. When it was captured the
player had already spent all 30 (`resRest = 0`, `GetCanDonate() = false`), which confirms the
counting. The diamond path is `GetGoldDonateRestCount()` and is effectively unlimited.

## The donate call — `UIAllianceScienceInfoCtrl`

The donate button is handled by the **detail** window's controller,
`UI.UIAlliance.UIAllianceScienceInfo.Controller.UIAllianceScienceInfoCtrl`:

```
OnResDonateClick(self, scienceId, resType, resNum, btnPos, techPointPos)   -- "Donate 1000"
OnGoldDonateClick(self, scienceId, goldNum, btnPos, techPointPos)          -- diamond donate
OnResearchClick(self, scienceId)                                          -- start research
OnScienceInfoClick / GotoScience                                          -- open detail
```

`btnPos` / `techPointPos` are only the fly-animation anchors — passing `nil` is fine, the
send fires regardless. Each `OnResDonateClick` emits one `AlScienceDonateMessage`
(`Net.Msgs.Alliance.AlScienceDonateMessage`, a `SFSBaseMessage`) → wire `al.science.donate`.

## The open → donate chain (verified live, end-to-end)

This is how a *player* gets there, and it is what the trace shows; the bot no longer
walks it (see "No window needed" above — the press is sent straight to the module).
Kept because it is the ground truth the headless call was checked against, and because
opening the panel is still the way to eyeball the result.

Each step lands on the **next frame**, so it is staged as separate daemon chunks with a
short settle between them (a single Lua chunk cannot see the window it just opened):

```lua
UIManager.Instance:OpenWindow(UIWindowNames.UIAllianceScience)             -- list (top = UIAllianceScience)
local list = UIManager.Instance:GetStackTopWindow()
list.Ctrl:OnScienceInfoClick(recommendedScience, nil)                      -- detail (top = UIAllianceScienceInfo)
local info = UIManager.Instance:GetStackTopWindow()
info.Ctrl:OnResDonateClick(rec.scienceId, rec.res, rec.resNum)             -- one press
```

Confirmed live: `OpenWindow` → `top = UIAllianceScience`; `OnScienceInfoClick(rec, tab)` →
`top = UIAllianceScienceInfo`; `OnResDonateClick(...)` returns `ok = true`. Because the
resource quota was already `0` that day, the call **safely gated** (no spend, no error) —
which is exactly the behaviour the loop relies on to stop.

**Observed since** (2026-07-29, quota unspent): `resRest` counting down for real —
14 → 13 on a single headless press, 13 → 8 on one chunk of five, 8 → 0 on one chunk of
eight. The diamond path is still never auto-fired (it costs gems).

## Auto-donate

The list controller exposes `UIAllianceScienceCtrl:ChangeAutoDonteState` (sic) and the list
carries an `AllianceScienceAutoDonate` component (`OnAllianceAutoDinateMessage`). This is the
in-game "auto-donate to the recommended tech" toggle; it is a lighter alternative to the
press-loop but its exact arguments were not pinned down (out of scope for this task).

## Usage

```bash
# report the priority tech and the current attempt counters (read-only):
/mnt/c/Python312/python.exe tools/alliance_donate.py --status

# donate every accumulated resource attempt to the priority tech:
/mnt/c/Python312/python.exe tools/alliance_donate.py

# cap the presses, or spend diamonds instead (careful — real gems):
/mnt/c/Python312/python.exe tools/alliance_donate.py --max 5
/mnt/c/Python312/python.exe tools/alliance_donate.py --gold
```

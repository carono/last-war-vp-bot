r"""Named game "buttons" — the friendly vocabulary the DSL `TAP` primitive speaks.

This is where the ugly engine names live so the recipes don't have to. A recipe says
`TAP alliance` / `TAP donate_1000 x30`; the real `UIManager.Instance:OpenWindow(...)`
and `OnResDonateClick(...)` calls are hidden here, one entry per button. Adding a new
button for a recipe author = add one entry below (name -> the Lua it fires).

Each button is a `Button`:
  * ``lua``   — the raw Lua chunk that "presses" it (runs in the game VM, verbatim).
  * ``wait``  — seconds to pause AFTER pressing, so the next step sees the result.
                Crucial for anything that waits on the server (a donation only lowers
                its counter after the reply) — the pause is baked in here, not in the
                recipe, which is why `TAP donate_1000 x30` is safe and never freezes.
  * ``label`` — a human phrase for the log.

The catalogue is deliberately small and readable. See docs/dsl.md ("TAP") and, for the
alliance-science calls, docs/research/alliance-tech-donate.md.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lua_actions as _lua_actions  # noqa: E402


@dataclass(frozen=True)
class Button:
    lua: str
    wait: float
    label: str
    # Optional: a Lua expression returning "how many times this button can still do
    # something right now" (e.g. remaining donations). Given, the recipe can say
    # `TAP <button> xall` to press exactly that many times instead of a fixed count —
    # the real count is substituted at run time, and the loop re-reads it so throttled
    # / dropped presses are retried until the count actually reaches zero.
    count_lua: str | None = None
    # Safety cap on `xall` iterations, so a miscounting expression can't spin forever.
    max_taps: int = 60


# The recommended-science object is fetched fresh inside each press (it is cheap and
# avoids stashing engine objects across daemon calls).
_REC = "DataCenter.AllianceScienceDataManager:GetCurRecommendScience()"

BUTTONS: dict[str, Button] = {
    # --- Alliance -> Alliance Tech -> donate to the priority tech -------------
    "alliance": Button(
        lua="UIManager.Instance:OpenWindow(UIWindowNames.UILWAlMain)",
        wait=1.2, label="Alliance panel",
    ),
    "alliance_tech": Button(
        lua="UIManager.Instance:OpenWindow(UIWindowNames.UIAllianceScience)",
        wait=1.5, label="Alliance Tech",
    ),
    "recommended_tech": Button(
        # Open the server-recommended (priority) tech's detail = the donate panel.
        lua=("local rec = %s "
             "UIManager.Instance:GetStackTopWindow().Ctrl:OnScienceInfoClick(rec, nil)"
             % _REC),
        wait=1.5, label="recommended tech",
    ),
    "donate_1000": Button(
        # One "Donate 1000" press. No-op (safely gated) once the quota is spent, so
        # repeating it more times than there are attempts is harmless. The in-game
        # long-press does the same thing — repeat this click at an interval — so a
        # small pause plus `xall` (which re-reads the count) reproduces "hold".
        lua=("local rec = %s "
             "local w = UIManager.Instance:GetStackTopWindow() "
             "if w and tostring(w.Name) == 'UIAllianceScienceInfo' then "
             "w.Ctrl:OnResDonateClick(rec.scienceId, rec.res, rec.resNum) end" % _REC),
        wait=0.12, label="Donate 1000",
        count_lua="DataCenter.AllianceScienceDataManager:GetResDonateRestCount()",
        max_taps=40,
    ),
    # --- Alliance -> help every member with an open help request -------------
    "help_ally_all": Button(
        # The in-game "Помочь всем" (Help All) button. OnHelpAll clears EVERY pending
        # request in one shot, so it needs no UI window open — it reads the help list
        # and fires the al.help.all message straight from the data manager. Helping is
        # unlimited; only the daily HELP POINTS are capped (GetAllianceHelpSliderData ->
        # {todayHelpPoint, maxHelpCount=1000}), and hitting that cap does NOT stop you
        # from helping. See docs/research/alliance-tech-donate.md sibling notes.
        lua="DataCenter.AllianceHelpDataManager:OnHelpAll()",
        wait=1.0, label="Help All (alliance)",
        # GetHelpNum = how many requests are still waiting; one OnHelpAll drops it to 0,
        # so `xall` presses once and re-reads to confirm (and mops up any that arrive in
        # the gap) instead of guessing a fixed count.
        count_lua="DataCenter.AllianceHelpDataManager:GetHelpNum()",
        max_taps=10,
    ),
    # --- Alliance -> gifts: open the section, then claim each tab -------------
    # The "Подарки альянса" window has two "collect all" buttons — ordinary gifts
    # (type 1) and premium/privilege gifts (type 2) — handled by the same click
    # handler UILWAllianceGiftCtrl:OnGetAllBtnClick(type) (nparams=2 = self+type).
    # On the wire each press is alliance.reward.allreceive {type}; opening the
    # window sends alliance.reward.list. Unlike a headless data call these are the
    # real button clicks, so the window has to be open first (they read the loaded
    # list). Live-confirmed: opening the window and firing OnGetAllBtnClick(2)
    # collected the premium gifts in-game. See docs/research/alliance-gift-collection.md.
    "alliance_gifts": Button(
        lua="UIManager.Instance:OpenWindow(UIWindowNames.UILWAllianceGift)",
        wait=1.3, label="Alliance gifts panel",
    ),
    "collect_gifts_ordinary": Button(
        # "Забрать всё" on the ordinary-gifts tab (type 1). No-op if that tab is
        # already empty. Guarded so it only fires with the gift window on top.
        lua=("local w=UIManager.Instance:GetStackTopWindow() "
             "if w and tostring(w.Name)=='UILWAllianceGift' then w.Ctrl:OnGetAllBtnClick(1) end"),
        wait=0.8, label="Collect ordinary gifts",
    ),
    "collect_gifts_premium": Button(
        # "Забрать всё" on the premium/privilege tab (type 2). Same guard.
        lua=("local w=UIManager.Instance:GetStackTopWindow() "
             "if w and tostring(w.Name)=='UILWAllianceGift' then w.Ctrl:OnGetAllBtnClick(2) end"),
        wait=0.8, label="Collect premium gifts",
    ),
    "dismiss_reward_popup": Button(
        # After a collect the game raises a "you received …" reward-list modal
        # (UIGiftPackageRewardGet, confirmed live). It sits on a SEPARATE UI layer,
        # NOT on the main window stack — GetStackTopWindow() still returns the gift
        # window, which is why a top-of-stack close never sees it. So scan every
        # window name, and for each reward-show popup that is currently open
        # (name carries 'Reward' or 'GetGift') close it via GetWindow -> CloseSelf.
        # Safe: the gift window ('UILWAllianceGift') and the HUD ('UIMain') match
        # neither token, so they are never touched; a no-op when no popup is up.
        lua=("local mgr=UIManager.Instance "
             "for _,name in pairs(UIWindowNames) do local s=tostring(name) "
             "if s:find('Reward') or s:find('GetGift') then "
             "local ok,open=pcall(function() return mgr:IsWindowOpen(name) end) "
             "if ok and open then local w=mgr:GetWindow(name) "
             "if w and w.Ctrl and w.Ctrl.CloseSelf then pcall(function() w.Ctrl:CloseSelf() end) end "
             "end end end"),
        wait=0.5, label="dismiss reward popup",
    ),
    # --- base -> collect every ready resource building -----------------------
    "collect_base_resources": Button(
        # "Собрать все ресурсы с базы" — the base's own "Collect All" in one press.
        # The base's resource generators are production lines tracked by
        # DataCenter.ProductLineManager; harvesting one is SendCollect(uuid), and
        # the game's Collect-All button simply fires that for every ready building.
        # So this loops GetAllBuildUuids() and calls SendCollect on the ready ones.
        # READINESS IS MANDATORY: SendCollect on a building with nothing banked is
        # NOT a no-op — the server answers `building.production.collect` with
        # errorCode 602026 "In production, please be patient." and the client pops
        # that toast, one per building (confirmed on the wire, task #1087).
        # GetBuildingCurrStorage(uuid) is the banked amount and the server bills
        # exactly floor() of it (stor 30155.12 -> resNum 30155, stor 210.87 ->
        # resNum 210, both captured live), so `>= 1` is precisely the server's own
        # accept condition — and it also skips the sub-unit window right after a
        # collect, where storage is positive but floors to 0.
        # Verified live through the warm daemon: sweeping all 38 production
        # buildings dropped their pending storage from ~29k to ~6k (16 ready -> 0).
        # No world positions, itemId grouping or 205-building scan — the earlier
        # BuildingUtils.CityCollectionByItemId approach is retired.
        # See docs/research/resource-collection.md.
        lua=(
            "local plm=DataCenter.ProductLineManager "
            "for _,u in pairs(plm:GetAllBuildUuids() or {}) do "
            "local ok,stor=pcall(function() return plm:GetBuildingCurrStorage(u) end) "
            "if ok and (stor or 0)>=1 then pcall(function() plm:SendCollect(u) end) end end"
        ),
        wait=1.5, label="Collect base resources",
    ),
    # --- base -> collect every supply truck that has arrived ------------------
    "collect_trucks": Button(
        # "Собрать грузовики". A supply truck surfaces on the base as a build bubble:
        # BuildBubbleType.TruckTravelling while en route, TruckReward / TruckReady
        # once it has arrived. Tapping the ready bubble collects its goods, so this
        # fires OnClick on every TruckReward/TruckReady bubble — the literal
        # reproduction of the "Сбор грузовика ресурсов" trace. Like help_ally_all it
        # clears all pending ones in a single press (no window needs to be open).
        # See docs/research/resource-collection.md.
        lua=(
            "local m=DataCenter.BuildBubbleManager local BT=_G.BuildBubbleType "
            "for _,v in pairs(m.allBuildBubble or {}) do local ty=v.param and v.param.buildBubbleType "
            "if ty==BT.TruckReward or ty==BT.TruckReady then pcall(function() v:OnClick() end) end end"
        ),
        wait=1.2, label="Collect ready trucks",
    ),
    # --- general navigation --------------------------------------------------
    "close": Button(
        # Close the top window by state (pop one off the UI stack). Repeat with xN.
        lua=("local w = UIManager.Instance:GetStackTopWindow() "
             "if w and w.Ctrl and w.Ctrl.CloseSelf then w.Ctrl:CloseSelf() end"),
        wait=0.4, label="close window",
    ),
}


# --- Government -> ministry: apply for one of the server's eight posts --------
# One button per post ("apply_minister_science", "apply_vice_president", …) rather
# than one parameterised button, because `TAP` takes no arguments and a recipe that
# names the post it wants reads like the in-game click it replaces. Every entry is
# the same gated one-liner from lua_actions.ministry_apply(); the ids, the names and
# the gate are documented in docs/research/ministry-apply.md.
#
# `max_taps=1` on purpose: an application is a single press. `xall` then means "press
# only if the post can actually be applied for right now" — which is what makes
# submit_ministry.md able to walk a preference list and stop at the first post that
# takes it. (Without the cap, a server that queues applicants instead of granting them
# instantly would leave CheckCanApply true and the loop would re-apply in a spin.)
for _pid, (_slug, _en, _ru) in _lua_actions.MINISTRY_POSTS.items():
    BUTTONS["apply_%s" % _slug] = Button(
        lua=_lua_actions.ministry_apply(_pid),
        wait=1.2, label="Apply: %s (%s)" % (_en, _ru),
        count_lua=_lua_actions.ministry_can_apply(_pid),
        max_taps=1,
    )


def get(name: str) -> Button | None:
    return BUTTONS.get(name)


def names() -> list[str]:
    return sorted(BUTTONS)

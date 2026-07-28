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

from dataclasses import dataclass


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
    # --- general navigation --------------------------------------------------
    "close": Button(
        # Close the top window by state (pop one off the UI stack). Repeat with xN.
        lua=("local w = UIManager.Instance:GetStackTopWindow() "
             "if w and w.Ctrl and w.Ctrl.CloseSelf then w.Ctrl:CloseSelf() end"),
        wait=0.4, label="close window",
    ),
}


def get(name: str) -> Button | None:
    return BUTTONS.get(name)


def names() -> list[str]:
    return sorted(BUTTONS)

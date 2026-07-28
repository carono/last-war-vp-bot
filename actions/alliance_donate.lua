-- Donate all accumulated attempts to the alliance's PRIORITY (recommended) tech.
--
-- Human-readable recipe in the game's own Lua primitives. Reverse-engineered from
-- results/traces/*жертва_альянсу* and confirmed live via the daemon — see
-- docs/research/alliance-tech-donate.md. The runner tools/alliance_donate.py stages
-- these lines across frames (each OpenWindow / click lands the NEXT frame, so the
-- window it opens is only reachable on the following daemon chunk).

local mgr = DataCenter.AllianceScienceDataManager
local tech = mgr:GetCurRecommendScience()               -- the PRIORITY tech (server pick)

UIManager.Instance:OpenWindow(UIWindowNames.UIAllianceScience)          -- open Alliance Tech
-- [next frame] the list is now on top; open the priority tech's detail panel:
UIManager.Instance:GetStackTopWindow().Ctrl:OnScienceInfoClick(tech, nil)
-- [next frame] the detail ("Donate 1000" panel) is on top; press until attempts run out:
local info = UIManager.Instance:GetStackTopWindow()
while mgr:GetResDonateRestCount() > 0 and mgr:GetCanDonate() do          -- accumulated presses
    info.Ctrl:OnResDonateClick(tech.scienceId, tech.res, tech.resNum)    -- one "Donate 1000"
end
-- Diamond variant: info.Ctrl:OnGoldDonateClick(tech.scienceId, tech.goldNum)  -- spends gems

# Upgrade every base decoration that is ready.
# ru: Повысить украшения на базе, которые уже можно повысить.
#
# In the game this is: tap the building that carries decorations, switch to its
# handbook, pick a decoration whose upgrade is available and press the upgrade
# button. This does the same without opening any of it — it finds the decoration
# itself, so nothing has to be picked or prepared beforehand.
#
# It only presses on a decoration that can really be upgraded: the upgrade step
# has to exist at the decoration's current level, and a spare duplicate of that
# decoration has to be banked to feed into it. One spare copy buys one step of
# progress towards the next star. Spares are rare, so the ordinary outcome is
# that this does nothing and says so — that is not a failure, and pressing
# anyway would be refused by the game.
#
# To see where each decoration stands (the star score it is at, the threshold it
# is climbing to, how many steps its spares would buy), run
# `TAP dump_decorations` — it writes a line per decoration and sends nothing.
# `TAP decorations` opens the decoration window if you want to look.
#
# Run on a clock (`timers.item.upgrade_decorations`, every 4 hours by default, off
# until switched on): the gate below is what makes that safe — a tick that finds
# nothing ready reads the count, says so with numbers and stops before the TAP, so
# a run four hours after the last one spends nothing it did not already have.

READ_LUA (function() local bm=DataCenter.BuildManager local function scan(cb) for itemId in pairs(bm:GetAllDecoratorBuildingData() or {}) do local ok,d=pcall(function() return bm:GetMaxLvBuildDataByBuildId(itemId) end) if ok and d then local ok2,adv=pcall(function() return BuildingUtils.IsExistAdvanceUpgrade(itemId,d.level) end) if ok2 and adv then local ok3,cells=pcall(function() return BuildingUtils.GetDecorateUpLevelBuilds(d) end) local steps=0 if ok3 and type(cells)=='table' then for _,c in pairs(cells) do local n=tonumber(c.count) if n and n>0 then steps=steps+n end end end if cb(itemId,d,steps) then return true end end end end return false end  local n=0 scan(function(_,_,steps) n=n+steps end) return n end)() INTO steps

READ_LUA (function() local bm=DataCenter.BuildManager local function scan(cb) for itemId in pairs(bm:GetAllDecoratorBuildingData() or {}) do local ok,d=pcall(function() return bm:GetMaxLvBuildDataByBuildId(itemId) end) if ok and d then local ok2,adv=pcall(function() return BuildingUtils.IsExistAdvanceUpgrade(itemId,d.level) end) if ok2 and adv then local ok3,cells=pcall(function() return BuildingUtils.GetDecorateUpLevelBuilds(d) end) local steps=0 if ok3 and type(cells)=='table' then for _,c in pairs(cells) do local n=tonumber(c.count) if n and n>0 then steps=steps+n end end end if cb(itemId,d,steps) then return true end end end end return false end  local checked,ready=0,0 scan(function(_,_,steps) checked=checked+1 if steps>0 then ready=ready+1 end end) return tostring(checked)..' decoration(s) checked, '..tostring(ready)..' had a spare banked, '..tostring(checked-ready)..' skipped (no spare duplicate banked)' end)() INTO summary

IF steps == 0
    LOG "Decorations: {summary}. Nothing to upgrade this run."
    STOP

TAP upgrade_decoration xall

READ_LUA (function() local bm=DataCenter.BuildManager local function scan(cb) for itemId in pairs(bm:GetAllDecoratorBuildingData() or {}) do local ok,d=pcall(function() return bm:GetMaxLvBuildDataByBuildId(itemId) end) if ok and d then local ok2,adv=pcall(function() return BuildingUtils.IsExistAdvanceUpgrade(itemId,d.level) end) if ok2 and adv then local ok3,cells=pcall(function() return BuildingUtils.GetDecorateUpLevelBuilds(d) end) local steps=0 if ok3 and type(cells)=='table' then for _,c in pairs(cells) do local n=tonumber(c.count) if n and n>0 then steps=steps+n end end end if cb(itemId,d,steps) then return true end end end end return false end  local n=0 scan(function(_,_,steps) n=n+steps end) return n end)() INTO steps_left

LOG "Decorations: {summary}; {steps} step(s) were available and spent, {steps_left} left after this run (0 expected unless the per-run cap of 25 presses was hit)."

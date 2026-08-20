# Upgrade every base decoration that is ready — every level its spares buy, in one go.
# ru: Повысить украшения на базе, которые уже можно повысить, — сразу на все доступные уровни.
#
# In the game this is: tap the building that carries decorations, switch to its
# handbook, pick a decoration whose upgrade is available and hold the upgrade button
# down for a long press. This does the same without opening any of it — it finds every
# ready decoration itself, so nothing has to be picked or prepared beforehand.
#
# It only presses on a decoration that can really be upgraded: the upgrade step has to
# exist at the decoration's current level, and a spare duplicate of that decoration has
# to be banked to feed into it. One spare copy buys one point of progress towards the
# next star. Spares are rare, so the ordinary outcome is that this does nothing and says
# so — that is not a failure, and pressing anyway would be refused by the game.
#
# **A LONG PRESS, not a tap held down and let go 25 times.** The wire message
# (`decorator.progress.upgrade`) already carries a COUNT, not a slot — the game's own
# long press just sends a bigger count in the SAME one message, and nothing about the
# gate cares which: `num` is capped to the spares actually banked either way. Proven
# live on 2026-08-20 (#1560): decoration 103401000 read 25 spares banked, one message
# carried `num=25`, and the very next read had already crossed the whole gap — one round
# trip instead of 25. So every ready decoration gets its WHOLE available count in ONE
# message, all fired inside a single game-VM call (the same reasoning
# `alliance_donate_batch` spends a whole quota on: a round trip costs about 0.15 s and
# the loop inside it is free). A decoration whose spares outrun the immediate next star
# spends only what that star prices — the game caps the count itself — and whatever is
# left over is picked up the next time this runs, once the following star's own cell
# opens up.
#
# To see where each decoration stands (the star score it is at, the threshold it is
# climbing to, how many steps its spares would buy), run `TAP dump_decorations` — it
# writes a line per decoration and sends nothing. `TAP decorations` opens the decoration
# window if you want to look. `TAP upgrade_decoration xall` still exists for a one-step-
# at-a-time press if that is ever wanted, but this recipe no longer uses it.
#
# Run on a clock (`timers.item.upgrade_decorations`, every 4 hours by default, off until
# switched on): the gate below is what makes that safe — a tick that finds nothing ready
# reads the count, says so with numbers and stops before sending anything, so a run four
# hours after the last one spends nothing it did not already have.

READ_LUA (function() local bm=DataCenter.BuildManager local function scan(cb) for itemId in pairs(bm:GetAllDecoratorBuildingData() or {}) do local ok,d=pcall(function() return bm:GetMaxLvBuildDataByBuildId(itemId) end) if ok and d then local ok2,adv=pcall(function() return BuildingUtils.IsExistAdvanceUpgrade(itemId,d.level) end) if ok2 and adv then local ok3,cells=pcall(function() return BuildingUtils.GetDecorateUpLevelBuilds(d) end) local steps=0 if ok3 and type(cells)=='table' then for _,c in pairs(cells) do local n=tonumber(c.count) if n and n>0 then steps=steps+n end end end if cb(itemId,d,steps) then return true end end end end return false end  local n=0 scan(function(_,_,steps) n=n+steps end) return n end)() INTO steps

IF steps == 0
    LOG "Decorations: nothing ready this run — no decoration with an upgrade step has a spare duplicate banked."
    STOP

# One game-VM call: every ready decoration gets its whole available count in one
# message, and the reply is a report string — checked/upgraded/total, then one line
# per decoration actually sent (before -> after / goal, and by how much), then the
# ones a spare is still missing for.
READ_LUA (function() local bm=DataCenter.BuildManager local function scan(cb) for itemId in pairs(bm:GetAllDecoratorBuildingData() or {}) do local ok,d=pcall(function() return bm:GetMaxLvBuildDataByBuildId(itemId) end) if ok and d then local ok2,adv=pcall(function() return BuildingUtils.IsExistAdvanceUpgrade(itemId,d.level) end) if ok2 and adv then local ok3,cells=pcall(function() return BuildingUtils.GetDecorateUpLevelBuilds(d) end) local steps=0 if ok3 and type(cells)=='table' then for _,c in pairs(cells) do local n=tonumber(c.count) if n and n>0 then steps=steps+n end end end if cb(itemId,d,steps) then return true end end end end return false end  local checked,ready,total=0,0,0 local sent_lines,why={},{} scan(function(itemId,d,steps) checked=checked+1 local score,goal='?','?' pcall(function() local cells=BuildingUtils.GetDecorateUpLevelBuilds(d) for _,c in pairs(cells or {}) do goal=c.nextScore if tonumber(c.count) and tonumber(c.count)>0 then score=c.needScore end end end) if steps>0 then ready=ready+1 total=total+steps pcall(function() SFSNetwork.SendMessage(MsgDefines.DecoratorProgressUpgradeMessage, d.uuid, steps) end) sent_lines[#sent_lines+1]=tostring(itemId)..': '..tostring(score)..'->'..tostring((tonumber(score) or 0)+steps)..'/'..tostring(goal)..' (+'..tostring(steps)..')' else why[#why+1]=tostring(itemId)..' (goal '..tostring(goal)..')' end end) local out='checked '..tostring(checked)..', '..tostring(ready)..' upgraded now, '..tostring(total)..' step(s) sent total' if #sent_lines>0 then out=out..' :: '..table.concat(sent_lines,'; ') end if #why>0 then out=out..' :: no spare banked for: '..table.concat(why,', ') end return out end)() INTO report

WAIT 2.0

READ_LUA (function() local bm=DataCenter.BuildManager local function scan(cb) for itemId in pairs(bm:GetAllDecoratorBuildingData() or {}) do local ok,d=pcall(function() return bm:GetMaxLvBuildDataByBuildId(itemId) end) if ok and d then local ok2,adv=pcall(function() return BuildingUtils.IsExistAdvanceUpgrade(itemId,d.level) end) if ok2 and adv then local ok3,cells=pcall(function() return BuildingUtils.GetDecorateUpLevelBuilds(d) end) local steps=0 if ok3 and type(cells)=='table' then for _,c in pairs(cells) do local n=tonumber(c.count) if n and n>0 then steps=steps+n end end end if cb(itemId,d,steps) then return true end end end end return false end  local n=0 scan(function(_,_,steps) n=n+steps end) return n end)() INTO steps_left

LOG "Decorations: {report}; {steps_left} step(s) left after this run (0 unless a decoration crossed into a new star whose own cell needs a fresh read to spend the rest)."

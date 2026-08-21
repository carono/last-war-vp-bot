# Bring the hunt's squad home — the game's own recall. (the second squad)
# ru: Вернуть отряд охоты домой — штатный игровой отзыв. (второй отряд)
#
# The recall is sent for the MARCH, not for the squad (#1702): `OnBackHome(formation)`
# frees a squad that is walking and leaves one that has landed on a mine and started
# gathering — measured live against a gather with 24 762 seconds left on it, twice.

ARGS squad = 2

LUA DataCenter.__lw_gold2_squad = {squad}
# NOT `golden_arm` (#1702). Arming builds the run's state from nothing, which throws
# away the zombie «Найти ближайшего» fixed — and then «Атаковать выбранного» after a
# recall answers «цель не зафиксирована», which is exactly what the operator hit. This
# points at the squad and touches nothing else.
TAP golden2_use_squad
TAP golden2_unstick
WAIT 6
CALL fill_empty_squads
READ_LUA (function() local out = {} pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do local i = math.floor(tonumber(v.index) or -1) out[#out+1] = 'squad' .. i .. ' state=' .. tostring(v.state) .. ' free=' .. tostring((function(f) local st = math.floor(tonumber(f.state) or -1) if st ~= 0 then return false end local ok, idle = pcall(function() return f:IsFree() end) if ok and idle ~= nil then return (idle and true or false) end return true end)(v)) .. ' soldiers=' .. tostring(v.totalSoldierNum) end end) local n = -1 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms ~= nil then n = ms.Count end end) out[#out+1] = 'marches=' .. tostring(n) return table.concat(out, ' | ') end)() INTO squad_state
LOG "after the recall: {squad_state}"

# Bring the hunt's squad home — the game's own recall.
# ru: Вернуть отряд охоты домой — штатный игровой отзыв.
#
# The recall is sent for the MARCH, not for the squad (#1702): `OnBackHome(formation)`
# frees a squad that is walking and leaves one that has landed on a mine and started
# gathering — measured live against a gather with 24 762 seconds left on it, twice.

ARGS squad = 2

LUA DataCenter.__lw_gold_squad = {squad}
TAP golden_arm
TAP golden_unstick
WAIT 6
CALL fill_empty_squads
READ_LUA (function() local out = {} pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do local i = math.floor(tonumber(v.index) or -1) out[#out+1] = 'squad' .. i .. ' state=' .. tostring(v.state) .. ' canMarch=' .. tostring(v.canMarch) .. ' soldiers=' .. tostring(v.totalSoldierNum) end end) local n = -1 pcall(function() local ms = DataCenter.WorldMarchDataManager:GetOwnerMarches() if ms ~= nil then n = ms.Count end end) out[#out+1] = 'marches=' .. tostring(n) return table.concat(out, ' | ') end)() INTO squad_state
LOG "after the recall: {squad_state}"

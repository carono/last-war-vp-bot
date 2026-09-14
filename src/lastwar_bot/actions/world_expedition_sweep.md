# Press «авто-испытание» in every open zone of «Мировой поход».
# ru: Нажать «авто-испытание» в каждой открытой зоне «Мирового похода».
#
# HEADLESS and FREE: the event rations nothing — no attempt counter, no stamina, no item
# — so one press a day per zone costs the account nothing and earns whatever the lineup
# can still clear (`docs/research/world-expedition.md`).
#
# A ZONE THAT CLEARS NOTHING IS NOT A FAILURE. The auto challenge walks up the stages
# until the lineup loses one, which is the ordinary end of it: «упёрлись в сильного
# соперника» is a result, not an error, and tomorrow's press tries the same wall again
# with whatever the account has grown since. So the run reports how far each zone moved
# and ends well even when nothing moved at all.
#
# A zone whose lineup is empty is skipped rather than pressed — `world_expedition_lineup`
# is what fills one, and the errand calls it first.
#
# NOTHING HERE STOPS: a `STOP` inside a called recipe halts the CALLER with it, so a
# «nothing to do» that stopped here would take the rest of the day's run with it — the
# lineup's «all set already» would cancel the auto challenge and both claims. So every
# «nothing to do» is an `IF` with a line in the log, and this file ends by running out.

CALL read_world_expedition

IF open == 0
    LOG "Мировой поход: раунд не идёт — нажимать нечего"
ELSE
    IF live == 0
        LOG "Мировой поход: ни одна зона ещё не открыта"
    ELSE
        READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = DataCenter.LWSeasonTowerManager local FM = DataCenter.ArmyFormationDataManager local S = DataCenter.__lw_ge or {} DataCenter.__lw_ge_before = {} local sent = 0 for i = 1, 4 do if num(S['o' .. i]) == 1 and num(S['h' .. i]) == 1 then local sid = num(S['id' .. i]) local heroes = {} pcall(function() local f = M:GetFormation(sid) for uuid, slot in pairs(f.heroes or {}) do heroes[#heroes + 1] = {heroUuid = uuid, index = num(slot)} end end) if #heroes == 0 then local a = nil pcall(function() a = FM:GetOneArmyInfoByIndex(1) end) if type(a) == 'table' and type(a.localIndexToHeroDic) == 'table' then for slot = 1, 12 do local uuid = a.localIndexToHeroDic[slot] if uuid ~= nil then heroes[#heroes + 1] = {heroUuid = uuid, index = slot} end end end end if sid > 0 and #heroes > 0 then DataCenter.__lw_ge_before[i] = num(S['f' .. i]) local ok = pcall(function() M:Battle(sid, 1, heroes) end) if ok then sent = sent + 1 end end end end return sent end)() INTO ge_sent

        LOG "Мировой поход: авто-испытание запущено в зонах — {ge_sent}"

        IF ge_sent == 0
            LOG "Мировой поход: нажимать было негде — ни в одной открытой зоне нет отряда"
        ELSE
            WAIT 8

            CALL read_world_expedition

            READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local S = DataCenter.__lw_ge or {} local was = DataCenter.__lw_ge_before or {} local out = {} local moved = 0 for i = 1, 4 do if was[i] ~= nil then local d = num(S['f' .. i]) - num(was[i]) moved = moved + d out[#out + 1] = 'зона ' .. i .. ': ' .. num(was[i]) .. ' → ' .. num(S['f' .. i]) end end DataCenter.__lw_ge_moved = moved return table.concat(out, ' · ') end)() INTO ge_report

            READ_LUA (function() return math.floor(DataCenter.__lw_ge_moved or 0) end)() INTO ge_moved

            LOG "Мировой поход: пройдено этапов {ge_moved} — {ge_report}"

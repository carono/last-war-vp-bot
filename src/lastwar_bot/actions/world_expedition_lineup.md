# Put a lineup into every open zone of «Мировой поход» that still has none.
# ru: Собрать отряд в каждой открытой зоне «Мирового похода», где его ещё нет.
#
# A zone with an empty lineup cannot be challenged, and a round opens its four zones over
# a week — so a new zone arrives empty and would sit out the day it opened. The lineup is
# the account's own FIRST squad, read out of the game rather than written down anywhere:
# the heroes standing in squad 1 today are the heroes that go, EACH IN ITS OWN SLOT.
#
# THE SLOT IS READ OFF `localIndexToHeroDic`, never off `GetHeroUuidListInSquad`. The two
# hold the same five heroes in DIFFERENT orders — measured live, the list's key is its own
# position and not the squad's slot — so the first version of this recipe put the front
# hero at the back and the panel's zones fought in an order nobody had chosen.
#
# THE OVERLORD DOES NOT TRAVEL. `season.tower.save.formation` carries `stageId`,
# `chipSetId` and the hero list and nothing else — proven by catching the message itself,
# and again by sending one with a dominator key added, which the server dropped. So the
# recipe attaches it locally (`SetLocalDominator`), says so in the log when a zone comes
# back without one, and a zone that must fight with the Overlord wants one touch in the
# game's own window, once per round (`docs/research/world-expedition.md`).
#
# NOTHING IS TAKEN OUT OF THE BASE. The expedition's lineup is a formation of its own —
# it cannot march and holds no soldiers — so the same heroes go on defending the base and
# riding rallies while they clear stages here (`docs/research/world-expedition.md`).
#
# A zone that already has a lineup is left exactly as it is: a person who arranged one by
# hand keeps it.
#
#     ARGS squad = 1

CALL read_world_expedition

IF open == 0
    LOG "Мировой поход: раунд не идёт — отряд собирать некуда"
ELSE
    IF unset == 0
        LOG "Мировой поход: во всех открытых зонах отряд уже стоит"
    ELSE
        READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = DataCenter.LWSeasonTowerManager local FM = DataCenter.ArmyFormationDataManager local S = DataCenter.__lw_ge or {} local idx = num({squad}) if idx < 1 then idx = 1 end local a = nil pcall(function() a = FM:GetOneArmyInfoByIndex(idx) end) local heroes = {} if type(a) == 'table' and type(a.localIndexToHeroDic) == 'table' then for slot = 1, 12 do local uuid = a.localIndexToHeroDic[slot] if uuid ~= nil then heroes[#heroes + 1] = {heroUuid = uuid, index = slot} end end end if #heroes == 0 then local ok, list = pcall(function() return FM:GetHeroUuidListInSquad(idx) end) if ok and type(list) == 'table' then for slot, uuid in pairs(list) do heroes[#heroes + 1] = {heroUuid = uuid, index = num(slot)} end end end if #heroes == 0 then return -1 end local dom = nil if type(a) == 'table' then dom = a.dominatorUuid or a.localDominatorUuid end local saved = {} local done = 0 for i = 1, 4 do if num(S['o' .. i]) == 1 and num(S['h' .. i]) == 0 then local sid = num(S['id' .. i]) if sid > 0 then local set = pcall(function() local f = M:GetFormation(sid) if dom ~= nil then pcall(function() f:SetLocalDominator(dom) end) end M:SaveFormation(sid, num(f.localChipSetId) > 0 and num(f.localChipSetId) or 1, heroes) end) if set then done = done + 1 saved[#saved + 1] = sid end end end end DataCenter.__lw_ge_want = heroes DataCenter.__lw_ge_dom = dom DataCenter.__lw_ge_saved = saved return done end)() INTO ge_set

        IF ge_set < 0
            FAIL "Мировой поход: отряд {squad} пуст — в нём нет ни одного героя"

        LOG "Мировой поход: отряд поставлен в зон — {ge_set}"
        WAIT 3

        READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = DataCenter.LWSeasonTowerManager local want = DataCenter.__lw_ge_want or {} local saved = DataCenter.__lw_ge_saved or {} local dom = DataCenter.__lw_ge_dom local bad = {} local nodom = 0 local good = 0 for _, sid in ipairs(saved) do local f = nil pcall(function() f = M:GetFormation(sid) end) local got = {} if type(f) == 'table' and type(f.heroes) == 'table' then for uuid, slot in pairs(f.heroes) do got[tostring(uuid)] = num(slot) end end local miss = 0 local n = 0 for _, h in ipairs(want) do n = n + 1 if got[tostring(h.heroUuid)] ~= h.index then miss = miss + 1 end end local extra = 0 for _ in pairs(got) do extra = extra + 1 end extra = extra - n if extra < 0 then extra = 0 end if miss > 0 or extra > 0 then bad[#bad + 1] = sid .. ':' .. miss .. '/' .. n .. (extra > 0 and ('+' .. extra) or '') else good = good + 1 end if dom ~= nil and type(f) == 'table' and f.dominatorUuid == nil then nodom = nodom + 1 end end DataCenter.__lw_ge_bad = table.concat(bad, ' ') DataCenter.__lw_ge_nodom = nodom DataCenter.__lw_ge_badn = #bad return good end)() INTO ge_ok

        READ_LUA (function() return tostring(DataCenter.__lw_ge_bad or '') end)() INTO ge_bad
        READ_LUA (function() return math.floor(DataCenter.__lw_ge_badn or 0) end)() INTO ge_badn
        READ_LUA (function() return math.floor(DataCenter.__lw_ge_nodom or 0) end)() INTO ge_nodom

        IF ge_badn > 0
            LOG "Мировой поход: ОТРЯД ЛЁГ НЕ ТАК — зона:промахов/героев {ge_bad} (сошлось зон — {ge_ok} из {ge_set})"
        ELSE
            LOG "Мировой поход: состав и порядок сошлись во всех зонах — {ge_ok} из {ge_set}"

        IF ge_nodom > 0
            LOG "Мировой поход: Повелитель не встал в зон — {ge_nodom}: игра не передаёт его в сохранении отряда, поставьте его один раз в окне похода за раунд"

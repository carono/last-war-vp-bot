# Put a lineup into every open zone of «Мировой поход» that still has none.
# ru: Собрать отряд в каждой открытой зоне «Мирового похода», где его ещё нет.
#
# A zone with an empty lineup cannot be challenged, and a round opens its four zones over
# a week — so a new zone arrives empty and would sit out the day it opened. The lineup is
# the account's own FIRST squad, read out of the game (`GetHeroUuidListInSquad`) rather
# than written down anywhere: the heroes standing in squad 1 today are the heroes that go.
# The Overlord is attached where the game takes it (`SetLocalDominator`).
#
# NOTHING IS TAKEN OUT OF THE BASE. The expedition's lineup is a formation of its own —
# it cannot march and holds no soldiers — so the same heroes go on defending the base and
# riding rallies while they clear stages here (`docs/research/world-expedition.md`).
#
# A zone that already has a lineup is left exactly as it is: a person who arranged one by
# hand keeps it.
#
#     ARGS squad = 1      which of the player's squads the heroes are taken from
#
# NOTHING HERE STOPS: a `STOP` inside a called recipe halts the CALLER with it, so a
# «nothing to do» that stopped here would take the rest of the day's run with it — the
# lineup's «all set already» would cancel the auto challenge and both claims. So every
# «nothing to do» is an `IF` with a line in the log, and this file ends by running out.

ARGS squad = 1

CALL read_world_expedition

IF open == 0
    LOG "Мировой поход: раунд не идёт — отряд собирать некуда"
ELSE
    IF unset == 0
        LOG "Мировой поход: во всех открытых зонах отряд уже стоит"
    ELSE
        READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = DataCenter.LWSeasonTowerManager local FM = DataCenter.ArmyFormationDataManager local S = DataCenter.__lw_ge or {} local idx = num({squad}) if idx < 1 then idx = 1 end local heroes = {} local ok, list = pcall(function() return FM:GetHeroUuidListInSquad(idx) end) if ok and type(list) == 'table' then for slot, uuid in pairs(list) do heroes[#heroes + 1] = {heroUuid = uuid, index = num(slot)} end end if #heroes == 0 then return -1 end local dom = nil pcall(function() local a = FM:GetOneArmyInfoByIndex(idx) dom = a.localDominatorUuid or a.dominatorUuid end) local done = 0 for i = 1, 4 do if num(S['o' .. i]) == 1 and num(S['h' .. i]) == 0 then local sid = num(S['id' .. i]) if sid > 0 then local set = pcall(function() local f = M:GetFormation(sid) if dom ~= nil then pcall(function() f:SetLocalDominator(dom) end) end M:SaveFormation(sid, num(f.localChipSetId) > 0 and num(f.localChipSetId) or 1, heroes) end) if set then done = done + 1 end end end end return done end)() INTO ge_set

        IF ge_set < 0
            FAIL "Мировой поход: отряд {squad} пуст — в нём нет ни одного героя"

        LOG "Мировой поход: отряд поставлен в зон — {ge_set}"
        WAIT 2

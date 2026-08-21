# Find the nearest golden zombie IN THE REGISTRY, fix its tile, and show it.
# ru: Найти в реестре ближайшего золотого зомби, зафиксировать координаты и показать.
#
# The operator's own words for what this button is: «посмотреть в реестр монстров,
# вычислить ближайшего до выбранного отряда или базы, зафиксировать его координаты»
# (#1702). So it is ARITHMETIC over a list the panel already holds, not an expedition:
#
#   * no lap of the map — the registry is what the scans and the sweeps have filled, and
#     «Обновить карту» is its own button for when a person wants it refilled;
#   * no camera move before the sum. The chain moves the camera because it is about to
#     ORDER something and the client only answers for ground it holds; this button only
#     measures, and a tile's coordinates do not depend on where anybody is looking;
#   * one flight at the END, to show what was found. That is the answer, not a step.
#
# THE ORIGIN IS THE SQUAD, OR THE BASE WHEN THE SQUAD IS AT HOME. Both are said out
# loud in the report line (`from=anchor` / `from=home`), because «ближайший» means
# nothing until you know what it is nearest to.

ARGS squad = 2
ARGS radius = 2000

LUA DataCenter.__lw_gold_squad = {squad}
LUA DataCenter.__lw_gold_radius = {radius}
LUA DataCenter.__lw_gold_reach = 0
TAP golden_arm
READ_LUA (function() local p = DataCenter.__lw_gold or {} if p.formation == nil then return 0 end if (tonumber(p.soldiers) or 0) <= 0 then return -1 end return 1 end)() INTO armed
IF armed == 0
    FAIL "the squad is not one this account has — nothing to hunt with"

# WHERE THE MEASURING STARTS. A squad standing at home is measured from the base, and a
# squad that is out is measured from where the hunt last sent it. Nothing is asked of
# the game beyond the formation's own state.
READ_LUA (function() local p = DataCenter.__lw_gold or {} local out = 0 pcall(function() for _, v in pairs(DataCenter.ArmyFormationDataManager.ArmyFormationList) do if tostring(v.uuid) == tostring(p.formation) then if math.floor(tonumber(v.state) or 0) ~= 0 then out = 1 end end end end) if out == 1 then if p.anchor == nil then p.anchor = p.last_sent end else p.anchor = nil end DataCenter.__lw_gold = p return out end)() INTO squad_is_out
IF squad_is_out == 1
    LOG "measuring from where the squad stands"
IF squad_is_out == 0
    LOG "the squad is at home — measuring from the base"

# …AND THE GROUND AROUND THE ORIGIN IS ASKED ABOUT WHEN THE SQUAD IS OUT (#1702). The
# client only holds what the camera has been shown — about sixty tiles around it — so a
# registry filled by an earlier sweep can be full of far zombies and hold none of the
# ones standing beside the squad. The operator saw exactly that: «рядом с ним есть
# зомби», and the pick threw him hundreds of tiles away. At home this is not needed —
# the camera lives there — so the flight is paid only when the squad is in the field.
IF squad_is_out == 1
    TAP golden_scan
    TAP golden_look_from
    READ_LUA (function() local p = DataCenter.__lw_gold or {} return (math.floor(tonumber(p.looked_moved) or 0) == 1) and 1 or 0 end)() INTO looked_moved
    IF looked_moved == 1
        WAIT 1
    TAP golden_scan

# The registry, as it stands. Empty only on a panel that has never scanned: then one
# cheap look at the ground under the camera fills it rather than sending the person to
# another button.
READ_LUA (function() local p = DataCenter.__lw_gold or {} return math.floor(tonumber(p.found) or 0) end)() INTO found
IF found == 0
    LOG "the registry is empty — taking one look at the ground here"
    TAP golden_scan
    READ_LUA (function() local p = DataCenter.__lw_gold or {} return math.floor(tonumber(p.found) or 0) end)() INTO found

TAP golden_pick
READ_LUA (function() local p = DataCenter.__lw_gold or {} return (p.cur ~= nil) and 1 or 0 end)() INTO picked
IF picked == 0
    LOG "nothing to choose from — the registry holds {found} golden zombie(s)"
    STOP "no target"

READ_LUA (function() local p = DataCenter.__lw_gold or {} local c = p.cur if c == nil then return '' end local srv = math.floor(tonumber(c.server or p.server) or 0) local core = 'X:' .. tostring(math.floor(tonumber(c.x) or 0)) .. ' Y:' .. tostring(math.floor(tonumber(c.y) or 0)) if srv > 0 then return '#' .. tostring(srv) .. ' ' .. core end return core end)() INTO where
READ_LUA (function() local p = DataCenter.__lw_gold or {} local c = p.cur if c == nil then return 'none' end local o = p.anchor or p.home local hd = nil pcall(function() hd = tonumber(SceneUtils.TileDistanceToMyHome(c.pid, p.server)) end) return 'at=' .. tostring(c.x) .. ',' .. tostring(c.y) .. ' dist=' .. tostring(math.floor(tonumber(p.curdist) or 0)) .. ' from=' .. tostring(p.curfrom or '-') .. ' origin=' .. tostring(o and o.x) .. ',' .. tostring(o and o.y) .. ' home_dist=' .. tostring(hd and math.floor(hd + 0.5)) .. ' src=' .. tostring(c.src or '-') .. ' queued=' .. tostring(#(p.targets or {})) .. ' attacks=' .. tostring(math.floor(tonumber(p.attacks) or 0)) end)() INTO pick
LOG "found a golden zombie at {where} — {pick}"

# …and the camera goes to it, because being shown what you asked for is the answer.
TAP golden_look

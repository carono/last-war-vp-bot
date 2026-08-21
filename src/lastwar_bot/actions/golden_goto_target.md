# Fly the camera to the zombie that was chosen. A look, and nothing else.
# ru: Перелететь камерой к выбранному зомби. Только взгляд, ничего не отправляется.
#
# The phone's half of «перейти по координатам» (#1702): in the window a person clicks
# the coordinate in the log and the panel flies there, and a phone has no log to click.
# So the same flight is a press, and both front-ends can act on the tile that was found.

READ_LUA (function() local p = DataCenter.__lw_gold or {} return (p.cur ~= nil) and 1 or 0 end)() INTO have_target
IF have_target == 0
    STOP "nothing chosen — press «найти ближайшего» first"
TAP golden_look
WAIT 1
TAP golden_scan
READ_LUA (function() local p = DataCenter.__lw_gold or {} local c = p.cur if c == nil then return '' end local srv = math.floor(tonumber(c.server or p.server) or 0) local core = 'X:' .. tostring(math.floor(tonumber(c.x) or 0)) .. ' Y:' .. tostring(math.floor(tonumber(c.y) or 0)) if srv > 0 then return '#' .. tostring(srv) .. ' ' .. core end return core end)() INTO where
LOG "the camera is on the chosen zombie at {where}"

--lua

require('dist/init-develop')

:: start ::

if (cooldown('attachHandle') == 1 and Window:attachHandle() == 0) then
    Game:start()
end

Alliance:applyHelp()
Alliance:clickHealTroops()

if (cooldown('checkAllianceMapNormalize') == 1) then
    Map:normalize()
end

if (cooldown('checkAlliance') == 1) then
    Game:checkAlliance()
end

if (cooldown('autoRally', 5000) == 1) then
    Rally:joinIfExist()
end

Alliance:applyHelp()

if (Game:isLogout() == 1) then
    Game:clickLogout()
end

close_connection_error()

goto start
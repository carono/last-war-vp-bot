--lua

require('dist/init-develop')

local logout_timeout = 7 * 60 * 1000
local allianceServiceCooldown = 60 * 1000

:: start ::

if (cooldown('attachHandle') == 1) then
    if (Window:attachHandle() == 0) then
        Game:start()
    end
    reset_cooldown('attachHandle')
end

Alliance:applyHelp()
Alliance:clickHealTroops()

if (cooldown('checkAllianceMapNormalize') == 1) then
    Map:normalize()
    reset_cooldown('checkAllianceMapNormalize')
end

if (cooldown('checkAlliance', allianceServiceCooldown) == 1) then
    Game:checkAlliance()
    reset_cooldown('checkAlliance')
end

if (cooldown('autoRally', allianceServiceCooldown) == 1) then
    Rally:joinIfExist()
    reset_cooldown('autoRally')
end

Alliance:applyHelp()

if (kfindcolor(893, 638, 4143607)) == 1 then
    left(893, 638)
    wait(logout_timeout)
end

close_connection_error()

goto start
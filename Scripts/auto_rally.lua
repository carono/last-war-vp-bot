--lua

require('dist/init')
reset_cooldown('checkMinistryRequests')

:: start ::
Game:waitIfUserIsActive()

if (cooldown('attachHandle') == 1 and Window:attachHandle() == 0) then
    Game:start()
end

if (cooldown('checkMinistryRequests') == 1) then
  Game:checkMinistryRequests()
end

if (cooldown('checkAllianceMapNormalize') == 1) then
    Map:normalize()
end

if (cooldown('checkAlliance') == 1) then
    Game:checkAlliance()
end

if (cooldown('autoRally', 5000) == 1) then
    Rally:joinIfExist()
end

if (Game:isLogout() == 1) then
    Game:clickLogout()
end

Alliance:applyHelp()
Alliance:clickHealTroops()

close_connection_error()

goto start
--lua

require('dist/init')
reset_cooldown()

Map:normalize()
Game:resetUserActivity()

:: start ::
log('clear')

if (cooldown('attachHandle') == 1 and Window:attachHandle() == 0) then
    Game:start()
end

if (cooldown('checkMinistryRequests', 15000) == 1) then
    Game:checkMinistryRequests()
end

if (cooldown('MapNormalize') == 1) then
    Map:normalize()
end

if (cooldown('checkAlliance') == 1) then
    Game:checkAlliance()
end

if (cooldown('autoRally', 15000) == 1) then
    Rally:joinIfExist()
end

if (Game:isLogout() == 1) then
    Game:clickLogout()
end

Alliance:applyHelp()
Alliance:clickHealTroops()
Game:getRallyPresents()
--Game:readAllMail()

close_connection_error()

Game:waitIfUserIsActive()


goto start
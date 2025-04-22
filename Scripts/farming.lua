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

if (Game:isLogout() == 1) then
    Game:clickLogout()
end

if (cooldown('checkMinistryRequests', 30) == 1) then
    Game:checkMinistryRequests()
end

if (cooldown('MapNormalize') == 1) then
    Map:normalize()
end

if (cooldown('checkAlliance', 300) == 1) then
    Alliance:open()
    Alliance:checkTech()
    Alliance:getPresent()
    Map:normalize()
end

if (cooldown('autoRally', 5) == 1) then
    Rally:joinIfExist()
end

if (cooldown('collectSimpleResources', 180) == 1) then
    Game:collectSimpleResources()
end

if (cooldown('collectPromoGifts', 180) == 1) then
    Promo:collectGifts()
end

if (cooldown('checkSurvival', 180) == 1) then
    Map:openBase()
    Base:greetingSurvivals()
    Base:getVipPresents()
end

Alliance:applyHelp()
Alliance:clickHealTroops()
Game:getRallyPresents()
Game:collectDailyPresents()

if (Game:isLogout() == 1) then
    Game:clickLogout()
end

close_connection_error()
Game:waitIfUserIsActive()

goto start
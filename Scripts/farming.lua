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

if (Game:isLogout() == 1 and Game:userIsActive() == 0) then
    Game:clickLogout()
end

if (cooldown('MapNormalize') == 1 and Game:userIsActive() == 0) then
    Map:normalize()
end

if (cooldown('checkAlliance', 600) == 1 and Game:userIsActive() == 0) then
    Alliance:open()
    Alliance:checkTech()
    Alliance:getPresent()
    Map:normalize()
end

if (cooldown('autoRally', 5) == 1 and Game:userIsActive() == 0) then
    Rally:joinIfExist()
end

if (cooldown('collectSimpleResources', 600) == 1 and Game:userIsActive() == 0) then
    Game:collectSimpleResources()
end

if (cooldown('collectPromoGifts', 600) == 1 and Game:userIsActive() == 0) then
    Promo:collectGifts()
end

if (cooldown('checkSurvival', 600) == 1 and Game:userIsActive() == 0) then
    Map:openBase()
    Base:greetingSurvivals()
    Base:getVipPresents()
    Base:getShopGifts(1)
end

if (Game:userIsActive() == 0) then
    Alliance:applyHelp()
    Alliance:clickHealTroops()
    Game:getRallyPresents()
    Game:collectDailyPresents()
end

if (Game:isLogout() == 1) then
    Game:clickLogout()
end

close_connection_error()
Game:waitIfUserIsActive()

wait(30000)
goto start
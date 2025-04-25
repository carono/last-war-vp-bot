--lua

require('dist/init')

reset_cooldown()
Map:normalize()
Game:resetUserActivity()

:: start ::
log('clear')

if (cooldown('attachHandle') == 1 and Window:attachHandle() == 0) then
    log('Start the game')
    Game:start()
    Window:repos()
end

if (Game:isLogout() == 1 and Game:userIsActive() == 0) then
    Notify:accountIsLogout()
    Game:clickLogout()
end

if (cooldown('MapNormalize') == 1 and Game:userIsActive() == 0) then
    Map:normalize()
end

if (cooldown('autoRally', 5) == 1 and Game:userIsActive() == 0) then
    log('Try join to rally')
    Rally:joinIfExist()
end

if (cooldown('checkBase', 600) == 1 and Game:userIsActive() == 0) then
    log('Start checking tasks on base')
    Base:openBase(1)
    Base:getVipPresents()
    Base:getShopGifts(1)
    Base:collectMilitaryTrack()
    Base:collectAdvancedResourcesByOneClick()
    Base:greetingSurvivals()
end

if (cooldown('checkAlliance', 600) == 1 and Game:userIsActive() == 0) then
    log('Start checking alliance tasks')
    Alliance:open()
    Alliance:checkTech()
    Alliance:getPresent()
    Map:normalize()
end

if (cooldown('secretMissions', 600) == 1) then
    log('Start checking secret missions')
    if (Base:clickMissionButton() == 1) then
        Game:collectSecretMissions()
        Game:collectAllianceSecretMissions()
        Map:normalize()
    end
end

if (cooldown('collectPromoGifts', 600) == 1 and Game:userIsActive() == 0) then
    log('Start checking gifts')
    Promo:collectGifts()
end

if (cooldown('readMail', 600) == 1 and Game:userIsActive() == 0) then
    log('Start checking gifts')
    Game:readAllMail(1)
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

local farming_timeout = Storage:get('farming_timeout', 0)
if farming_timeout > 0 then
    log('Waiting farming iteration ' .. farming_timeout .. 's')
    wait(Storage:get('farming_timeout', 0) * 1000)
end

goto start
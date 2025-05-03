--lua


function notify_treasure()
    if (Storage:get('treasure_notify', 0) == 1 and Radar:hasTreasureExcavatorNotification() == 1 and Game:isLogout() == 0) then
        local telegram_chat_id = Storage:get('treasure_telegram_chat_id', Storage:get('telegram_chat_id'))
        local telegram_bot_id = Storage:get('telegram_bot_id')
        local treasure_message = Storage:get('treasure_message', 'Digging treasure')
        if (telegram_bot_id ~= nil) then
            Notify:sendTelegramMessage(treasure_message, telegram_chat_id, telegram_bot_id)
            log('Click treasure notify and wait 10s')
            click(1045, 970, 10000)
        end
    end
end

function check_handle()
    if (cooldown('attachHandle') == 1 and Window:attachHandle() == 0) then
        log('Start the game')
        Game:start()
        Window:repos()
    end
end

function check_logout()
    if (Game:isLogout() == 1 and Game:userIsActive() == 0) then
        Notify:accountIsLogout()
        Game:clickLogout()
    end
end

function normalize_map()
    if (cooldown('MapNormalize') == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) then
        Map:normalize()
    end
end

function auto_rally()
    if (cooldown('autoRally', 5) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) then
        log('Try join to rally')
        Rally:joinIfExist()
    end
end

function check_base()
    if (cooldown('checkBase', 600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) then
        log('Start checking tasks on base')
        Base:openBase(1)
        Base:getVipPresents()
        Base:getShopGifts(1)
        Base:collectMilitaryTrack()
        Base:collectAdvancedResourcesByOneClick()
        Base:greetingSurvivals()
    end
end

function check_alliance()
    if (cooldown('checkAlliance', 600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) then
        log('Start checking alliance tasks')
        Alliance:open()
        Alliance:checkTech()
        Alliance:getPresent()
        Map:normalize()
    end
end

function check_secret_missions()
    if (cooldown('secretMissions', 600) == 1) then
        log('Start checking secret missions')
        if (Base:clickMissionButton() == 1) then
            Game:collectSecretMissions()
            Game:collectAllianceSecretMissions()
            Map:normalize()
        end
    end
end

function collect_promo_gifts()
    if (cooldown('collectPromoGifts', 600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) then
        log('Start checking gifts')
        Promo:collectGifts()

    end
end

function read_mail()
    if (cooldown('readMail', 600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) then
        log('Start checking gifts')
        Game:readAllMail(1)
    end
end

function check_events()
    if (cooldown('checkEvents', 600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) then
        if (Event:open() == 1) then
            Event:openGWTab()
            Event:collectGW()
            Map:normalize()
        end
    end
end

function farming_timeout()
    local farming_timeout = Storage:get('farming_timeout', 0)
    if farming_timeout > 0 then
        log('Waiting farming iteration ' .. farming_timeout .. 's')
        wait(Storage:get('farming_timeout', 0) * 1000)
    end
end

function check_connection()
    if kfindcolor(913, 573, 2546431) == 1 then
        log('Connection error, click something 1')
        click(913, 573, 400)
    end
    if kfindcolor(862, 593, 16765462) == 1 then
        log('Connection error, click something 2')
        click(862, 593, 400)
    end
    if (Game:hasUpdateFinishedModal() == 1) then
        log('Updates is finished, click OK and wait 30s')
        click(910, 597, 30000)
    end

    if (is_blue(1061, 597) == 1 and is_yellow(856, 593) == 1 and Game:isPreloadMenu() == 1) then
        log('Connection error, click confirm and wait 30s')
        click(1061, 597, 30000)
    end

    if (cooldown('checkConnections', 600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) then
        if (Game:checkConnection() == 0) then
            Game:restart()
        end
    end
end
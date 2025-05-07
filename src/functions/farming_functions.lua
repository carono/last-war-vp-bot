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
        --Game:checkFreeTavernHero()
    end
end

function check_alliance()
    if (cooldown('checkAlliance', 600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) then
        log('Start checking alliance tasks')
        if (Alliance:open() == 1) then
            Alliance:checkTech()
            Alliance:getPresent()
            Map:normalize()
        end
    end
end

function check_secret_missions(force)
    if ((cooldown('secretMissions', 600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) or force == 1) then
        log('Start checking secret missions')

        if (Hud:clickButton('missions') == 1) then
            log('Collect missions')
            Game:collectSecretMissions()
            Game:collectAllianceSecretMissions()
            click(772, 419, 400)

            log('Setting missions')
            Game:rotateSecretMissionsToUR()
            Game:setSecretMissions()
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

function military_race()
    if (cooldown('militaryRace', 600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) then
        log('Start checking military race')
        if (MilitaryRaceEvent:getEventNumber() >= 3) then
            DroneRace:getStamina()
        end
        if (MilitaryRaceEvent:getEventNumber() >= 4) then
            local rally = Rally:createDoomElite()
            if (rally >= 1 and rally < 4) then
                reset_cooldown('militaryRace')
            end
        end
    end
end

function vs()
    if (cooldown('vs', 600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) then
        VS:collectGifts()
    end
end

function check_events(force)
    if ((cooldown('checkEvents', 600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) or force == 1) then
        if (Event:open() == 1) then
            Hud:leftScrollModalTabs(10)
            Hud:clickFirstTab()
            local i = 0
            repeat
                local tab = Event:getEventTabName()
                log('See ' .. tab .. ' event')
                if (tab ~= 0) then
                    if (tab == 'military_race') then
                        Event:collectMilitaryRaceGifts()
                    end
                    if (tab == 'judgment_day' == 1) then
                        Event:collectJudgmentDayGifts()
                    end
                    if (tab == 'code_name') then
                        CodeNameEvent:execute()
                    end
                end
                if (Event:clickNextTab() == 0) then
                    Hud:rightScrollModalTabs(2)
                end
                i = i + 1
            until (tab == 'social' or i >= 10)
        end
        Map:normalize()
    end
end

function check_radar()
    if (cooldown('checkRadar', 600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) then
        if (VS:isRadarDay() == 1) then

            Radar:collectFinishedTasks()
        end

        if (MilitaryRaceEvent:getEventNumber() >= 4) then
            Radar:autoFinishTasks()
        end

        Radar:collectFinishedTrucks()
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
--lua
function farming()
    log('clear')
    check_handle()
    check_logout()
    -- ################

    normalize_map()
    notify_treasure()

    -- ################

    check_secret_missions()
    weekly_events()

    check_events()
    military_race()
    vs()
    check_base()

    check_alliance()
    check_radar()

    collect_promo_gifts()
    auto_rally()
    doom_rally()
    read_mail()
    collect_daily_presents()
    ministry_notify()

    check_connection()

    Alliance:applyHelp()
    Alliance:clickHealTroops()

    Game:waitIfUserIsActive()

    if (cooldown('restart', preventive_restart) == 1) then
        Game:restart(30, 'Preventive restart')
        reset_cooldown()
        cooldown('restart', preventive_restart, true)
    end

    wait(1000)
    farming_timeout()
    farming()
end

function weekly_events(force)
    if ((cooldown('weekly_events') == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) or force == 1) then
        log('clear')
        Event:executeGenerals()
    end
end

function ministry_notify()
    if (Storage:get('ministry_hat_notify', 0) == 1) then
        local hat = Ministry:hasMinistryHat()
        if (hat ~= nil and cooldown_is_expire('ministry_hat') == 1) then
            Notify:sendTelegramMessage('Has ministry hat: ' .. hat)
            cooldown('ministry_hat', 6 * 60, true)
        end
        if (Notify:hasLabel() == 1 and cooldown_is_expire('label') == 1) then
            Notify:sendHasLabel('Has info label')
            cooldown('label', 4 * 60, true)
        end
    end
end

function collect_daily_presents(force)
    if ((cooldown('collect_daily_presents') == 1 and Game:isLogout() == 0) or force == 1) then
        log('clear')
        Game:collectDailyPresents()
    end
end

function dig_treasure()
    local x, y = find_color(1029, 848, 1042, 923, '(14476276,15187370)')
    if (x > 0) then
        click(x, y, 500)
        if (click_and_wait_color(884, 531, 6211909, 889, 646) == 1 and click_if_green(889, 646) == 1) then
            click_blue_button(958, 832)
        end
    end
end

function wait_treasure()
    local x, y = find_color(852, 445, 937, 551, 193445)
    x, y = Window:modifyCord(x, y)
    local timer
    if (x > 0) then
        log('Waiting treasure....')
        repeat
            x1, y1 = find_color(852, 445, 937, 551, 193445)
        until x1 == 0
        timer = ktimer(5000)
        while os.clock() < timer do
            kleft(x, y + 10)
        end
    end
end

function notify_treasure(force)
    if ((Radar:hasTreasureExcavatorNotification() == 1 and Game:isLogout() == 0) or force == 1) then
        log('clear')
        local telegram_chat_id = Storage:get('treasure_telegram_chat_id', Storage:get('telegram_chat_id'))
        local telegram_bot_id = Storage:get('telegram_bot_id')
        local treasure_message = Storage:get('treasure_message', 'Digging treasure')
        if (telegram_bot_id ~= nil and Storage:get('treasure_notify', 0) == 1) then
            Notify:sendTelegramMessage(treasure_message, telegram_chat_id, telegram_bot_id, false)
        end
        log('Click treasure notify and wait 10s')
        click_and_wait_color(1045, 970, blue_color, 1162, 1020)
        wait(4000)
        dig_treasure()
        wait_treasure()
    end
end

function check_handle()
    if (cooldown('attachHandle') == 1 or Window:attachHandle() == 0) then
        log('clear')
        if (Window:attachHandle() == 0) then
            Game:start()
        else
            Window:repos()
            Window:resizeCanonical()
        end
    end
end

function check_logout(force)
    if (Game:isLogout() == 1 or force == 1) then
        log('clear')
        if (Storage:get('logout_notify', 0) == 1) then
            Notify:accountIsLogout()
        end
        Game:clickLogout()
    end
end

function normalize_map(force)
    if ((cooldown('MapNormalize') == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) or force == 1) then
        log('clear')
        Map:normalize()
        wait(1000)
    end
end

function auto_rally(force)
    --if (MilitaryRaceEvent:getEventNumber() == 5) then
    --    return
    --end

    if ((use_auto_rally == 1 and cooldown('autoRally', 5) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) or force == 1) then
        log('clear')
        log('Try join to rally')
        Game:getRallyPresents()
        Rally:joinIfExist()
    end
end

function doom_rally(force)
    if ((cooldown('doom_rally', 30) == 1 and MilitaryRaceEvent:getEventNumber() ~= 4 and MilitaryRaceEvent:getEventNumber() ~= 3 and Game:userIsActive() == 0 and Game:isLogout() == 0) or force == 1) then
        local rally = Rally:createDoomElite()
        log('Rally result ' .. rally)
        if (rally >= 1) then
            reset_cooldown('doom_rally')
        end
    end
end

function check_base(force)
    if ((cooldown('checkBase', 3600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) or force == 1) then
        log('clear')
        log('Start checking tasks on base')
        Base:openBase(1)
        Base:getVipPresents()
        Base:getShopGifts(1)
        Base:collectAdvancedResourcesByOneClick()
        Base:collectMilitaryTrack()
        Base:greetingSurvivals()
        --Game:checkFreeTavernHero()
    end
end

function check_alliance(force)
    if ((cooldown('checkAlliance', 3600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) or force == 1) then
        log('clear')
        log('Start checking alliance tasks')
        if (Alliance:open() == 1) then
            Alliance:checkTech()
            Alliance:getPresent()
            Map:normalize()
            Alliance:fillForge()
        end
    end
end

function check_secret_missions(force)
    if ((cooldown('check_secret_missions', 3600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) or force == 1) then
        log('clear')
        log('Start checking secret missions')

        log('Collect missions')

        Game:collectSecretMissions()

        if (Storage:getDay('allianceSecretMissions') ~= 1) then
            Game:collectAllianceSecretMissions()
        end

        log('Setting missions')

        Game:setSecretMissions()
        Map:normalize()
    end
end

function collect_promo_gifts(force)
    if ((cooldown('collectPromoGifts', 3600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) or force == 1) then
        log('clear')
        log('Start checking gifts')
        Promo:collectGifts()
        Map:normalize()
    end
end

function read_mail(force)
    if ((cooldown('readMail', 3600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) or force == 1) then
        log('Start checking gifts')
        Game:readAllMail(1)
    end
end

function military_race(force)
    if ((cooldown('militaryRace', 3600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) or force == 1) then
        log('clear')
        log('Start checking military race')
        if (MilitaryRaceEvent:getEventNumber() >= 3) then
            DroneRace:getStamina()
        end
    end
end

function vs(force)
    if (Server:getDay(1) == 'Sunday') then
        return 0
    end
    if ((cooldown('vs', 3600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) or force == 1) then
        log('clear')
        VS:collectDroneComponents()
        VS:upgradeDrone()
        --VS:openBuildings()
        VS:collectGifts()
        Map:normalize()
    end
end

function check_events(force)
    if ((cooldown('checkEvents', 3600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) or force == 1) then
        log('clear')
        if (Event:open() == 1) then
            Hud:leftScrollModalTabs(10)
            Hud:clickFirstTab()
            local military_race_gift = Storage:getDay('collectMilitaryRaceGifts-' .. MilitaryRaceEvent:getEventName(), 0)
            local code_name = Storage:getDay('code_name', 0)

            local i = 0
            repeat
                local tab = Event:getEventTabName()
                log('See ' .. tab .. ' event')
                if (tab ~= 0) then
                    if (tab == 'military_race' and military_race_gift ~= 1) then
                        Event:collectMilitaryRaceGifts()
                    end
                    if (tab == 'judgment_day' == 1) then
                        Event:collectJudgmentDayGifts()
                    end
                    if (tab == 'code_name' and code_name ~= 1) then
                        CodeNameEvent:execute()
                    end
                    if (tab == 'generals') then
                        Event:collectGeneralsGifts()
                    end
                    if (tab == 'marshal') then
                        if (click_if_red(1145, 340, 1171, 313) == 1 and click_blue_button(957, 823) == 1) then
                            click_blue_button(1121, 792)
                            escape(1000, 'Close marshal modal')
                        end
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

function check_radar(force)
    if ((cooldown('checkRadar', 3600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) or force == 1) then
        log('clear')
        log('Race event is ' .. MilitaryRaceEvent:getEventName() .. '(' .. MilitaryRaceEvent:getEventNumber() .. ')')

        if (VS:isRadarDay() == 1) then
            if (Radar:collectFinishedTasks() == 0) then
                log('No radar tasks')
            else
                log('Radar tasks was collected')
            end
        end
        --
        if (Radar:autoFinishTasks() == 1) then
            reset_cooldown('checkRadar')
        end
        Map:openBase()
        Radar:collectFinishedTrucks()
        Radar:setTrucks()
        Map:normalize()
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
    if (Game:hasUpdateFinishedModal() == 1) then
        Game:restart(30, 'Updates is finished')
    end

    if ((is_blue(1061, 597) == 1 and is_yellow(856, 593) == 1)) then
        Game:restart(120, 'Connection error')
    end

    if (Game:isPreloadMenu() == 1) then
        Game:restart(120, 'Some thing wrong, detect preloader menu')
    end

    if (cooldown('checkConnections', 3600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) then
        if (Game:checkConnection() == 0 and Game:checkConnection() == 0) then
            Game:restart(30, 'Game is zombie')
        end
    end
end
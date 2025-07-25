Game = {}

function Game:checkMinistryRequests()
    Ministry:openMinistryIfRequest()
    Ministry:checkAndApproveMinisterRequest('mil_commander')
    Ministry:checkAndApproveMinisterRequest('adm_commander')
    Ministry:checkAndApproveMinisterRequest('strategy')
    Ministry:checkAndApproveMinisterRequest('security')
    Ministry:checkAndApproveMinisterRequest('development')
    Ministry:checkAndApproveMinisterRequest('science')
    Ministry:checkAndApproveMinisterRequest('interior')
    Map:normalize()
end

function Game:checkAlliance()
    Alliance:applyHelp()

    if (Rally:hasActiveRallies() == 0 and Alliance:isMarked() == 1 and Alliance:open() == 1) then
        wait(500)
        Alliance:checkTech()
        Alliance:getPresent()
        Alliance:clickBack()
    end
end

function Game:start()
    local game_path = Storage:get('game_path', os.getenv('LOCALAPPDATA') .. "\\TheLastWar\\Launch.exe")
    local startup_timeout = 30000
    log('Try launch the game: ' .. game_path .. ' and wait ' .. (startup_timeout / 1000) .. 's')
    Notify:accountStartGame()
    exec(game_path)
    wait(startup_timeout)

    Window:attachHandle()
    Window:repos()
    Window:resizeCanonical()
end

function Game:hasLogoutModal()
    if (Map:state() == 0 and is_red(810, 636) == 1 and is_red(968, 629) == 1 and kfindcolor(1029, 371, modal_header_color) == 1) then
        return 1
    end
    if (Map:state() == 0 and is_blue(810, 636) == 1 and is_blue(968, 629) == 1 and kfindcolor(1029, 371, modal_header_color) == 1) then
        return 1
    end
    return 0
end

function Game:isLogout()
    if (Game:hasLogoutModal() == 1) then
        wait(500);
        if (Game:hasLogoutModal() == 1) then
            log('Logout detected')
            return 1
        end
    end
    return 0
end

function Game:isPreloadMenu()
    if kfindcolor(48, 302, 16777215) == 1 and kfindcolor(11, 1050, '(7096837,16760096)') == 1 then
        return 1
    end
    return 0
end

function Game:hasUpdateFinishedModal()
    if (kfindcolor(884, 597, 16765462) == 1 and Game:isPreloadMenu() == 1) then
        return 1
    end
    return 0
end

function Game:clickLogout()
    log('Click logout button')
    wait(1000)
    left(893, 638)
    local logout_timeout = Storage:get('logout_timeout', 7 * 60)
    local logout_timeout_inc = Storage:get('logout_timeout_inc', logout_timeout)

    if (os.clock() < Storage:get('logout_timer', os.clock())) then
        log('Instance re-login, increase timeout')
        logout_timeout = logout_timeout_inc + (logout_timeout_inc * 70 / 100)
    else
        Storage:set('logout_timer', nil)
        Storage:get('logout_timeout_inc', Storage:get('logout_timeout'))
    end

    Game:restart(logout_timeout, 'Logout')
    Storage:set('logout_timer', ktimer(3 * 60 * 1000))
    Storage:set('logout_timeout_inc', logout_timeout)

    reset_cooldown()
    cooldown('restart', preventive_restart, true)
end

function Game:resetUserActivity()
    log('Reset user mouse pos')
    local x, y = mouse_pos("abs")
    Storage:set('lastMousePosX', x)
    Storage:set('lastMousePosY', y)
end

function Game:userIsActive()
    local x, y = mouse_pos("abs")
    local oldX = Storage:get('lastMousePosX')
    local oldY = Storage:get('lastMousePosY')
    if (oldY ~= y or oldX ~= x) then
        log('Old mouse cords is ' .. oldX .. ',' .. oldY .. ' current is ' .. x .. ',' .. y)
        return 1
    end
    return 0
end

function Game:waitIfUserIsActive()
    if (self:userIsActive() == 1) then
        local x, y = mouse_pos("abs")
        Storage:set('lastMousePosX', x)
        Storage:set('lastMousePosY', y)
        local timeout = Storage:get('timeout_if_user_active', 90)
        log('Waiting ' .. timeout .. 's, while user working')
        wait(timeout * 1000)
        return Game:waitIfUserIsActive()
    end
    return 1
end

function Game:sendSquadToResourceSpot()
    local centerX, centerY = Window:getCenterCords()
    if (click_and_wait_color(centerX, centerY, green_color, 870, 664) == 1) then
        click(870, 664, 2000)
        Hero:march()
        return 1
    end
    Map:normalize()
    return 0
end

function Game:hasResourceSpot()
    return is_red(1147, 279)
end

function Game:clickResourceSpotCords()
    if click_and_wait_not_color(1039, 359, red_color, 1147, 269) == 1 then
        return 1
    end
    return 0
end

function Game:openRallyPresents()
    return Hud:clickButton('rally_present')
end

function Game:getRallyPresents(check_spot)
    check_spot = check_spot or 1
    if (Game:openRallyPresents() == 1) then
        if (check_spot == 1 and Game:hasResourceSpot() == 1 and Game:clickResourceSpotCords() == 1) then
            Game:sendSquadToResourceSpot()
            return Game:getRallyPresents(0)
        end
        click(934, 821, 500)
        log('Get rally presents')
        return 1
    end
    return 0
end

function Game:readAllMail(force)
    force = force or 0
    if (is_red(1760, 855) == 1 or force == 1) then
        log('Have email, read it')
        if click_and_wait_color(1731, 874, modal_header_color, 1008, 22) == 1 then
            local count = 0
            repeat
                local x, y = find_color(1055, 101, 1105, 891, '(3456511-3259391,11697507)')
                if (x ~= 0 and click_and_wait_color(x - 200, y + 50, blue_color, 1075, 1031) == 1) then
                    click(1075, 1031, 800)
                    if (close_gift_modal() == 1) then
                        wait(1000)
                    end
                    escape(500)
                end
                count = count + 1
            until x == 0 or count > 10
            Map:normalize()
        end
    end
end

function Game:collectDailyPresents()
    if (kfindcolor(47, 970, 6158242) == 1) then
        click(230, 957)
        close_gift_modal()
        wait(2000)
        return Game:collectDailyPresents()
    end
    if (is_red(61, 924) == 1 or is_red(15, 257) == 1 or is_red(48, 938) == 1) then
        click_and_wait_color(36, 961, 6179651, 863, 30)
    end
    if (kfindcolor(1139, 18, modal_header_color) == 1) then
        if (kfindcolor(1087, 433, 4187738) == 1) then
            click(1087, 433, 500)
            wait(2000)
        end
        local x, y = find_color(694, 233, 1185, 263, '(15204351)')
        if (x > 0) then
            click(x, y, 1000)
            close_gift_modal()
        end
        Map:normalize()
        return 1
    end
    return 0
end

function Game:openCard()
    click_and_wait_color(740, 884, 10837327, 925, 446)
    wait(1000)
    click_and_wait_not_color(925, 446, 10837327)
    click_if_color(628, 1054, 16777215)
    escape(500)
end

function Game:checkFreeTavernHero()
    Map:normalize()
    click_and_wait_color(84, 1055, 16765462, 897, 995, nil, nil, 'Open heroes menu');
    click_and_wait_color(897, 995, 4187738, 820, 840, nil, nil, 'Open hiring heroes');
    wait(200)

    if (kfindcolor(1160, 201, 16777215) == 1) then
        if (find_color(654, 833, 847, 909, 4898535) == 0) then
            log('Open season hero card')
            Game:openCard()
        end
    end

    if (kfindcolor(1161, 335, 16777215) == 1) then
        if (find_color(654, 833, 847, 909, 54783) == 0) then
            log('Open hero card')
            Game:openCard()
        end
    end

    click_and_wait_color(1080, 1022, 11891208, nil, nil, nil, 500, 'Click survival tab')
    if (kfindcolor(1173, 262, 16777215) == 1) then
        if (find_color(654, 833, 847, 909, 4444407) == 0) then
            log('Open survival card')
            Game:openCard()
        end
    end

    Map:normalize()
end

function Game:searchResourceButtonAndClick()
    local x, y = find_color(1060, 510, 1095, 622, 16765462)
    if (x > 0) then
        click(x, y, 1500)
        return 1
    end
    return 0
end

function Game:collectResources(x, y)
    if (Game:userIsActive() == 0 and Map:state() ~= 0) then
        click_and_wait_color(x, y, 10257016, 1049, 174)
        if (Game:searchResourceButtonAndClick() == 1) then
            escape(1500, 'Close resource modal')
        end
        return 1
    end
    return 0
end

function Game:collectSimpleResources()
    log('Collect food')
    Game:collectResources(117, 21)

    log('Collect steel')
    Game:collectResources(247, 27)

    log('Collect gold')
    Game:collectResources(376, 23)
end

function Game:collectSecretMissions()
    --if (Storage:getDay('collectSecretMissions') == 1) then
    --    return 1
    --end
    Hud:clickButton('missions')
    --if (kfindcolor(964, 1018, '(12763842-10987431)') == 1 and find_color(1066, 497, 1163, 558, '(8908639)') == 0) then
    --    Storage:setDay('collectSecretMissions', 1)
    --end
    if (click_green_button(1146, 512) == 1) then
        wait(2000)
        escape(2000, 'Close mission gifts modal')
        return 1
    end
    Map:normalize();
    return 0
end

local function current_mission_is_ur()
    if (kfindcolor(692, 493, '(3637996-3976954)') == 1 or kfindcolor(625, 473, '( 4814335, 4682751, 4879871, 4879615)') == 1) then
        return 1
    end
    return 0
end

function Game:rotateSecretMissionsToUR()
    --if (Storage:getDay('collectSecretMissions') == 1) then
    --    return 1
    --end
    if (Hud:clickButton('missions') == 1) then
        click(772, 419, 400)
    end
    if (current_mission_is_ur() == 0) then
        if (kfindcolor(860, 1055, 3754730) == 1) then
            log('Tickets is end')
            return 0
        end

        if (is_blue(937, 1046) ~= 1) then
            log('Switch MEGA')
            click(1145, 1032, 1000)
        end

        if (click_blue_button(955, 1040) == 1) then
            wait(1000)
            if (current_mission_is_ur() == 0) then
                return Game:rotateSecretMissionsToUR()
            end
            return 1
        end
    end
    return 0
end

function Game:setSecretMissions()
    --if (Storage:getDay('setSecretMissions') == 1) then
    --    log('Skip collect secret missions')
    --    return 1
    --end

    Hud:clickButton('missions')

    if (current_mission_is_ur() == 1) then
        if (click_blue_button(1147, 514) == 1 and wait_color(618, 1042, 4140846) == 1) then
            if (kfindcolor(829, 1041, 2546431) == 1) then
                log('Click auto assign heroes to mission')
                click(829, 1041, 1000)
                if (click_blue_button(1023, 1039)) then
                    log('Send heroes to mission')
                    wait(3000)
                    return Game:setSecretMissions()
                else
                    log('Fail send heroes to mission')
                    Map:normalize()
                end
            end
        end
    else
        if (Game:rotateSecretMissionsToUR() == 1) then
            return Game:setSecretMissions()
        end
    end
    return 0
end

function Game:restart(logout_timeout, comment)
    comment = comment or ''
    logout_timeout = logout_timeout or Storage:get('logout_timeout', 7 * 60)
    Window:detach();
    if (comment ~= '' and Storage:get('restart_notify', 0) == 1) then
        Notify:sendTelegramMessage('Game is restart, ' .. comment .. ' wait ' .. logout_timeout .. 's')
    end
    log('Try killing a game')
    exec("taskkill /f /im lastwar.exe")
    log('Waiting logout timeout at ' .. (logout_timeout) .. 's after ' .. comment)
    wait(logout_timeout * 1000)
    Game:start()
end

function Game:collectAllianceSecretMissions()
    if (Storage:getDay('collectAllianceSecretMissions') == 1) then
        return 1
    end
    Hud:clickButton('missions')
    log('Open alliance tab missions')
    click(1138, 419, 400)
    if (kfindcolor(1066, 486, ur_color) == 1 and is_blue(1154, 537) == 1) then
        log('Try collect alliance mission')
        click(1154, 537)
        if (close_help_modal() == 1) then
            log('Successful collect alliance mission, change tab and retry')
            click(767, 424)
            return self:collectAllianceSecretMissions()
        else
            Storage:setDay('collectAllianceSecretMissions', 1)
        end
    end
    Map:normalize();
    return 0
end

function Game:checkConnection()
    Map:normalize()
    Ministry:open()
    Ministry:clickMinister('vp')
    wait(1000)
    local result = kfindcolor(1118, 956, 16777215)
    Map:normalize()
    return result
end
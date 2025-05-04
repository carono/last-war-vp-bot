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
    return kfindcolor(48, 302, 16777215)
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

    Game:restart(logout_timeout)
    Storage:set('logout_timer', ktimer(3 * 60 * 1000))
    Storage:set('logout_timeout_inc', logout_timeout)
end

function Game:resetUserActivity()
    log('Reset user mouse pos')
    local x, y = mouse_pos()
    Storage:set('lastMousePosX', x)
    Storage:set('lastMousePosY', y)
end

function Game:userIsActive()
    local x, y = mouse_pos()
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
        local x, y = mouse_pos()
        Storage:set('lastMousePosX', x)
        Storage:set('lastMousePosY', y)
        local timeout = Storage:get('timeout_if_user_active', 90)
        log('Waiting ' .. timeout .. 's, while user working')
        wait(timeout * 1000)
        return Game:waitIfUserIsActive()
    end
    return 1
end

function Game:getRallyPresents()
    if kfindcolor(256, 211, 3741951) == 1 then
        click_and_wait_color(256, 211, 16765462, 934, 821)
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
                local x, y = find_red_mark(1148, 98, 1190, 917)
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
    if (is_red(61, 924) == 1) then
        click_and_wait_color(36, 961, 6179651, 863, 30)
    end
    if (kfindcolor(35, 978, 6354839) == 1) then
        click(230, 957)
        close_gift_modal()
        wait(2000)
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
    click_and_wait_color(84, 1055, 16765462, 897, 995);
    click_and_wait_color(897, 995, 4187738, 820, 840);
    wait(200)
    if (find_color(654, 833, 847, 909, 54783) == 0) then
        log('Open hero')
        Game:openCard()
    end
    click_and_wait_color(1080, 1022, 11891208, nil, nil, nil, 500, 'Click survival tab')
    if (find_color(654, 833, 847, 909, 4444407) == 0) then
        log('Open survival')
        Game:openCard()
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
    if (click_green_button(1146, 512) == 1) then
        wait(2000)
        escape(2000, 'Close mission gifts modal')
        return 1
    end
    return 0
end

local function current_mission_is_ur()
    return is_blue(1150, 515) == 1 and (kfindcolor(692, 493, '(3637996-3976954)') == 1 or kfindcolor(625, 473, 4879615) == 1)
end

function Game:rotateSecretMissionsToUR()
    if (not current_mission_is_ur()) then
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
            if (not current_mission_is_ur()) then
                return Game:rotateSecretMissionsToUR()
            end
            return 1
        end
    end
    return 0
end

function Game:setSecretMissions()
    if (current_mission_is_ur()) then
        if (click_blue_button(1147, 514) == 1 and wait_color(618, 1042, 4140846) == 1) then
            if (kfindcolor(829, 1041, 2546431) == 1) then
                log('Click auto assign heroes to mission')
                click(829, 1041, 1000)
                if (click_blue_button(1023, 1039)) then
                    log('Send heroes to mission')
                    return 1
                else
                    log('Fail send heroes to mission')
                    Map:normalize()
                end
            end
        end
    end
    return 0
end

function Game:restart(logout_timeout)
    logout_timeout = logout_timeout or Storage:get('logout_timeout', 7 * 60)
    Window:detach();
    log('Try killing a game')
    exec("taskkill /f /im lastwar.exe")
    log('Waiting logout timeout at ' .. (logout_timeout) .. 's')
    wait(logout_timeout * 1000)
end

function Game:collectAllianceSecretMissions()
    log('Open alliance tab missions')
    click(1138, 419, 400)
    if (kfindcolor(1073, 499, 3642098) == 1 and is_blue(1154, 537)) then
        log('Try collect alliance mission')
        click(1154, 537)
        if (close_help_modal() == 1) then
            log('Successful collect alliance mission, change tab and retry')
            click(767, 424)
            return self:collectAllianceSecretMissions()
        end
    end
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
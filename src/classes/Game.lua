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
    exec(game_path)
    wait(startup_timeout)
    if (Game:isLogout() == 1) then
        log('User instance login, waiting')
        local logout_timeout = Storage:get('logout_timeout', 7 * 60)
        Game:clickLogout(logout_timeout * 2)
        return Game:start()
    end
end

function Game:hasLogoutModal()
    if (is_red(827, 595) == 1 and is_red(960, 637) and kfindcolor(1024, 376, modal_header_color)) then
        return 1
    end
    return 0
end

function Game:isLogout()
    if (Game:hasLogoutModal() == 1) then
        wait(500);
        if (Game:hasLogoutModal() == 1) then
            log('Logout detected')
            --stop_script()
            return 1
        end
    end
    return 0
end

function Game:hasUpdateFinishedModal()
    if (kfindcolor(884, 597, 16765462) == 1 and kfindcolor(48, 302, 16777215) == 1) then
        return 1
    end
    return 0
end

function Game:clickLogout(logout_timeout)
    logout_timeout = Storage:get('logout_timeout', 7 * 60)
    log('Click logout button')
    wait(1000)
    left(893, 638)
    Window:detach();
    log('Try killing a game')
    exec("taskkill /f /im lastwar.exe")
    log('Waiting logout timeout at ' .. (logout_timeout) .. 's')
    wait(logout_timeout * 1000)
end

function Game:resetUserActivity()
    local x, y = mouse_pos()
    Storage:set('lastMousePosX', x)
    Storage:set('lastMousePosY', y)
end

function Game:userIsActive()
    local x, y = mouse_pos()
    local oldX = Storage:get('lastMousePosX')
    local oldY = Storage:get('lastMousePosY')
    if (oldY ~= y or oldX ~= x) then
        return 1
    end
    return 0
end

function Game:waitIfUserIsActive()
    if (self:userIsActive() == 1) then
        local x, y = mouse_pos()
        Storage:set('lastMousePosX', x)
        Storage:set('lastMousePosY', y)
        local timeout = Storage:get('timeout_if_user_active', 30)
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
        click_and_wait_color(1731, 874, modal_header_color, 1008, 22)
        repeat
            local x, y = find_red_mark(1148, 98, 1190, 917)
            if (x ~= 0 and click_and_wait_color(x - 200, y + 50, blue_color, 1075, 1031) == 1) then
                click(1075, 1031, 800)
                if (close_gift_modal() == 1) then
                    wait(1000)
                end
                escape(500)
            end
        until x == 0
        Map:normalize()
    end
end

function Game:collectDailyPresents()
    if (is_red(61, 924) == 1) then
        click_and_wait_color(36, 961, 6179651, 863, 30)
        if (kfindcolor(1087, 433, 4187738) == 1) then
            click(1087, 433, 500)
        end
        click(743, 252, 1000)
        escape(500)

        click(847, 257, 1000)
        escape(500)

        click(948, 254, 1000)
        escape(500)

        click(1044, 255, 1000)
        escape(500)

        click(1145, 253, 1000)
        Map:normalize()
        return 1
    end
    return 0
end

function Game:openCard()
    click(740, 884, 3000)
    click(905, 470, 3000)
    click(905, 470, 3000)
    escape(2000)
end

-- development in process
function Game:checkFreeTavernHero()
    Map:normalize()
    click_and_wait_color(84, 1055, 16765462, 897, 995);
    click_and_wait_color(897, 995, 4187738, 820, 840);
    wait(200)
    if (kfindcolor(738, 885, 6344247) == 1) then
        log('Open hero')
        msg(1)
        --Game:openCard()
    end
    click(1057, 1016, 200)
    if (kfindcolor(731, 886, 5233404) == 1) then
        log('Open survival')
        msg(2)
        --Game:openCard()
    end
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
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
        Alliance:openSeason2buildings()

        Alliance:clickBack()
    end
end

function Game:start()
    log('Try launch the game: ' .. config.game_path)
    exec(config.game_path)
    wait(30000)
    Window:repos()
end

function Game:isLogout()
    return kfindcolor(893, 638, 4143607)
end

function Game:hasUpdateFinishedModal()
    if (kfindcolor(884, 597, 16765462) == 1 and kfindcolor(48, 302, 16777215) == 1) then
        return 1
    end
    return 0
end

function Game:clickLogout()
    wait(1000)
    left(893, 638, 1000)
    Window:detach();
    wait(1000)
    exec("taskkill /f /im lastwar.exe")
    wait(config.logout_timeout)
end

function Game:resetUserActivity()
    local x, y = mouse_pos()
    Storage:set('lastMousePosX', x)
    Storage:set('lastMousePosY', y)
end

function Game:waitIfUserIsActive()
    local x, y = mouse_pos()
    local oldX = Storage:get('lastMousePosX')
    local oldY = Storage:get('lastMousePosY')
    if (oldY ~= y or oldX ~= x) then
        Storage:set('lastMousePosX', x)
        Storage:set('lastMousePosY', y)
        local timeout = 30000
        log('Waiting ' .. (timeout / 1000) .. 's, while user working')
        wait(30000)
        return Game:waitIfUserIsActive()
    end
    return 0
end

function Game:getRallyPresents()
    if kfindcolor(256, 211, 3741951) == 1 then
        click_and_wait_color(256, 211, 16765462, 934, 821)
        left(934, 821, 500)
        log('Get rally presents')
        return 1
    end
    return 0
end

function Game:readAllMail()
    if (is_red(1760, 855) == 1) then
        log('Have email, read it')
        click_and_wait_color(1731, 874, 6179651, 1040, 35)
        repeat
            local x, y = find_red_mark(1148, 98, 1190, 917)
            if (x ~= 0) then
                click_and_wait_color(x, y, 16765462, 1075, 1031)
                left(1075, 1031, 800)
                close_gift_modal()
                wait(3000)
                escape(500)
            end
        until x == 0
        Map:normalize()
    end
end
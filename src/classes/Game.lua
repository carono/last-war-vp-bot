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

function Game:collectDailyPresents()
    if (is_red(61, 924) == 1) then
        click_and_wait_color(36, 961, 6179651, 863, 30)
        if (kfindcolor(1087, 433, 4187738) == 1) then
            left(1087, 433, 500)
        end
        left(743, 252, 1000)
        left(847, 257, 1000)
        left(948, 254, 1000)
        left(1044, 255, 1000)
        left(1145, 253, 1000)
        Map:normalize()
        return 1
    end
    return 0
end

function Game:openCard()
    left(740, 884, 3000)
    left(905, 470, 3000)
    left(905, 470, 3000)
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
    left(1057, 1016, 200)
    if (kfindcolor(731, 886, 5233404) == 1) then
        log('Open survival')
        msg(2)
        --Game:openCard()
    end
end

function Game:collectSimpleResources()
    log('Collect food')
    click_and_wait_color(117, 21, 10257016, 1049, 174)
    left(1090, 555, 1500)
    escape(1500)

    log('Collect steel')
    click_and_wait_color(247, 27, 10257016, 1049, 174)
    left(1090, 555, 1500)
    escape(1500)

    log('Collect gold')
    click_and_wait_color(376, 23, 10257016, 1049, 174)
    left(1090, 555, 1500)
    escape(1500)
end
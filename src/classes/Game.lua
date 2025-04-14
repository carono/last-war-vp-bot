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

function Game:clickLogout()
    wait(1000)
    left(893, 638, 1000)
    Window:detach();
    wait(1000)
    exec("taskkill /f /im lastwar.exe")
    wait(config.logout_timeout)
end

function Game:waitIfUserIsActive()
    local x, y = mouse_pos()
    local oldX = Storage:get('lastMousePosX')
    local oldY = Storage:get('lastMousePosY')
    if (oldY ~= y or oldX ~= x) then
        Storage:set('lastMousePosX', x)
        Storage:set('lastMousePosY', y)
        log('Waiting, while user working')
        wait(10000)
        return Game:waitIfUserIsActive()
    end
    return 0
end
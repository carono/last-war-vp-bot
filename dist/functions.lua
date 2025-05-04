-- lua color_functions.lua
red_color = '(3741951, 3740927, 3740911, 4869631, 214-240, 2171052,1845489-1521647,1066991, 13526, 10902, 3741951, 6513405,4144119)'
green_color = '(4187738, 6540855, 6148674, 6344247)'
modal_header_color = '(6179651, 10257016-10257017)'
blue_color = '(16765462, 16231954-16758336)'
yellow_color = '(2415103-2546431, 571647-639999)'
white_color = '(16777215)'
stamina_color = '(48383-183295)'

inactive_tab_color = '(5390650,5390649)'
active_tab_color = '(560895, 16768189, 16770006, 16772335)'
tab_body_color = '14080996'

function kfindcolor (x, y, color, margin, deviation)
    if (Window:getGameHandle() == 0) then
        return 0
    end
    deviation = deviation or 5
    margin = margin or 5
    x, y = Window:modifyCord(x, y)
    local x1 = x - margin
    local y1 = y - margin
    local x2 = x + margin
    local y2 = y + margin

    local result, count = findcolor(x1, y1, x2, y2, 1, 1, color, '%ResultArray', 2, 1, deviation)

    return result or 0, count
end

function store_colors_in_range(startX, startY, margin)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    margin = margin or 2
    local arr = {}
    table.insert(arr, startX)
    table.insert(arr, startY)
    table.insert(arr, margin)
    for i = startX, startX + margin do
        for j = startY, startY + margin do
            table.insert(arr, color(i, j))
        end
    end
    log(table.concat(arr))
    return arr
end

function stored_colors_not_changed(arr)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    if (arr == nil or arr[1] == nil) then
        arr = { 1, 1, 2 }
    end

    local targetArr = store_colors_in_range(arr[1], arr[2], arr[3])
    if (table.concat(arr) == table.concat(targetArr)) then
        return 1
    end
    return 0
end

function is_white(x, y, color)
    color = color or white_color
    if kfindcolor(x, y, color) == 1 then
        return 1
    end
    return 0
end

function is_red(x, y, color)
    color = color or red_color
    if kfindcolor(x, y, color) == 1 then
        return 1
    end
    return 0
end

function is_blue(x, y, color)
    color = color or blue_color
    if kfindcolor(x, y, color) == 1 then
        return 1
    end
    return 0
end

function is_yellow(x, y, color)
    color = color or yellow_color
    if kfindcolor(x, y, color) == 1 then
        return 1
    end
    return 0
end

function is_green(x, y, color)
    color = color or green_color
    if kfindcolor(x, y, color) == 1 then
        return 1
    end
    return 0
end

function find_color(startX, startY, endX, endY, color)
    if (Window:getGameHandle() == 0) then
        return 0, 0;
    end
    endX = endX or startX;
    endY = endY or startY;
    startX, startY = Window:modifyCord(startX, startY)
    endX, endY = Window:modifyCord(endX, endY)
    local res = findcolor(startX, startY, endX, endY, 1, 1, color, '%arr', 2, 1, 5)
    if (res == 1) then
        return Window:canonizeCord(arr[1][1], arr[1][2])
    end
    return 0, 0
end

function find_colors(startX, startY, endX, endY, colors)
    startX, startY = Window:modifyCord(startX, startY)
    endX, endY = Window:modifyCord(endX, endY)

    local firstTargetColor = table.remove(colors, 1)
    local res = findcolor(startX, startY, endX, endY, 1, 1, firstTargetColor[3], '%arr', 2, -1, 5)
    local startTime = os.clock()
    if (res ~= nil) then
        for _, findFirstColor in pairs(arr) do
            local findFirstColorX, findFirstColorY = Window:canonizeCord(findFirstColor[1], findFirstColor[2])
            local result = 1
            for _, nextTargetColor in pairs(colors) do
                local dX = nextTargetColor[1] - firstTargetColor[1]
                local dY = nextTargetColor[2] - firstTargetColor[2]
                local nextColorX = findFirstColorX + dX
                local nextColorY = findFirstColorY + dY
                if (findcolor(nextColorX, nextColorY, nextColorX, nextColorY, 1, 1, nextTargetColor[3], '%arr', 2, 1, 5) == nil) then
                    result = 0
                    break
                end
            end
            if (result == 1) then
                log('Successful find color in chain cords', findFirstColorX .. ', ' .. findFirstColorY .. ' in ' .. (os.clock() - startTime))
                return findFirstColorX, findFirstColorY
            end
        end
    end

    return 0, 0
end

function find_red_mark(startX, startY, endX, endY, color)
    color = color or red_color
    return find_color(startX, startY, endX, endY, color)
end

function wait_color(x, y, findcolor, timeout, cd)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    cd = cd or 200
    timeout = timeout or 5000
    local timer = ktimer(timeout)
    while os.clock() < timer do
        if (kfindcolor(x, y, findcolor) == 1) then
            wait(cd)
            log('Color', findcolor, 'is successful find')
            return 1
        end
        log('Wait color', findcolor, 'in', x .. ', ' .. y, 'current color:', color(x, y), math.ceil(timer - os.clock()) .. 's')
    end
    log('Timeout wait color', x, ',', y, findcolor, timer)
    return 0
end

function wait_not_color(x, y, color, timeout)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    timeout = timeout or 5000
    local timer = ktimer(timeout)
    while os.clock() < timer do
        if (kfindcolor(x, y, color) ~= 1) then
            wait(200)
            return 1
        end
    end
    return 0
end


-- lua farming.lua
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
        Game:checkFreeTavernHero()
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
            Game:rotateSecretMissionsToUR()
            Game:setSecretMissions()
        end

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
            if (Event:openEventTab('military_race') == 1) then
                Event:collectMilitaryRaceGifts()
            end
            if (Event:openEventTab('judgment_day') == 1) then
                Event:collectJudgmentDayGifts()
            end
        end
        CodeNameEvent:execute()
        Map:normalize()
    end
end

function check_radar()
    if (cooldown('checkRadar', 600) == 1 and Game:userIsActive() == 0 and Game:isLogout() == 0) then
        if (VS:isRadarDay() == 1) then
            Radar:collectFinishedTasks()
        end
        Radar:autoFinishTasks()
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

-- lua modals.lua
function close_gift_modal()
    log('Waiting modal with gifts')
    if (wait_color(1068, 342, 7059183, 2000) == 1) then
        escape(1000, 'Close gift modal')
        return 1
    end
    return 0
end

function close_help_modal()
    log('Waiting modal with gifts')
    if (wait_color(1084, 327, 2669297, 2000) == 1) then
        escape(1000, 'Close help modal')
        return 1
    end
    return 0
end

-- lua override.lua
function kdrag(x1, y1, x2, y2, r)
    x1, y1 = Window:modifyCord(x1, y1)
    x2, y2 = Window:modifyCord(x2, y2)
    r = r or 20
    local oldX, oldY = mouse_pos()
    move(x1, y1, r, r, r, r)
    kleft_down(x1, y1, r, r, r, r)
    move_smooth(x2, y2, r, r, r, r)
    kleft_up(x2, y2, r, r, r, r)
    move(oldX, oldY)
end

function wheel_down(x, y, count)
    local oldX, oldY = mouse_pos()
    for i = 1, count do
        kwheel_down(x, y, 1)
        wait(50)
    end
    move(oldX, oldY)
end

function wheel_up(x, y, count)
    local oldX, oldY = mouse_pos()
    for i = 1, count do
        kwheel_up(x, y, 1)
        wait(50)
    end
    move(oldX, oldY)
end

function left(x, y, timeout)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    local oldX, oldY = mouse_pos()
    x, y = Window:modifyCord(x, y)
    kleft(x, y)
    timeout = timeout or 100
    wait(timeout)
    move(oldX, oldY)
end

function click(x, y, time)
    if (Game:isLogout() == 1) then
        return 0
    end
    left(x, y, time)
end

function click_and_wait_color(x, y, color, colorX, colorY, timeout, cd, comment)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    if (comment ~= nil) then
        log(comment)
    end
    click(x, y)
    colorX = colorX or x
    colorY = colorY or y
    return wait_color(colorX, colorY, color, timeout, cd)
end

function click_and_wait_not_color(x, y, color, colorX, colorY)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    click(x, y)
    colorX = colorX or x
    colorY = colorY or y
    return wait_not_color(colorX, colorY, color)
end

function click_while_color(x, y, color, colorX, colorY, timeout)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    colorX = colorX or x
    colorY = colorY or y
    timeout = timeout or 150
    local timer = ktimer(5000)
    while os.clock() < timer do
        if (kfindcolor(colorX, colorY, color) == 1) then
            click(x, y)
            wait(timeout)
        else
            return 1
        end
    end
    return 0
end

function click_while_not_color(x, y, color, colorX, colorY, timeout)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    timeout = timeout or 0
    colorX = colorX or x
    colorY = colorY or y
    local timer = ktimer(5000)
    while os.clock() < timer do
        if (kfindcolor(colorX, colorY, color) ~= 1) then
            click(x, y, timeout)
        else
            return 1
        end
    end
    return 0
end

function click_if_red(x, y, colorX, colorY, timeout)
    colorX = colorX
    colorY = colorY
    return click_if_color(x, y, red_color, colorX, colorY, timeout)
end

function click_red_mark(colorX, colorY, x, y, timeout)
    x = x or colorX - 25
    y = y or colorY + 25
    return click_if_color(x, y, red_color, colorX, colorY, timeout)
end

function click_green_button(x, y, colorX, colorY, timeout)
    return click_if_color(x, y, green_color, colorX, colorY, timeout)
end

function click_blue_button(x, y, colorX, colorY, timeout)
    return click_if_color(x, y, blue_color, colorX, colorY, timeout)
end

function click_if_color(x, y, color, colorX, colorY, timeout, wait_color_timeout)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    timeout = timeout or 300
    wait_color_timeout = wait_color_timeout or 0
    colorX = colorX or x
    colorY = colorY or y
    wait(wait_color_timeout)
    if (kfindcolor(colorX, colorY, color) == 1) then
        click(x, y, 300)
        return 1
    end
    return 0
end

function escape(timeout, comment)
    timeout = timeout or 100
    comment = comment or ''
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    if (Game:isLogout() == 1) then
        return 0
    end
    send('Escape')
    log('Send escape button and wait ' .. (timeout / 1000) .. 's ' .. comment)
    wait(timeout)
end

function ktimer(timeout)
    return os.clock() + (timeout / 1000)
end

function cooldown(slug, time)
    time = time or 30
    local key = "cooldown" .. "." .. slug
    local timer = Storage:get(key, nil)
    log(key .. ': ' .. math.ceil((timer or os.clock()) - os.clock()) .. 's')
    if (timer == nil or os.clock() > timer or timer - os.clock() > time) then
        Storage:set(key, ktimer(time * 1000))
        return 1
    end
    return 0
end

function reset_cooldown(slug)
    log('Reset cooldown: ' .. (slug or 'all'))
    if (slug == nil) then
        Storage:set('cooldown', {})
        return
    end
    local key = "cooldown" .. "." .. slug
    Storage:set(key, nil)
end

function drag_tabs()
    local x, y = Window:modifyCord(1110, 110)
    local oldX, oldY = mouse_pos()
    log('Drag tabs...')
    move(x, y)
    kleft_down(x, y)
    move_smooth(x - 470, y)
    wait(300)
    move_smooth(x - 475, y)
    kleft_up(x - 470, y)
    wait(3000)
    log('Finish drag tabs')
    move(oldX, oldY)
end
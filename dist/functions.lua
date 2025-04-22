-- lua color_functions.lua
red_color = '(3741951, 3740927, 3740911, 4869631, 240, 214, 227, 237, 2171052)'
green_color = '(4187738, 6540855, 6148674, 6344247)'
inactive_tab_color = '(5390650)'
modal_header_color = '(6179651)'
blue_color = '(16765462, 16231954-16758336)'
active_tab_color = '(560895, 16768189, 16770006, 16772335)'

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

function is_red(x, y, color)
    color = color or red_color
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
                log('Successful find color in chain cords', findFirstColorX .. ', ' .. findFirstColorY)
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


-- lua daily.lua
function service_alliance()

end

-- lua modals.lua
function close_gift_modal()
    log('Waiting modal with gifts')
    wait_color(1068, 342, 7059183, 2000)
    escape(1000)
    --click_and_wait_not_color(1464, 167, 7059183, 1068, 342)
end

function close_connection_error()
    if kfindcolor(913, 573, 2546431) == 1 then
        click(913, 573, 400)
    end
    if kfindcolor(862, 593, 16765462) == 1 then
        click(862, 593, 400)
    end
    if (Game:hasUpdateFinishedModal() == 1) then
        --Confirm update finished
        log('Updates is finished, click OK and wait 30s')
        click(910, 597, 30000)
    end
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
    left(x, y, time)
end

function click_and_wait_color(x, y, color, colorX, colorY, timeout)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    click(x, y)
    colorX = colorX or x
    colorY = colorY or y
    return wait_color(colorX, colorY, color, timeout)
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
    return click_if_color(x, y, red_color, colorX, colorY, timeout)
end

function click_if_green(x, y, colorX, colorY, timeout)
    return click_if_color(x, y, green_color, colorX, colorY, timeout)
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

function escape(timeout)
    timeout = timeout or 100
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    if (Game:isLogout() == 1) then
        return 0
    end
    send('Escape')
    log('Send escape button and wait ' .. (timeout / 1000) .. 's')
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
    if (slug == nil) then
        Storage:set('cooldown', {})
        return
    end
    local key = "cooldown" .. "." .. slug
    Storage:set(key, nil)
end
-- lua color_functions.lua
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
    if (arr == nil or arr[1] == nil) then
        arr = { 1, 1, 2 }
    end

    local targetArr = store_colors_in_range(arr[1], arr[2], arr[3])
    if (table.concat(arr) == table.concat(targetArr)) then
        return 1
    end
    return 0
end

function find_red_mark(startX, startY, endX, endY, color)
    color = color or 3741951
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

function wait_color(x, y, findcolor, timeout, cd)
    cd = cd or 200
    timeout = timeout or 5000
    local timer = ktimer(timeout)
    while os.clock() < timer do
        if (kfindcolor(x, y, findcolor) == 1) then
            wait(cd)
            log('Color', findcolor, 'is successful find')
            return 1
        end
        log('Wait color', findcolor, 'in', x .. ',' .. y, 'current color:', color(x, y), math.ceil(timer - os.clock()) .. 's')
    end
    log('Timeout wait color', x, ',', y, findcolor, timer)
    return 0
end

function wait_not_color(x, y, color, timeout)
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
function pull_request_list()
    if (kfindcolor(621, 170, 16054013) == 1 and kfindcolor(1151, 176, 16054013) == 1) then
        kdrag(863, 255, 863, 932)
    end
end

function pull_list()
    local timer = 0
    require("color")
    --address, width, height, length = getimage(658, 221, 660, 429)
    --saveimage("tmp.bmp", address)


    --local path = [["tmp.bmp"]]
    log(ext.findimage(0, 0, 1024, 1024, { path }, 2))

    --    while (not (kfindcolor(1012, 232, 8617353) == 1 and kfindcolor(1049, 279, 12894420) == 1)) do
    --        if timer > 30000 then
    --            break
    --        end
    --        pull_request_list()
    --        wait(200)
    --        pull_request_list()
    --        wait(200)
    --    end
end

function close_gift_modal()
    wait_color(1068, 342, 7059183, 2000)
    click_and_wait_not_color(1464, 167, 7059183, 1068, 342)
end

function close_simple_modal(count)
    require("lib/color")
    local path = [["img/close_modal_button.bmp"]]
    count = count or 1
    for i = 1, count do
        local result, errorCode = findimage(1128, 71, 1192, 295, { path }, 2, 30, 1)
        if (result and (kfindcolor(result[1][1] - 25, result[1][2], 10257016) == 1 or kfindcolor(result[1][1] - 25, result[1][2], 10257017) == 1)) then
            log('Successful find close modal button', errorCode)
            click_and_wait_not_color(result[1][1], result[1][2], 16777215)
        else
            break
        end
        wait(300)
    end
end

function close_connection_error()
    if kfindcolor(913, 573, 2546431) == 1 then
        left(913, 573, 400)
    end
    if kfindcolor(862, 593, 16765462) == 1 then
        left(862, 593, 400)
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

function left(x, y, timeout, return_pos)
    local oldX, oldY = mouse_pos()
    x, y = Window:modifyCord(x, y)
    return_pos = return_pos or 1
    kleft(x, y)
    timeout = timeout or 100
    wait(timeout)
    if return_pos == 1 then
        move(oldX, oldY)
    end
end

function click_and_wait_color(x, y, color, colorX, colorY, timeout)
    left(x, y)
    colorX = colorX or x
    colorY = colorY or y
    return wait_color(colorX, colorY, color, timeout)
end

function click_and_wait_not_color(x, y, color, colorX, colorY)
    left(x, y)
    colorX = colorX or x
    colorY = colorY or y
    return wait_not_color(colorX, colorY, color)
end

function click_while_color(x, y, color, colorX, colorY)
    colorX = colorX or x
    colorY = colorY or y
    local timer = ktimer(5000)
    while os.clock() < timer do
        if (kfindcolor(colorX, colorY, color) == 1) then
            left(x, y)
            wait(150)
        else
            return 1
        end
    end
    return 0
end

function click_while_not_color(x, y, color, colorX, colorY)
    colorX = colorX or x
    colorY = colorY or y
    local timer = ktimer(5000)
    while os.clock() < timer do
        if (kfindcolor(colorX, colorY, color) ~= 1) then
            left(x, y)
        else
            return 1
        end
    end
    return 0
end

function click_if_color(x, y, color, colorX, colorY)
    colorX = colorX or x
    colorY = colorY or y
    if (kfindcolor(colorX, colorY, color) == 1) then
        left(x, y)
        wait(300)
    end
end

function escape(timeout)
    timeout = timeout or 100
    send('Escape')
    wait(timeout)
end

function ktimer(timeout)
    return os.clock() + (timeout / 1000)
end

function cooldown(slug, time)
    time = time or 30000
    local key = "cooldown" .. "." .. slug
    local timer = Storage:get(key, ktimer(time))
    log(key .. ': ' .. timer - os.clock() .. 's')
    if (os.clock() > timer or timer - os.clock() > time / 1000) then
        Storage:set(key, nil)
        return 1
    end
    return 0
end

function reset_cooldown(slug)
    local key = "cooldown" .. "." .. slug
    Storage:set(key, nil)
end
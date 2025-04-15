red_color = '(3741951, 3740927, 240, 214, 227, 237)'

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

function find_red_mark(startX, startY, endX, endY, color)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    color = color or red_color
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
        log('Wait color', findcolor, 'in', x .. ',' .. y, 'current color:', color(x, y), math.ceil(timer - os.clock()) .. 's')
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

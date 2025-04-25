red_color = '(3741951, 3740927, 3740911, 4869631, 214-240, 2171052,1845489-1521647,1066991, 13526, 10902, 3741951, 6513405,4144119)'
green_color = '(4187738, 6540855, 6148674, 6344247)'
inactive_tab_color = '(5390650)'
modal_header_color = '(6179651, 10257016-10257017)'
blue_color = '(16765462, 16231954-16758336)'
yellow_color = '(2415103-2546431, 571647-639999)'
white_color = '(16777215)'
active_tab_color = '(560895, 16768189, 16770006, 16772335)'
stamina_color = '(48383-183295)'

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

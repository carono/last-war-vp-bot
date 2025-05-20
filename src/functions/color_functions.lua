red_color = '(3741951, 3740927, 3740911, 4869631, 214-240, 2171052,1845489-1521647,1066991, 13526, 10902, 3741951, 6513405,4144119,3943143)'
green_color = '(4187738, 6540855, 6148674, 6344247)'
modal_header_color = '(6179651, 10257016-10257017)'
blue_color = '(16765462, 16231954-16758336)'
yellow_color = '(2415103-2546431, 571647-639999,10675967)'
ur_color = '(3441646-4173044, 4354303-2381030)'
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
    -- Модифицируем координаты один раз в начале
    startX, startY = Window:modifyCord(startX, startY)
    endX, endY = Window:modifyCord(endX, endY)

    -- Создаем копию таблицы цветов и извлекаем первый цвет
    local firstTargetColor = colors[1]
    local otherColors = {}

    -- Подготавливаем таблицу относительных координат заранее
    for i = 2, #colors do
        otherColors[i - 1] = {
            dx = colors[i][1] - firstTargetColor[1],
            dy = colors[i][2] - firstTargetColor[2],
            color = colors[i][3]
        }
    end

    -- Ищем первый цвет
    local res = findcolor(startX, startY, endX, endY, 1, 1, firstTargetColor[3], '%arr', 2, 1, 5)
    local startTime = os.clock()

    if res ~= 1 then
        log('First chain color not found')
        return 0, 0
    end

    res = findcolor(startX, startY, endX, endY, 1, 1, firstTargetColor[3], '%arr', 2, -1, 5)

    log('Start search color chain in ' .. startX .. ', ' .. startY .. ' to ' .. endX .. ', ' .. endY)

    -- Оптимизация: используем ipairs вместо pairs для массивов
    for _, findFirstColor in ipairs(arr) do
        local findFirstColorX, findFirstColorY = Window:canonizeCord(findFirstColor[1], findFirstColor[2])
        local allMatch = true

        -- Проверяем все остальные цвета
        for _, nextTarget in ipairs(otherColors) do
            local nextColorX = findFirstColorX + nextTarget.dx
            local nextColorY = findFirstColorY + nextTarget.dy

            if findcolor(nextColorX, nextColorY, nextColorX, nextColorY, 1, 1, nextTarget.color, '%arr', 2, 1, 5) ~= 1 then
                allMatch = false
                break
            end
        end

        if allMatch then
            log('Successful find color in chain cords ' .. findFirstColorX .. ', ' .. findFirstColorY .. ' in ' .. (os.clock() - startTime))
            return findFirstColorX, findFirstColorY
        end
    end

    log('Chain color not found')
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
        log('Wait color ' .. findcolor .. ' in ' .. x .. ', ' .. y .. ' current: ' .. color(x, y) .. ' ' .. math.ceil(timer - os.clock()) .. 's')
    end
    log('Timeout wait color ' .. x, ', ' .. y .. findcolor, timer)
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

function log_color(x, y)
    local colors = {}
    table.insert(colors, color(x, y))
    table.insert(colors, color(x + 1, y))
    table.insert(colors, color(x - 1, y))
    table.insert(colors, color(x, y + 1))
    table.insert(colors, color(x, y - 1))

    log('Cords:' .. x .. ', ' .. y)
    log(table.concat(colors, ', '))

    local max, min = table.maxmin(colors)
    log('Range: ' .. min .. '-' .. max)
end
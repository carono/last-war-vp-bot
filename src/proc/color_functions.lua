function kfindcolor (x, y, color, margin, deviation)
    deviation = deviation or 5
    margin = margin or 5
    x, y = Window:modifyCord(x, y)
    local x1 = x - margin
    local y1 = y - margin
    local x2 = x + margin
    local y2 = y + margin

    return findcolor(x1, y1, x2, y2, 1, 1, color, '%ResultArray', 2, 1, deviation)
end

function find_red_mark(startX, startY, endX, endY, color)
    color = color or 3741951
    startX, startY = Window:modifyCord(startX, startY)
    endX, endY = Window:modifyCord(endX, endY)
    local res = findcolor(startX, startY, endX, endY, 1, 1, color, '%arr', 2, 1, 5)
    if (res == 1) then
        return Window:canonizeCord(arr[1][1], arr[1][2])
    end
    return nil
end

function wait_color(x, y, color, timeout, cd)
    cd = cd or 200
    timeout = timeout or 5000
    local timer = ktimer(timeout)
    while os.clock() < timer do
        if (kfindcolor(x, y, color) == 1) then
            wait(cd)
            return 1
        end
        log('Wait', x, ',', y, color, os.clock(), timer)
    end
    log('Timeout wait color', x, ',', y, color, timer)
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

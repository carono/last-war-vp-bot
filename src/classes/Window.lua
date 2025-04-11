Window = {}

function Window:resizeCanonical()
    local handle = self:attachHandle()
    width, height = self:getCanonicalSize()
    x, y = windowpos(handle)
    windowpos(x, y, width, height, handle)
end

function Window:getCanonicalSize()
    return 1796, 1154
end

function Window:repos()
    local handle = self:attachHandle()
    if (handle ~= 0) then
        x, y, width, height = windowpos(handle)
        x = config.win_pos_x
        y = config.win_pos_y
        windowpos(x, y, width, height, handle)
    end
end

function Window:detach()
    workwindow(nil)
    wait(1000)
end

function Window:attachHandle()
    local handle = self:getGameHandle()
    if (handle ~= 0) then
        workwindow(handle)
        showwindow(handle, "TOP")
    end
    return handle
end

function Window:getGameHandle()
    local handle = findwindow("Last War-Survival Game")
    if (handle == nil) then
        return 0
    end
    return handle[1][1]
end

function Window:modifyCord (xReference, yReference)
    local handle = self:getGameHandle()
    WidthCurrent, HeightCurrent = self:getCanonicalSize()
    x, y, WidthReference, HeightReference = windowpos(handle)
    local xCurrent = (xReference * WidthReference) / WidthCurrent
    local yCurrent = (yReference * HeightReference) / HeightCurrent
    return math.ceil(xCurrent), math.ceil(yCurrent)
end

function Window:canonizeCord (xReference, yReference)
    local handle = self:getGameHandle()
    WidthReference, HeightReference = self:getCanonicalSize()
    x, y, WidthCurrent, HeightCurrent = windowpos(handle)
    local xCurrent = (xReference * WidthReference) / WidthCurrent
    local yCurrent = (yReference * HeightReference) / HeightCurrent
    return math.ceil(xCurrent), math.ceil(yCurrent)
end
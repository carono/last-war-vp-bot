Window = {}

function Window:resizeCanonical()
    local handle = self:attachHandle()
    local width, height = self:getCanonicalSize()
    local x, y = windowpos(handle)
    windowpos(x, y, width, height, handle)
end

function Window:getCanonicalSize()
    return 1796, 1154
end

function Window:repos()
    local handle = self:attachHandle()
    if (handle ~= 0) then
        local x, y, width, height = windowpos(handle)
        x = Storage:get('win_pos_x', 0)
        y = Storage:get('win_pos_y', 0)
        windowpos(x, y, width, height, handle)
        return 1
    end
    return 0
end

function Window:detach()
    log('Detach a window handle')
    workwindow(nil)
    wait(1000)
end

function Window:getCenterCords()
    local handle = self:getGameHandle()
    local _, _, WidthReference, HeightReference = windowpos(handle)
    return WidthReference / 2, HeightReference / 2
end

function Window:toTop()
    local handle = self:getGameHandle()
    if (handle ~= 0) then
        showwindow(handle, "TOP")
    end
end

function Window:attachHandle()
    local handle = self:getGameHandle()
    if (handle ~= 0) then
        workwindow(handle)
    end
    Window:toTop()
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
    local WidthCurrent, HeightCurrent = self:getCanonicalSize()
    local x, y, WidthReference, HeightReference = windowpos(handle)
    local xCurrent = (xReference * WidthReference) / WidthCurrent
    local yCurrent = (yReference * HeightReference) / HeightCurrent
    return math.ceil(xCurrent), math.ceil(yCurrent)
end

function Window:canonizeCord (xReference, yReference)
    local handle = self:getGameHandle()
    local WidthReference, HeightReference = self:getCanonicalSize()
    local x, y, WidthCurrent, HeightCurrent = windowpos(handle)
    local xCurrent = (xReference * WidthReference) / WidthCurrent
    local yCurrent = (yReference * HeightReference) / HeightCurrent
    return math.ceil(xCurrent), math.ceil(yCurrent)
end
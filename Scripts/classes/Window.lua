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

function Window:attachHandle()
    local handle = self:getGameHandle()
    workwindow(handle)
    showwindow(handle, "TOP")
    return handle
end

function Window:getGameHandle()
    local handle = findwindow("Last War-Survival Game")
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
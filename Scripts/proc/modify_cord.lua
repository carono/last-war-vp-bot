function get_canonical_size()
    return 1796, 1154
end

function get_game_handle()
    local handle = findwindow("Last War-Survival Game")
    return handle[1][1]
end

function modify_cord (xReference, yReference)
    local handle = get_game_handle()
    WidthCurrent, HeightCurrent = get_canonical_size()
    x, y, WidthReference, HeightReference = windowpos(handle)
    local xCurrent = (xReference * WidthReference) / WidthCurrent
    local yCurrent = (yReference * HeightReference) / HeightCurrent
    return math.ceil(xCurrent), math.ceil(yCurrent)
end
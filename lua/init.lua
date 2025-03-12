--lua
-- input.lua
function kdrag(x1, y1, x2, y2, r)
    r = r or 20
    local oldX, oldY = mouse_pos()
    move(x1, y1, r, r, r, r)
    kleft_down(x1, y1, r, r, r, r)
    move_smooth(x2, y2, r, r, r, r)
    kleft_up(x2, y2, r, r, r, r)
    move(oldX, oldY)
end

function kfindcolor (x, y, color, margin)
    margin = margin or 5
    x, y = modify_cord(x, y)
    local x1 = x - margin
    local y1 = y - margin
    local x2 = x + margin
    local y2 = y + margin

    return findcolor(x1, y1, x2, y2, 1, 1, color, '%ResultArray', 2, 1, 5)
end

-- modals.lua
function pull_request_list()
    if (kfindcolor(621, 170, 16054013) == 1 and kfindcolor(1151, 176, 16054013) == 1) then
        kdrag(863, 223, 863, 932)
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

-- modify_cord.lua
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
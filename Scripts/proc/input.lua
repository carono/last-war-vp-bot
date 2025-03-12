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
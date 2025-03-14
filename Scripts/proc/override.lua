function kdrag(x1, y1, x2, y2, r)
    r = r or 20
    local oldX, oldY = mouse_pos()
    move(x1, y1, r, r, r, r)
    kleft_down(x1, y1, r, r, r, r)
    move_smooth(x2, y2, r, r, r, r)
    kleft_up(x2, y2, r, r, r, r)
    move(oldX, oldY)
end

function left(x, y, timeout, return_pos)
    local oldX, oldY = mouse_pos()
    x, y = Window:modifyCord(x, y)
    return_pos = return_pos or 1
    kleft(x, y)
    timeout = timeout or 100
    wait(timeout)
    if return_pos == 1 then
        move(oldX, oldY)
    end
end

function click_and_wait_color(x, y, color, colorX, colorY)
    left(x, y)
    colorX = colorX or x
    colorY = colorY or y
    return wait_color(colorX, colorY, color)
end

function click_and_wait_not_color(x, y, color, colorX, colorY)
    left(x, y)
    colorX = colorX or x
    colorY = colorY or y
    return wait_not_color(colorX, colorY, color)
end

function click_while_color(x, y, color, colorX, colorY)
    colorX = colorX or x
    colorY = colorY or y
    local timer = 0
    while (timer < 5000) do
        if (kfindcolor(colorX, colorY, color) == 1) then
            left(x, y)
            wait(150)
        else
            return 1
        end
    end
    return 0
end

function click_while_not_color(x, y, color, colorX, colorY)
    colorX = colorX or x
    colorY = colorY or y
    local timer = 0
    while (timer < 5000) do
        if (kfindcolor(colorX, colorY, color) ~= 1) then
            left(x, y)
        else
            return 1
        end
    end
    return 0
end

function click_if_color(x, y, color, colorX, colorY)
    colorX = colorX or x
    colorY = colorY or y
    if (kfindcolor(colorX, colorY, color)) then
        left(x, y)
        wait(300)
    end
end

function escape(timeout)
    timeout = timeout or 100
    send('Escape')
    wait(timeout)
end
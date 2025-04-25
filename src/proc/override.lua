function kdrag(x1, y1, x2, y2, r)
    x1, y1 = Window:modifyCord(x1, y1)
    x2, y2 = Window:modifyCord(x2, y2)
    r = r or 20
    local oldX, oldY = mouse_pos()
    move(x1, y1, r, r, r, r)
    kleft_down(x1, y1, r, r, r, r)
    move_smooth(x2, y2, r, r, r, r)
    kleft_up(x2, y2, r, r, r, r)
    move(oldX, oldY)
end

function left(x, y, timeout)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    local oldX, oldY = mouse_pos()
    x, y = Window:modifyCord(x, y)
    kleft(x, y)
    timeout = timeout or 100
    wait(timeout)
    move(oldX, oldY)
end

function click(x, y, time)
    if (Game:isLogout() == 1) then
        return 0
    end
    left(x, y, time)
end

function click_and_wait_color(x, y, color, colorX, colorY, timeout)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    click(x, y)
    colorX = colorX or x
    colorY = colorY or y
    return wait_color(colorX, colorY, color, timeout)
end

function click_and_wait_not_color(x, y, color, colorX, colorY)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    click(x, y)
    colorX = colorX or x
    colorY = colorY or y
    return wait_not_color(colorX, colorY, color)
end

function click_while_color(x, y, color, colorX, colorY, timeout)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    colorX = colorX or x
    colorY = colorY or y
    timeout = timeout or 150
    local timer = ktimer(5000)
    while os.clock() < timer do
        if (kfindcolor(colorX, colorY, color) == 1) then
            click(x, y)
            wait(timeout)
        else
            return 1
        end
    end
    return 0
end

function click_while_not_color(x, y, color, colorX, colorY, timeout)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    timeout = timeout or 0
    colorX = colorX or x
    colorY = colorY or y
    local timer = ktimer(5000)
    while os.clock() < timer do
        if (kfindcolor(colorX, colorY, color) ~= 1) then
            click(x, y, timeout)
        else
            return 1
        end
    end
    return 0
end

function click_if_red(x, y, colorX, colorY, timeout)
    colorX = colorX
    colorY = colorY
    return click_if_color(x, y, red_color, colorX, colorY, timeout)
end

function click_red_mark(colorX, colorY, x, y, timeout)
    x = x or colorX - 25
    y = y or colorY + 25
    return click_if_color(x, y, red_color, colorX, colorY, timeout)
end

function click_green_button(x, y, colorX, colorY, timeout)
    return click_if_color(x, y, green_color, colorX, colorY, timeout)
end

function click_blue_button(x, y, colorX, colorY, timeout)
    return click_if_color(x, y, blue_color, colorX, colorY, timeout)
end

function click_if_color(x, y, color, colorX, colorY, timeout, wait_color_timeout)
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    timeout = timeout or 300
    wait_color_timeout = wait_color_timeout or 0
    colorX = colorX or x
    colorY = colorY or y
    wait(wait_color_timeout)
    if (kfindcolor(colorX, colorY, color) == 1) then
        click(x, y, 300)
        return 1
    end
    return 0
end

function escape(timeout, comment)
    timeout = timeout or 100
    comment = comment or ''
    if (Window:getGameHandle() == 0) then
        return 0;
    end
    if (Game:isLogout() == 1) then
        return 0
    end
    send('Escape')
    log('Send escape button and wait ' .. (timeout / 1000) .. 's ' .. comment)
    wait(timeout)
end

function ktimer(timeout)
    return os.clock() + (timeout / 1000)
end

function cooldown(slug, time)
    time = time or 30
    local key = "cooldown" .. "." .. slug
    local timer = Storage:get(key, nil)
    log(key .. ': ' .. math.ceil((timer or os.clock()) - os.clock()) .. 's')
    if (timer == nil or os.clock() > timer or timer - os.clock() > time) then
        Storage:set(key, ktimer(time * 1000))
        return 1
    end
    return 0
end

function reset_cooldown(slug)
    if (slug == nil) then
        Storage:set('cooldown', {})
        return
    end
    local key = "cooldown" .. "." .. slug
    Storage:set(key, nil)
end

function drag_tabs()
    local x, y = Window:modifyCord(1110, 110)
    local oldX, oldY = mouse_pos()
    log('Drag tabs...')
    move(x, y)
    kleft_down(x, y)
    move_smooth(x - 470, y)
    wait(300)
    move_smooth(x - 475, y)
    kleft_up(x - 470, y)
    wait(3000)
    log('Finish drag tabs')
    move(oldX, oldY)
end
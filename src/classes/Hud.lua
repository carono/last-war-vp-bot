--lua

Hud = {
    wait_colors = {
        default = { 1048, 19, modal_header_color },
        events = { 952, 11, modal_header_color },
        trucks = { 892, 146, 4567463 },
        search = { 803, 498, modal_header_color },
        radar = { 1071, 28, stamina_color },
        inventory = { 838, 26, modal_header_color }
    }
}

function Hud:findButton(name)
    log('Searching "' .. name .. '" button on hud')

    if name == 'trucks' then
        return find_colors(11, 506, 83, 913, { { 34, 636, 14065176 }, { 52, 632, 14065183 } })
    end
    if name == 'search' then
        return find_colors(11, 506, 83, 913, { { 48, 880, 16116175 }, { 46, 851, 15321748 } })
    end
    if name == 'radar' then
        return find_colors(11, 506, 83, 913, { { 30, 808, 15189130 }, { 63, 791, 16314589 } })
    end
    if name == 'missions' then
        return find_colors(11, 506, 83, 913, { { 28, 726, 15717020 }, { 61, 707, 16777193 } })
    end

    if name == 'events' then
        return find_color(1697, 76, 1765, 346, 16737536)
    end
    if name == 'vs' then
        return find_colors(1684, 164, 1771, 419, { { 1703, 285, 3229666 }, { 1737, 289, 16755819 } })
    end

    if name == 'inventory' then
        return find_colors(1688, 920, 1767, 996, { { 1706, 967, 6500368 }, { 1745, 944, 6699289 } })
    end
    return 0, 0
end

function Hud:clickButton(name)
    local x, y = self:findButton(name)
    if (x > 0) then
        log('Click "' .. name .. '" button')
        if self.wait_colors[name] == nil then
            name = 'default'
        end
        local colorX = self.wait_colors[name][1]
        local colorY = self.wait_colors[name][2]
        local color = self.wait_colors[name][3]
        local result = click_and_wait_color(x, y, color, colorX, colorY)
        wait(1000)
        return result
    end
    log('Button "' .. name .. '" not found')
    return 0
end

function Hud:scrollLeftEnd()
    Hud:leftScrollModalTabs(10)
end

function Hud:scrollRightEnd()
    Hud:rightScrollModalTabs(10)
end

function Hud:leftScrollModalTabs(count)
    count = count or 1
    wheel_down(915, 115, count * 10)
end

function Hud:rightScrollModalTabs(count)
    count = count or 1
    wheel_up(915, 115, count * 10)
end

function Hud:clickFirstTab()
    click(681, 107, 1000)
end


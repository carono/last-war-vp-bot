--lua

Hud = {
    wait_colors = {
        default = { 1048, 19, modal_header_color },
        events = { 952, 11, modal_header_color },
        trucks = { 629, 1068, 16777215 },
        search = { 803, 498, modal_header_color },
        radar = { 1071, 28, stamina_color },
        inventory = { 838, 26, modal_header_color },
        survivals = { 830, 628, 7570073 },
        development = { 1077, 401, blue_color },
        rally_present = { 927, 826, blue_color }
    }
}

function Hud:findButton(name)
    log('Searching "' .. name .. '" button on hud')
    local x, y
    if name == 'trucks' then
        x, y = find_colors(11, 506, 83, 913, { { 34, 636, 14065176 }, { 52, 632, 14065183 } })
        if (x > 0) then
            return x, y
        end
        x, y = find_colors(11, 506, 83, 913, { { 49, 647, 14601654 }, { 29, 612, 16777204 } })
        if (x > 0) then
            return x, y
        end
    end
    if name == 'search' then
        return find_colors(11, 506, 83, 913, { { 36, 890, 15387558 }, { 59, 867, 16775653 } })
    end
    if name == 'radar' then
        return find_colors(11, 506, 83, 913, { { 30, 808, 15189130 }, { 63, 791, 16314589 } })
    end
    if name == 'missions' then
        return find_colors(11, 506, 83, 913, { { 28, 726, 15717020 }, { 61, 716, 14070149 } })
    end
    if name == 'survivals' then
        return find_colors(11, 506, 83, 913, { { 26, 559, 16315083 }, { 60, 550, 15853256 } })
    end

    if name == 'development' then
        return find_colors(12, 201, 83, 366, { { 32, 233, 16776441 }, { 60, 242, 5159164 } })
    end

    if name == 'rally_present' then
        return find_colors(224, 171, 271, 294, { { 240, 247, 16777215 }, { 252, 270, 16777215 } })
    end

    if name == 'events' then
        return find_color(1697, 76, 1765, 346, 16737536)
    end
    if name == 'vs' then
        x, y = find_colors(1684, 75, 1766, 432, { { 1703, 285, 3229666 }, { 1737, 289, 16755819 } })
        if (x > 0) then
            return x, y
        end
        x, y = find_colors(1684, 75, 1766, 432, { { 1709, 284, 8710143 }, { 1728, 298, 12998656 } })
        if (x > 0) then
            return x, y
        end
    end

    if name == 'inventory' then
        return find_colors(1688, 920, 1767, 996, { { 1706, 967, 6500368 }, { 1745, 944, 6699289 } })
    end
    return 0, 0
end

function Hud:clickButton(name)
    local x, y = self:findButton(name)

    if self.wait_colors[name] == nil then
        name = 'default'
    end

    local colorX = self.wait_colors[name][1]
    local colorY = self.wait_colors[name][2]
    local color = self.wait_colors[name][3]

    if (kfindcolor(colorX, colorY, color) == 1) then
        log('Menu already opened')
        return 1
    end

    if (x > 0) then
        log('Click "' .. name .. '" button')
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
    wait(500)
end

function Hud:clickFirstTab()
    click(681, 107, 1000)
end

function Hud:closeNpcDialogs()
    click_while_color(1163, 957, 15330287)
end

function Hud:scrollDown(count, x, y)
    count = count or 1
    x = x or 892
    y = y or 502
    wheel_down(x, y, count * 10)
end

function Hud:scrollUp(count, x, y)
    count = count or 1
    x = x or 892
    y = y or 502
    wheel_up(x, y, count * 10)
end
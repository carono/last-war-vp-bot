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
        rally_present = { 927, 826, blue_color },
        alliance_forge = { 1079, 88, 16772459 }
    }
}

function Hud:findButton(name)
    log('Searching "' .. name .. '" button on hud')
    local x, y
    if name == 'trucks' then
        return 47, 632
    end
    if name == 'search' then
        Map:openMap()
        return 43, 869
    end
    if name == 'radar' then
        return 40, 799
    end
    if name == 'missions' then
        return 40, 712
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

    if (name == 'alliance_forge') then
        if (Alliance:open() == 0) then
            return 0, 0
        end
        Hud:scrollDown()
        x, y = find_colors(608, 380, 1186, 976, { { 632, 917, 16442590 }, { 767, 890, 6342399 } })
        if (x > 0) then
            return x, y
        end
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

function Hud:afterClickButton(name, x, y)
    local colorX = self.wait_colors[name][1]
    local colorY = self.wait_colors[name][2]
    local color = self.wait_colors[name][3]

    log('Click "' .. name .. '" button')
    local result = click_and_wait_color(x, y, color, colorX, colorY, nil, 1000)
    if (name == 'trucks' and result == 0 and kfindcolor(862, 271, '(7505500, 7439708, 7505756, 7308380)') == 1) then
        result = click_and_wait_color(714, 253, color, colorX, colorY, nil, 1000)
        log(result)
    end
    return result
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
        return Hud:afterClickButton(name, x, y)
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
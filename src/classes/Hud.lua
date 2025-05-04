--lua

Hud = {
    wait_colors = {
        events = { 952, 11, modal_header_color },
        trucks = { 892, 146, 4567463 }
    }
}

function Hud:findButton(name)
    if name == 'events' then
        return find_color(1697, 76, 1765, 346, 16737536)
    end
    if name == 'trucks' then
        return find_colors(11, 506, 83, 913, { { 34, 636, 14065176 }, { 52, 632, 14065183 } })
    end
    return 0, 0
end

function Hud:clickButton(name)
    local x, y = self:findButton(name)
    if (x > 0) then
        local result = click_and_wait_color(x, y, self.wait_colors[name][3], self.wait_colors[name][1], self.wait_colors[name][2])
        wait(1000)
        return result
    end
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


--lua
Building = {
    structures = {
        drone = { tab = 2, sort = 'desc', colors = { { 938, 231, 8684089 } } },
        present_economic = { tab = 1, colors = { { 1085, 454, '(3224831, 2961663)' }, { 1114, 468, '(1607423, 1607422)' } } },
        present_military = { tab = 2, colors = { { 1085, 454, '(3224831, 2961663)' }, { 1114, 468, '(1607423, 1607422)' } } }
    }
}

function Building:searchStructureInList(name)
    log('Try search ' .. name)
    return find_colors(602, 157, 1173, 949, Building.structures[name]['colors'])
end

function Building:clickDevelopmentList()
    return click_and_wait_color(1146, 992, blue_color, 73, 1024)
end

function Building:findStructure(name)
    if (Building.structures[name] == nil) then
        log('Structure ' .. name .. ' not defined')
    end
    local centerX, centerY = Window:getCenterCords()
    Base:openBase()
    if (Hud:clickButton('development') == 1 and Building:clickDevelopmentList() == 1) then
        if (Building.structures[name]['tab'] == 1) then
            click_and_wait_color(215, 97, 560895)
        else
            click_and_wait_color(452, 97, 560895)
        end
        if (Building.structures[name]['scrolls'] ~= nil) then
            Hud:scrollDown(Building.structures[name]['scrolls'])
        end
        if (Building.structures[name]['sort'] ~= nil) then
            if (click_and_wait_color(1728, 1042, 15198183, 1739, 891) == 1) then
                if (Building.structures[name]['sort'] == 'desc') then
                    click(1583, 927)
                else
                    click(1580, 862)
                end
                click_and_wait_color(1728, 1042, 16054013, 1739, 891)
            end
        end
        Hud:scrollUp(10)
        for _ = 1, 10 do
            local x, y = Building:searchStructureInList(name)
            if (x > 0) then
                click(x, y, 1000)
                x = 0
                y = 0
                local timer = ktimer(5000)
                while os.clock() < timer do
                    x, y = find_color(centerX - 100, centerY - 200, centerX + 100, centerY + 200, 2029567)
                    if (x > 0) then
                        y = y + 95
                        break
                    end
                end

                return x, y
            end

            Hud:scrollDown()
            wait(1000)
        end
    end
    return 0
end
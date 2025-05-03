--lua

Event = {}

function Event:open()
    return Hud:clickButton('events')
end

function Event:collectMilitaryRaceGifts()
    if (kfindcolor(770, 538, 50943) == 1) then
        click(686, 456, 500)
        close_gift_modal()
    end
    if (kfindcolor(961, 542, 50943) == 1) then
        click(907, 458, 500)
        close_gift_modal()
    end
    if (kfindcolor(1159, 537, 50943) == 1) then
        click(1078, 458, 500)
        close_gift_modal()
    end
    if (kfindcolor(710, 330, 1689938) == 1) then
        click(660, 288, 500)
        close_gift_modal()
    end
end

function Event:openMilitaryRaceTab()
    if (kfindcolor(670, 114, 1934802) == 1) then
        return 1
    end
    Hud:leftScrollModalTabs(10)
    click(676, 108, 200)
    return 1
end

function Event:getEventTabName()
    if kfindcolor(769, 438, 16030309) == 1 then
        return 'military_race'
    end
    if kfindcolor(661, 221, 15191056) == 1 then
        return 'winter_storm'
    end
    if kfindcolor(1139, 561, '(3646383-4106685)') == 1 then
        return 'desert_storm'
    end
    if kfindcolor(640, 753, 14998902) == 1 then
        return 'zombie_siege'
    end
    if kfindcolor(878, 585, 9726543) == 1 then
        return 'marshal'
    end
    --if find_color(586, 103, 1191, 131, '(2779848,2713030)') > 0 then
    if kfindcolor(1142, 555, 16777215) == 1 then
        return 'code_name'
    end
    if kfindcolor(721, 855, 16737800) == 1 then
        return 'social'
    end
    return 0
end

function Event:clickNextTab()
    local x, y = find_color(584, 121, 1198, 133, 16772335)
    x, y = find_color(x, 130, 1198, 131, inactive_tab_color)
    if (x > 0) then
        click(x + 15, y, 300)
        return 1
    end
    return 0
end

function Event:openEventTab(name)
    Hud:clickButton('events')

    if (Event:getEventTabName() == name) then
        return 1
    end

    Hud:leftScrollModalTabs(10)
    Hud:clickFirstTab()

    for i = 1, 10 do
        if (Event:clickNextTab() == 0) then
            Hud:rightScrollModalTabs(2)
        end
        if (Event:getEventTabName() == name) then
            return 1
        end
    end
    return 0
end
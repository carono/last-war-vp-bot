--lua

Event = {
    names = {
        military_race = {},
        winter_storm = {},
        desert_storm = {},
        zombie_siege = {},
        marshal = {},
        code_name = {},
        social = {},
        judgment_day = {},
        defense_breakthrough = {}
    }
}

function Event:open()
    return Hud:clickButton('events')
end

function Event:collectMilitaryRaceGifts()
    log('Collect military race gifts')
    if (kfindcolor(770, 538, 50943) == 1) then
        click(686, 456, 500)
        close_gift_modal()
        wait(2000)
    end
    if (kfindcolor(961, 542, 50943) == 1) then
        click(907, 458, 500)
        close_gift_modal()
        wait(2000)
    end
    if (kfindcolor(1159, 537, 50943) == 1) then
        click(1078, 458, 500)
        close_gift_modal()
        wait(2000)
    end
    if (kfindcolor(696, 344, 1886538) == 1) then
        click(660, 288, 500)
        close_gift_modal()
        wait(1000)
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
    if kfindcolor(1135, 184, 16777215) == 1 then
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
    if kfindcolor(1087, 657, 8777688) == 1 then
        return 'judgment_day'
    end
    if kfindcolor(726, 795, 1723853) == 1 then
        return 'defense_breakthrough'
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
    if (Event:getEventTabName() == name) then
        return 1
    end

    Map:normalize()
    Hud:clickButton('events')

    Hud:leftScrollModalTabs(10)
    Hud:clickFirstTab()

    log('Try find ' .. name .. ' event')
    for i = 1, 10 do
        log('Tab ' .. i .. 'is ' .. Event:getEventTabName())
        if (Event:getEventTabName() == name) then
            return 1
        end
        if (Event:clickNextTab() == 0) then
            Hud:rightScrollModalTabs(2)
        end
    end
    return 0
end

function Event:collectJudgmentDayGifts()
    log('Collect judgment day gifts')
    if click_if_red(1164, 285) == 1 then
        wait(1000)
        click_green_button(879, 938)
        close_gift_modal()
        escape(1000)
    end
end
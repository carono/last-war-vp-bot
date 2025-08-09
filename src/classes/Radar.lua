--lua
Radar = {}

local collectFinishedTasksCount = 0

function Radar:hasTreasureExcavatorNotification()
    if (kfindcolor(1047, 965, 686838) == 1 or kfindcolor(1055, 975, 2964595) == 1) then
        return 1
    end
    return 0
end

function Radar:hasEasterEggNotification()
    if (kfindcolor(1045, 970, 52223) == 1 or kfindcolor(1014, 970, 5425394) == 1) then
        return 1
    end
    return 0
end

function Radar:searchEasterEggInChat()
    return find_color(694, 214, 792, 968, 4177663)
end

function Radar:clickEasterEggModal()
    click(935, 706, 100)
    click(935, 706, 100)
    click(935, 706, 100)
end

function Radar:open()
    if (Hud:clickButton('radar') == 1) then
        wait(2000)
        return 1
    end
    return 0
end

function Radar:searchTask()
    local x, y
    x, y = find_colors(653, 190, 1186, 861, { { 890, 306, 3773172 }, { 889, 372, 7066879 } })
    if (x > 0) then
        return x, y + 50
    end

    x, y = find_colors(653, 190, 1186, 861, { { 1094, 486, 14535758 }, { 1095, 544, 15652689 } })
    if (x > 0) then
        return x, y + 50
    end

    x, y = find_colors(653, 190, 1186, 861, { { 1093, 655, 5591122 }, { 1095, 707, 12434365 } })
    if (x > 0) then
        return x, y + 50
    end

    x, y = find_colors(653, 190, 1186, 861, { { 681, 436, 8701987 }, { 682, 496, 9428001 } })
    if (x > 0) then
        return x, y + 50
    end

    x, y = find_colors(653, 190, 1186, 861, { { 708, 690, 14601041 }, { 694, 750, 15718483 } })
    if (x > 0) then
        return x, y + 50
    end

    return 0, 0
end

function Radar:executeTask()
    local executeTimeout = 3000
    Radar:clickExecuteTaskButton()
    local result = 0
    if (click_green_button(833, 640, 2000) == 1) then
        result = 1
    end
    if (is_blue(916, 673) == 1) then
        Hero:march()
        result = 1
    end
    if (click_green_button(897, 692, 2000) == 1) then
        click(897, 692, 2000)
        Hero:march()
        result = 1
    end
    if (click_if_color(836, 635, '(4354047)', nil, nil, 2000) == 1) then
        Hero:march()
        result = 1
    end
    if (click_if_color(889, 779, 4354303, nil, nil, 2000) == 1) then
        -- single zombie
        Hero:march()
        result = 1
    end
    if (click_if_color(906, 684, '(5547258)', nil, nil, 2000) == 1) then
        Hero:march()
        result = 1
    end
    if (result == 1) then
        Hud:closeNpcDialogs()
        wait(executeTimeout)
        close_gift_modal()
        return 1
    end
    return 0
end

function Radar:clickExecuteTaskButton()
    if (Hud:checkOpened('radar') == 1 and is_blue(898, 1034) == 1) then
        click(898, 1034, 3000)
        Hud:closeNpcDialogs()
        return 1
    end
    return 0
end

function Radar:searchAndExecute()
    Radar:clickExecuteTaskButton()

    if (Hud:checkOpened('radar') == 1) then
        local x, y = Radar:searchTask();
        if (x > 0) then
            click(x, y, 1300)
            if (close_gift_modal() == 1) then
                return 1
            end
        end
    end

    return Radar:executeTask()
end

function Radar:collectFinishedTasks()
    if (collectFinishedTasksCount > 5 or Game:userIsActive() == 1) then
        collectFinishedTasksCount = 0
        Map:normalize()
        return 0
    end
    if (self:open() == 1) then
        log('Collecting tasks')
        local x, y = find_color(630, 176, 1186, 818, red_color)
        if (x > 0) then
            click(x - 15, y + 15, 1000)
            close_gift_modal()
            if (click_blue_button(857, 1030) == 1) then
                wait(5000)
                Radar:executeTask()
            end
            collectFinishedTasksCount = collectFinishedTasksCount + 1
            return self:collectFinishedTasks()
        end
        Map:normalize()
    end
    if (collectFinishedTasksCount > 0) then
        collectFinishedTasksCount = 0
        return 1
    end
    return 0
end

function Radar:autoFinishTasks()
    if (self:open() == 1 and click_blue_button(959, 1043) == 1) then
        log('Finish tasks')
        wait(3000)
        Map:normalize()
        return 1
    end
    return 0
end

function Radar:executeAllTasks()
    Map:normalize();
    Hud:clickButton('radar')
    local collectFinished = Radar:collectFinishedTasks()

    Map:normalize();
    Hud:clickButton('radar')
    local executeTask = Radar:searchAndExecute()
    if (collectFinished == 1 or executeTask == 1) then
        return Radar:executeAllTasks();
    end
    return 0
end

function Radar:collectFinishedTrucks()
    if Hud:clickButton('trucks') == 1 then
        click(1096, 1055)
        for i = 1, 4 do
            local x, y = find_color(727, 317, 1066, 420, '(14062642,15702825,13272105)')
            if (x > 0) then
                click(x, y, 1000)
                close_gift_modal()
                wait(5000)
                escape(1000, 'Close truck info')
            end
        end
    end
    Map:normalize()
end

function Radar:setTrucks()
    --and Storage:getDay('setTrucks') ~= 1
    if Hud:clickButton('trucks') == 1 then
        click(1096, 1055, 2000)
        :: search_truck ::
        local x, y = find_color(758, 460, 1032, 487, 4383636)
        if (x > 0) then
            if (click_and_wait_color(x, y, blue_color, 960, 937) == 1) then
                wait(1000)
                :: search_ur ::
                if (kfindcolor(1062, 358, 3621342) == 1) then
                    log('Out of tickets')
                    escape(5000)
                    if (click_blue_button(975, 942, 2000) == 1) then
                        log('Send ordinary truck')
                        goto search_truck
                    end
                end

                if (kfindcolor(702, 442, ur_color) == 1 and click_blue_button(975, 942, 2000) == 1) then
                    log('Send UR truck')
                    goto search_truck
                end

                if (click(1100, 447, 2000) == 1) then
                    log('Change change truck')
                    if (click_green_button(1025, 342, 2000) == 1) then
                        log('Confirm change truck')
                    end
                    goto search_ur
                end
            end
        end
        x, y = find_color(758, 460, 1032, 487, 13290186)
        move(x, y)
        if (x > 0) then
            Storage:setDay('setTrucks', 1)
        end
        Map:normalize()
    end
end
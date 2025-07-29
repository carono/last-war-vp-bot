--lua
Radar = {}

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

function Base:radarIsOpen()
    return kfindcolor(1071, 28, stamina_color)
end

function Radar:open()
    if (Base:radarIsOpen() == 1 or Hud:clickButton('radar') == 1) then
        wait(2000)
        return 1
    end
    return 0
end

function Radar:executeTask()
    if (is_green(833, 640) == 1) then
        click(833, 640, 2000)
    end
    if (is_blue(916, 673) == 1) then
        click(916, 673, 2000)
        Hero:march()
        wait(2000)
    end
    if (is_green(897, 692) == 1) then
        click(897, 692, 2000)
        Hero:march()
        wait(2000)
        Hud:closeNpcDialogs()
    end
    if (kfindcolor(836, 635, '(4354047)') == 1) then
        click(836, 635, 2000)
        Hero:march()
        wait(2000)
    end
end

function Radar:collectFinishedTasks(count)
    count = count or 0
    if (count > 20) then
        Map:normalize()
        return 0
    end
    if (self:open() == 1) then
        log('Collecting tasks')
        local x, y = find_color(630, 176, 1186, 818, red_color)
        log(x, y)
        if (x > 0) then
            --click(x - 15, y + 15, 500)
            click(x - 15, y + 15, 1000)
            close_gift_modal()
            if (click_blue_button(857, 1030) == 1) then
                wait(5000)
                Radar:executeTask()
            end
            return self:collectFinishedTasks(count + 1)
        end
        Map:normalize()
    end
    if (count > 0) then
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
                    if (click_green_button(1025, 342, nil, nil, 2000) == 1) then
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
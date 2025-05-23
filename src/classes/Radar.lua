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
    if (Base:radarIsOpen() == 1 or Hud:clickButton('radar')) then
        wait(2000)
        return 1
    end
    return 0
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
            click(x - 15, y + 15, 500)
            click(x - 15, y + 15, 1000)
            close_gift_modal()
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
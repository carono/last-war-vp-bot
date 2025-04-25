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
    Base:clickRadarButton()
    return Base:radarIsOpen()
end

function Radar:collectFinishedTasks()
    if (self:open() == 1) then
        local x, y = find_red_mark(630, 176, 1186, 818)
        if (x > 0) then
            click(x, y, 1000)
            close_gift_modal()
            return self:collectFinishedTasks()
        end
    end
end


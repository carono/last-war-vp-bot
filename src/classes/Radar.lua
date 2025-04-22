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
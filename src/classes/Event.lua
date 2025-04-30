--lua

Event = {}

function Event:open()
    return Hud:clickButton('events')
end

function Event:collectGW()
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

function Event:openGWTab()
    if (kfindcolor(670, 114, 1934802) == 1) then
        return 1
    end
    Hud:leftScrollModalTabs(10)
    click(676, 108, 200)
    return 1
end
--lua

Promo = {
    cords = { 1754, 97 }
}

function Promo:isMarked()
    return is_red(Promo.cords[1], Promo.cords[2])
end

function Promo:isOpen()
    kfindcolor(926, 31, 6114370)
end

function Promo:open()
    log('Try promo modal opening')
    click_and_wait_color(Promo.cords[1], Promo.cords[2], 6114370, 926, 31)
    return self:isOpen()
end

function Promo:getMark()
    return find_red_mark(587, 63, 1199, 93)
end

function Promo:clickMarkedTab()
    local x, y = self:getMark()
    if (x > 0) then
        click(x - 50, y + 50, 1000)
        return 1
    end
    return 0
end

function Promo:isArsenalBattle()
    if kfindcolor(945, 287, 13522176) == 1 and kfindcolor(1042, 240, 3112601) then
        return 1
    end
    return 0
end

function Promo:clickGetButtonInArsenalBattle()
    local x, y = find_color(1145, 438, 1176, 979, 4187738)
    if (x > 0) then
        log('Click get-all button in arsenal battle')
        click(x, y, 500)
        close_gift_modal()
        return self:clickGetButtonInArsenalBattle()
    end
    return 0
end

function Promo:clickGetButtonSupply()
    if (click_green_button(783, 1067) == 1) then
        wait(2000)
        close_gift_modal()
    end

    if (is_red(752, 267) == 1 and is_blue(726, 291) == 1) then
        log('Get free keys')
        if (click_blue_button(728, 291) == 1 and click_green_button(1111, 302) == 1) then
            close_gift_modal()
            escape(300, 'Close modal with free keys')
        end
    end
end

function Promo:clickGetAllButton()
    if (kfindcolor(889, 1037, 4187738) == 1) then
        log('Click get-all button in promo')
        click(889, 1037, 1000)
        close_gift_modal()
        return 1
    end
    return 0
end

function Promo:collectGifts(force)
    force = force or 0
    if (self:isMarked() == 1 or force == 1) then
        self:open()
        if (Promo:clickMarkedTab() == 1) then
            Promo:clickGetAllButton()
            Promo:clickGetButtonInArsenalBattle()
            Promo:clickGetButtonSupply()
        end
        Map:normalize()
        return 1
    end
    return 0
end
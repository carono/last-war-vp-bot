--lua
Base = {}

function Base:openBase()
    Map:openBase()
end

function Base:clickHireSurvival()
    if (kfindcolor(843, 801, 16765462) == 1) then
        log('Hire new survival')
        click(843, 801, 1500)
        return self:clickHireSurvival()
    end
    return 0
end

function Base:getSurvival()
    return find_color(867, 471, 955, 566, 2039583)
end

function Base:clickSurvival()
    local x, y = Base:getSurvival()
    if (x > 0) then
        log('Find survival with gift or new, clicking')
        click(x, y, 500)
        click(x, y, 500)
        Base:clickHireSurvival()
        return Base:clickSurvival()
    end
    return 0
end

function Base:clickSurvivalButton()
    if (Map:isBase() == 1) then
        local x, y = find_colors(11, 506, 83, 913, { { 22, 553, 16777207 }, { 59, 549, 16777208 }, { 32, 537, 16776699 } })
        if (x > 0) then
            click(x, y, 200)
            wait(200)
        end
    end
end

function Base:greetingSurvivals()
    Base:clickSurvivalButton()
    Base:clickSurvival()
end

function Base:getVipPresents()
    if (Map:isBase() == 1) then
        if click_if_red(42, 158, 64, 130) == 1 then
            wait_color(885, 34, modal_header_color)
            if (click_if_red(1127, 207, 1152, 183) == 1) then
                log('Get vip points')
                wait(2000)
                escape(2000)
            end
            if (click_green_button(1143, 710) == 1) then
                log('Get vip gifts')
                close_gift_modal()
            end
            escape(2000)
        end
    end
end

function Base:isShopModal()
    if kfindcolor(802, 43, 5018864) == 1 and kfindcolor(895, 32, 12048886) == 1 then
        return 1
    end
    return 0
end

function Base:openShop()
    log('Opening shop')
    click(1722, 31, 1000)
    return 1
end

function Base:getShopGifts(force)
    force = force or 0
    log(force)
    log(Base:isShopModal())
    if (force == 1 and Base:isShopModal() == 0) then
        Base:openShop()
    end
    if (Base:isShopModal() == 0) then
        log('Shop modal is not opening,')
    end
    local x, y = find_red_mark(701, 48, 1184, 61)
    if (x > 0) then
        log('Has new shop gifts, try collect')
        click(x - 50, y + 50, 1000)
        if (click_red_mark(689, 388) == 1) then
            log('Get daily promo diamonds')
            close_gift_modal()
        end
        if (click_green_button(873, 1035) == 1) then
            log('Get super monthly card gift')
            close_gift_modal()
        end
        if (click_red_mark(684, 315) == 1) then
            log('Get daily card diamonds')
            close_gift_modal()
        end
        return 1
    else
        log('No shop gifts')
    end
    if (is_red(1181, 83) == 1) then
        log('Pull tabs')
        drag_tabs()
        return Base:getShopGifts(force)
    end
    if (Base:isShopModal() == 1) then
        escape(1000, 'Close shop modal')
    end
    return 0
end
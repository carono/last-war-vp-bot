--lua
Base = {}

function Base:openBase(force)
    force = force or 0
    if (Map:isWorld() == 1 or force == 1) then
        Map:openMap()
    end
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
    local x, y = find_color(867, 471, 955, 566, '(6676611,16549736,2744831,2039583)')
    if (x > 0) then
        log('Find survival')
        return x, y
    end
    return 0, 0
end

function Base:clickSurvival()
    local x, y = Base:getSurvival()
    if (x > 0) then
        log('Find survival with gift or new, clicking')
        click(x, y, 1500)
        click(x, y, 1500)
        Hud:closeNpcDialogs()
        Base:clickHireSurvival()
        click_blue_button(960, 820)
        return 1
    end
    return 0
end

function Base:findRadarButton()
    return find_colors(11, 506, 83, 913, { { 26, 805, 14067020 }, { 37, 770, 11371842 } })
end

function Base:findMissionButton()
    return find_colors(11, 506, 83, 913, { { 48, 701, 14261531 }, { 51, 727, 14064152 } })
end

function Base:findSurvivalButton()
    if (Map:isBase() == 1) then
        return find_colors(11, 506, 83, 913, { { 33, 563, 14262085 }, { 61, 545, 10319159 } })
    end
    return 0, 0
end

function Base:clickSurvivalButton()
    if (Map:isBase() == 1) then
        local x, y = Base:findSurvivalButton()
        if (x > 0) then
            click(x, y, 400)
            return 1
        end
    end
    return 0
end

function Base:clickRadarButton()
    local x, y = Base:findRadarButton()
    if (x > 0) then
        click_and_wait_color(x, y, stamina_color, 1071, 28)
        wait(500)
        return 1
    end
    return 0
end

function Base:clickMissionButton()
    local x, y = Base:findMissionButton()
    if (x > 0) then
        click_and_wait_color(x, y, modal_header_color, 1176, 15)
        wait(500)
        return 1
    end
    return 0
end

function Base:greetingSurvivals()
    if (Hud:clickButton('survivals') == 1) then
        wait(2000)
        Base:clickSurvival()
    end
end

function Base:getVipPresents()
    if (Map:isBase() == 1) then
        log('Check vip if marked')
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
        Map:normalize()
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
        Map:normalize()
        return 1
    else
        log('No shop gifts')
    end
    if (is_red(1181, 83) == 1) then
        log('Pull tabs')
        drag_tabs()
        return Base:getShopGifts(force)
    end
    Map:normalize()
    return 0
end

function Base:findOreMine()
    return find_color(99, 177, 1653, 949, 12581626)
end

--function Base:findBreadResource()
--    return find_color(99, 177, 1653, 949, '(2054105, 4815280)')
--end

function Base:findProgress()
    return find_color(139, 129, 1666, 986, '(6532682, 6336583)')
end

function Base:findOreResource()
    return find_color(139, 129, 1666, 986, 14062113)
end

function Base:collectAdvancedResourcesByOneClick()
    local x, y
    x, y = Base:findProgress();
    if (x > 0) then
        log('Collect resources')
        click(x, y, 2000)
        return 1
     end

    x, y = Base:findOreMine();
    if (x > 0) then
        log('Collect resources')
        click(x, y, 2000)
        return 1
    end

    log('Resources not found')
    return 0
end

function Base:collectMilitaryTrack()
    log('Check military track')
    if (kfindcolor(440, 842, '(13138464-15704617)') == 1) then
        if (click_and_wait_color(440, 847, green_color, 964, 739) == 1) then
            click_green_button(964, 739)
            close_gift_modal()
            Map:normalize()
        end
    end
end
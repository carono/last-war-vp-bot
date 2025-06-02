Rally = {
    rally_target = {
        doom_walker = { 1104, 277, '(8821360-8493169)' },
        doom_elite_s2 = { 1127, 294, '(2985694-2721495)' },
        cl7 = { 1050, 316, '(14074989-14073708)' }
    }
}

function Rally:joinIfExist(to_last_place)
    to_last_place = to_last_place or 0
    if (Rally:openList() == 1) then
        if (to_last_place == 1) then
            log('wait last place')
            wait_not_color(819, 318, 5438656, 30000)
        end
        if (Rally:join() == 1) then
            log('Start join rally')
            Rally:applyJoin()
        else
            if (Rally:listIsOpen() == 1) then
                log('Out rally list')
                Alliance:clickBack()
            end
        end
    end
end

function Rally:listIsOpen()
    local back_button = kfindcolor(606, 118, 560895)
    local big_blue_button = kfindcolor(865, 1017, 16765462)
    local daily_yellow_line = kfindcolor(616, 172, 6535924)
    local store = kfindcolor(792, 1055, 5625855)
    local first_place_rating = kfindcolor(633, 226, 4146908)
    if back_button == 1 and big_blue_button ~= 1 and daily_yellow_line ~= 1 and store ~= 1 and first_place_rating ~= 1 then
        return 1
    end
    return 0
end

function Rally:join()
    if (kfindcolor(897, 311, '(5438670-5962650)') == 1) then
        if click_and_wait_color(898, 322, 16777215, 725, 857, 2000) == 0 then
            escape(800)
            return 0
        end
        return 1
    end
end

function Rally:hasActiveRallies()
    return is_red(1695, 700)
end

function Rally:hasAvailableRally()
    return kfindcolor(1751, 672, 3741951, 3)
end

function Rally:openList()
    if (Rally:hasActiveRallies() == 1 and Rally:hasAvailableRally() == 1) then
        log('open rally list')
        return click_and_wait_color(1721, 701, 16765462, 648, 1033)
    end
end

function Rally:applyJoin()
    if (kfindcolor(1075, 695, 8882570) == 1) then
        log('Low troops for rally')
        Map:normalize()
        return 0
    end

    if (kfindcolor(955, 835, blue_color) == 1) then
        return click_and_wait_not_color(954, 850, 16756752)
    end
end

function Rally:createDoomElite()
    if (Map:openMap() == 1) then
        if (Hud:clickButton('search') == 1) then
            click(1085, 548, 1000)
            if (click_blue_button(898, 1013) == 1) then
                wait(2000)
                if (click_and_wait_color(897, 827, blue_color, 918, 831, 2000, 1000, 'Try create rally') == 0) then
                    log('Cant create rally')
                    Map:normalize()
                    return -2
                end

                local result = Hero:march()
                Map:normalize()
                return result
            end
        end
    end
    return 0
end

function Radar:isDoomWalker()
    return kfindcolor(1104, 277, '(8821360-8493169)');
end

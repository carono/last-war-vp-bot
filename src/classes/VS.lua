--lua
VS = {}

function VS:isRadarDay()
    local currentDay = Server:getDay(1)
    log(currentDay)
    if (currentDay == 'Monday' or currentDay == 'Wednesday' or currentDay == 'Friday' or currentDay == 'Saturday') then
        return 1
    end
    return 0
end

function VS:collectGifts()
    if (Hud:clickButton('vs') == 1) then
        if (click_if_yellow(776, 565) == 1) then
            close_gift_modal()
        end
        if (click_if_yellow(952, 565) == 1) then
            close_gift_modal()
        end
        if (click_if_yellow(1136, 565) == 1) then
            close_gift_modal()
        end
        Map:normalize()
    end
end
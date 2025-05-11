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
        click(659, 126, 1000)
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

function VS:collectDroneComponents()
    if (Server:getDay(1) == 'Wednesday') then
        if (Hud:clickButton('inventory') == 1) then
            --local color1 = '(2331870,2861280,2199518,2198747,2795489)'
            --local color2 = '(12146539,11884395,12474475,12014955,12409707)'
            local color1 = '(2331870,2861280,2199518)'
            local color2 = '(12146539,11884395,12474475)'
            repeat
                local x, y = find_colors(630, 216, 1162, 686, { { 794, 243, color1 }, { 836, 249, color2 } })
                if (x > 0) then
                    click(x, y, 400)
                    click(974, 923)
                    if (click_blue_button(938, 1019) == 1) then
                        close_gift_modal()
                        wait(100)
                    end
                end
            until x == 0
            Map:normalize()
        end
    end
end
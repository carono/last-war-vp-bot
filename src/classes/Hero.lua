Hero = {}

function Hero:clickAttack()
    if (kfindcolor(757, 574, 4354047) == 1) then
        click_and_wait_color(757, 574, 16756752, 958, 856, 1)

        return
    end
end

function Hero:openAttackMenu()
    if (not Hero:attackMenuIsOpen() and kfindcolor(786, 600, 4354047)) then
        click_and_wait_color(786, 600, 16756752, 958, 856, 1)
        log('Open attack')
        return
    end
    require("lib/color")
    local path = [["img/attack_button.bmp"]]
    local handle = Window:getGameHandle()
    x, y, WidthReference, HeightReference = windowpos(handle)
    attackButton = findimage(100, 100, WidthReference, HeightReference, { path }, 2, 95, 1, 3)
    log(attackButton, 100, 100, WidthReference, HeightReference)
    if (attackButton) then
        click_and_wait_color(attackButton[1][1], attackButton[1][2], 16756752, 958, 856, 1)
    end
end

function Hero:attackMenuIsOpen()
    return kfindcolor(958, 856, 16756752) == 1
end

function Hero:select()
    if (Hero:attackMenuIsOpen() and kfindcolor(748, 977, 6552575) ~= 1) then
        log('Select hero')
        click_and_wait_color(748, 977, 6552575, nil, nil, 1)
    end
end

function Hero:clickAttack()
    left(955, 826)
    log('Click attack')
end

function Hero:attackIfCan()
    if (Hero:attackMenuIsOpen()) then

        if (kfindcolor(650, 974, 16579836, 1) == 1 and kfindcolor(659, 982, 15592425) == 1) then
            --Hero already attacking
            log('In process..')
            stop_script()
        end

        if (kfindcolor(658, 983, 14069823)) then
            --Hero is sleap
            Hero:clickAttack()
        end
        if (kfindcolor(658, 973, 5197303, 11) and kfindcolor(650, 977, 16579836, 1)) then
            --Hero returning
            Hero:clickAttack()
        end
        if (kfindcolor(658, 983, 14069823)) then
            --Hero harvesting
            Hero:clickAttack()
        end
    end
end

--[[
if (kfindcolor(958, 856, 16756752) == 1) then
    log('Open selecting')





    if (kfindcolor(658, 971, 6473532)) then
        log('Attack 2')
        left(955, 826)
    end




end
]]--
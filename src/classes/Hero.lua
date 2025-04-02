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
        log('Open attack menu')
        return
    end
    require("lib/color")
    local path = [["img/attack_button.bmp"]]

    x, y = Window:modifyCord(716, 620)
    x2, y2 = Window:modifyCord(1093, 856)
    attackButton = findimage(x, y, x2, y2, { path }, 2, 80, 1, 10)
    log("Attack button img", attackButton)
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
        log('Menu is opened, try attack...')
        if (kfindcolor(650, 974, 16579836, 1) == 1 and kfindcolor(659, 982, 15592425) == 1) then
            --Hero already attacking
            log('In process..')
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
        if (kfindcolor(649, 977, 6475577)) then
            --Hero on tile
            Hero:clickAttack()
        end
    end
end
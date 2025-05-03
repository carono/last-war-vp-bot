Hero = {}

function Hero:clickAttack()
    if (kfindcolor(757, 574, 4354047) == 1) then
        click_and_wait_color(757, 574, 16756752, 958, 856, 1)
        return
    end
end

function Hero:openAttackMenu()
    if (not Hero:attackMenuIsOpen() == 1 and kfindcolor(786, 600, 4354047) == 1) then
        click_and_wait_color(786, 600, 16756752, 958, 856, 2000, 500)
        log('Open attack menu')
        return
    end

    local x, y = find_color(790, 615, 994, 720, 4354047)

    if (x > 0) then
        click_and_wait_color(x, y, 16756752, 958, 856, 1)
        return 1
    end
    return 0
end

function Hero:attackMenuIsOpen()
    return kfindcolor(958, 856, 16756752)
end

function Hero:select()
    if (Hero:attackMenuIsOpen() == 1 and kfindcolor(748, 977, 6552575) ~= 1) then
        log('Select hero')
        click_and_wait_color(748, 977, 6552575, nil, nil, 1)
    end
end

function Hero:clickAttack()
    click(955, 826)
    log('Click attack')
end

function Hero:attackIfCan()
    local startX = 641
    local startY = 970
    local endX = 666
    local endY = 998

    if (Hero:attackMenuIsOpen() == 1) then
        log('Menu is opened, try attack..1.')
        if (is_red(662, 985) and is_white(650, 981)) then
            --Hero already attacking
            log('In process..')
        end
        if (is_blue(649, 980) == 1) then
            --Hero is sleep
            log('Attack from sleep')
            Hero:clickAttack()
        end
        --if (find_colors()) then
        --    --Hero return
        --    log('Attack from running')
        --    Hero:clickAttack()
        --end
        --if (kfindcolor(658, 983, 14069823) == 1) then
        --    --Hero harvesting
        --    log('Attack from harvesting')
        --    Hero:clickAttack()
        --end
        --if (kfindcolor(649, 977, 6475577) == 1) then
        --    --Hero on tile
        --    log('Attack from tile')
        --    Hero:clickAttack()
        --end
    end
end
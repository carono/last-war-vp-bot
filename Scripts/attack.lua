--lua
require("dist/init")
Window:attachHandle()

if (kfindcolor(757, 574, 4354047) == 1) then
    click_and_wait_color(757, 574, 16756752, 958, 856)
    log('Open attack')
end

if (kfindcolor(958, 856, 16756752) == 1) then
    log('Open selecting')

    if (kfindcolor(748, 977, 6552575) ~= 1) then
        left(694, 998)
        log('Select hero')
    end

    if (kfindcolor(658, 983, 14069823)) then
        log('Attack 1')
        left(955, 826)
    end

    if (kfindcolor(658, 971, 6473532)) then
        log('Attack 2')
        left(955, 826)
    end

    if (kfindcolor(658, 983, 14069823)) then
        log('Attack 1')
        left(955, 826)
    end

    if (kfindcolor(650, 974, 16579836, 1) == 1 and kfindcolor(659, 982, 15592425) == 1) then
        stop_script()
    end
end

stop_script()
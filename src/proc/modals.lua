function close_gift_modal()
    log('Waiting modal with gifts')
    if (wait_color(1068, 342, 7059183, 2000) == 1) then
        escape(1000, 'Close gift modal')
        if (kfindcolor(1068, 342, 7059183)) then
            escape(1000, 'Close gift modal try 2')
        end
        return 1
    end
    return 0
end

function close_help_modal()
    log('Waiting modal with gifts')
    if (wait_color(1084, 327, 2669297, 2000) == 1) then
        escape(1000, 'Close help modal')
        return 1
    end
    return 0
end

function close_connection_error()
    if kfindcolor(913, 573, 2546431) == 1 then
        log('Connection error, click something 1')
        click(913, 573, 400)
    end
    if kfindcolor(862, 593, 16765462) == 1 then
        log('Connection error, click something 2')
        click(862, 593, 400)
    end
    if (Game:hasUpdateFinishedModal() == 1) then
        log('Updates is finished, click OK and wait 30s')
        click(910, 597, 30000)
    end

    if (is_blue(1061, 597) == 1 and is_yellow(856, 593) == 1) then
        log('Connection error, click confirm and wait 30s')
        click(1061, 597, 30000)
    end
end
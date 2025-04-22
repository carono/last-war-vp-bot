function close_gift_modal()
    log('Waiting modal with gifts')
    if (wait_color(1068, 342, 7059183, 2000) == 1) then
        escape(1000, 'Close gift modal')
    end
end

function close_connection_error()
    if kfindcolor(913, 573, 2546431) == 1 then
        click(913, 573, 400)
    end
    if kfindcolor(862, 593, 16765462) == 1 then
        click(862, 593, 400)
    end
    if (Game:hasUpdateFinishedModal() == 1) then
        --Confirm update finished
        log('Updates is finished, click OK and wait 30s')
        click(910, 597, 30000)
    end
end
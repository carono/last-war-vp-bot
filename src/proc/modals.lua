function close_gift_modal()
    wait_color(1068, 342, 7059183, 2000)
    click_and_wait_not_color(1464, 167, 7059183, 1068, 342)
end

function close_connection_error()
    if kfindcolor(913, 573, 2546431) == 1 then
        left(913, 573, 400)
    end
    if kfindcolor(862, 593, 16765462) == 1 then
        left(862, 593, 400)
    end
    if (Game:hasUpdateFinishedModal() == 1) then
        --Confirm update finished
        log('Updates is finished, click OK and wait 30s')
        left(910, 597, 30000)
    end
end
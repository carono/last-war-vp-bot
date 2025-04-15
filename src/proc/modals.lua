function close_gift_modal()
    wait_color(1068, 342, 7059183, 2000)
    click_and_wait_not_color(1464, 167, 7059183, 1068, 342)
end

function close_simple_modal(count)
    require("lib/color")
    local path = [["img/close_modal_button.bmp"]]
    count = count or 1
    for i = 1, count do
        local result, errorCode = findimage(1128, 71, 1192, 295, { path }, 2, 30, 1)
        if (result and (kfindcolor(result[1][1] - 25, result[1][2], 10257016) == 1 or kfindcolor(result[1][1] - 25, result[1][2], 10257017) == 1)) then
            log('Successful find close modal button', errorCode)
            click_and_wait_not_color(result[1][1], result[1][2], 16777215)
        else
            break
        end
        wait(300)
    end
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
        log('Updates is finished, click OK')
        left(910, 597, 5000)
    end
end
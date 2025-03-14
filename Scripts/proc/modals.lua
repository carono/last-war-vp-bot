function pull_request_list()
    if (kfindcolor(621, 170, 16054013) == 1 and kfindcolor(1151, 176, 16054013) == 1) then
        kdrag(863, 223, 863, 932)
    end
end

function pull_list()
    local timer = 0
    require("color")
    --address, width, height, length = getimage(658, 221, 660, 429)
    --saveimage("tmp.bmp", address)


    --local path = [["tmp.bmp"]]
    log(ext.findimage(0, 0, 1024, 1024, { path }, 2))

    --    while (not (kfindcolor(1012, 232, 8617353) == 1 and kfindcolor(1049, 279, 12894420) == 1)) do
    --        if timer > 30000 then
    --            break
    --        end
    --        pull_request_list()
    --        wait(200)
    --        pull_request_list()
    --        wait(200)
    --    end
end

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


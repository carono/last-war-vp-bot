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
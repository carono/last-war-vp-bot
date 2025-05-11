Ministry = {}
MinistryPos = {
    vp = { 627, 440 },
    strategy = { 817, 427 },
    security = { 1002, 427 },

    development = { 627, 673 },
    science = { 817, 673 },
    interior = { 1002, 673 },

    mil_commander = { 691, 420 },
    adm_commander = { 925, 420 }
}

function Ministry:getMinisterCords(minister)
    local x = MinistryPos[minister][1]
    local y = MinistryPos[minister][2]
    if (Ministry:capitolIsCapturedOrConquered() == 1 and (minister ~= "mil_commander" and minister ~= "adm_commander")) then
        y = y + 220
    end
    return x, y
end

--function Ministry:checkOvertime(minister)
--    require("lib/color")
--    --  storage = require [[lib/storage]]
--
--    local x = MinistryPos[minister][1]
--    local y = MinistryPos[minister][2]
--    x, y = Window:modifyCord(x, y)
--
--    local x1 = x + 25
--    local y1 = y + 170
--    local x2 = x + 130
--    local y2 = y + 195
--    --local y2 = y + 250
--    local path = [["img/time.bmp"]]
--    --lessFiveMinutes = findimage(x1, y1, x2, y2, { path }, 2, 95, 1, 80)
--
--    local a = findcolor(x1, y1, x2, y2, 16777215, '%ResultArray', 2, 1, 3)
--
--    -- storage.save("colors.tmp", ResultArray)
--
--    saveimage_from_screen(x1, y1, x2, y2, "img/" .. minister .. '_tmp.bmp')
--
--    if (a == nil) then
--        return 2
--    end
--
--    if (lessFiveMinutes == nil) then
--        return 1
--    end
--
--    return 0
--end

function Ministry:clickDismiss()
    if kfindcolor(817, 929, 6513405) == 1 then
        click(817, 929, 300)
    end
end

function Ministry:clickConfirmDismiss()
    if kfindcolor(809, 599, 16765462) == 1 then
        click(809, 599, 300)
    end
end

function Ministry:capitolIsCapturedOrConquered()
    if (kfindcolor(1084, 925, 2119560) == 0) then
        --        return 1
    end
    return 0
end

function Ministry:dismiss(x, y)
    if (kfindcolor(1098, 115, 10257017) ~= 1) then
        click(x, y, 300)
    end

    local empty_list = kfindcolor(963, 529, 16054013)
    local has_list_request = kfindcolor(1139, 924, 3741951)

    if (empty_list == 1 and has_list_request == 0) then
        Ministry:clickDismiss()
        Ministry:clickConfirmDismiss()
        click(1152, 113, 300)
    end
end

function Ministry:hasRequest()
    return kfindcolor(30, 18, 3745271);
end

function Ministry:open()
    Profile:open()
    wait(2000)
    Profile:closeLike()
    wait(2000)
    Profile:closeLike()
    Profile:clickMinistry()
end

function Ministry:openMinistryIfRequest()
    if (Ministry:hasRequest() == 1) then
        Ministry:open()
    end
end

function Ministry:hasMinisterRequest(minister)
    local x, y = Ministry:getMinisterCords(minister)
    return kfindcolor(x, y, 2502143, 25)
end

function Ministry:clickMinister(minister)
    local x, y = Ministry:getMinisterCords(minister)
    click_and_wait_color(x, y, 10257017, 628, 122)
end

function Ministry:checkAndApproveMinisterRequest(minister, check_overtime)
    check_overtime = check_overtime or 0
    if (Ministry:hasMinisterRequest(minister) == 1) then
        log(minister .. ' has request')
        Ministry:clickMinister(minister)

        if (Ministry:requestListHasMark() ~= 0) then
            Ministry:openRequestList()
            Ministry:approve()
            local x = 0
            while (kfindcolor(896, 33, 7225143) == 0) do
                escape(1000)
                x = x + 1
                if (x >= 4) then
                    break
                end
            end
        end
    end
end

function Ministry:closemin()
    while (Map:state() == 0) do
        escape(800)
    end
end

function Ministry:clickApproveButton()
    click(1028, 256, 200)
end

function Ministry:requestListHasMark()
    return find_red_mark(1137, 924)
end

function Ministry:openRequestList()
    if (kfindcolor(1108, 955, 16777215) == 1) then
        return click_and_wait_color(1138, 924, 10257017, 1091, 117)
    end
end

function Ministry:hasRequestsInList()
    if (find_red_mark(1006, 214, 1054, 951, 4253017) ~= 0) then
        return 1
    end
    return 0
end

function Ministry:approve()
    wait(500)
    if (Ministry:hasRequestsInList() == 1) then
        if (find_red_mark(829, 642, 980, 945, 14144488) ~= 0) then
            Ministry:pullList()
        end

        local ar1 = {}
        while stored_colors_not_changed(ar1) == 0 do
            Ministry:clickApproveButton()
            Ministry:clickApproveButton()
            Ministry:clickApproveButton()
            log('click approve')
            wait(500)
            ar1 = store_colors_in_range(655, 245)
        end
    end
end

function Ministry:pullList(try)
    try = try or 1
    if (try >= 20) then
        Map:normalize()
        return 0
    end
    wait(400)
    local x, y = Window:modifyCord(923, 218)
    local x2, y2 = Window:modifyCord(975, 315)
    local res = findcolor(x, y, x2, y2, 1, 1, 14144488, '%arr', 2, 1, 5)
    local is_last = 0;
    local oldX, oldY = mouse_pos()
    if (res == 1) then
        x = arr[1][1]
        y = arr[1][2]
        move(x, y)
        kleft_down(x, y)
        move_smooth(x, y + 600)
        wait(100)
        if (kfindcolor(648, 308, 16054013) == 1 and kfindcolor(648, 220, 16054013) == 1) then
            log('is last')
            is_last = 1
        end
        kleft_up(x, y + 600)
        wait(100)
        click(x, y + 600)
        wait(200)
        if (is_last == 0) then
            move(oldX, oldY)
            return self:pullList(try + 1)
        end
    end
    move(oldX, oldY)
end

function Ministry:iAmIsVP()

end

function Ministry:hasMinistryHat()
    if (find_colors(96, 121, 348, 160, { { 125, 151, 8898541 }, { 111, 133, 15726583 } }) > 0) then
        return 'development'
    end
    if (find_colors(96, 121, 348, 160, { { 115, 140, 1056718 }, { 126, 144, 14871791 } }) > 0) then
        return 'security'
    end
    return nil
end
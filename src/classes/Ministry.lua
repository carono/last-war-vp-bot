Ministry = {}
MinistryPos = {
    vp = { 638, 440 },
    strategy = { 825, 440 },
    security = { 1011, 440 },
    development = { 638, 680 },
    science = { 825, 680 },
    interior = { 1011, 680 },
    mil_commander = { 691, 420 },
    adm_commander = { 925, 420 }
}

function Ministry:getMinisterCords(minister)
    local x = MinistryPos[minister][1]
    local y = MinistryPos[minister][2]
    if (Ministry:capitolIsCapturedOrConquered() and (minister ~= "mil_commander" and minister ~= "adm_commander")) then
        y = y + 220
    end
    return Window:modifyCord(x, y)
end

function Ministry:checkOvertime(minister)
    require("lib/color")
    --  storage = require [[lib/storage]]

    local x = MinistryPos[minister][1]
    local y = MinistryPos[minister][2]
    x, y = Window:modifyCord(x, y)

    local x1 = x + 25
    local y1 = y + 170
    local x2 = x + 130
    local y2 = y + 195
    --local y2 = y + 250
    local path = [["img/time.bmp"]]
    --lessFiveMinutes = findimage(x1, y1, x2, y2, { path }, 2, 95, 1, 80)

    local a = findcolor(x1, y1, x2, y2, 16777215, '%ResultArray', 2, 1, 3)

    -- storage.save("colors.tmp", ResultArray)

    saveimage_from_screen(x1, y1, x2, y2, "img/" .. minister .. '_tmp.bmp')

    if (a == nil) then
        return 2
    end

    if (lessFiveMinutes == nil) then
        return 1
    end

    return 0
end

function Ministry:clickDismiss()
    if kfindcolor(817, 929, 6513405) == 1 then
        left(817, 929, 300)
    end
end

function Ministry:clickConfirmDismiss()
    if kfindcolor(809, 599, 16765462) == 1 then
        left(809, 599, 300)
    end
end

function Ministry:capitolIsCapturedOrConquered()
    if (kfindcolor(1084, 925, 2119560) == 0) then
        return 1
    end
    return 0
end

function Ministry:dismiss(x, y)
    if (kfindcolor(1098, 115, 10257017) ~= 1) then
        left(x, y, 300)
    end

    local empty_list = kfindcolor(963, 529, 16054013)
    local has_list_request = kfindcolor(1139, 924, 3741951)

    if (empty_list == 1 and has_list_request == 0) then
        Ministry:clickDismiss()
        Ministry:clickConfirmDismiss()
        left(1152, 113, 300)
    end
end

function Ministry:hasRequest()
    return kfindcolor(30, 18, 3745271);
end

function Ministry:openMinistryIfRequest()
    if (Ministry:hasRequest() == 1) then
        Profile:open()
        Profile:closeLike()
        Profile:clickMinistry()
    end
end

function Ministry:hasMinisterRequest(minister)
    x, y = Ministry:getMinisterCords(minister)
    return kfindcolor(x, y, 2502143, 25)
end

function Ministry:clickMinister(minister)
    x, y = Ministry:getMinisterCords(minister)
    click_and_wait_color(x, y, 10257017, 628, 122)
end

function Ministry:checkAndApproveMinisterRequest(minister, check_overtime)
    check_overtime = check_overtime or 0
    if (Ministry:hasMinisterRequest(minister) == 1) then
        Ministry:clickMinister(minister)

        if (Ministry:requestListHasMark() ~= 0) then
            Ministry:openRequestList()
            Ministry:approve()
            while (kfindcolor(896, 33, 7225143) == 0) do
                escape(1000)
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
    left(1028, 256, 200)
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

function Ministry:pullList()
    local ar1 = {}
    ar1 = store_colors_in_range(655, 245)
    pull_request_list()
    wait(1500)
    if (stored_colors_not_changed(ar1) == 1) then
        log('Checking list...')
        pull_request_list()
        wait(3000)
        ar1 = store_colors_in_range(655, 245)
        if (stored_colors_not_changed(ar1) == 1) then
            log('Finish pull list')
            return 1
        else
            log('Something change, restart pulling list')
            return self:pullList()
        end
    else
        log('Continue pull')
        return self:pullList()
    end
    return 0
end

function Ministry:iAmIsVP()

end
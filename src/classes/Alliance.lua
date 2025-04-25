Alliance = {}
AllianceModal = { startX = 605, startY = 388, endX = 1175, endY = 966 }

function Alliance:isMarked()
    return is_red(1760, 767)
end

function Alliance:isOpen()
    if (kfindcolor(784, 130, 16054013) == 1 and kfindcolor(1145, 227, 7319026) == 1) then
        return 1
    end
    return 0
end

function Alliance:open()
    if (kfindcolor(1725, 855, 16777215) == 1) then
        click_and_wait_color(1725, 792, 16054013, 784, 130)
        return Alliance:isOpen()
    end
    return 0
end

function Alliance:openPresentsTab()
    log('Open present tab')
    click_and_wait_color(829, 537, 560895, 848, 274)
end

function Alliance:getPresent(force)
    force = force or 0
    if (force == 1) then
        self:open()
    end
    if (self:isOpen() == 0) then
        log('Alliance modal not opened, cannot check presents')
        return 0
    end

    self:openPresentsTab()
    self:clickBigGreenButton()

    log('Click premium tab')
    click_and_wait_color(1130, 277, active_tab_color)

    log('Try click get all premium presents')
    click_if_color(1084, 1017, green_color, nil, nil, 1000)
    close_gift_modal()

    click_while_color(1114, 468, green_color)

    Alliance:clickBack()
end

function Alliance:clickBack(count)
    count = count or 1
    for i = 1, count do
        click_if_color(644, 1031, 16765462)
        wait(300)
    end
end

function Alliance:haveMark()
    local x, y = find_red_mark(AllianceModal.startX, AllianceModal.startY, AllianceModal.endX, AllianceModal.endY)
    if (x > 0) then
        return 1
    end
    return 0
end

function Alliance:clickMark()
    local x, y = find_red_mark(AllianceModal.startX, AllianceModal.startY, AllianceModal.endX, AllianceModal.endY)
    if (x ~= nil) then
        click(x, y)
    end
end

function Alliance:clickBigGreenButton()
    if (kfindcolor(909, 1014, 4187738) == 1) then
        log('Click green button')
        click_and_wait_not_color(909, 1014, 4187738, 909, 1014)
        close_gift_modal()
    end
end

function Alliance:applyHelp()
    if (kfindcolor(1646, 791, '(3103061,6177331,1455406,13038591)') == 1) then
        log('Apply alliance help request')
        click(1648, 763, 300)
        return 1
    end
    if (kfindcolor(120, 872, '(3103061,6177331,1455406,13038591)') == 1) then
        log('Send help request alliance for healing troops')
        click(120, 872, 300)
        return 1
    end
    return 0
end

function Alliance:checkTech(force)
    force = force or 0
    if (force == 1) then
        self:open()
    end
    if (self:isOpen() == 0) then
        log('Alliance modal not opened, cannot check tech')
        return 0
    end
    click_and_wait_color(1110, 641, 7756114, 660, 202)
    local x, y = find_colors(612, 212, 1161, 757, { { 802, 582, red_color }, { 816, 591, 16777215 } })
    if (x > 0) then
        log('Successful find recommended tech')
        wait(1000)

        click_and_wait_not_color(x + 50, y + 50, 3940594)
        wait(1000)

        if (is_green(1072, 851) == 1) then
            log('Clicking tech')
            click_while_not_color(1078, 855, 11447982, 954, 856, 400)
        else
            log('Tech already helped')
        end

        wait(3000)

        if (kfindcolor(645, 174, modal_header_color) == 1) then
            escape(1500, 'Close recommended tech modal')
        end
        if (kfindcolor(1105, 133, modal_header_color) == 1) then
            escape(1500, 'Close tech modal')
        end
        --if (kfindcolor(1105, 20, modal_header_color) == 1) then
        --    escape(1500, 'Close alliance tab')
        --end
    else
        log('Recommended tech not found')
        escape(500)
    end
end

function Alliance:openSeason2buildings()
    if (kfindcolor(1165, 890, 3741951) == 1) then
        click(1111, 928)
        click_and_wait_not_color(892, 1031, 16765462)
        close_gift_modal()
        self:clickBack()
    end
end

function Alliance:clickHealTroops()
    if (kfindcolor(122, 865, 646802) == 1) then
        log('Healing troops')
        click_and_wait_color(127, 864, 10257016, 1057, 237)
        click(1033, 874)
    end

    if (kfindcolor(153, 871, '(6867952, 7849964)') == 1) then
        log('Return troops from hospital')
        click(119, 855)
    end
end
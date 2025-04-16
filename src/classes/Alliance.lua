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
        left(1725, 792, 100)
        return 1
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

    click_and_wait_color(1130, 277, 560895)
    log('click premium tab')

    if (kfindcolor(1109, 1016, 4187738) == 1) then
        Alliance:clickBigGreenButton()
    else
        click_and_wait_color(1140, 277, 560895)
        click_while_color(1114, 468, 4187738)
    end

    close_gift_modal()
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
    x, y = find_red_mark(AllianceModal.startX, AllianceModal.startY, AllianceModal.endX, AllianceModal.endY)
    if (x > 0) then
        return 1
    end
    return 0
end

function Alliance:clickMark()
    x, y = find_red_mark(AllianceModal.startX, AllianceModal.startY, AllianceModal.endX, AllianceModal.endY)
    if (x ~= nil) then
        left(x, y)
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
    if (kfindcolor(1646, 791, 3103061) == 1) then
        log('Apply alliance help request')
        left(1648, 763, 300)
        return 1
    end
    if (kfindcolor(120, 872, 13038591) == 1) then
        log('Send help request alliance for healing troops')
        left(120, 872, 300)
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
    x, y = find_red_mark(612, 212, 1161, 757)
    if (x > 0) then
        log('Successful find recommended tech')
        click_and_wait_not_color(x, y, 3940594)
        click_while_not_color(1078, 855, 11447982)
        wait(3000)
        escape(1500)
        escape(1500)
    else
        log('Recommended tech not found')
        escape(500)
    end
end

function Alliance:openSeason2buildings()
    if (kfindcolor(1165, 890, 3741951) == 1) then
        left(1111, 928)
        click_and_wait_not_color(892, 1031, 16765462)
        close_gift_modal()
        self:clickBack()
    end
end

function Alliance:clickHealTroops()
    if (kfindcolor(122, 865, 646802) == 1) then
        log('Healing troops')
        click_and_wait_color(127, 864, 10257016, 1057, 237)
        left(1033, 874)
    end

    if (kfindcolor(153, 871, '(6867952, 7849964)') == 1) then
        log('Return troops from hospital')
        left(119, 855)
    end
end
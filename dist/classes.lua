-- lua allianceButton.lua
AllianceButton = {}
AllianceModal = { startX = 605, startY = 388, endX = 1175, endY = 966 }

function AllianceButton:isMarked()
    return kfindcolor(1760, 767, 3741951)
end

function AllianceButton:open()
    if (kfindcolor(1696, 783, 12688166)) then
        left(1725, 792, 100)
    end
end

function AllianceButton:openPresents()
    log('Open present tab')
    click_and_wait_color(829, 537, 560895, 848, 274)
end

function AllianceButton:getPresent()
    if (kfindcolor(873, 500, 3741951)) then
        self:openPresents()
    end

    self:clickBigGreenButton()

    if (kfindcolor(1182, 247, 1586415)) then
        log('click premium tab')
        click_and_wait_color(1140, 277, 560895)
        click_while_color(1114, 468, 4187738)
    end

    AllianceButton:clickBack()
    AllianceButton:clickBack()
end

function AllianceButton:clickBack()
    click_if_color(644, 1031, 16765462)
end

function AllianceButton:haveMark()
    x, y = find_red_mark(AllianceModal.startX, AllianceModal.startY, AllianceModal.endX, AllianceModal.endY)
    if (x > 0) then
        return 1
    end
    return 0
end

function AllianceButton:clickMark()
    x, y = find_red_mark(AllianceModal.startX, AllianceModal.startY, AllianceModal.endX, AllianceModal.endY)
    if (x ~= nil) then
        left(x, y)
    end
end

function AllianceButton:clickBigGreenButton()
    if (kfindcolor(909, 1014, 4187738) == 1) then
        log('Click green button')
        click_and_wait_not_color(909, 1014, 4187738, 909, 1014)
        close_gift_modal()
    end
end

function AllianceButton:applyHelp()
    if (kfindcolor(1648, 763, 4962287) == 1) then
        left(1648, 763)
    end
end

function AllianceButton:checkTech()
    if (kfindcolor(1165, 597, 3741951) == 1) then
        click_and_wait_color(1110, 641, 7756114, 660, 202)
        x, y = find_red_mark(612, 212, 1161, 757, 3940594)
        if (x > 0) then
            log('Successful find recommended tech')
            click_and_wait_not_color(x, y, 3940594)
            click_while_not_color(1078, 855, 11447982)
            close_simple_modal(2)
        end
    end
end

-- lua window.lua
Window = {}

function Window:resizeCanonical()
    local handle = self:attachHandle()
    width, height = self:getCanonicalSize()
    x, y = windowpos(handle)
    windowpos(x, y, width, height, handle)
end

function Window:getCanonicalSize()
    return 1796, 1154
end

function Window:attachHandle()
    local handle = self:getGameHandle()
    workwindow(handle)
    showwindow(handle, "TOP")
    return handle
end

function Window:getGameHandle()
    local handle = findwindow("Last War-Survival Game")
    return handle[1][1]
end

function Window:modifyCord (xReference, yReference)
    local handle = self:getGameHandle()
    WidthCurrent, HeightCurrent = self:getCanonicalSize()
    x, y, WidthReference, HeightReference = windowpos(handle)
    local xCurrent = (xReference * WidthReference) / WidthCurrent
    local yCurrent = (yReference * HeightReference) / HeightCurrent
    return math.ceil(xCurrent), math.ceil(yCurrent)
end

function Window:canonizeCord (xReference, yReference)
    local handle = self:getGameHandle()
    WidthReference, HeightReference = self:getCanonicalSize()
    x, y, WidthCurrent, HeightCurrent = windowpos(handle)
    local xCurrent = (xReference * WidthReference) / WidthCurrent
    local yCurrent = (yReference * HeightReference) / HeightCurrent
    return math.ceil(xCurrent), math.ceil(yCurrent)
end
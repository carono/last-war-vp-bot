-- lua Alliance.lua
Alliance = {}
AllianceModal = { startX = 605, startY = 388, endX = 1175, endY = 966 }

function Alliance:isMarked()
    return kfindcolor(1760, 767, 3741951)
end

function Alliance:open()
    if (kfindcolor(1696, 783, 12688166)) then
        left(1725, 792, 100)
        return 1
    end
    return 0
end

function Alliance:openPresentsTab()
    log('Open present tab')
    click_and_wait_color(829, 537, 560895, 848, 274)
end

function Alliance:getPresent()
    if (kfindcolor(873, 500, 3741951)) then
        self:openPresentsTab()
    end

    self:clickBigGreenButton()

    if (kfindcolor(1182, 247, 1586415)) then
        log('click premium tab')
        click_and_wait_color(1140, 277, 560895)
        click_while_color(1114, 468, 4187738)
    end

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
    if (kfindcolor(1648, 763, 4962287) == 1) then
        left(1648, 763)
    end
end

function Alliance:checkTech()
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

function Alliance:openSeason2buildings()
    if (kfindcolor(1165, 890, 3741951) == 1) then
        left(1111, 928)
        click_and_wait_not_color(892, 1031, 16765462)
        close_gift_modal()
        self:clickBack()
    end
end

-- lua Map.lua
Map = {}

function Map:isBase()
    return kfindcolor(42, 317, 16766290)
end

function Map:isWorld()
    return kfindcolor(1724, 1033, 14052657) or Map:isScrollOut()
end

function Map:mapState()
    if (Map:isBase() == 1) then
        return 1
    end
    if (Map:isWorld() == 1) then
        return 2
    end
    return 0
end

function Map:isHideInterface()
    if (kfindcolor(14, 99, 50431)) then
        return 0
    end
    return 1
end

function Map:isScrollOut()
    if (Map:isHideInterface() == 1 and kfindcolor(1767, 1036, 14069289) == 1) then
        return 1
    end
    return 0
end

function Map:resetScrollOut()
    if (self:isScrollOut() == 1) then
        return Map:clickBaseButton()
    end
    return 0
end

function Map:clickBaseButton()
    log('state', Map:mapState())
    if (Map:mapState() ~= 0) then
        left(1723, 1044, 500)
        return 1
    end
    return 0
end

function Map:showInterface()
    if (Map:isHideInterface()) then
        send('Escape')
    end
end

-- lua Profile.lua
Profile = {}

function Profile:open()
    left(47, 44, 500)
    self:closeLike()
    wait_color(976, 109, 11896387)
end

function Profile:closeLike()
    if (kfindcolor(947, 832, 16765462) == 1) then
        escape()
        return 1
    end
    return 0
end

function Profile:openMinistry()
    if (self:isOpen() ~= 1) then
        self:open()
    end
    click_and_wait_color(945, 372, 7225143, 881, 34)
end

function Profile:isOpen()
    self:closeLike()
    return kfindcolor(1173, 125, 16765462)
end

function Profile:close()
    if (self:isOpen() == 1) then
        escape()
        return 1
    end
    return 0
end

-- lua Rally.lua
Rally = {}

function Rally:joinIfExist()
    Rally:openList()
    if (Rally:join()) then
        log('Start join rally')
        Rally:applyJoin()
    else
        if (Rally:listIsOpen()) then
            log('Out rally list')
            Alliance:clickBack()
        end
    end
end

function Rally:listIsOpen()
    return kfindcolor(606, 118, 560895)
end

function Rally:join()
    if (kfindcolor(897, 311, 5438667)) then
        return click_and_wait_color(898, 322, 16777215, 725, 857)
    end
end

function Rally:openList()
    if (kfindcolor(1696, 783, 12688166) and kfindcolor(1751, 672, 3741951, 3)) then
        return click_and_wait_color(1721, 701, 16765462, 648, 1033)
    end
end

function Rally:applyJoin()
    if (kfindcolor(954, 850, 16756752)) then
        return click_and_wait_not_color(954, 850, 16756752)
    end
end


--

--
--if 660, 1070 50431
--kleft 1341, 154
--end_if
--
--if 1636, 786 13562365
--kleft 1636, 786
--end_if

-- lua Window.lua
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
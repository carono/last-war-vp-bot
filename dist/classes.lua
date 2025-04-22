-- lua Alliance.lua
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
    if (kfindcolor(1646, 791, 3103061) == 1) then
        log('Apply alliance help request')
        click(1648, 763, 300)
        return 1
    end
    if (kfindcolor(120, 872, 13038591) == 1) then
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
    --local x, y = find_red_mark(612, 212, 1161, 757)
    local x, y = find_colors(612, 212, 1161, 757, { { 802, 582, red_color }, { 816, 591, 16777215 } })
    if (x > 0) then
        log('Successful find recommended tech')
        wait(1000)
        click_and_wait_not_color(x + 50, y + 50, 3940594)
        wait(1000)
        log('Clicking tech')

        click_while_not_color(1078, 855, 11447982, 954, 856, 400)
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

-- lua Base.lua
--lua
Base = {}

function Base:openBase()
    Map:openBase()
end

function Base:clickHireSurvival()
    if (kfindcolor(843, 801, 16765462) == 1) then
        log('Hire new survival')
        click(843, 801, 1500)
        return self:clickHireSurvival()
    end
    return 0
end

function Base:getSurvival()
    return find_color(867, 471, 955, 566, 2039583)
end

function Base:clickSurvival()
    local x, y = Base:getSurvival()
    if (x > 0) then
        log('Find survival with gift or new, clicking')
        click(x, y, 500)
        click(x, y, 500)
        Base:clickHireSurvival()
        return Base:clickSurvival()
    end
    return 0
end

function Base:clickSurvivalButton()
    if (Map:isBase() == 1) then
        local x, y = find_colors(11, 506, 83, 913, { { 22, 553, 16777207 }, { 59, 549, 16777208 }, { 32, 537, 16776699 } })
        if (x > 0) then
            click(x, y, 200)
            wait(200)
        end
    end
end

function Base:greetingSurvivals()
    Base:clickSurvivalButton()
    Base:clickSurvival()
end

function Base:getVipPresents()
    if (Map:isBase() == 1) then
        if click_if_red(42, 158, 64, 130) == 1 then
            wait_color(885, 34, modal_header_color)
            if (click_if_red(1127, 207, 1152, 183) == 1) then
                log('Get vip points')
                wait(2000)
                escape(2000)
            end
            if (click_green_button(1143, 710) == 1) then
                log('Get vip gifts')
                close_gift_modal()
            end
            escape(2000)
        end
    end
end

function Base:isShopModal()
    if kfindcolor(802, 43, 5018864) == 1 and kfindcolor(895, 32, 12048886) == 1 then
        return 1
    end
    return 0
end

function Base:openShop()
    log('Opening shop')
    click(1722, 31, 1000)
    return 1
end

function Base:getShopGifts(force)
    force = force or 0
    log(force)
    log(Base:isShopModal())
    if (force == 1 and Base:isShopModal() == 0) then
        Base:openShop()
    end
    if (Base:isShopModal() == 0) then
        log('Shop modal is not opening,')
    end
    local x, y = find_red_mark(701, 48, 1184, 61)
    if (x > 0) then
        log('Has new shop gifts, try collect')
        click(x - 50, y + 50, 1000)
        if (click_red_mark(689, 388) == 1) then
            log('Get daily promo diamonds')
            close_gift_modal()
        end
        if (click_green_button(873, 1035) == 1) then
            log('Get super monthly card gift')
            close_gift_modal()
        end
        if (click_red_mark(684, 315) == 1) then
            log('Get daily card diamonds')
            close_gift_modal()
        end
        return 1
    else
        log('No shop gifts')
    end
    if (is_red(1181, 83) == 1) then
        log('Pull tabs')
        drag_tabs()
        return Base:getShopGifts(force)
    end
    if (Base:isShopModal() == 1) then
        escape(1000, 'Close shop modal')
    end
    return 0
end

-- lua Game.lua
Game = {}

function Game:checkMinistryRequests()
    Ministry:openMinistryIfRequest()
    Ministry:checkAndApproveMinisterRequest('mil_commander')
    Ministry:checkAndApproveMinisterRequest('adm_commander')
    Ministry:checkAndApproveMinisterRequest('strategy')
    Ministry:checkAndApproveMinisterRequest('security')
    Ministry:checkAndApproveMinisterRequest('development')
    Ministry:checkAndApproveMinisterRequest('science')
    Ministry:checkAndApproveMinisterRequest('interior')
    Map:normalize()
end

function Game:checkAlliance()
    Alliance:applyHelp()

    if (Rally:hasActiveRallies() == 0 and Alliance:isMarked() == 1 and Alliance:open() == 1) then
        wait(500)
        Alliance:checkTech()
        Alliance:getPresent()
        Alliance:clickBack()
    end
end

function Game:start()
    log('Try launch the game: ' .. config.game_path)
    exec(config.game_path)
    wait(30000)
    Window:repos()
end

function Game:isLogout()
    return kfindcolor(893, 638, 4143607)
end

function Game:hasUpdateFinishedModal()
    if (kfindcolor(884, 597, 16765462) == 1 and kfindcolor(48, 302, 16777215) == 1) then
        return 1
    end
    return 0
end

function Game:clickLogout()
    wait(1000)
    left(893, 638, 1000)
    Window:detach();
    wait(1000)
    exec("taskkill /f /im lastwar.exe")
    wait(config.logout_timeout)
end

function Game:resetUserActivity()
    local x, y = mouse_pos()
    Storage:set('lastMousePosX', x)
    Storage:set('lastMousePosY', y)
end

function Game:waitIfUserIsActive()
    local x, y = mouse_pos()
    local oldX = Storage:get('lastMousePosX')
    local oldY = Storage:get('lastMousePosY')
    if (oldY ~= y or oldX ~= x) then
        Storage:set('lastMousePosX', x)
        Storage:set('lastMousePosY', y)
        local timeout = 30000
        log('Waiting ' .. (timeout / 1000) .. 's, while user working')
        wait(30000)
        return Game:waitIfUserIsActive()
    end
    return 0
end

function Game:getRallyPresents()
    if kfindcolor(256, 211, 3741951) == 1 then
        click_and_wait_color(256, 211, 16765462, 934, 821)
        click(934, 821, 500)
        log('Get rally presents')
        return 1
    end
    return 0
end

function Game:readAllMail()
    if (is_red(1760, 855) == 1) then
        log('Have email, read it')
        click_and_wait_color(1731, 874, 6179651, 1040, 35)
        repeat
            local x, y = find_red_mark(1148, 98, 1190, 917)
            if (x ~= 0) then
                click_and_wait_color(x, y, 16765462, 1075, 1031)
                click(1075, 1031, 800)
                close_gift_modal()
                wait(3000)
                escape(500)
            end
        until x == 0
        Map:normalize()
    end
end

function Game:collectDailyPresents()
    if (is_red(61, 924) == 1) then
        click_and_wait_color(36, 961, 6179651, 863, 30)
        if (kfindcolor(1087, 433, 4187738) == 1) then
            click(1087, 433, 500)
        end
        click(743, 252, 1000)
        escape(500)

        click(847, 257, 1000)
        escape(500)

        click(948, 254, 1000)
        escape(500)

        click(1044, 255, 1000)
        escape(500)

        click(1145, 253, 1000)
        Map:normalize()
        return 1
    end
    return 0
end

function Game:openCard()
    click(740, 884, 3000)
    click(905, 470, 3000)
    click(905, 470, 3000)
    escape(2000)
end

-- development in process
function Game:checkFreeTavernHero()
    Map:normalize()
    click_and_wait_color(84, 1055, 16765462, 897, 995);
    click_and_wait_color(897, 995, 4187738, 820, 840);
    wait(200)
    if (kfindcolor(738, 885, 6344247) == 1) then
        log('Open hero')
        msg(1)
        --Game:openCard()
    end
    click(1057, 1016, 200)
    if (kfindcolor(731, 886, 5233404) == 1) then
        log('Open survival')
        msg(2)
        --Game:openCard()
    end
end

function Game:searchResourceButtonAndClick()
    local x, y = find_color(1060, 510, 1095, 622, 16765462)
    if (x > 0) then
        click(x, y, 1500)
    end
end

function Game:collectSimpleResources()
    log('Collect food')
    click_and_wait_color(117, 21, 10257016, 1049, 174)
    Game:searchResourceButtonAndClick()
    escape(1500)

    log('Collect steel')
    click_and_wait_color(247, 27, 10257016, 1049, 174)
    Game:searchResourceButtonAndClick()
    escape(1500)

    log('Collect gold')
    click_and_wait_color(376, 23, 10257016, 1049, 174)
    Game:searchResourceButtonAndClick()
    escape(1500)
end

-- lua Hero.lua
Hero = {}

function Hero:clickAttack()
    if (kfindcolor(757, 574, 4354047) == 1) then
        click_and_wait_color(757, 574, 16756752, 958, 856, 1)
        return
    end
end

function Hero:openAttackMenu()
    if (not Hero:attackMenuIsOpen() and kfindcolor(786, 600, 4354047) == 1) then
        click_and_wait_color(786, 600, 16756752, 958, 856, 1)
        log('Open attack menu')
        return
    end
    require("lib/color")
    local path = [["img/attack_button.bmp"]]

    local x, y = Window:modifyCord(716, 620)
    local x2, y2 = Window:modifyCord(1093, 856)
    local attackButton = findimage(x, y, x2, y2, { path }, 2, 80, 1, 10)
    log("Attack button img", attackButton)
    if (attackButton) then
        click_and_wait_color(attackButton[1][1], attackButton[1][2], 16756752, 958, 856, 1)
    end
end

function Hero:attackMenuIsOpen()
    return kfindcolor(958, 856, 16756752) == 1
end

function Hero:select()
    if (Hero:attackMenuIsOpen() and kfindcolor(748, 977, 6552575) ~= 1) then
        log('Select hero')
        click_and_wait_color(748, 977, 6552575, nil, nil, 1)
    end
end

function Hero:clickAttack()
    click(955, 826)
    log('Click attack')
end

function Hero:attackIfCan()
    if (Hero:attackMenuIsOpen()) then
        log('Menu is opened, try attack...')
        if (kfindcolor(650, 974, 16579836, 1) == 1 and kfindcolor(659, 982, 15592425) == 1) then
            --Hero already attacking
            log('In process..')
        end
        if (kfindcolor(658, 983, 14069823) == 1) then
            --Hero is sleep
            Hero:clickAttack()
        end
        if (kfindcolor(658, 973, 5197303, 11) == 1 and kfindcolor(650, 977, 16579836, 1) == 1) then
            --Hero returning
            Hero:clickAttack()
        end
        if (kfindcolor(658, 983, 14069823) == 1) then
            --Hero harvesting
            Hero:clickAttack()
        end
        if (kfindcolor(649, 977, 6475577) == 1) then
            --Hero on tile
            Hero:clickAttack()
        end
    end
end

-- lua Map.lua
Map = {}

function Map:isBase()
    --science button is exists
    return kfindcolor(45, 313, 16756763)
end

function Map:isWorld()
    return kfindcolor(1724, 1033, 14052657) or Map:isScrollOut()
end

function Map:state()
    if (Map:isBase() == 1) then
        return 1
    end
    if (Map:isWorld() == 1) then
        return 2
    end
    return 0
end

function Map:isHideInterface()
    if (kfindcolor(14, 99, 50431) == 1) then
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
    if (Map:state() ~= 0) then
        click(1723, 1044, 500)
        return 1
    end
    return 0
end

function Map:showInterface()
    if (Map:isHideInterface()) then
        send('Escape')
    end
end

function Map:openBase()
    Map:normalize()
    if (Map:state() == 2) then
        self:clickBaseButton()
        wait(10000)
    end
end

function Map:isCrossServer()
    if (kfindcolor(407, 133, 13016716) == 1) then
        return 1
    end
    return 0
end

function Map:normalize()
    if (Window:getGameHandle() == 0) then
        return -1
    end
    if (Game:isLogout() == 1) then
        return -2
    end
    if (Game:hasUpdateFinishedModal() == 1) then
        return -3
    end
    if (Map:isCrossServer() == 1) then
        click(416, 137, 5000)
    end
    if (self:state() == 0 and Map:isHideInterface() == 1) then
        log('Try normalize map, send escape button')
        escape(500)
        return self:normalize()
    end

    return 1
end

-- lua Ministry.lua
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

function Ministry:openMinistryIfRequest()
    if (Ministry:hasRequest() == 1) then
        Profile:open()
        Profile:closeLike()
        Profile:clickMinistry()
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

-- lua Profile.lua
Profile = {}

function Profile:open()
    click(47, 44, 500)
    self:closeLike()
    if (kfindcolor(1096, 313, 11897418) == 1) then
        wait_color(1093, 308, 11897160)
    else
        wait_color(976, 109, 11896387)
    end
end

function Profile:closeLike()
    if (kfindcolor(947, 832, 16765462) == 1) then
        escape()
        return 1
    end
    return 0
end

function Profile:clickMinistry()
    if (self:isOpen() ~= 1) then
        self:open()
    end
    if (kfindcolor(1096, 313, 11897418) == 1) then
        return click_and_wait_color(903, 550, 7225143, 881, 34)
    end
    return click_and_wait_color(945, 372, 7225143, 881, 34)
end

function Profile:isOpen()
    self:closeLike()
    if (kfindcolor(1173, 125, 16765462) == 1 or kfindcolor(1096, 313, 11897418)) then
        return 1
    end
    return 0
end

function Profile:close()
    if (self:isOpen() == 1) then
        escape()
        return 1
    end
    return 0
end

-- lua Promo.lua
--lua

Promo = {
    cords = { 1754, 97 }
}

function Promo:isMarked()
    return is_red(Promo.cords[1], Promo.cords[2])
end

function Promo:isOpen()
    kfindcolor(926, 31, 6114370)
end

function Promo:open()
    log('Try promo modal opening')
    click_and_wait_color(Promo.cords[1], Promo.cords[2], 6114370, 926, 31)
    return self:isOpen()
end

function Promo:getMark()
    return find_red_mark(587, 63, 1199, 93)
end

function Promo:clickMarkedTab()
    local x, y = self:getMark()
    if (x > 0) then
        click(x - 50, y + 50, 1000)
        return 1
    end
    return 0
end

function Promo:isArsenalBattle()
    if kfindcolor(945, 287, 13522176) == 1 and kfindcolor(1042, 240, 3112601) then
        return 1
    end
    return 0
end

function Promo:clickGetButtonInArsenalBattle()
    local x, y = find_color(1145, 438, 1176, 979, 4187738)
    if (x > 0) then
        log('Click get-all button in arsenal battle')
        click(x, y, 500)
        close_gift_modal()
        return self:clickGetButtonInArsenalBattle()
    end
    return 0
end

function Promo:clickGetAllButton()
    if (kfindcolor(889, 1037, 4187738) == 1) then
        log('Click get-all button in promo')
        click(889, 1037, 1000)
        close_gift_modal()
        return 1
    end
    return 0
end

function Promo:collectGifts(force)
    force = force or 0
    if (self:isMarked() == 1 or force == 1) then
        self:open();
        if (Promo:clickMarkedTab() == 1) then
            Promo:clickGetAllButton()
            Promo:clickGetButtonInArsenalBattle()
            Map:normalize()
        end
        return 1
    end
    return 0
end

-- lua Radar.lua
--lua
Radar = {}

function Radar:hasTreasureExcavatorNotification()
    if (kfindcolor(1047, 965, 686838) == 1 or kfindcolor(1055, 975, 2964595) == 1) then
        return 1
    end
    return 0
end

function Radar:hasEasterEggNotification()
    if (kfindcolor(1045, 970, 52223) == 1 or kfindcolor(1014, 970, 5425394) == 1) then
        return 1
    end
    return 0
end

function Radar:searchEasterEggInChat()
    return find_color(694, 214, 792, 968, 4177663)
end

function Radar:clickEasterEggModal()
    click(935, 706, 100)
    click(935, 706, 100)
    click(935, 706, 100)
end

-- lua Rally.lua
Rally = {}

function Rally:joinIfExist(to_last_place)
    to_last_place = to_last_place or 0
    if (Rally:openList() == 1) then
        if (to_last_place == 1) then
            log('wait last place')
            wait_not_color(819, 318, 5438656, 30000)
        end
        if (Rally:join()) then
            log('Start join rally')
            Rally:applyJoin()
        else
            if (Rally:listIsOpen() == 1) then
                log('Out rally list')
                Alliance:clickBack()
            end
        end
    end
end

function Rally:listIsOpen()
    local back_button = kfindcolor(606, 118, 560895)
    local big_blue_button = kfindcolor(865, 1017, 16765462)
    local daily_yellow_line = kfindcolor(616, 172, 6535924)
    local store = kfindcolor(792, 1055, 5625855)
    local first_place_rating = kfindcolor(633, 226, 4146908)
    if back_button == 1 and big_blue_button ~= 1 and daily_yellow_line ~= 1 and store ~= 1 and first_place_rating ~= 1 then
        return 1
    end
    return 0
end

function Rally:join()
    if (kfindcolor(897, 311, 5438667) == 1) then
        if click_and_wait_color(898, 322, 16777215, 725, 857, 2000) == 0 then
            escape(800)
            return 0
        end
        return 1
    end
end

function Rally:hasActiveRallies()
    return is_red(1695, 700)
end

function Rally:hasAvailableRally()
    return kfindcolor(1751, 672, 3741951, 3)
end

function Rally:openList()
    if (Rally:hasActiveRallies() == 1 and Rally:hasAvailableRally() == 1) then
        log('open rally list')
        return click_and_wait_color(1721, 701, 16765462, 648, 1033)
    end
end

function Rally:applyJoin()
    if (kfindcolor(955, 835, 16765462) == 1) then
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
    local width, height = self:getCanonicalSize()
    local x, y = windowpos(handle)
    windowpos(x, y, width, height, handle)
end

function Window:getCanonicalSize()
    return 1796, 1154
end

function Window:repos()
    local handle = self:attachHandle()
    if (handle ~= 0) then
        local x, y, width, height = windowpos(handle)
        x = config.win_pos_x
        y = config.win_pos_y
        windowpos(x, y, width, height, handle)
    end
end

function Window:detach()
    workwindow(nil)
    wait(1000)
end

function Window:attachHandle()
    local handle = self:getGameHandle()
    if (handle ~= 0) then
        workwindow(handle)
        showwindow(handle, "TOP")
    end
    return handle
end

function Window:getGameHandle()
    local handle = findwindow("Last War-Survival Game")
    if (handle == nil) then
        return 0
    end
    return handle[1][1]
end

function Window:modifyCord (xReference, yReference)
    local handle = self:getGameHandle()
    local WidthCurrent, HeightCurrent = self:getCanonicalSize()
    local x, y, WidthReference, HeightReference = windowpos(handle)
    local xCurrent = (xReference * WidthReference) / WidthCurrent
    local yCurrent = (yReference * HeightReference) / HeightCurrent
    return math.ceil(xCurrent), math.ceil(yCurrent)
end

function Window:canonizeCord (xReference, yReference)
    local handle = self:getGameHandle()
    local WidthReference, HeightReference = self:getCanonicalSize()
    local x, y, WidthCurrent, HeightCurrent = windowpos(handle)
    local xCurrent = (xReference * WidthReference) / WidthCurrent
    local yCurrent = (yReference * HeightReference) / HeightCurrent
    return math.ceil(xCurrent), math.ceil(yCurrent)
end
Ministry = {}
MinistryPos = { vp = { 638, 440 }, strategy = { 825, 440 }, security = { 1011, 440 }, development = { 638, 680 }, science = { 825, 680 }, interior = { 1011, 680 } }

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


--[[
proc check_overtime #x #y
  set linedelay 0

    call check_captured_capitol
    if $check_captured_capitol = 1
      call pull_captured_ministry
      set #y #y + 88
    end_if

    set #x1 #x + 25
    set #y1 #y + 170
    set #x2 #x + 130
    set #y2 #y + 195
    set $response FindImage (#x1, #y1 #x2, #y2 (img\time.bmp) %ResultArray 2 90 1 80

    set #a findcolor (#x1, #y1 #x2, #y2 16777215 %ResultArray 2 1 3)

    if $response > 0 or #a = 0
      set $result 0
    else
      set $result 1
    end_if
    set linedelay 100
end_proc
]]--


Rally = {}

function Rally:joinIfExist()
    Rally:openList()
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
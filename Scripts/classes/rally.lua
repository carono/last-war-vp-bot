Rally = {}

function Rally:joinIfExist()
    Rally:openList()
    if (Rally:join()) then
        log('Start join rally')
        Rally:applyJoin()
    else
        if (Rally:listIsOpen()) then
            log('Out rally list')
            AllianceButton:clickBack()
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
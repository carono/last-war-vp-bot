Profile = {}

function Profile:open()
    left(47, 44, 500)
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
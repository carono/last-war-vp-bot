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

function Profile:clickMinistry()
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
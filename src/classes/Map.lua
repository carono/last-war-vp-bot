Map = {}

function Map:isBase()
    return kfindcolor(42, 317, 16766290)
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

function Map:openBase()
    Map:normalize()
    if (Map:state() == 2) then
        self:clickBaseButton()
    end
end

function Map:normalize()
    if (self:state() == 0 and Map:isHideInterface() == 1) then
        escape(500)
        log('Normalize map')
        return self:normalize()
    end

    return 1
end
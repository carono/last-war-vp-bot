Map = {}
local mapNormalizeCount = 0;

function Map:isBase()
    return kfindcolor(45, 313, '(16760361-16755736)')
end

function Map:isWorld()
    if (kfindcolor(1724, 1033, 14052657) == 1) then
        return 1
    end
    return 0
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
        log('Waiting opening base at 5s')
        self:clickBaseButton()
        wait(5000)
        return 1
    end
    return 0
end

function Map:openMap()
    Map:normalize()
    if (Map:state() == 1) then
        self:clickBaseButton()
        log('Waiting opening map at 5s')
        wait(5000)
        return 1
    end
    return Map:isWorld()
end

function Map:isCrossServer()
    if (kfindcolor(407, 133, 13016716) == 1) then
        return 1
    end
    return 0
end

function Map:normalize()
    if (mapNormalizeCount > 10) then
        Game:restart(30, 'Fail normalize map')
    end
    if (Window:getGameHandle() == 0) then
        mapNormalizeCount = 0
        return -1
    end
    if (Game:isLogout() == 1) then
        mapNormalizeCount = 0
        return -2
    end
    if (Game:hasUpdateFinishedModal() == 1) then
        mapNormalizeCount = 0
        return -3
    end
    if (Map:isCrossServer() == 1) then
        click(416, 137, 5000)
    end
    if (self:state() == 0 and Map:isHideInterface() == 1) then
        escape(1000, 'Try normalize map')
        mapNormalizeCount = mapNormalizeCount + 1
        return self:normalize()
    end
    mapNormalizeCount = 0
    wait(1000)
    return 1
end
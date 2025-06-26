Finish = {}

function Finish:store1()
    Hud:clickButton('store')
    if kfindcolor(635, 391, 10260895) == 1 then
        Storage:setDay('store1', 1)
    end
end

function Finish:allianceSecretMissions()
    if Hud:clickButton('missions') == 1 and is_red(1171, 411) == 0 then
        log('Daily alliance secret missions is finished')
        return Storage:setDay('allianceSecretMissions', 1)
    end
    return Storage:setDay('allianceSecretMissions', 0)
end
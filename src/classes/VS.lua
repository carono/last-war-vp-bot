--lua
VS = {}

function VS:isRadarDay()
    local currentDay = Server:getDay(1)
    if (currentDay == 'Monday' or currentDay == 'Wednesday' or currentDay == 'Friday' or currentDay == 'Saturday') then
        return 1
    end
    return 0
end
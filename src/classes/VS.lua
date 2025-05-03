--lua
VS = {}

function VS:isRadarDay()
    local currentDay = os.date("*t").wday
    if (currentDay == 2 or currentDay == 4 or currentDay == 6 or currentDay == 7) then
        return 1
    end
    return 0
end
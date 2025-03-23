-- lua daily.lua
function service_alliance()
    if (Alliance:open()) then
        Alliance:applyHelp()
        Alliance:checkTech()
        Alliance:getPresent()
        Alliance:openSeason2buildings()

        Alliance:clickBack()
    end
end
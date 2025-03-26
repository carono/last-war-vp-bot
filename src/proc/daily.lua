function service_alliance()
    Alliance:applyHelp()
    if (Alliance:isMarked() and Alliance:open()) then
        Alliance:applyHelp()
        Alliance:checkTech()
        Alliance:getPresent()
        Alliance:openSeason2buildings()

        Alliance:clickBack()
    end
end
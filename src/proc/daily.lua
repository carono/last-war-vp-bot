function service_alliance()
    Alliance:applyHelp()
    if (Alliance:isMarked() and Alliance:open()) then
        wait(500)
        Alliance:checkTech()
        Alliance:getPresent()
        Alliance:openSeason2buildings()

        Alliance:clickBack()
    end
end
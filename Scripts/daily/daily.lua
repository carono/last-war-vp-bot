function service_alliance()
    if (AllianceButton:open()) then
        AllianceButton:applyHelp()
        AllianceButton:checkTech()
        AllianceButton:getPresent()
        AllianceButton:openSeason2buildings()

        AllianceButton:clickBack()
    end
end
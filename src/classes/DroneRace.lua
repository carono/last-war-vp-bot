--lua
DroneRace = {}

function DroneRace:getStamina()
    Map:normalize()
    if (click_if_red(82, 94) == 1) then
        wait(2000)
        if (click_green_button(1090, 319) == 1) then
            Map:normalize()
        end
    end
end

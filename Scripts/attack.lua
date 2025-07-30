--lua
require("dist/init")
require("dist/init-develop")
Window:attachHandle()

:: start ::
local squad = 1

function move_hero(x, y)
    if (x > 0) then
        click(x, y)
        Hero:waitHeroSelectingMenu()
        Hero:select(squad)
        local hero_status = Hero:getHeroStatusInSelectMenu(squad)
        if (hero_status == 'attacking') then
            return nil
        end
        Hero:march()
        wait(1000)
    end
end

move_hero(Hero:getTaleMenuButton())
move_hero(Hero:getAttackMenuButton())

local hero_status = Hero:getHeroStatusInSelectMenu(squad)
if (hero_status ~= 'attacking') and (hero_status ~= nil) then
    Hero:select(squad)
    Hero:march()
    wait(1000)
end

goto start
--stop_script()
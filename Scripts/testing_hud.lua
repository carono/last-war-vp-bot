--lua

require("dist/init-develop")

:: start ::

Map:normalize()
for obj, count in pairs(Hud.wait_colors) do
    if (obj == 'rally_present') then
        goto continue
    end
    if Hud:clickButton(obj) == 0 then
        msg(obj .. ' not found')
        stop_script()
    end
    Map:normalize();
    :: continue ::
end

stop_script()
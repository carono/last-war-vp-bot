--lua
require("dist/init")
require("dist/init-develop")
Window:attachHandle()

::start::

Hero:openAttackMenu()
Hero:select()
Hero:attackIfCan()

goto start
--stop_script()
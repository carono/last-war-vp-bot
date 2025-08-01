--lua

require('dist/init')

--------------------------------
-- GAME CONFIG
use_auto_rally = 1
open_drone_components = 1
default_farming_timeout = 600

-- SYSTEM CONFIG
debug = 0
logout_timeout = 15
preventive_restart_hour = 8
--------------------------------

reset_cooldown()
cooldown('restart', preventive_restart_hour * 60 * 60)
wait(10000)
Game:resetUserActivity()

farming()
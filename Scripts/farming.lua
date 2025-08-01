--lua

require('dist/init')

reset_cooldown()
cooldown('restart', preventive_restart)
wait(10000)
Game:resetUserActivity()

-- GAME CONFIG
use_auto_rally = 1
open_drone_components = 1

-- SYSTEM CONFIG
debug = 0
logout_timeout = 15
preventive_restart = 8 * 60 * 60

farming()
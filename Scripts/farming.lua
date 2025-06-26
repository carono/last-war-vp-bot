--lua
debug = 0
require('dist/init')
preventive_restart = 8 * 60 * 60

reset_cooldown()
cooldown('restart', preventive_restart)
wait(10000)
Game:resetUserActivity()

use_auto_rally = 1
debug = 1

farming()
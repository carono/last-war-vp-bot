--lua
debug = 0
require('dist/init')

reset_cooldown()
cooldown('restart', 60 * 60)
wait(10000)
Game:resetUserActivity()

use_auto_rally = 0


farming()
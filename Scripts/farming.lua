--lua

require('dist/init')
debug = 0

reset_cooldown()
Map:normalize()
wait(10000)
Game:resetUserActivity()

:: start ::
log('clear')

check_handle()
check_logout()

normalize_map()
notify_treasure()
check_secret_missions()
check_events()
military_race()
check_base()

check_alliance()
check_radar()

collect_promo_gifts()
auto_rally()
read_mail()

check_connection()

Alliance:applyHelp()
Alliance:clickHealTroops()
Game:getRallyPresents()
Game:collectDailyPresents()
Game:waitIfUserIsActive()

wait(1000)
farming_timeout()

goto start
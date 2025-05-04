--lua

require('dist/init')

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
auto_rally()
check_base()
check_alliance()
check_secret_missions()
collect_promo_gifts()
check_events()
read_mail()
check_radar()
check_connection()

Alliance:applyHelp()
Alliance:clickHealTroops()
Game:getRallyPresents()
Game:collectDailyPresents()
Game:waitIfUserIsActive()

wait(1000)
farming_timeout()

goto start
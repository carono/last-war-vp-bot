--lua

require('dist/init')

reset_cooldown()
Map:normalize()
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

Alliance:applyHelp()
Alliance:clickHealTroops()
Game:getRallyPresents()
Game:collectDailyPresents()

close_connection_error()
Game:waitIfUserIsActive()

farming_timeout()

goto start
--lua
debug = 0
require('dist/init')

:: init ::

reset_cooldown()
cooldown('restart', 60 * 60)

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
vs()
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

if (cooldown('restart', 60 * 60) == 1) then
    Game:restart(60)
    goto init
end

wait(1000)
farming_timeout()

goto start
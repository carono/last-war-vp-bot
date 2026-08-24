# Rotate the trade station's trucks up to the wanted rarity, then send out what the day allows.
# ru: Ротация грузовиков торговой станции до нужного качества и отправка по дневной норме.
#
# THE TRADE STATION, not the base. Three trucks in the game are called the same word and
# only this one spends anything: `collect_truck_resources.md` empties the accumulator
# parked on the base, the checklist's `trucks_ready` counts supply trucks that have
# ARRIVED, and this one is the fleet a commander dispatches to another server, other
# players rob on the way, and the initiator empties on arrival.
#
# THE ABILITY IS THE GAME'S OWN «Супер режим» WINDOW. `UILWTruckSuperDeparture` holds
# both halves — a Refresh tab that lifts several trucks' rarity in one send, and a
# Departure tab that sends several trucks with their escorts in one more. Pressing its
# button rather than building `train.batch.change` / `train.batch.send` by hand is the
# same decision the secret tasks made about theirs, and for the same two reasons: the
# client decides which purse a rotation comes out of, and the window arrives with an
# escorting squad already against every truck. Both of those are exactly what a
# hand-written frame would have to guess at, and the player pays for the guess.
#
# WHAT «UP TO THE WANTED RARITY» MEANS. A truck's `quality` runs 1..5, where 5 is UR, and
# above it sits the Reindeer Sleigh Ride — `quality` 10 with `isSpecialURQuality` beside
# it, its own tech, and worth more than a UR. So `target` is that number: 10 asks for the
# sleigh and 5 for a plain UR. An account without the sleigh tech cannot be asked for one,
# so the run quietly aims at UR instead and says so.
#
# THE PRICE WAS MEASURED, ONE TRUCK AT A TIME, and it is flat: three Trade Contracts to
# bring ANY truck to UR — a level-1 truck and a level-4 truck cost the same — and six to
# bring it to the sleigh. None of that is written down anywhere here: the selection is
# made, the window's own `CalcRefreshTruckCost` is asked, and the number it answers is
# what the gate is judged on. A price copied into a recipe is a price that was true once.
#
# AND IT DOES NOT HAGGLE. That is the operator's own instruction for this ability — «в
# супер режиме всегда обновляем до требуемого уровня НЕ ТОРГУЯСЬ» — so `diamond_cap`
# defaults to 0, which means no ceiling at all. The secret tasks' 1200 is a rule about a
# different screen and a different currency, and carrying it over here would be inventing
# a limit nobody asked for. The purse is still read again afterwards and the difference
# said out loud, because the game tops a short bag up with diamonds by itself and tells
# nobody (#1903).
#
# THE SELECTION IS BUILT, NEVER «SELECT ALL». The window's own select-all ticks every
# truck it MAY touch, and at the UR target that includes a truck which is already UR — a
# press would re-roll a win and charge for it. So only the trucks below the target are
# ticked, out of the ones the game says are selectable.
#
# AND THE DISPATCH IS CAPPED BY THE DAY, not by the fleet. Trucks standing at the station
# and dispatches still banked today are two different numbers; when the allowance is the
# smaller one the trucks are ranked by rarity and the best go first, because a sleigh held
# back for tomorrow is a sleigh the next rotation throws away.

# What the run is aiming for: 10 = the Reindeer Sleigh Ride, 5 = an ordinary UR. The
# sleigh is the default because it is worth more, and an account that has not unlocked it
# falls back to UR by itself.
ARGS target = 10

# Rotate at all before sending. 0 sends the fleet exactly as it stands — which is what a
# person who would rather spend their contracts elsewhere wants.
ARGS refresh = 1

# May diamonds top a short bag of contracts up? The game does it silently when the bag
# cannot cover the price; 0 keeps the whole run inside the contracts.
ARGS use_diamonds = 1

# The ceiling on that top-up, in diamonds. 0 = none, and none is the instruction for this
# ability (above). Anybody who wants one sets it here and the rotation stops at it.
ARGS diamond_cap = 0

# Send the trucks out afterwards. 0 rotates and leaves them standing.
ARGS dispatch = 1

# 1. Park the rule where the presses can read it — `TAP` takes no arguments — and stamp
#    the two purses everything below is measured against.
LUA pcall(function() local M=DataCenter.LWMyStationDataManager M.__lw_trk_target={target} M.__lw_trk_gold={use_diamonds} M.__lw_trk_budget={diamond_cap} end)
TAP arm_truck_station

# 2. Open the station and look at it once, so every question underneath is answered about
#    the same moment.
TAP open_truck_station
TAP scan_truck_station
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_lock) or 1) INTO locked
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_win) or 0) INTO window
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_sent) or 0) INTO sent
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_cap) or 0) INTO cap
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_ready) or 0) INTO ready
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_tick) or 0) INTO tickets
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_poor) or 0) INTO poor
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_good) or 0) INTO good
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_sleigh) or 0) INTO sleigh_open
LOG "trade station: {sent} of {cap} sent today, {ready} could go now, {poor} truck(s) below the target and {good} at it, {tickets} contract(s) in hand, sleigh tech={sleigh_open}"

# 3. A station the base has not unlocked yet answers zero to everything, exactly like an
#    idle one. Say which of the two it is and stop, rather than reporting a day's work
#    nobody could have done.
IF locked == 1
    LOG "the trade station is still locked on this account — nothing to send"
    TAP close_truck_station
    STOP "trade station locked"

# 4. …and the same for a window that did not come up: without it there is no fleet to
#    read, no price to ask and no button to press.
IF window == 0
    LOG "the super-mode window did not open — nothing can be read or pressed this run"
    TAP close_truck_station
    STOP "super mode window did not open"

# 5. The rotation. The selection is built first and the price read off the game, so the
#    decision below is made against a number nobody guessed.
IF refresh == 1
    IF poor > 0
        TAP select_truck_refresh
        READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_want) or 0) INTO want
        READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_cost) or -1) INTO cost
        READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_need) or 0) INTO gold_need
        READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_ok) or 0) INTO afford
        READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_aim) or 0) INTO aim
        IF afford == 1
            LOG "rotating {want} truck(s) to quality {aim}: {cost} contract(s), {gold_need} diamond(s) on top — taking it"
            TAP refresh_trucks
            TAP confirm_truck_rotation
            # …and then say what was REALLY taken. A press is not believed on its own
            # word: the game tops a short bag up with diamonds and reports it nowhere.
            READ_LUA (function() local M=DataCenter.LWMyStationDataManager local was=tonumber(M.__lw_trk_gold0) if was==nil then return 0 end local now=0 pcall(function() now=LuaEntry.Player.gold+0 end) local d=was-now if d<0 then d=0 end return d end)() INTO gold_spent
            LOG "the purse went down by {gold_spent} diamond(s)"
            TAP scan_truck_station
            READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_poor) or 0) INTO poor
            READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_good) or 0) INTO good
            LOG "after rotating: {good} truck(s) at the target, {poor} still below it"
        ELSE
            LOG "rotating {want} truck(s) would want {cost} contract(s) and {gold_need} diamond(s) on top — dearer than this run is allowed, left alone"
    ELSE
        LOG "no truck is below the target — nothing to rotate"

# 6. The dispatch. Capped by the day's own allowance, best trucks first.
IF dispatch == 1
    TAP select_truck_departure
    READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_picked) or 0) INTO picked
    READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_standing) or 0) INTO standing
    READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_left) or 0) INTO allowance
    IF picked > 0
        LOG "sending {picked} of the {standing} truck(s) standing — {allowance} dispatch(es) left today"
        TAP press_truck_departure
    ELSE
        LOG "nothing to send: {standing} truck(s) standing, {allowance} dispatch(es) left today"

# 7. One last look, so whoever pressed this — the window or the phone — is told the state
#    it LEFT rather than the one it started from.
TAP scan_truck_station
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_sent) or 0) INTO sent
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_cap) or 0) INTO cap
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_ready) or 0) INTO ready
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_tick) or 0) INTO tickets
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_good) or 0) INTO good
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_trk_poor) or 0) INTO poor
READ_LUA (function() local M=DataCenter.LWMyStationDataManager local was=tonumber(M.__lw_trk_tick0) if was==nil then return 0 end local now=tonumber(M.__lw_trk_tick) or was local d=was-now if d<0 then d=0 end return d end)() INTO contracts_spent
LOG "trade station: {sent}/{cap} sent, {ready} still able to go, {good} at the target, {poor} below it, {tickets} contract(s) left — this run spent {contracts_spent} contract(s)"

# 8. What could not go is not abandoned. A truck on the road comes home at a moment the
#    client knows to the millisecond, so THAT is when this errand is worth playing again —
#    plus a minute, so the arrival has really landed. Nothing out, or nothing left to
#    send: `0`, and the timer's own period stands (docs/dsl.md, `next_run_in`).
READ_LUA (function() local M=DataCenter.LWMyStationDataManager local sent=tonumber(M.__lw_trk_sent) or 0 local cap=tonumber(M.__lw_trk_cap) or 0 if sent>=cap then return 0 end local now=0 pcall(function() now=UITimeManager:GetInstance():GetServerSeconds()+0 end) if now<=0 then return 0 end local best=0 pcall(function() for _,t in pairs(M:GetMyTrainList() or {}) do local a=math.floor((t.arriveTs or 0)/1000) if a>now then local d=a-now if best==0 or d<best then best=d end end end end) if best<=0 then return 0 end return best+60 end)() INTO next_run_in
IF next_run_in > 0
    LOG "a truck is still on the road — coming back in {next_run_in} s, when the nearest one is home"

# 9. Leave the screen as it was found.
TAP close_truck_station

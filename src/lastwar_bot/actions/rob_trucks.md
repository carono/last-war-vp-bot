# Rob other players' trade trucks: the sleighs of grown players, and only the ones we beat.
# ru: Грабёж чужих торговых грузовиков: оленьи повозки взрослых игроков, и только те, кого точно бьём.
#
# THE OTHER TAB OF THE TRADE STATION. `send_trucks.md` is our own fleet — the rotation and
# the dispatch. This is the board of trucks OTHER players have on the road, and the press
# that robs one. Four a day, capped by the game itself (`MAX_DAILY_LOOT_COUNT`), counted
# by the game itself (`GetRobCount`), and nothing about that number is written down here.
#
# IT IS THE «БЫСТРЫЙ ГРАБЁЖ» AND THERE IS NO OTHER KIND FOR A BOT. No squad leaves the
# base, no march is drawn on the map and no window has to stay open: the robbery is one
# frame and the answer comes back in a second or two. What the game calls the slow way is
# a camera flight to the truck and a press on the panel that flies up beside it — the same
# frame, with an animation in front of it.
#
# WHAT «ОЛЕНЬИ ПОВОЗКИ» ARE. `quality` runs 1..5 for N..UR, and above UR sits the Reindeer
# Sleigh Ride at `quality` 10 with `isSpecialURQuality` beside it. `quality = 10` therefore
# asks for the sleighs and nothing else, `5` for UR and better, and `0` for any truck at
# all. It is the game's own number, so the setting travels as the thing it names.
#
# WHAT «СЛАБЕЕ НАС НА 5%» IS MEASURED AGAINST, and this is the one number the client will
# not give straight: it cannot price a squad of its own (`GetFormationPowerByUuid` answers
# 0 for every formation on the account, and there is no `*BattlePower` anywhere in
# `DataCenter`). Two readings exist and `lua_actions.truck_rob_scan` prefers them in this
# order — the server's own valuation of the escort, read off one of OUR trucks while it is
# on the road, which is the same number in the same units as the `power` the board prints
# against somebody else's truck; and, when no truck of ours is out, the heroes of the
# squad added up. The second reads LOWER than the first (39.8M against 60.1M for the same
# squad, measured live), so a rule judged on it comes out STRICTER than asked — which is
# the safe direction for a press that loses troops when the reading was optimistic. The
# run says which of the two it used.
#
# A DEFEAT IS NOT ARGUED WITH. The game answers a robbery by moving its own daily counter;
# a press that leaves it where it was did not rob anything, whatever the reason, and the
# owner of that truck goes on the blacklist and is not offered again. The list is this
# profile's own memory (`REMEMBER`), so it survives a restart, and only a person clears
# it — `python -m panel.forget truck_rob_blacklist` — because a bot that forgets who beat
# it walks into the same escort tomorrow.

# The level of the player whose truck is worth taking. Below it the load is small and the
# server is usually somebody's first week.
ARGS min_level = 31

# 10 = the Reindeer Sleigh Ride and nothing else, 5 = UR and better, 0 = any truck.
ARGS quality = 10

# How much weaker than us the escort has to be, in per cent.
ARGS margin = 5

# Which of our four squads goes. 1 is the first, which is the strongest one the person has
# arranged.
ARGS squad = 1

# 1. What we already know about who beats us, out of this profile's own memory and into
#    the game VM, where the presses below can read it. `PARK` rather than `{name}`: a
#    value a run has only just recalled cannot travel through a placeholder (docs/dsl.md).
RECALL truck_rob_blacklist INTO blacklist
LUA pcall(function() local M=DataCenter.LWMyStationDataManager M.__lw_rob_lvl={min_level} M.__lw_rob_q={quality} M.__lw_rob_margin={margin} M.__lw_rob_squad={squad} M.__lw_rob_seen=nil end)
PARK blacklist INTO DataCenter.LWMyStationDataManager.__lw_rob_black

# 2. Open the board and look at it once, so every branch below is about the same moment.
TAP open_truck_targets
TAP scan_truck_targets
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_rob_win) or 0) INTO window
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_rob_n) or 0) INTO board
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_rob_fit) or 0) INTO fit
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_rob_done) or 0) INTO done
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_rob_cap) or 0) INTO cap
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_rob_ours) or 0) INTO ours
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_rob_src) or -1) INTO source
READ_LUA (function() local M=DataCenter.LWMyStationDataManager M.__lw_rob_seen=tonumber(M.__lw_rob_done) or 0 return M.__lw_rob_seen end)() INTO seen
LOG "truck robbery: {done} of {cap} taken today, {board} truck(s) on the board, {fit} of them within the rule, our escort reads {ours} (source {source}: 1 = the server's own number, 0 = the heroes added up)"

# 3. A board that did not come up is not an empty board. Without it there is nothing to
#    read, nothing to choose and nothing to press.
IF window == 0
    LOG "the board of targets did not open — nothing can be read or robbed this run"
    TAP close_truck_targets
    STOP "the target board did not open"

# 4. Nothing to measure with is nothing to decide with. Rather than rob blind, say so.
IF ours == 0
    LOG "neither of our escort readings answered — nothing is robbed while «weaker than us» cannot be judged"
    TAP close_truck_targets
    STOP "our own strength is unreadable"

# 5. The day's own ceiling, kept by the game.
READ_LUA (function() local M=DataCenter.LWMyStationDataManager local d=tonumber(M.__lw_rob_done) or 0 local c=tonumber(M.__lw_rob_cap) or 0 local u=tonumber(M.__lw_rob_used) or 0 if u==1 then return 0 end local left=c-d if left<0 then left=0 end return left end)() INTO left
IF left == 0
    LOG "the day's {cap} robberies are spent"
    TAP close_truck_targets
    STOP "no robbery left today"

# 6. One at a time: rob, ask the game whether its counter moved, and let the answer decide
#    whether the owner is worth offering again. The loop ends by setting its own `left` to
#    0 rather than by `STOP`, so the closing lines and the `close` below always run — a
#    board left open is a window the person finds in their way.
WHILE left > 0 LIMIT 4
    READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_rob_fit) or 0) INTO fit
    IF fit == 0
        LOG "nothing left on the board passes the rule — {board} truck(s) were looked at"
        READ_LUA 0 INTO left
    IF fit > 0
        TAP rob_truck
        READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_rob_hit) or 0) INTO sent
        READ_LUA tostring(DataCenter.LWMyStationDataManager.__lw_rob_owner or '') INTO owner
        READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_rob_lv) or 0) INTO target_level
        READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_rob_pw) or 0) INTO target_power
        READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_rob_qual) or 0) INTO target_quality
        READ_LUA tostring(DataCenter.LWMyStationDataManager.__lw_rob_err or '') INTO refusal
        IF sent == 0
            LOG "nothing was sent: {refusal}"
            READ_LUA 0 INTO left
        IF sent == 1
            LOG "sent against a level {target_level} player: quality {target_quality}, escort {target_power}"
            # The server needs a moment to fight it and answer, and its own daily counter
            # is the answer — so the board is re-read AFTER the wait rather than before.
            WAIT 4
            TAP scan_truck_targets
            READ_LUA (function() local M=DataCenter.LWMyStationDataManager local was=tonumber(M.__lw_rob_seen) local now=tonumber(M.__lw_rob_done) or 0 M.__lw_rob_seen=now if was==nil then return 1 end if now>was then return 1 end return 0 end)() INTO moved
            READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_rob_done) or 0) INTO now_done
            READ_LUA (function() local M=DataCenter.LWMyStationDataManager local d=tonumber(M.__lw_rob_done) or 0 local c=tonumber(M.__lw_rob_cap) or 0 local u=tonumber(M.__lw_rob_used) or 0 if u==1 then return 0 end local n=c-d if n<0 then n=0 end return n end)() INTO left
            IF moved == 0
                # The game's own counter did not move, so nothing was robbed — the escort
                # held, or the truck was gone by the time the frame landed. Either way that
                # owner is not offered again until a person clears the list.
                READ_LUA (function() local M=DataCenter.LWMyStationDataManager local black=tostring(M.__lw_rob_black or '') local who=tostring(M.__lw_rob_owner or '') if who=='' then return black end if (','..black..','):find(','..who..',',1,true) then return black end if black=='' then black=who else black=black..','..who end M.__lw_rob_black=black return black end)() INTO blacklist
                REMEMBER truck_rob_blacklist FROM blacklist
                LOG "the day's count did not move — that escort held, and its owner is off the list from now on"
            IF moved == 1
                LOG "robbed — {now_done} of {cap} taken today"

# 7. Say what the run ends on, and leave the screen as it was found.
TAP scan_truck_targets
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_rob_done) or 0) INTO done
READ_LUA (tonumber(DataCenter.LWMyStationDataManager.__lw_rob_fit) or 0) INTO fit
LOG "truck robbery: {done} of {cap} taken today, {fit} truck(s) still within the rule on the board"
TAP close_truck_targets

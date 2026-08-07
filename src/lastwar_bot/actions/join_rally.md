# Join the alliance rallies that are out, one squad each.
# ru: Присоединиться к выставленным ралли альянса — по отряду на ралли.
#
# `squads` is which squad slots may be spent, in order — the 1/2/3/4 the player sees in
# the dispatch panel. Each squad goes to a DIFFERENT rally: `squads = [1]` joins only the
# first rally with squad 1, `squads = [2, 3]` joins two rallies, one with squad 2 and one
# with squad 3. With fewer rallies out than squads, the leftover squads stay home; with
# more rallies than squads, the run says so.
#
#   run join_rally                       -- every ticked squad, one rally each
#   run join_rally {"squads": [2, 3]}    -- only squads 2 and 3
#
# TWO CALLS FROM THE PUSH TO THE SEND, and that is the whole point of this recipe's
# shape. A rally lives tens of seconds during an event; a call into the game VM was
# measured at 0.14 s with the daemon free and 10–19 s under the panel's ordinary
# background load, with the client at 59 fps the whole time (#1281,
# `tools/dev/rally_latency.py`). The version this replaces took EIGHT readings before it
# sent anything — 5.5 s to the send with the daemon quiet, and 100 s twice over when it
# was not — so it arrived after the banner it was woken for. Everything those readings
# asked is now a local variable inside ONE chunk (`lua_actions.rally_join_all`): the
# rallies out, the squads at home, the pairing, the send. Measured back to back on the
# same client, same minute: **5.48 s → 0.19 s.**
#
# NO WINDOW IS OPENED ON THE PATH THAT CATCHES A BANNER. The join is one message — the
# same `SendCreateMarchMessage` the game's own squad screen ends at, aimed at the tile the
# joiners gather on rather than at the monster (#1237, #1238), with the march type as the
# SECOND argument (#1277). The one thing left off this path is the squad
# standing EMPTY: the client refuses a squad with no soldiers before a byte leaves. That
# is not the march, so it is not on the march's path — the fast send goes out first for
# every squad that has an army, and only a run that sent NOTHING because every candidate
# was empty pays for `fill_empty_squads`, one request that fetches the army the server had
# all along (#1285). No window is opened by that either; there is none left in this file.
#
# EVERY SQUAD AND EVERY RALLY LEFT BEHIND IS NAMED IN THE LOG. The chunk writes its own
# sentence — how many went, how many rallies were out, and one word per squad it passed
# over (`out`, `empty`, `no-formation`) plus the server's own refusal for a send that
# threw — and this recipe reads it back and logs it. There is no ending where nothing
# happened and nothing was said.
#
# ALL THE RALLIES OUT, NOT THE FIRST ONE. The chunk pairs every free squad with a
# different banner in one pass, so two banners in the same minute cost one run. The old
# recipe joined ONE rally per run and the push for the second arrived while the first run
# was still going, where the work queue coalesced it away (#1281).
#
# The engine calls live in tools/lib/game_buttons.py (`rally_join_*`) and
# tools/lib/lua_actions.py; the reverse-engineering is docs/research/rally-join.md.

ARGS squads = [1, 2, 3, 4]

# The squads this run may spend, parked where the press can read them — `TAP` carries no
# arguments of its own. One call, and it is the only thing that stands between the push
# and the send.
LUA DataCenter.__lw_rally_squads = { {squads} }

# Sieve, pair, send — every rally, in one press. Nothing is read before it and no window
# is opened by it.
TAP rally_join_all

# What it did, and what it left behind. A reading, so it costs nothing a banner cares
# about: the sends are already away.
READ_LUA (DataCenter.__lw_rally_report or "the join left no report — the press did not run") INTO report

LOG "{report}"

# One number, three answers: how many went out, `0` for nothing to be done, and `-1` for
# «there is a rally standing there and the only squads left are empty», which is the one
# case `fill_empty_squads.md` earns its keep in.
READ_LUA (DataCenter.__lw_rally_todo or 0) INTO todo

IF todo == 0
    LOG "nothing was sent — the reason is on the line above"
    STOP

# OFF THE BANNER'S PATH ON PURPOSE, and in its own file so that a reader of this one can
# see at a glance that none of it is on the way to a send. Reached only when every squad
# that could go had already gone and one is standing empty.
#
# A SQUAD THAT READS EMPTY IS USUALLY A SQUAD NOBODY HAS ASKED ABOUT (#1285): the army is
# on the server and the client has not fetched it, and one request puts it back in 0.37 s
# with nothing on screen. The four presses and the window that used to be here are gone,
# because the game's own launch threw from inside its own code and the case had no working
# route at all.
#
# WRITTEN OUT HERE RATHER THAN `CALL fill_empty_squads`, and that is a correction paid for
# on a live measurement: a sub-recipe's failure FAILS THE CALLER
# (`script_engine._do_call`), so one bad step inside the try turned «nothing could be
# sent» into «the join run failed» — 59 times in an hour, on a panel that had not been
# restarted since the button was added and so had never heard of it. A press looks up a
# button in a catalogue the running process holds in memory; a recipe is read off the disk
# every run. So the one thing standing between a banner and a second chance is a `LUA`
# chunk, wrapped in `pcall`s of its own, which cannot fail the run whatever it finds.
#
# `fill_empty_squads.md` is still the ability and still what the «Ралли» button plays —
# this is the same request, on the path where a banner is waiting and nothing may throw.
IF todo < 0
    LOG "every squad that could go has gone and one is standing empty — asking the game for its army before giving up"
    LUA pcall(function() local afd = DataCenter.ArmyFormationDataManager for _, f in pairs(afd.ArmyFormationList) do local n = 0 pcall(function() n = tonumber(f.totalSoldierNum) or 0 end) if n == 0 then pcall(function() SFSNetwork.SendMessage(MsgDefines.GetFormationSoldier, f.uuid) end) end end end)
    WAIT 0.4
    READ_LUA (function() local afd = DataCenter.ArmyFormationDataManager local n = 0 for _, f in pairs(afd.ArmyFormationList) do local v = 0 pcall(function() v = tonumber(f.totalSoldierNum) or 0 end) if v > 0 then n = n + 1 end end return n end)() INTO armed_squads

    IF armed_squads == 0
        LOG "the squad is empty and the game has no army to fill it — nothing was sent"
        STOP

    TAP rally_join_all
    READ_LUA (DataCenter.__lw_rally_report or "the second join left no report — the press did not run") INTO report
    LOG "{report}"
    READ_LUA (DataCenter.__lw_rally_todo or 0) INTO todo

# THE ONE ENDING THAT IS A SKIP AND NOT A FAILURE. The squads were asked about and the
# game had no army to put in them: nothing the bot can press changes that, and the answer
# is the barracks or the hospital rather than this ability. Said in its own words so it
# does not read as the join being broken.
IF todo < 0
    LOG "the squad is empty and the game has no army to fill it — nothing was sent"
    STOP

IF todo == 0
    LOG "nothing was sent even after the squads were asked about — the reason is on the line above"
    STOP

# --- the send went out: did the map move? ----------------------------------------
# A send returns cleanly whether the server took it or dropped it, and this ability spent
# weeks reporting success while joining nobody (#1237). The proof is one more of OUR
# squads standing in a rally than before the press, counted by the same chunk that sent
# them.
READ_LUA ((function() local P=LuaEntry.Player local wm=DataCenter.WorldMarchDataManager local afd=DataCenter.ArmyFormationDataManager local n=0 for _,f in pairs(afd.ArmyFormationList) do pcall(function() local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) if m~=nil and tostring(m.teamUuid)~="0" then n=n+1 end end) end return n end)()) - (DataCenter.__lw_rally_before or 0) INTO joined

# A few more looks and no more. The server answers in well under a second when it accepts
# off the fast path, and a poll that keeps asking is a poll holding the game in front of
# the next banner — but a run that came through `fill_empty_squads` waits longer, because
# the squad it just fetched an army for has to reach the map. Two looks called that a
# failure while the squad was already on its way (#1285, measured on a live banner), so
# the ceiling is three seconds and it is only ever paid when nothing has appeared yet.
WHILE joined < 1 LIMIT 6
    WAIT 0.5
    READ_LUA ((function() local P=LuaEntry.Player local wm=DataCenter.WorldMarchDataManager local afd=DataCenter.ArmyFormationDataManager local n=0 for _,f in pairs(afd.ArmyFormationList) do pcall(function() local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) if m~=nil and tostring(m.teamUuid)~="0" then n=n+1 end end) end return n end)()) - (DataCenter.__lw_rally_before or 0) INTO joined

IF joined >= 1
    LOG "the squads are in the rally — {joined} more of ours standing in one than before"
    STOP

# WHAT THE SERVER SAID, before giving up on it (#1281). «The send went out and no squad
# appeared» is the same shape this ability spent weeks in — a press that returned cleanly
# over nothing happening — and naming it without naming the REFUSAL leaves the next reader
# exactly where we were. The client puts the server's own words on screen as a message
# tip; that tip is what «invalid end point» was, and reading it costs one call on the
# failing path only. Empty when the server said nothing, which is itself the answer: then
# the message never reached it.
READ_LUA (function() local ok, v = pcall(function() local m = UIManager.Instance if not m:IsWindowOpen(UIWindowNames.UICommonMessageTip) then return '' end local w = m:GetWindow(UIWindowNames.UICommonMessageTip) local t = w and w.View and w.View.tipText return t == nil and '' or tostring(t) end) if not ok or v == nil or v == '' then return 'the server said nothing on screen' end return v end)() INTO refusal

FAIL "the join was sent and no squad appeared in a rally — the game says: {refusal}"

# Join the alliance rallies that are out, one squad each.
# ru: Присоединиться к выставленным ралли альянса — по отряду на ралли.
#
# `squads` is which squad slots may be spent, in order — the 1/2/3 the player sees
# in the dispatch panel. Each squad goes to a DIFFERENT rally: `squads = [1]` joins
# only the first rally with squad 1, `squads = [2, 3]` joins two rallies, one with
# squad 2 and one with squad 3. With fewer rallies out than squads, the leftover
# squads simply stay home.
#
#   run join_rally                       -- all three squads, one rally each
#   run join_rally {"squads": [2, 3]}    -- only squads 2 and 3
#
# Only squads standing in the BASE are spent: a squad already marching, gathering or
# in another rally cannot join one, and the send for it is a silent no-op. The run
# fails, saying so, when not one of the chosen squads is at home.
#
# A rally is an alliance march the bot can read straight off the game (no map
# panning, no pcap): the leader's march carries the rally id, its target tile and
# server, which is everything a join needs. Rallies the player is already in are
# skipped, and so is a rally an earlier press in this same run has just joined —
# the server takes seconds to confirm, and waiting for it would let two squads land
# on the same rally.
#
# Nothing is opened on screen as long as one squad is already loaded. If every
# squad is cold the join would be a silent no-op, so the press loads them the way
# the game does and closes the panel it opens.
#
# The engine calls live in tools/lib/game_buttons.py ("join_rally") and
# tools/lib/lua_actions.py; the reverse-engineering is in
# docs/research/rally-join.md.
#
# UNPROVEN as a recipe: the calls behind it are the ones tools/rally_join.py joins
# with, but this file has not been run against a live rally yet.

ARGS squads = [1, 2, 3]

# First read who is already in the rallies out right now — the leader's teamUuid,
# the target and server, and every member with the squad they sent — and log it, so
# a join is recorded against the rally it joined. Same read the «rally_monitor»
# trigger uses (actions/rally_monitor.md); reused here with CALL, not duplicated.
CALL rally_monitor

# Which squads may be spent — sieved through the same question `create_rally.md` asks
# before it raises one: a squad that is already out joins nothing, and the send is a
# silent no-op that looks exactly like a join. Sieved HERE rather than in the panel
# because it is a rule of the ability, not of the button (CLAUDE.md); a squad whose
# state cannot be read is kept, because a gate that cannot see must not refuse.
#
# THAT RULE HAS THREE HOLES AND ALL THREE ARE PLUGGED HERE. A squad missing from the
# formation list is kept; a `state` that will not become a number is kept; and — the one
# that was leaking — an idle flag that could not be read at all is kept. `IsFree()` was
# called inside a `pcall` whose failure left `free` at FALSE, which is not «unknown», it
# is «busy»: a squad sitting at home behind a manager that happened to refuse was sieved
# out and the run then said nobody was home. `ok`/`idle` tell a refusal from an answer,
# and only an actual «no» closes the gate.
#
# `__lw_rally_want` is the count that arrived, kept because AN EMPTY LIST IS A
# DIFFERENT FAILURE from a list whose squads are all out — and one the reading below
# cannot tell apart, since both leave `home` empty. Nobody ticked one is a settings
# page nobody filled in; until #1237 that page was not even DRAWN, so every auto-join
# refused with «none is in the base» and sent whoever read the log to look at their
# marches instead of at the empty list they were sent out with.
LUA DataCenter.__lw_rally_squads = (function() local want = { {squads} } DataCenter.__lw_rally_want = #want local afd = DataCenter.ArmyFormationDataManager local home = {} for _, idx in ipairs(want) do local f = nil for _, v in pairs(afd.ArmyFormationList) do if tonumber(v.index) == tonumber(idx) then f = v end end if f == nil then home[#home+1] = idx else local st = tonumber(f.state) local ok, idle = pcall(function() return f:IsFree() end) local free = true if ok and idle ~= nil then free = (idle and true or false) end if st == nil or (st == 0 and free) then home[#home+1] = idx end end end return home end)() DataCenter.__lw_rally_joined = {}

# Both answers in ONE round trip: -1 for «none was ticked», otherwise how many of the
# ticked ones are standing in the base. A second READ_LUA to count the argument the
# panel already knows would be a VM call spent on arithmetic (#1230).
READ_LUA (function() if (DataCenter.__lw_rally_want or 0) == 0 then return -1 end return #(DataCenter.__lw_rally_squads or {}) end)() INTO free_squads

IF free_squads == -1
    FAIL "no squad is ticked for joining — the auto-rally settings page holds the list a join may spend"

IF free_squads == 0
    FAIL "not one of the chosen squads is in the base — there is nothing to join with"

TAP join_rally xall   # one press per squad, each to a rally of its own

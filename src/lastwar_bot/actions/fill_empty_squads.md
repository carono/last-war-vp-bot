# Put the soldiers back into every squad that is standing empty.
# ru: Вернуть солдат в отряды, которые стоят пустыми.
#
# `squads` is which squad slots to look at — the 1/2/3/4 the player sees. Squads that
# already hold an army are left alone; only the ones reading zero are asked about.
#
#   run fill_empty_squads                       -- every squad
#   run fill_empty_squads {"squads": [2, 3]}    -- only squads 2 and 3
#
# THE EMPTY SQUAD WAS NEVER EMPTY (#1285). A squad reads zero soldiers in a session where
# nothing has needed the number yet, and every gate downstream believes it: a march is
# refused before a byte leaves, the rally join reports the squad as `empty` and the run
# ends having spent nothing. The army is on the SERVER the whole time — the client simply
# had not asked for it. One request fetches it, and no window is opened by any of this.
#
# Measured live on a client whose three squads all read zero while the base held thousands
# of soldiers: **zero to a full squad in 0.37 s**, that time including the two calls into
# the game around it. So this is cheap enough to stand on the path of a banner, which is
# where `join_rally.md` calls it from.
#
# NOTHING HERE RECRUITS. Every filler the client has of its own — `AutoInitFormationData`,
# `AutoAddSoldierByForm`, `AutoAddSoldier`, `FetchFormationSoldier` — was pressed on a
# live empty squad and each returned cleanly having changed nothing, because they all draw
# on a table the client is never sent. A squad that still reads zero AFTER this run is
# genuinely empty, and that is the one case the log is allowed to call impossible.
#
# The engine call is `squads_fill_empty` in tools/lib/lua_actions.py; the
# reverse-engineering is docs/research/rally-join.md.

ARGS squads = [1, 2, 3, 4]

# The slots this run may ask about, parked where the press can read them — `TAP` carries
# no arguments of its own.
LUA DataCenter.__lw_fill_squads = { {squads} }

# One press: every chosen squad that reads zero gets a request of its own.
TAP fill_empty_squads

# `fill_report` and not `report`, and the name is load-bearing: a recipe's `{name}` is
# substituted from the run's variables BEFORE it is parsed, so a CALLed recipe that
# reuses the caller's variable name prints the CALLER's value — the fill would log the
# join's report, which is exactly the sentence a reader is trying to get past.
READ_LUA (DataCenter.__lw_fill_report or "the fill left no report — the press did not run") INTO fill_report

# The request is away; the soldiers arrive with the server's answer. Polled rather than
# slept on, because the answer was measured at a fifth of a second and a banner is what
# is usually waiting behind this. Counted over the slots the press actually ASKED for
# (`__lw_fill_wanted`), so a squad that was already loaded is not a success this run
# earned — and `-1` is «nothing was asked for», which leaves the poll below at once
# instead of spending two seconds waiting for an answer nobody sent for. The same text is
# `squads_filled_count()` in tools/lib/lua_actions.py.
READ_LUA (function() local names = DataCenter.__lw_fill_wanted if type(names) ~= 'table' or #names == 0 then return -1 end local afd = DataCenter.ArmyFormationDataManager local n = 0 for _, f in pairs(afd.ArmyFormationList) do local idx, num = nil, 0 pcall(function() idx = f.index num = tonumber(f.totalSoldierNum) or 0 end) if idx ~= nil and num > 0 then for _, s in ipairs(names) do if tostring(s) == tostring(idx) then n = n + 1 end end end end return n end)() INTO fill_count

WHILE fill_count == 0 LIMIT 8
    WAIT 0.25
    READ_LUA (function() local names = DataCenter.__lw_fill_wanted if type(names) ~= 'table' or #names == 0 then return -1 end local afd = DataCenter.ArmyFormationDataManager local n = 0 for _, f in pairs(afd.ArmyFormationList) do local idx, num = nil, 0 pcall(function() idx = f.index num = tonumber(f.totalSoldierNum) or 0 end) if idx ~= nil and num > 0 then for _, s in ipairs(names) do if tostring(s) == tostring(idx) then n = n + 1 end end end end return n end)() INTO fill_count

# NO `STOP` IN ANY OF THESE ENDINGS, and that is not tidiness: a `STOP` inside a CALLed
# recipe halts the CALLER too (`script_engine._do_call` re-raises the halt), and this one
# is CALLed by `join_rally.md`, which has a banner to press at afterwards. So each ending
# says its own sentence and the run simply finishes.
IF fill_count < 0
    LOG "nothing to ask for — every chosen squad already holds its army"

IF fill_count == 0
    LOG "the squads are empty and the game has no army to put in them — nothing can be sent with them"

IF fill_count > 0
    LOG "the squads that read empty are holding an army again — the count is on the fill_count line above"

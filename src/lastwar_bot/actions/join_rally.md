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
# THE SEND IS NOT RELIABLE, and this recipe is written around that rather than over
# it. It was seen joining once in a live game — the alliance's participant list came
# back one name longer with the player in it — and on the next day's rallies the same
# press went out repeatedly and joined nobody, with `SendCreateMarchMessage` returning
# `ok=true` and creating no march, on both the warm and the cold path. So the run now
# COUNTS: the squads standing in a rally before the press and after it, and it fails
# saying so when the number did not move. Whatever the game wants that it is not being
# given, a run that pressed and achieved nothing must not come back «OK».

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

# IS THERE ANYTHING TO JOIN — asked before the press, because the two ways this run
# ends with nothing joined are not the same thing. A quiet minute with no rally out is
# an ordinary success; a rally that WAS out and no squad in it afterwards is a fault,
# and the auto-join trigger must retry the second and not the first. Until #1237 both
# came back «OK» with no line at all, which is exactly what «пытается, эффекта ноль»
# looks like from the log.
READ_LUA (function() local wm=DataCenter.WorldMarchDataManager local function g(mo,k) local ok,v=pcall(function() return mo[k] end) if ok then return v end return nil end local function cur(e) local mo=e.Current local ok,v=pcall(function() return mo.Value end) if ok and v~=nil then return v end return mo end local taken=DataCenter.__lw_rally_joined or {} local om=wm:GetOwnerMarches() if om then local e=om:GetEnumerator() while e:MoveNext() do local mo=cur(e) local t=g(mo,'teamUuid') if t~=nil and tostring(t)~='0' then taken[tostring(t)]=true end end end local rallies={} local col=wm:GetAllMarches() if col then local e=col:GetEnumerator() while e:MoveNext() do local mo=cur(e) local team=g(mo,'teamUuid') local ts=tostring(team) if team~=nil and ts~='0' and ts~='nil' and not taken[ts] then local lead=false pcall(function() lead=(tostring(g(mo,'uuid'))==tostring(team-1)) end) if lead then rallies[#rallies+1]={team=team,point=g(mo,'targetPos'),server=(g(mo,'serverId') or g(mo,'targetServer'))} end end end end table.sort(rallies,function(a,b) return tostring(a.team)<tostring(b.team) end) local squads=DataCenter.__lw_rally_squads or {1,2,3}  return #rallies end)() INTO rallies_out

IF rallies_out == 0
    LOG "no rally is out that this account is not already in — nothing to join"
    STOP

# What the press is about to be judged against.
LUA DataCenter.__lw_rally_before = (function() local P=LuaEntry.Player local wm=DataCenter.WorldMarchDataManager local afd=DataCenter.ArmyFormationDataManager local n=0 for _,f in pairs(afd.ArmyFormationList) do pcall(function() local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) if m~=nil and tostring(m.teamUuid)~="0" then n=n+1 end end) end return n end)()

TAP join_rally xall   # one press per squad, each to a rally of its own

# …AND WHETHER IT ACTUALLY DID IT. The press cannot answer this for itself: the send is
# put on the game's own timer and returns before the server has replied, so a join that
# worked and a join that vanished return exactly the same thing. Only the squads
# standing in a rally afterwards can say, and the difference is the answer.
READ_LUA ((function() local P=LuaEntry.Player local wm=DataCenter.WorldMarchDataManager local afd=DataCenter.ArmyFormationDataManager local n=0 for _,f in pairs(afd.ArmyFormationList) do pcall(function() local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) if m~=nil and tostring(m.teamUuid)~="0" then n=n+1 end end) end return n end)()) - (DataCenter.__lw_rally_before or 0) INTO joined

IF joined == 0
    FAIL "the press went out and no squad joined the rally — the send is accepted by the game and quietly does nothing in this state (docs/research/rally-join.md)"

LOG "joined {joined} rally(ies)"

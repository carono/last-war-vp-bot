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

# IS THERE ANYTHING OF OURS TO JOIN — asked before the press, because the two ways this run
# ends with nothing joined are not the same thing. A quiet minute with no rally out is
# an ordinary success; a rally that WAS out and no squad in it afterwards is a fault,
# and the auto-join trigger must retry the second and not the first. Until #1237 both
# came back «OK» with no line at all, which is exactly what «пытается, эффекта ноль»
# looks like from the log.
READ_LUA (function() local wm=DataCenter.WorldMarchDataManager local function g(mo,k) local ok,v=pcall(function() return mo[k] end) if ok then return v end return nil end local function cur(e) local mo=e.Current local ok,v=pcall(function() return mo.Value end) if ok and v~=nil then return v end return mo end local taken=DataCenter.__lw_rally_joined or {} local om=wm:GetOwnerMarches() if om then local e=om:GetEnumerator() while e:MoveNext() do local mo=cur(e) local t=g(mo,'teamUuid') if t~=nil and tostring(t)~='0' then taken[tostring(t)]=true end end end local rallies={} local col=wm:GetAllMarches() if col then local e=col:GetEnumerator() while e:MoveNext() do local mo=cur(e) local team=g(mo,'teamUuid') local ts=tostring(team) if team~=nil and ts~='0' and ts~='nil' and not taken[ts] then local lead=false pcall(function() lead=(tostring(g(mo,'uuid'))==tostring(team-1)) end) if lead then rallies[#rallies+1]={team=team,point=g(mo,'targetPos'),server=(g(mo,'serverId') or g(mo,'targetServer'))} end end end end table.sort(rallies,function(a,b) return tostring(a.team)<tostring(b.team) end) local squads=DataCenter.__lw_rally_squads or {1,2,3} local P = LuaEntry.Player if col then local e2 = col:GetEnumerator() while e2:MoveNext() do local m2 = cur(e2) local u, an = nil, nil pcall(function() u = tostring(m2.ownerUid) an = tostring(m2.allianceName) end) if u == tostring(P.uid) and an ~= nil and an ~= '' and an ~= 'nil' then DataCenter.__lw_my_alliance = an end end end local mine = DataCenter.__lw_my_alliance local ours = {} if col and mine then local e3 = col:GetEnumerator() while e3:MoveNext() do local m3 = cur(e3) local t3, n3 = nil, nil pcall(function() t3 = m3.teamUuid n3 = tostring(m3.allianceName) end) if t3 ~= nil and tostring(t3) ~= '0' and n3 == mine then ours[tostring(t3)] = true end end end if mine ~= nil then local kept = {} for _, r in ipairs(rallies) do if ours[tostring(r.team)] then kept[#kept+1] = r end end rallies = kept end for _, r in ipairs(rallies) do if col then local e4 = col:GetEnumerator() while e4:MoveNext() do local m4 = cur(e4) local t4 = nil pcall(function() t4 = m4.teamUuid end) if t4 ~= nil and tostring(t4) == tostring(r.team) then local isL = false pcall(function() isL = (tostring(m4.uuid) == tostring(t4 - 1)) end) if isL then pcall(function() local s = m4.startPos if s == nil then s = m4.homePos end if s ~= nil then r.point = s end end) end end end end end  return #rallies end)() INTO rallies_out

IF rallies_out == 0
    LOG "no rally of this alliance is out that we are not already in — nothing to join"
    STOP

# What the join is about to be judged against.
LUA DataCenter.__lw_rally_before = (function() local P=LuaEntry.Player local wm=DataCenter.WorldMarchDataManager local afd=DataCenter.ArmyFormationDataManager local n=0 for _,f in pairs(afd.ArmyFormationList) do pcall(function() local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) if m~=nil and tostring(m.teamUuid)~="0" then n=n+1 end end) end return n end)()

# --- 1. Which rally, and which squad --------------------------------------------
# Parked before anything is opened, so every step below reads ONE answer instead of
# racing the map for its own — the same reason `create_rally.md` arms first.
TAP rally_join_arm

READ_LUA (function() local p = DataCenter.__lw_rally_join if p == nil or p.formation == nil then return 0 end return 1 end)() INTO armed

IF armed == 0
    FAIL "there is a rally out and a squad at home, but they could not be paired up — the squad has no formation the game knows"

# --- 2. Open the game's own squad screen -----------------------------------------
# THE DIRECT SEND DOES NOT WORK. The message the bot built matched the player's own
# argument for argument and the server created no march (docs/research/rally-join.md),
# so the join is made the way the raise is: through the windows. This press is what a
# player's tap on the rally does, and it opens the squad screen.
#
# NOTHING CLOSES THAT SCREEN. The old press opened it and shut it in the same breath,
# which is why the send behind it had nothing to stand on — the lesson #1172 paid for
# on the create side, repeated here because it cost this ability weeks.
TAP rally_join_open

READ_LUA (function() local function _isformation(w) return w ~= nil and (w.Name == 'UIFormationSelectListV2' or w.Name == 'UIFormationSelectListNew') end local w = UIManager.Instance:GetStackTopWindow() if _isformation(w) then return 1 end return 0 end)() INTO screen

WHILE screen == 0 LIMIT 8
    WAIT 1
    READ_LUA (function() local function _isformation(w) return w ~= nil and (w.Name == 'UIFormationSelectListV2' or w.Name == 'UIFormationSelectListNew') end local w = UIManager.Instance:GetStackTopWindow() if _isformation(w) then return 1 end return 0 end)() INTO screen

IF screen == 0
    FAIL "the rally did not bring up the squad screen — nothing was sent"

# --- 3. Pick the squad, and read the pick back -----------------------------------
# A launch on a screen that is not holding the wanted squad is a press that ends in
# nothing, so the pick is confirmed before the send.
TAP rally_join_squad

READ_LUA (function() local function _isformation(w) return w ~= nil and (w.Name == 'UIFormationSelectListV2' or w.Name == 'UIFormationSelectListNew') end local p = DataCenter.__lw_rally_join or {} local w = UIManager.Instance:GetStackTopWindow() if not _isformation(w) then return 0 end if p.formation ~= nil and tostring(w.Ctrl.selectFormationUuid) == tostring(p.formation) then return 1 end return 0 end)() INTO picked

IF picked == 0
    TAP close
    FAIL "the squad screen would not take the chosen squad — nothing was sent"

# --- 4. Launch, and let the game say whether we are in ---------------------------
# The proof is one more of OUR squads standing in a rally than before the run — not the
# press returning cleanly, which it did for weeks while joining nothing.
# STILL THERE? A banner is minutes at best and seconds during an event, and the steps
# above cost a few of them. Launching at a rally that has already come down aims the
# send at a tile that is no longer one — the server refuses it, and what the player is
# shown is «invalid end point». Said apart from «pressed and nothing happened», because
# they are different things and only one of them is the bot's fault.
READ_LUA (function() local p = DataCenter.__lw_rally_join if p == nil then return 0 end local wm = DataCenter.WorldMarchDataManager local col = wm:GetAllMarches() if col == nil then return 1 end local e = col:GetEnumerator() while e:MoveNext() do local mo = e.Current local ok, v = pcall(function() return mo.Value end) if ok and v ~= nil then mo = v end local t = nil pcall(function() t = mo.teamUuid end) if t ~= nil and tostring(t) == tostring(p.team) then return 1 end end return 0 end)() INTO alive

IF alive == 0
    TAP close
    FAIL "the rally came down before the squad could be sent — it was gone by the time the screen was ready"

TAP rally_join_launch

READ_LUA ((function() local P=LuaEntry.Player local wm=DataCenter.WorldMarchDataManager local afd=DataCenter.ArmyFormationDataManager local n=0 for _,f in pairs(afd.ArmyFormationList) do pcall(function() local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) if m~=nil and tostring(m.teamUuid)~="0" then n=n+1 end end) end return n end)()) - (DataCenter.__lw_rally_before or 0) INTO joined

WHILE joined < 1 LIMIT 5
    WAIT 1.2
    READ_LUA ((function() local P=LuaEntry.Player local wm=DataCenter.WorldMarchDataManager local afd=DataCenter.ArmyFormationDataManager local n=0 for _,f in pairs(afd.ArmyFormationList) do pcall(function() local m=wm:GetOwnerFormationMarch(P.uid,f.uuid,P.allianceId) if m~=nil and tostring(m.teamUuid)~="0" then n=n+1 end end) end return n end)()) - (DataCenter.__lw_rally_before or 0) INTO joined

IF joined < 1
    FAIL "everything was pressed and no squad joined the rally"

LOG "joined the rally"

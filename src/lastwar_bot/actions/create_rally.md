# Raise a rally («Стягивание») on a monster of a given level, with a chosen squad.
# ru: Поднять стяг на монстра нужного уровня выбранным отрядом.
#
# The CREATE side of a rally; joining one somebody else raised is join_rally.md.
# Three arguments say what to raise:
#
#   run create_rally                                          -- squad 1, a level-35 elite
#   run create_rally {"squad": 2, "level": 60}                -- squad 2, a level-60 elite
#   run create_rally {"squad": 3, "level": 12, "target": "monster"}
#
#   * `squad`  — which squad raises the banner, the 1/2/3/4 the player sees in the
#                dispatch panel. One run raises ONE rally, with this one squad.
#   * `level`  — the target's level, 1 to 200. A season puts monsters far above the
#                everyday range on the map, so the range is wide on purpose; a level
#                the server has nothing for simply comes back empty.
#   * `target` — what to look for: `boss` is a «Роковая Элита», `monster` an ordinary
#                field monster. They differ only in which «лупа» tab is used;
#                anything else reads as `boss`.
#
# It does what a player does, in the same order, and each step waits for the game to
# actually be in the next state rather than sleeping a guessed amount — starting with
# the question a player answers by looking at the base:
#
#   0. is that squad even at home? A squad already marching, gathering, standing in
#      somebody else's rally or wiped cannot raise one, and the game only says so at
#      the last press. This asks first, and says which of those it is;
#
#   1. ask the game's own map search («лупа») for a target of that kind and level —
#      not a scan of whatever monsters happen to be loaded on screen;
#   2. the server flies the camera in and opens the target's window by itself: press
#      «Стягивание» there, with the window still open;
#   3. the squad screen comes up: pick the squad on it and read the pick back;
#   4. launch, and confirm by looking — a rally of ours has to actually appear.
#
# Nothing is claimed from a press that returned cleanly. The run ends as a FAILURE,
# naming the step, when the squad is not in the base (with what it is doing instead),
# when the search finds nothing of that level, when the search finds something that
# cannot be rallied, when the squad is not one the game knows, when «Стягивание» does
# not bring up the squad screen, when that screen will not take the squad, or when
# everything was pressed and no banner appeared. A timer therefore keeps its place and
# tries again instead of counting a run that raised nothing.
#
# The presses live in tools/lib/game_buttons.py (`rally_*`) and their engine calls in
# tools/lib/lua_actions.py; the reverse-engineering is docs/research/rally-create.md
# (the flow) and docs/research/rally-elite-search.md (the search). The same flow driven
# from the command line is tools/rally_create.py, and the panel's «Ралли» tab runs it
# in a loop — this recipe is the one-shot form, so a scenario or a timer can raise one.
#
# UNPROVEN as a recipe: every call behind it is the one a live level-35 rally went out
# with, but this file has not itself raised a banner yet.

ARGS squad = 1
ARGS level = 35
ARGS target = boss

# --- 0. The squad has to be standing in the base ----------------------------------
# FIRST, before the camera moves and before anything is pressed. A rally is raised BY a
# squad, and a squad that is already out cannot raise one — the game refuses at the
# LAST press, which is a minute of searching, a camera flight and an open window later,
# and all the operator saw was «не вышло». Asking the squad first costs one VM read and
# names what it is doing instead.
#
# The code is the same one the panel's squad line is drawn from — the state, the idle
# flag and (when there is one) the march's `MarchStatus`, mapped exactly as in
# actions/read_squad_state.md and docs/research/squad-state.md:
#
#     0 at home   1 marching   2 in a rally   3 gathering   4 in battle
#     5 coming home   6 stationed out   7 wiped   8 captured   9 out (unnamed)
#    -1 nothing could be read
#
# -1 does NOT stop the run. A read that failed says nothing about the squad, and a gate
# that cannot see must not refuse — the send goes out and the game answers, exactly as
# it did before this gate existed.
#
# The idle flag obeys the same rule and did not used to. `IsFree()` sat inside a `pcall`
# whose failure left `free` at FALSE, so a squad standing at home behind a manager that
# refused to answer fell past `st == 0` and out of the bottom as 9 — «squad N is not in
# the base», a sentence about the squad that was really about the read. `ok`/`idle` tell
# a refusal from an answer; unknown means the send goes out, exactly as -1 does.
READ_LUA (function() local afd = DataCenter.ArmyFormationDataManager local f = nil for _, v in pairs(afd.ArmyFormationList) do if tonumber(v.index) == {squad} then f = v end end if f == nil then return -1 end local st = tonumber(f.state) or -1 local ok, idle = pcall(function() return f:IsFree() end) local free = true if ok and idle ~= nil then free = (idle and true or false) end if st == 0 and free then return 0 end if st == 3 or st == 5 then return 7 end if st == 2 or st == 6 then return 8 end local status, team = "", "0" pcall(function() local P = LuaEntry.Player local m = DataCenter.WorldMarchDataManager:GetOwnerFormationMarch(P.uid, f.uuid, P.allianceId) if m ~= nil then status = tostring(m.status):match("^[%u%d_]+") or "" team = tostring(m.teamUuid) end end) if team ~= "0" and team ~= "nil" then return 2 end if status == "WAIT_RALLY" or status == "IN_TEAM" then return 2 end if status == "COLLECTING" or status == "COLLECTING_ASSISTANCE" or status == "TREASURE_DIGGING" or status == "SAMPLING" or status == "PICKING" then return 3 end if status == "ATTACKING" or status == "CHASING" then return 4 end if status == "BACK_HOME" or status == "TRANSPORT_BACK_HOME" then return 5 end if status == "STATION" then return 6 end if status == "MOVING" then return 1 end if st == 1 then return 1 end if st == 4 then return 5 end if st == 7 then return 6 end if st < 0 then return -1 end return 9 end)() INTO squad_state

IF squad_state == 1
    FAIL "squad {squad} is out on a march — a rally is raised by a squad standing in the base"
IF squad_state == 2
    FAIL "squad {squad} is already in a rally"
IF squad_state == 3
    FAIL "squad {squad} is gathering resources — it cannot raise a rally until it is home"
IF squad_state == 4
    FAIL "squad {squad} is in battle"
IF squad_state == 5
    FAIL "squad {squad} is on its way home — try again when it lands"
IF squad_state == 6
    FAIL "squad {squad} is stationed out in the world"
IF squad_state == 7
    FAIL "squad {squad} was wiped out and is not in the base"
IF squad_state == 8
    FAIL "squad {squad} is a prisoner"
IF squad_state == 9
    FAIL "squad {squad} is not in the base"

# The «лупа» is the world map's search, so the map has to be up. In the city the
# window would not open and the run would fail on a press instead of on a state.
IF scene != world
    GAME WORLD
    WAIT scene == world WITHIN 30s

# What to rally, parked where the presses can read it — `TAP` carries no arguments,
# the same reason join_rally.md parks its squads. `rally_arm` then fills in the two
# things only the game can answer: the squad's formation and how many rallies of ours
# are already out, which is what the raise is measured against at the end.
LUA DataCenter.__lw_rally_create = {squad = {squad}, level = {level}, kind = "{target}"}
TAP rally_arm

READ_LUA (((DataCenter.__lw_rally_create or {}).formation ~= nil) and 1 or 0) INTO armed

IF armed == 0
    FAIL "squad {squad} is not one the game knows — nothing was searched for"

# --- 1. Find a target -------------------------------------------------------------
# The magnifier only sends the request; the answer opens the target's window on its
# own a round trip later. Poll for that window AND for its monster data, which lands a
# beat after the window itself — a window read too early looks empty, not absent.
TAP rally_search_window
TAP rally_search

READ_LUA (function() local w = UIManager.Instance:GetStackTopWindow() if not w or w.Name ~= 'UIWorldPoint' then return 0 end local c = w.Ctrl local lvl = nil pcall(function() lvl = c:GetMonsterData(c.uuid).level end) if lvl == nil then return 0 end local b = '?' pcall(function() b = tostring(c:GetPointBtnEnumName(w.View.btnList[1])) end) if b == 'RallyBoss' then return 1 end return -1 end)() INTO found

WHILE found == 0 LIMIT 12
    WAIT 1
    READ_LUA (function() local w = UIManager.Instance:GetStackTopWindow() if not w or w.Name ~= 'UIWorldPoint' then return 0 end local c = w.Ctrl local lvl = nil pcall(function() lvl = c:GetMonsterData(c.uuid).level end) if lvl == nil then return 0 end local b = '?' pcall(function() b = tostring(c:GetPointBtnEnumName(w.View.btnList[1])) end) if b == 'RallyBoss' then return 1 end return -1 end)() INTO found

IF found == 0
    TAP close
    FAIL "the search turned up no {target} of level {level}"

# A window carrying «Атаковать» instead of «Стягивание» is a soloable monster, and no
# amount of pressing turns that into a rally. Which button the window carries is the
# reliable test — better than the target's own «can be attacked» flag.
IF found < 0
    TAP close
    FAIL "what the search returned cannot be rallied — it is a solo target"

# --- 2. Press «Стягивание», with the target's window still open -------------------
# Closing it first is what used to make the target "hide" with nothing pressed.
TAP rally_banner

READ_LUA (function() local function _isformation(w) return w ~= nil and (w.Name == 'UIFormationSelectListV2' or w.Name == 'UIFormationSelectListNew') end if _isformation(UIManager.Instance:GetStackTopWindow()) then return 1 end return 0 end)() INTO panel

WHILE panel == 0 LIMIT 8
    WAIT 1
    READ_LUA (function() local function _isformation(w) return w ~= nil and (w.Name == 'UIFormationSelectListV2' or w.Name == 'UIFormationSelectListNew') end if _isformation(UIManager.Instance:GetStackTopWindow()) then return 1 end return 0 end)() INTO panel

IF panel == 0
    FAIL "«Стягивание» did not bring up the squad screen — nothing was sent"

# --- 3. Pick the squad, and read the pick back ------------------------------------
# A launch on a screen that is not holding the wanted squad is the "nobody was chosen
# and it all ended" the player used to see, so the pick is confirmed before sending.
TAP rally_squad

READ_LUA (function() local function _isformation(w) return w ~= nil and (w.Name == 'UIFormationSelectListV2' or w.Name == 'UIFormationSelectListNew') end local p = DataCenter.__lw_rally_create or {} local w = UIManager.Instance:GetStackTopWindow() if not _isformation(w) then return 0 end if p.formation ~= nil and tostring(w.Ctrl.selectFormationUuid) == tostring(p.formation) then return 1 end return 0 end)() INTO picked

IF picked == 0
    TAP close
    FAIL "the squad screen would not take squad {squad} — nothing was sent"

# --- 4. Launch, and let the game say whether a banner went up ---------------------
# The proof is a new march of ours that is part of a rally, not the press returning
# cleanly: an ordinary march moves the plain march count for unrelated reasons.
TAP rally_launch

READ_LUA ((function() local wm = DataCenter.WorldMarchDataManager local om = wm:GetOwnerMarches() local n = 0 if om then local e = om:GetEnumerator() while e:MoveNext() do local mo = e.Current.Value if mo == nil then mo = e.Current end local ok, t = pcall(function() return mo.teamUuid end) if ok and t ~= nil and tostring(t) ~= '0' and tostring(t) ~= 'nil' then n = n + 1 end end end return n end)() - ((DataCenter.__lw_rally_create or {}).before or 0)) INTO raised

WHILE raised < 1 LIMIT 5
    WAIT 1.2
    READ_LUA ((function() local wm = DataCenter.WorldMarchDataManager local om = wm:GetOwnerMarches() local n = 0 if om then local e = om:GetEnumerator() while e:MoveNext() do local mo = e.Current.Value if mo == nil then mo = e.Current end local ok, t = pcall(function() return mo.teamUuid end) if ok and t ~= nil and tostring(t) ~= '0' and tostring(t) ~= 'nil' then n = n + 1 end end end return n end)() - ((DataCenter.__lw_rally_create or {}).before or 0)) INTO raised

IF raised < 1
    FAIL "everything was pressed and no rally came out"

LOG "The banner is up: a level {level} {target}, raised by squad {squad}"

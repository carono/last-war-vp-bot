# Attack the «Кодовое имя» boss once, with a squad standing in the base.
# ru: Одна атака по боссу события «Кодовое имя» отрядом, стоящим в базе.
#
# The event puts one boss on the world map for a few hours at a time and asks for
# THREE attacks on it; attempts themselves are not rationed («кол-во попыток в день
# не ограничено» — the game's own rules), and only the biggest single hit counts for
# the daily ranking. This recipe is ONE attack: run it three times for the day's
# credit, or as often as there is a squad free for a better hit.
#
# It takes no arguments. «A free squad» is not a choice the person should have to
# make three times a window: the run finds the first squad standing in the base and
# sends that one. A squad already marching, gathering, standing in a rally or wiped
# cannot be sent at all, and there is nothing to choose between the ones that can.
#
# It does what a player does, in the same order, and each step waits for the game to
# actually be in the next state rather than sleeping a guessed amount:
#
#   0. is the event even running? Outside a window there is no boss on the map, and
#      the read that says so is the same one the panel draws (read_codename_event.md);
#   1. find the boss in the event's own list and a squad standing in the base;
#   2. tap the boss on the map — the server opens its popup;
#   3. press «Атаковать» there, with the popup still on top;
#   4. the squad screen comes up: pick the squad on it and read the pick back;
#   5. launch, and confirm by looking — the attack COUNT has to move.
#
# Nothing is claimed from a press that returned cleanly. The run ends as a FAILURE,
# naming the step, when the event is not running, when the boss is not in the list,
# when no squad is standing in the base, when the tap opens something else, when
# «Атаковать» does not bring up the squad screen, when that screen will not take the
# squad, or when everything was pressed and the count did not move. A timer therefore
# keeps its place and tries again instead of counting an attack that never went out.
#
# The presses live in tools/lib/game_buttons.py (`codename_*`) and their engine calls
# in tools/lib/lua_actions.py; the reverse-engineering is
# docs/research/codename-event.md. The panel plays this from «События» and from the
# «Кодовое имя» block on «Чеклист».
#
# UNPROVEN: every call behind it is one the game itself makes — the popup and the
# squad screen are the very ones a rally walks (actions/create_rally.md, proven live),
# and the target type is the event's own `DIRECT_ATTACK_ACT_BOSS`. But the event has
# not been open since this was written, so no squad has gone out on it yet.

# --- 0. Is the event running at all? ----------------------------------------------
# First, before anything is opened. Outside a window there is no boss on the map, and
# every later step would fail on a press instead of on a state.
READ_LUA (function() local ok, v = pcall(function() return DataCenter.ActBossDataManager:IsBossAvailable() end) if not ok then return nil end return (v and 1 or 0) end)() INTO cn_open

IF cn_open != 1
    FAIL "«Кодовое имя» is not running right now — there is no boss on the map"

# The boss stands on the world map, so the map has to be up: in the city the tap would
# resolve nothing.
IF scene != world
    GAME WORLD
    WAIT scene == world WITHIN 30s

# --- 1. Which boss, and which squad -----------------------------------------------
# Both readings before any window is opened, for the reason create_rally.md takes its
# own first: a run that finds out at the last press that there was no squad has already
# flown the camera across the map and left a popup open on it.
TAP codename_arm

READ_LUA (function() local p = DataCenter.__lw_codename or {} if p.uuid == nil or p.point == nil then return 0 end if p.formation == nil then return -1 end return 1 end)() INTO armed

IF armed == 0
    FAIL "the event is running but its boss is not in the list yet — try again in a moment"
IF armed < 0
    FAIL "no squad is standing in the base — every one of them is already out"

# --- 2. Tap the boss --------------------------------------------------------------
# The popup lands a beat before the data inside it, so «up but empty» polls as «not
# yet» rather than being pressed into.
TAP codename_select

READ_LUA (function() local p = DataCenter.__lw_codename or {} local w = UIManager.Instance:GetStackTopWindow() if not w or w.Name ~= 'UIWorldPoint' then return 0 end local c = w.Ctrl if c == nil then return 0 end local pid = tonumber(c.pointId) if pid == nil then return 0 end if p.point ~= nil and pid ~= tonumber(p.point) then return -1 end return 1 end)() INTO popup

WHILE popup == 0 LIMIT 10
    WAIT 1
    READ_LUA (function() local p = DataCenter.__lw_codename or {} local w = UIManager.Instance:GetStackTopWindow() if not w or w.Name ~= 'UIWorldPoint' then return 0 end local c = w.Ctrl if c == nil then return 0 end local pid = tonumber(c.pointId) if pid == nil then return 0 end if p.point ~= nil and pid ~= tonumber(p.point) then return -1 end return 1 end)() INTO popup

IF popup == 0
    FAIL "the boss did not open — the map has nothing at that place"
IF popup < 0
    TAP close
    FAIL "the tap opened something else — the boss is not where the event said it was"

# --- 3. Press «Атаковать», with the popup still open ------------------------------
TAP codename_attack

READ_LUA (function() local function _isformation(w) return w ~= nil and (w.Name == 'UIFormationSelectListV2' or w.Name == 'UIFormationSelectListNew') end if _isformation(UIManager.Instance:GetStackTopWindow()) then return 1 end return 0 end)() INTO panel

WHILE panel == 0 LIMIT 8
    WAIT 1
    READ_LUA (function() local function _isformation(w) return w ~= nil and (w.Name == 'UIFormationSelectListV2' or w.Name == 'UIFormationSelectListNew') end if _isformation(UIManager.Instance:GetStackTopWindow()) then return 1 end return 0 end)() INTO panel

IF panel == 0
    FAIL "«Атаковать» did not bring up the squad screen — nothing was sent"

# --- 4. Pick the squad, and read the pick back ------------------------------------
TAP codename_squad

READ_LUA (function() local function _isformation(w) return w ~= nil and (w.Name == 'UIFormationSelectListV2' or w.Name == 'UIFormationSelectListNew') end local p = DataCenter.__lw_codename or {} local w = UIManager.Instance:GetStackTopWindow() if not _isformation(w) then return 0 end if p.formation ~= nil and tostring(w.Ctrl.selectFormationUuid) == tostring(p.formation) then return 1 end return 0 end)() INTO picked

IF picked == 0
    TAP close
    FAIL "the squad screen would not take the free squad — nothing was sent"

# --- 5. Launch, and let the game say whether an attack went out -------------------
# The proof is the SERVER's own attack count moving, not the press returning cleanly:
# the count is what the reward is paid against and what the board draws.
TAP codename_launch

READ_LUA (((function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.actBossTransTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() or 0) - ((DataCenter.__lw_codename or {}).before or 0)) INTO sent

WHILE sent < 1 LIMIT 6
    WAIT 1.2
    READ_LUA (((function() local ok, v = pcall(function() return DataCenter.ActBossDataManager.actBossTransTimes end) if not ok then return nil end return math.floor(tonumber(v) or 0) end)() or 0) - ((DataCenter.__lw_codename or {}).before or 0)) INTO sent

IF sent < 1
    FAIL "everything was pressed and the attack count did not move"

LOG "A squad is on its way to the «Кодовое имя» boss"

# Send a chosen squad at the target the game is already asking about.
# ru: Отправить выбранный отряд на цель, по которой открыт экран выбора отряда.
#
# The keyboard macro behind keys 1..4 (#1283). A person clicks a target on the map —
# a monster, a mine, another player's base, a rally somebody raised, anything at all —
# presses the action in its popup, and the game puts up the squad-selection screen.
# That screen is the whole point: by the time it is open, the game already knows what
# is being marched on. This recipe reads it and presses «Марш» with the squad the key
# named, so the macro replaces the MOUSE and nothing else.
#
#   run march_selected_squad                  -- squad 1
#   run march_selected_squad {"squad": 3}     -- squad 3
#
#   * `squad` — the 1/2/3/4 the player sees in the dispatch panel.
#
# Nothing about the target is passed in and nothing about it is guessed: `targetType`,
# `targetPoint`, `targetUuid`, `targetServerId`, `timeIndex` and `autoBackHome` are all
# read off the open screen's own controller, which is why one recipe covers every kind
# of target the game has. The write-up, and how those names were found without opening
# a window, is docs/research/march-hotkeys.md.
#
# THE LAUNCH IS THE GAME'S OWN BUTTON — `Ctrl:OnCheckTime(formation, nil)` — not a
# hand-made send. That matters: the game's pre-checks for that target type still run
# (stamina, the power warning, the rally cap, the transport warning), the screen still
# closes itself, and a target this squad may not be sent at is still refused by the
# game rather than by this file. `march_repeat_last.md` is the other half, and it is
# the one that sends directly, because by then there is no screen left to press.
#
# Nothing is claimed from a press that returned cleanly. The run ends as a FAILURE,
# naming the step, when no squad screen is open (nothing was chosen), when the game has
# no squad with that number, when the screen's target cannot be read, and when
# everything was pressed and no march appeared.
#
# **A march that does not appear can also mean the client has stopped talking to the
# server** — a stranded client answers every getter with yesterday's numbers and returns
# `true` from every send (docs/research/server-link-status.md). The panel's status strip
# is what says that, and it is worth a glance before believing the failure below.

ARGS squad = 1

# --- 1. Park which squad, then read the screen ------------------------------------
# `TAP` carries no arguments, so the squad travels as a parked value the presses read
# back — the same trick create_rally.md and join_rally.md use. The target does NOT
# travel this way: it is read off the screen the person's own click opened.
LUA DataCenter.__lw_macro = {squad = {squad}}

TAP macro_arm

READ_LUA (function() local p = DataCenter.__lw_macro or {} if tonumber(p.screen) ~= 1 then return 0 end if p.target == nil or p.type == nil then return -2 end if p.formation == nil then return -1 end return 1 end)() INTO armed

IF armed == 0
    FAIL "no target is chosen — the squad-selection screen is not open"
IF armed == -1
    FAIL "there is no such squad"
IF armed == -2
    FAIL "the squad screen is open but its target could not be read"

# --- 2. Press «Марш» with that squad ----------------------------------------------
# The pick and the launch, exactly as a finger makes them. The screen closes itself.
TAP macro_launch

# --- 3. Let the GAME say whether a march went out ---------------------------------
# The proof is a march of ours appearing, not the press returning cleanly: the server
# owns that list, and a squad the game refuses to send leaves it where it was.
READ_LUA ((function() local ok, n = pcall(function() local om = DataCenter.WorldMarchDataManager:GetOwnerMarches() local c = 0 if om then local e = om:GetEnumerator() while e:MoveNext() do c = c + 1 end end return c end) if not ok then return -1 end return n end)()) - ((DataCenter.__lw_macro or {}).before or 0) INTO sent

WHILE sent < 1 LIMIT 8
    WAIT 0.5
    READ_LUA ((function() local ok, n = pcall(function() local om = DataCenter.WorldMarchDataManager:GetOwnerMarches() local c = 0 if om then local e = om:GetEnumerator() while e:MoveNext() do c = c + 1 end end return c end) if not ok then return -1 end return n end)()) - ((DataCenter.__lw_macro or {}).before or 0) INTO sent

IF sent < 1
    FAIL "the launch was pressed and no march went out — the game refused it, or the client is no longer talking to the server"

LOG "The squad is on its way"

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

# --- 1. Park which squad, then send ------------------------------------------------
# `TAP` carries no arguments, so the squad travels as a parked value the press reads
# back — the same trick create_rally.md and join_rally.md use. The target does NOT
# travel this way: it is read off the screen the person's own click opened.
#
# TWO CALLS INTO THE GAME AND NOT FOUR (#1290). The reading, the check and the press
# used to be three statements with a 0.2 s pause in the middle, and a call costs ~90 ms
# — a fifth of a second of a key press spent going back and forth over a screen that a
# person's own click had put up and could close at any moment. `macro_send` does all
# three inside one chunk, on the game's own thread, in one frame.
LUA DataCenter.__lw_macro = {squad = {squad}}

TAP macro_send

# --- 2. What it decided, in its own words ------------------------------------------
# Read back AFTER the press rather than asked before it: the answer costs a round trip
# either way, and this way the round trip is not standing between the key and the march.
READ_LUA (tonumber((DataCenter.__lw_macro or {}).result) or 0) INTO sent_ok

IF sent_ok == 0
    FAIL "no target is chosen — the squad-selection screen is not open"
IF sent_ok == -1
    FAIL "there is no such squad"
IF sent_ok == -2
    FAIL "the squad screen is open but its target could not be read"
IF sent_ok == -3
    FAIL "the squad screen refused the launch"

# --- 3. Let the GAME say whether a march went out ---------------------------------
# The proof is a march of ours appearing, not the press returning cleanly: the server
# owns that list, and a squad the game refuses to send leaves it where it was.
#
# The poll is short and repeated rather than long and patient: the claim on the client
# is held until this loop ends, so every tenth of a second spent here is a tenth in
# which the NEXT key press answers «занят».
READ_LUA ((function() local ok, n = pcall(function() local om = DataCenter.WorldMarchDataManager:GetOwnerMarches() local c = 0 if om then local e = om:GetEnumerator() while e:MoveNext() do c = c + 1 end end return c end) if not ok then return -1 end return n end)()) - ((DataCenter.__lw_macro or {}).before or 0) INTO sent

WHILE sent < 1 LIMIT 12
    WAIT 0.2
    READ_LUA ((function() local ok, n = pcall(function() local om = DataCenter.WorldMarchDataManager:GetOwnerMarches() local c = 0 if om then local e = om:GetEnumerator() while e:MoveNext() do c = c + 1 end end return c end) if not ok then return -1 end return n end)()) - ((DataCenter.__lw_macro or {}).before or 0) INTO sent

IF sent < 1
    FAIL "the launch was pressed and no march went out — the game refused it, or the client is no longer talking to the server"

LOG "The squad is on its way"

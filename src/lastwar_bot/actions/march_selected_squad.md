# Send a chosen squad at the target the person last chose — clicked, or on screen.
# ru: Отправить выбранный отряд на цель, по которой человек кликнул (или на цель открытого экрана).
#
# The keyboard macro behind keys 1..4 (#1283, made early and windowless in #1328). A
# person clicks a target on the map — a monster, a mine, another player's base, a squad
# out gathering — and the game opens that point's popup. **That click is the whole
# input.** The macro sends the squad the key names straight at it: the «Атака» button is
# not pressed, the squad-selection screen is never opened, and nothing is guessed.
#
#   run march_selected_squad                          -- squad 1
#   run march_selected_squad {"squad": 3}             -- squad 3
#   run march_selected_squad {"squad": 2, "stale": 60}
#
#   * `squad` — the 1/2/3/4 the player sees in the dispatch panel;
#   * `stale` — how many seconds a clicked target stays the macro's target. 180 by
#     default: long enough to click, look, and press; short enough that a target chosen
#     before lunch is not marched on by accident.
#
# WHERE THE TARGET COMES FROM, and it is the game that answers both times:
#
#   * **the click.** The popup's own controller carries `pointId`, `uuid`, `serverId`,
#     `ownerUid` and the point's kind, and a watcher inside the game VM copies them the
#     moment the popup fills itself in — so the pin is made by the CLICK, not by anything
#     the panel later goes looking for. Which march that becomes is read out of the
#     game's own enums by name: a monster the game says can be soloed is attacked, a
#     resource tile is gathered, somebody else's base is attacked, somebody else's
#     gathering squad is attacked. Anything else is refused BY NAME below;
#   * **the squad screen**, if the person opened one anyway. Then it wins — its target is
#     fresher and carries a rally's wait slot, which a tile does not — and this recipe
#     behaves exactly as it did in #1283, pressing the screen's own «Марш».
#
# The watcher is armed by the press itself, so a client that restarted between two presses
# is watched again at no extra call into the game. The one press that can find nothing is
# the FIRST after such a restart with the popup already closed — and even that usually
# works, because a popup still standing open is read on the spot instead.
#
# A CLICK IS NOT SPENT BY A PRESS. Three keys in a row put three squads on one target,
# which is what clicking a boss is usually for. What ends a pin is time (`stale`), the
# scene (walking off the world map), and the account — never the panel's bookkeeping.
#
# AND A POINT THE BOT OPENED IS NOT A TARGET ANYBODY CHOSE. The panel opens world-point
# popups of its own all day — a rally hunt, a treasure sweep, a jump to coordinates — and
# the first pin ever caught live was one of those rather than a finger. Those are refused,
# not marched on: whose stack opened the popup is something the game can be asked.
#
# Nothing is claimed from a send that returned cleanly: the run ends as a FAILURE, naming
# the reason, when nothing was clicked, when the squad does not exist, when the pin has
# gone stale, when the point is a kind this macro does not march on, when the monster is
# rally-only, and when everything went out and no march appeared.
#
# **A march that does not appear can also mean the client has stopped talking to the
# server** — a stranded client answers every getter with yesterday's numbers and returns
# `true` from every send (docs/research/server-link-status.md). The panel's status strip
# is what says that, and it is worth a glance before believing the failure below.
#
# docs/research/march-hotkeys.md is the write-up.

ARGS squad = 1
ARGS stale = 180

# --- 1. Park what the press cannot carry, then send --------------------------------
# `TAP` carries no arguments, so the squad and the staleness window travel as parked
# values the press reads back — the same trick create_rally.md and join_rally.md use.
# The TARGET does not travel this way, either time: it is the person's own click, or the
# screen their own click opened.
#
# ONE CALL INTO THE GAME AND NOT FOUR (#1290). Arming the watcher, finding the screen,
# reading the pin, checking it, resolving the squad and sending all happen inside one
# chunk, on the game's own thread, in one frame — a call costs ~90 ms and a key press
# ought to feel like a mouse click.
LUA DataCenter.__lw_macro = {squad = {squad}, stale = {stale}}

TAP macro_send

# --- 2. What it decided, in its own words ------------------------------------------
# Read back AFTER the press rather than asked before it: the answer costs a round trip
# either way, and this way the round trip is not standing between the key and the march.
READ_LUA (tonumber((DataCenter.__lw_macro or {}).result) or 0) INTO sent_ok

IF sent_ok == 0
    FAIL "nothing is chosen — click the target on the map first"
IF sent_ok == -1
    FAIL "there is no such squad"
IF sent_ok == -2
    FAIL "the squad screen is open but its target could not be read"
IF sent_ok == -3
    FAIL "the squad screen refused the launch"
IF sent_ok == -4
    FAIL "the target was clicked too long ago — click it again"
IF sent_ok == -5
    FAIL "the macro does not march on that kind of point — click a monster, a mine, a base or a gathering squad"
IF sent_ok == -6
    FAIL "that monster cannot be soloed — a banner is raised through its own screen, not by this key"
IF sent_ok == -7
    FAIL "not on the world map any more — the clicked target no longer counts"
IF sent_ok == -8
    FAIL "the target was clicked by another account — click it again on this one"
IF sent_ok == -9
    FAIL "that point was opened by the panel, not clicked by you — click the target yourself"

# --- 3. Let the GAME say whether a march went out ---------------------------------
# The proof is a march of ours appearing, not the send returning cleanly: the server owns
# that list, and a squad the game refuses to send leaves it where it was.
#
# The poll is short and repeated rather than long and patient: the claim on the client is
# held until this loop ends, so every tenth of a second spent here is a tenth in which the
# NEXT key press answers «занят». The direct send is scheduled a third of a second out (a
# cold send is created and dropped), which this window covers.
READ_LUA ((function() local ok, n = pcall(function() local om = DataCenter.WorldMarchDataManager:GetOwnerMarches() local c = 0 if om then local e = om:GetEnumerator() while e:MoveNext() do c = c + 1 end end return c end) if not ok then return -1 end return n end)()) - ((DataCenter.__lw_macro or {}).before or 0) INTO sent

WHILE sent < 1 LIMIT 14
    WAIT 0.2
    READ_LUA ((function() local ok, n = pcall(function() local om = DataCenter.WorldMarchDataManager:GetOwnerMarches() local c = 0 if om then local e = om:GetEnumerator() while e:MoveNext() do c = c + 1 end end return c end) if not ok then return -1 end return n end)()) - ((DataCenter.__lw_macro or {}).before or 0) INTO sent

IF sent < 1
    FAIL "the launch was pressed and no march went out — the game refused it, or the client is no longer talking to the server"

# The target is named only once the march is real, and only then is the round trip free:
# the squad is already on its way while this is read.
READ_LUA tostring((DataCenter.__lw_macro or {}).desc or '-') INTO target

LOG "The squad is on its way to {target}"

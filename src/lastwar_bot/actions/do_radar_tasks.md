# Radar: run the errands that need no march and claim what the board has finished.
# ru: Радар: выполнить задания, которым не нужен марш, и забрать готовые.
#
# The radar hands out a board of small errands. Two of the three things a person does on
# it are messages and nothing else, so this recipe does them with no window open and no
# camera moving:
#
#   * «Быстро выполнить» — every «help an alliancemate» errand set running at once. Each
#     takes `Mathf.Min(3000, <distance> * 100)` ms, so three seconds covers the longest
#     of them, and then each is reported finished. **The client only reports the finish
#     while the radar window is open** — its own progress slider is what fires it — so a
#     headless run has to send the finish itself, or the errands sit half-done until
#     somebody opens the board.
#   * «Получить все» — one `receive.detect.event.reward` per finished errand. It is not
#     a command: the in-game button is a client-side loop over exactly that message
#     (eleven in a row in the recording, matching a red badge of 11), which is why
#     claiming all of them is `xall` of claiming one.
#
# The third — «Перейти» on a camp or a mine — puts the target on the map and is then an
# ORDINARY MARCH, with a squad, a travel time and a fight at the end. It is not part of
# this recipe and must not be: a march is somebody's squad for ten minutes, and a recipe
# called «do the radar» has no business spending one without being asked.
#
# ## The ceiling, and why «claim everything» is not always right
#
# Claiming is what scores on the duel day the radar belongs to, so a week's worth of
# errands claimed on that ONE day is worth far more than the same errands claimed as
# they ripen. That is what `claim = 0` is for: leave them standing.
#
# But the board has a CEILING (`GetMaxDetectNum`, 40 on the account this was read on),
# and a full board stops handing out new errands. So hoarding pays only while there is
# room: `keep_free` is how many slots the hoard is told to leave, and when the board
# gets that close to its ceiling the recipe claims the oldest finished ones — just
# enough — rather than letting the radar go quiet.
#
# **Which weekday that duel day is, is NOT decided here.** The caller says `claim = 1`
# or `claim = 0`; a timer, a plan or a person owns the calendar. A recipe that guessed
# the day would be wrong for every account whose week is not this one's.
#
# The wire, the manager, the two enums and the live readings are in
# docs/research/radar.md. Recording: results/traces/20260815_080129_радар_trace.log.

ARGS help = 1
ARGS claim = 1
ARGS keep_free = 5

# The board first: everything below names a uuid the server has just told us about.
TAP radar_read_board

READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local n = 0 for _, e in pairs(rawget(M, 'events') or {}) do local t = rawget(e, 'template') if rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH and t and rawget(t, 'type') == DetectEventType.HELPER and not rawget(e, 'isFrozen') then n = n + 1 end end return n end)() INTO helpable
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetFinishedDetectEventNum() end) return (ok and tonumber(n)) or 0 end)() INTO finished
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() INTO onboard
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetMaxDetectNum() end) return (ok and tonumber(n)) or 0 end)() INTO ceiling

LOG "radar: {finished} finished, {helpable} ally errand(s) ready to run, {onboard} of {ceiling} slots used"

# The ally errands. Pressing with nothing eligible sends nothing and says so, so this
# needs no gate of its own — the button IS the gate.
IF help == 0
    LOG "radar: leaving the ally errands alone (help = 0)"
ELSE
    TAP radar_help_start
    WAIT 3.2
    TAP radar_help_end
    WAIT 1.0
    TAP radar_read_board

READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetFinishedDetectEventNum() end) return (ok and tonumber(n)) or 0 end)() INTO finished
READ_LUA (function() local a = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetMaxDetectNum() end) return (ok and tonumber(n)) or 0 end)() local b = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() local d = a - b if d < 0 then d = 0 end return d end)() INTO free

IF claim == 0
    LOG "radar: hoarding {finished} finished errand(s) for the duel day, {free} slot(s) free"
ELSE
    LOG "radar: claiming {finished} finished errand(s)"

# Claim everything, or — while hoarding — only enough to keep the board off its ceiling.
IF claim == 1
    TAP radar_claim xall
ELSE
    WHILE free < keep_free LIMIT 60
        IF finished == 0
            LOG "radar: the board is near its ceiling and nothing on it is finished — the room is not mine to make"
            STOP
        TAP radar_claim
        READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetFinishedDetectEventNum() end) return (ok and tonumber(n)) or 0 end)() INTO finished
        READ_LUA (function() local a = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetMaxDetectNum() end) return (ok and tonumber(n)) or 0 end)() local b = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() local d = a - b if d < 0 then d = 0 end return d end)() INTO free

READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetFinishedDetectEventNum() end) return (ok and tonumber(n)) or 0 end)() INTO finished
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() INTO onboard

LOG "radar: done — {finished} finished errand(s) left standing, {onboard} of {ceiling} slots used"

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
#     somebody opens the board. Proven live on 2026-08-17: six pending, and the board's
#     finished count went from 1 to 7 across the three seconds.
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
# ## The duel day, and how this decides which one today is
#
# Claiming is what scores on the duel day the radar belongs to, so a week's worth of
# errands claimed on that ONE day is worth far more than the same errands claimed as they
# ripen. But the board has a CEILING (`GetMaxDetectNum`), and a full board stops handing
# out new errands — so hoarding pays only while there is room. `keep_free` is how many
# slots the hoard is told to leave.
#
# Two ways to say which mode today is, and the recipe prefers the second:
#
#   * `claim = 1 / 0` — say it outright. This is what a caller with its own calendar
#     does, and it is the default.
#   * `duel_day = 1…7` — name the weekday the radar scores on, and the recipe asks the
#     GAME which weekday it is on right now. Not the PC: the game's day turns at the
#     server's own midnight, so a machine west of it spends hours calling the game's
#     Tuesday «Monday». Given a `duel_day`, that comparison decides and `claim` is
#     ignored.
#
# **`duel_day` is a fact about the player's week and not one this recipe can read.** The
# client was searched for it (`docs/research/radar.md`, «what is NOT known»): the duel is
# open and in progress and says so, but WHICH activity scores on WHICH day is not exposed
# to a headless read — it arrives with the duel screen's own fetch. So the calendar is
# given, and what is derived from the game is only the weekday it is compared against.
#
# The wire, the manager, the two enums and the live readings are in
# docs/research/radar.md. Recording: results/traces/20260815_080129_радар_trace.log.

ARGS help = 1
ARGS claim = 1
ARGS duel_day = 0
ARGS keep_free = 5

# The board first: everything below names a uuid the server has just told us about.
TAP radar_read_board

READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local n = 0 for _, e in pairs(rawget(M, 'events') or {}) do local t = rawget(e, 'template') if rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH and t and rawget(t, 'type') == DetectEventType.HELPER and not rawget(e, 'isFrozen') then n = n + 1 end end return n end)() INTO helpable
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetFinishedDetectEventNum() end) return (ok and tonumber(n)) or 0 end)() INTO finished
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() INTO onboard
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetMaxDetectNum() end) return (ok and tonumber(n)) or 0 end)() INTO ceiling

# Which weekday the GAME is on — 1 = Monday … 7 = Sunday, 0 when it could not be asked.
READ_LUA (function() local ok, ms = pcall(function() return UITimeManager:GetInstance():GetTomorrowZero() end) if not ok or not tonumber(ms) then return 0 end local start = math.floor(tonumber(ms) / 1000) - 86400 local w = tonumber(os.date('!%w', start)) if w == nil then return 0 end if w == 0 then return 7 end return w end)() INTO gameday

# And the decision itself: the calendar when one was given, the plain answer otherwise.
# A `duel_day` the game could not be compared against (weekday 0 — no client to ask)
# falls back to `claim` rather than guessing that today is not the day.
READ_LUA (function() local duel = {duel_day} local plain = {claim} local today = (function() local ok, ms = pcall(function() return UITimeManager:GetInstance():GetTomorrowZero() end) if not ok or not tonumber(ms) then return 0 end local start = math.floor(tonumber(ms) / 1000) - 86400 local w = tonumber(os.date('!%w', start)) if w == nil then return 0 end if w == 0 then return 7 end return w end)() if duel < 1 or today < 1 then return plain end if today == duel then return 1 end return 0 end)() INTO do_claim

LOG "radar: {finished} finished, {helpable} ally errand(s) ready to run, {onboard} of {ceiling} slots used; game weekday {gameday}, duel day {duel_day}"

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

IF do_claim == 0
    LOG "radar: hoarding {finished} finished errand(s) for the duel day, {free} slot(s) free"
ELSE
    LOG "radar: claiming {finished} finished errand(s)"

# Claim everything, or — while hoarding — only enough to keep the board off its ceiling.
IF do_claim == 1
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
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local n = 0 for _, e in pairs(rawget(M, 'events') or {}) do local t = rawget(e, 'template') if rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH and t and rawget(t, 'type') == DetectEventType.HELPER and not rawget(e, 'isFrozen') then n = n + 1 end end return n end)() INTO helpable

LOG "radar: done — {finished} finished left standing, {helpable} ally errand(s) still runnable, {onboard} of {ceiling} slots used"

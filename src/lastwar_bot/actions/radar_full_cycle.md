# Radar: the whole board, in the mode today calls for.
# ru: Радар: вся доска, в том режиме, который нужен сегодня.
#
# ONE ability for a clock to call, so the clock does not have to think. It does every part
# of the radar this repository has proven, in the order the parts depend on each other:
#
#   1. put every errand that has no tile yet onto the map;
#   2. march a free squad at each errand that needs one — a mine, an enemy base;
#   3. run the errands that need no march at all (helping an alliancemate), which take
#      three seconds each and whose FINISH the client only sends while its own window is
#      open, so this sends it;
#   4. claim — all of it, or just enough, which is the whole of the difference between the
#      two modes.
#
# ## The two modes, and the day that chooses between them
#
# **A duel day discharges.** Claiming is what scores, so on the radar's own duel days a
# week's worth of held errands is worth far more than the same errands claimed as they
# ripened. Every ripe errand is taken.
#
# **Any other day hoards — but never into the ceiling.** The board holds only so many
# errands at once, and a board with no free place has nowhere to put the next one: the
# day's allowance goes undrawn and the refresh takes back what was never drawn. So hoarding
# means «do the work, hold the reward, and keep `keep_free` places open», not «touch
# nothing».
#
# `duel_days` is the weekdays the radar scores on, 1 = Monday … 7 = Sunday, and it defaults
# to what the player named: Monday, Wednesday, Friday, Saturday. It is an ARGUMENT and not
# a constant, because the duel's plan differs by season and by warzone — this default is one
# player's week, not everybody's.
#
# **The weekday is the GAME'S.** `UITimeManager:GetTomorrowZero()` minus a day is the start
# of the day now running; the server's midnight is 02:00 UTC on this warzone, so a machine
# west of it spends hours calling the game's Tuesday «Monday» and would hoard through the
# very day it meant to spend.
#
# ## Nothing about one player's radar is written down here
#
# The capacity and the allowance both come from the client's own `detect_level` row, looked
# up under the profile's own radar level:
#
#   detect_show_num  — how many errands the board holds AT ONCE (the capacity)
#   detect_max_num   — how many it hands out in a DAY (the allowance)
#
# Level 16 gives 12 and 40; level 1 gives 5 and 25. **So a second account has different
# numbers for both**, and neither may be a constant — which is exactly the mistake that was
# made once already, when `GetMaxDetectNum()` was taken for the capacity and turned out to
# be the allowance counting down.
#
# The wire, the enums, the march pairs and every measurement are in
# `docs/research/radar.md`.

ARGS duel_days = [1, 3, 5, 6]
ARGS force = 0
ARGS keep_free = 3
ARGS help = 1
ARGS march = 1

# --- which day is it, and what does that make today ------------------------
READ_LUA (function() local ok, ms = pcall(function() return UITimeManager:GetInstance():GetTomorrowZero() end) if not ok or not tonumber(ms) then return 0 end local start = math.floor(tonumber(ms) / 1000) - 86400 local w = tonumber(os.date('!%w', start)) if w == nil then return 0 end if w == 0 then return 7 end return w end)() INTO gameday
READ_LUA (function() local days = { {duel_days} } local today = (function() local ok, ms = pcall(function() return UITimeManager:GetInstance():GetTomorrowZero() end) if not ok or not tonumber(ms) then return 0 end local start = math.floor(tonumber(ms) / 1000) - 86400 local w = tonumber(os.date('!%w', start)) if w == nil then return 0 end if w == 0 then return 7 end return w end)() for _, d in ipairs(days) do if tonumber(d) == today then return 1 end end return 0 end)() INTO is_duel
# `force`: 0 asks the day, 1 always discharges, 2 always hoards. A weekday the client could
# not answer (0) falls back to HOARDING — the cautious half, because a wrongly spent duel
# day cannot be got back and a wrongly held one can.
READ_LUA (function() local f = {force} if f == 1 then return 1 end if f == 2 then return 0 end local days = { {duel_days} } local today = (function() local ok, ms = pcall(function() return UITimeManager:GetInstance():GetTomorrowZero() end) if not ok or not tonumber(ms) then return 0 end local start = math.floor(tonumber(ms) / 1000) - 86400 local w = tonumber(os.date('!%w', start)) if w == nil then return 0 end if w == 0 then return 7 end return w end)() if today < 1 then return 0 end for _, d in ipairs(days) do if tonumber(d) == today then return 1 end end return 0 end)() INTO discharge

# --- what this profile's radar actually is ----------------------------------
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, v = pcall(function() return M:GetDetectInfoLevel() end) return (ok and tonumber(v)) or 0 end)() INTO level
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local lvl = 0 pcall(function() lvl = tonumber(M:GetDetectInfoLevel()) or 0 end) if lvl < 1 then return 0 end local inst = LocalController.instance() pcall(function() inst:getTable('detect_level') end) local row = nil pcall(function() row = inst:getLine('detect_level', lvl) end) if type(row) ~= 'table' then return 0 end local md = nil pcall(function() md = row:getMetaData() end) if type(md) ~= 'table' then return 0 end local col = nil pcall(function() local e = md['detect_show_num'] col = e and e[1] end) if col == nil then return 0 end local ld = rawget(row, '_lineData') or {} return tonumber(ld[col]) or tonumber(ld[tostring(col)]) or tonumber(ld[tonumber(col) or -1]) or 0 end)() INTO capacity
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local lvl = 0 pcall(function() lvl = tonumber(M:GetDetectInfoLevel()) or 0 end) if lvl < 1 then return 0 end local inst = LocalController.instance() pcall(function() inst:getTable('detect_level') end) local row = nil pcall(function() row = inst:getLine('detect_level', lvl) end) if type(row) ~= 'table' then return 0 end local md = nil pcall(function() md = row:getMetaData() end) if type(md) ~= 'table' then return 0 end local col = nil pcall(function() local e = md['detect_max_num'] col = e and e[1] end) if col == nil then return 0 end local ld = rawget(row, '_lineData') or {} return tonumber(ld[col]) or tonumber(ld[tostring(col)]) or tonumber(ld[tonumber(col) or -1]) or 0 end)() INTO quota
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetMaxDetectNum() end) return (ok and tonumber(n)) or 0 end)() INTO left
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() INTO onboard
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetFinishedDetectEventNum() end) return (ok and tonumber(n)) or 0 end)() INTO finished
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local n = 0 for _, e in pairs(rawget(M, 'events') or {}) do local t = rawget(e, 'template') if rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH and t and rawget(t, 'type') == DetectEventType.HELPER and not rawget(e, 'isFrozen') then n = n + 1 end end return n end)() INTO helpable

LOG "radar: level {level} — the board holds {capacity} and the day hands out {quota}; {onboard} on it now, {finished} ripe, {helpable} runnable on the spot, {left} of the day's allowance left; game weekday {gameday}, duel days {duel_days}"

IF discharge == 1
    LOG "radar: today is a duel day — everything ripe is taken"
ELSE
    LOG "radar: today is not a duel day — holding the rewards, keeping {keep_free} place(s) open"

# --- the world, and the squads, before anything is sent ---------------------
GAME WORLD
WAIT 1.5
CALL fill_empty_squads
TAP radar_read_board

# --- the errands that need a squad ------------------------------------------
IF march == 0
    LOG "radar: not spending squads this run (march = 0)"
ELSE
    TAP radar_place_points
    WAIT 1.5
    TAP radar_read_board
    TAP radar_arm_squads
    TAP radar_march xall

# --- the errands that need none ---------------------------------------------
IF help == 0
    LOG "radar: leaving the ally errands alone (help = 0)"
ELSE
    TAP radar_help_start
    WAIT 3.2
    TAP radar_help_end
    WAIT 1.0

TAP radar_read_board
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetFinishedDetectEventNum() end) return (ok and tonumber(n)) or 0 end)() INTO finished
READ_LUA (function() local cap = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local lvl = 0 pcall(function() lvl = tonumber(M:GetDetectInfoLevel()) or 0 end) if lvl < 1 then return 0 end local inst = LocalController.instance() pcall(function() inst:getTable('detect_level') end) local row = nil pcall(function() row = inst:getLine('detect_level', lvl) end) if type(row) ~= 'table' then return 0 end local md = nil pcall(function() md = row:getMetaData() end) if type(md) ~= 'table' then return 0 end local col = nil pcall(function() local e = md['detect_show_num'] col = e and e[1] end) if col == nil then return 0 end local ld = rawget(row, '_lineData') or {} return tonumber(ld[col]) or tonumber(ld[tostring(col)]) or tonumber(ld[tonumber(col) or -1]) or 0 end)() local now = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() local d = cap - now if d < 0 then d = 0 end return d end)() INTO free

# --- the claim, which is where the two modes part ---------------------------
IF discharge == 1
    TAP radar_claim xall
ELSE
    LUA DataCenter.__lw_radar_hoard_from = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)()
    READ_LUA 0 INTO opened
    WHILE opened < {keep_free} LIMIT 60
        IF finished == 0
            LOG "radar: {free} place(s) open and nothing ripe to spend — the room is not mine to make"
            STOP
        IF left == 0
            LOG "radar: the day has nothing left to hand out — no reason to make room, holding all {finished}"
            STOP
        TAP radar_claim
        READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetFinishedDetectEventNum() end) return (ok and tonumber(n)) or 0 end)() INTO finished
        READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetMaxDetectNum() end) return (ok and tonumber(n)) or 0 end)() INTO left
        READ_LUA (function() local cap = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local lvl = 0 pcall(function() lvl = tonumber(M:GetDetectInfoLevel()) or 0 end) if lvl < 1 then return 0 end local inst = LocalController.instance() pcall(function() inst:getTable('detect_level') end) local row = nil pcall(function() row = inst:getLine('detect_level', lvl) end) if type(row) ~= 'table' then return 0 end local md = nil pcall(function() md = row:getMetaData() end) if type(md) ~= 'table' then return 0 end local col = nil pcall(function() local e = md['detect_show_num'] col = e and e[1] end) if col == nil then return 0 end local ld = rawget(row, '_lineData') or {} return tonumber(ld[col]) or tonumber(ld[tostring(col)]) or tonumber(ld[tonumber(col) or -1]) or 0 end)() local now = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() local d = cap - now if d < 0 then d = 0 end return d end)() INTO free
        READ_LUA (function() local now = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() local from = tonumber(DataCenter.__lw_radar_hoard_from) or now local d = from - now if d < 0 then d = 0 end return d end)() INTO opened

# --- what the game says about it afterwards ---------------------------------
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() INTO onboard
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetFinishedDetectEventNum() end) return (ok and tonumber(n)) or 0 end)() INTO finished
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local n = 0 for _, e in pairs(rawget(M, 'events') or {}) do local t = rawget(e, 'template') if rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH and t and rawget(t, 'type') == DetectEventType.HELPER and not rawget(e, 'isFrozen') then n = n + 1 end end return n end)() INTO helpable
READ_LUA (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetMaxDetectNum() end) return (ok and tonumber(n)) or 0 end)() INTO left
READ_LUA (function() local cap = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local lvl = 0 pcall(function() lvl = tonumber(M:GetDetectInfoLevel()) or 0 end) if lvl < 1 then return 0 end local inst = LocalController.instance() pcall(function() inst:getTable('detect_level') end) local row = nil pcall(function() row = inst:getLine('detect_level', lvl) end) if type(row) ~= 'table' then return 0 end local md = nil pcall(function() md = row:getMetaData() end) if type(md) ~= 'table' then return 0 end local col = nil pcall(function() local e = md['detect_show_num'] col = e and e[1] end) if col == nil then return 0 end local ld = rawget(row, '_lineData') or {} return tonumber(ld[col]) or tonumber(ld[tostring(col)]) or tonumber(ld[tonumber(col) or -1]) or 0 end)() local now = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() local d = cap - now if d < 0 then d = 0 end return d end)() INTO free
READ_LUA (function() local ok, n = pcall(function() local om = DataCenter.WorldMarchDataManager:GetOwnerMarches() local c = 0 if om then local e = om:GetEnumerator() while e:MoveNext() do c = c + 1 end end return c end) if not ok then return -1 end return n end)() INTO marches

LOG "radar: done — {onboard} of {capacity} on the board, {finished} ripe held, {helpable} still runnable, {free} place(s) open, {left} of the day left, {marches} march(es) of ours out"

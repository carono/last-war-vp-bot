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

# --- has this refresh window already been worked? ---------------------------
# ONE PASS PER REFRESH, and the moment is the GAME'S (#2390). The operator's rule, in
# their words: «Радар обновляется раз в 4 часа, один раз выполнили задания и все, ждем
# обновления». The board draws its day's allowance down to nothing and refills at
# `detectInfo.nextRefreshTime`; nothing on the wire announces that (docs/research/radar.md),
# so this reads the client's own copy of the stamp — no request, no window — and stops
# dead when the stamp is the one the last finished cycle parked. Measured before it
# existed: this errand held the client 1344 s out of 44 minutes, 51 % of the wall clock,
# running the whole board over and over inside one window.
#
# A cycle that was cut short parks nothing, so the next tick works the window again.
READ_LUA (function() local now = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local di = nil pcall(function() di = M.detectInfo end) if di == nil then pcall(function() di = M:GetDetectInfo() end) end if di == nil then return 0 end return math.floor(tonumber(rawget(di, 'nextRefreshTime')) or 0) end)() if now <= 0 then return 0 end local seen = tonumber(DataCenter.__lw_radar_done_for) or 0 if seen == now then return 1 end return 0 end)() INTO window_done
IF window_done == 1
    LOG "radar: this refresh window is already worked — nothing until the game refills the board"
    STOP

# --- which day is it, and what does that make today ------------------------
# ONE CALL, NOT ONE PER QUESTION (#2404). A read is a thread hijack into the
# client at half a second a time whatever it asks, and the machine can make about
# 1.4 of them a second in total (`docs/research/link-contention.md`), so a run of
# readings one statement at a time is that many seconds of everybody's budget for
# answers the game could hand over together. What each one is, and why it is asked,
# is on the comments and LOG lines that follow.
# `force`: 0 asks the day, 1 always discharges, 2 always hoards. A weekday the client could
# not answer (0) falls back to HOARDING — the cautious half, because a wrongly spent duel
# day cannot be got back and a wrongly held one can.
# --- what this profile's radar actually is ----------------------------------
READ_LUA (function() local __v0 = (function() local ok, ms = pcall(function() return UITimeManager:GetInstance():GetTomorrowZero() end) if not ok or not tonumber(ms) then return 0 end local start = math.floor(tonumber(ms) / 1000) - 86400 local w = tonumber(os.date('!%w', start)) if w == nil then return 0 end if w == 0 then return 7 end return w end)() local __v1 = (function() local days = { {duel_days} } local today = (function() local ok, ms = pcall(function() return UITimeManager:GetInstance():GetTomorrowZero() end) if not ok or not tonumber(ms) then return 0 end local start = math.floor(tonumber(ms) / 1000) - 86400 local w = tonumber(os.date('!%w', start)) if w == nil then return 0 end if w == 0 then return 7 end return w end)() for _, d in ipairs(days) do if tonumber(d) == today then return 1 end end return 0 end)() local __v2 = (function() local f = {force} if f == 1 then return 1 end if f == 2 then return 0 end local days = { {duel_days} } local today = (function() local ok, ms = pcall(function() return UITimeManager:GetInstance():GetTomorrowZero() end) if not ok or not tonumber(ms) then return 0 end local start = math.floor(tonumber(ms) / 1000) - 86400 local w = tonumber(os.date('!%w', start)) if w == nil then return 0 end if w == 0 then return 7 end return w end)() if today < 1 then return 0 end for _, d in ipairs(days) do if tonumber(d) == today then return 1 end end return 0 end)() local __v3 = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, v = pcall(function() return M:GetDetectInfoLevel() end) return (ok and tonumber(v)) or 0 end)() local __v4 = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local lvl = 0 pcall(function() lvl = tonumber(M:GetDetectInfoLevel()) or 0 end) if lvl < 1 then return 0 end local inst = LocalController.instance() pcall(function() inst:getTable('detect_level') end) local row = nil pcall(function() row = inst:getLine('detect_level', lvl) end) if type(row) ~= 'table' then return 0 end local md = nil pcall(function() md = row:getMetaData() end) if type(md) ~= 'table' then return 0 end local col = nil pcall(function() local e = md['detect_show_num'] col = e and e[1] end) if col == nil then return 0 end local ld = rawget(row, '_lineData') or {} return tonumber(ld[col]) or tonumber(ld[tostring(col)]) or tonumber(ld[tonumber(col) or -1]) or 0 end)() local __v5 = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local lvl = 0 pcall(function() lvl = tonumber(M:GetDetectInfoLevel()) or 0 end) if lvl < 1 then return 0 end local inst = LocalController.instance() pcall(function() inst:getTable('detect_level') end) local row = nil pcall(function() row = inst:getLine('detect_level', lvl) end) if type(row) ~= 'table' then return 0 end local md = nil pcall(function() md = row:getMetaData() end) if type(md) ~= 'table' then return 0 end local col = nil pcall(function() local e = md['detect_max_num'] col = e and e[1] end) if col == nil then return 0 end local ld = rawget(row, '_lineData') or {} return tonumber(ld[col]) or tonumber(ld[tostring(col)]) or tonumber(ld[tonumber(col) or -1]) or 0 end)() local __v6 = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetMaxDetectNum() end) return (ok and tonumber(n)) or 0 end)() local __v7 = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() local __v8 = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetFinishedDetectEventNum() end) return (ok and tonumber(n)) or 0 end)() local __v9 = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local n = 0 for _, e in pairs(rawget(M, 'events') or {}) do local t = rawget(e, 'template') if rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH and t and rawget(t, 'type') == DetectEventType.HELPER and not rawget(e, 'isFrozen') then n = n + 1 end end return n end)() return __v0, __v1, __v2, __v3, __v4, __v5, __v6, __v7, __v8, __v9 end)() INTO gameday, is_duel, discharge, level, capacity, quota, left, onboard, finished, helpable

LOG "radar: level {level} — the board holds {capacity} and the day hands out {quota}; {onboard} on it now, {finished} ripe, {helpable} runnable on the spot, {left} of the day's allowance left; game weekday {gameday}, duel days {duel_days}"

IF discharge == 1
    LOG "radar: today is a duel day — everything ripe is taken"
ELSE
    LOG "radar: today is not a duel day — holding the rewards, keeping {keep_free} place(s) open"

# --- is there anything a trip could change? ---------------------------------
# THE DAY'S OWN RULE, AND IT IS CHECKED BEFORE THE JOURNEY (#2390). The operator's, in
# their words: «лимит выполненных достигнут — к радару не ходим». Until this, a spent day
# still cost the whole trip — the world scene, the squads refilled, the board read three
# times, the points placed — and only at the claim did the cycle find out the day had
# nothing left to hand out. Measured live on 2026-09-03: `quota=40 left=0 board=12 ripe=12
# helpable=0 free_places=0`, a board on which not one of those steps could have changed
# anything.
#
# On a DUEL day it never applies: the ripe errands are the whole point of that day, so the
# cycle goes whatever the board looks like.
READ_LUA (function() local left = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetMaxDetectNum() end) return (ok and tonumber(n)) or 0 end)() if left > 0 then return 0 end if (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local n = 0 for _, e in pairs(rawget(M, 'events') or {}) do local t = rawget(e, 'template') if rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH and t and rawget(t, 'type') == DetectEventType.HELPER and not rawget(e, 'isFrozen') then n = n + 1 end end return n end)() > 0 then return 0 end if (function() local M = DataCenter.RadarCenterDataManager local map = {[DetectEventType.GATHER_RESOURCE] = MarchTargetType.COLLECT, [DetectEventType.DetectEventPickGarbage] = MarchTargetType.PICK_GARBAGE, [DetectEventType.FAKE_PLAYER] = MarchTargetType.ATTACK_CITY, [DetectEventType.TREASURE] = MarchTargetType.DETECT_TREASURE} local done = DataCenter.__lw_radar_marched or {} local list = {} if M then for _, e in pairs(rawget(M, 'events') or {}) do local t = rawget(e, 'template') local kind = t and rawget(t, 'type') local u = rawget(e, 'uuid') if kind ~= nil and kind ~= DetectEventType.HELPER and rawget(e, 'state') ~= DetectEventState.DETECT_EVENT_STATE_FINISHED and rawget(e, 'state') ~= DetectEventState.DETECT_EVENT_STATE_REWARDED and not rawget(e, 'isFrozen') and not done[tostring(u)] then list[#list + 1] = {uuid = u, kind = kind, pid = rawget(e, 'pointId'), state = rawget(e, 'state'), target = map[kind]} end end end local n = 0 for _, r in ipairs(list) do if r.target ~= nil and r.state == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH then n = n + 1 end end return n end)() > 0 then return 0 end return 1 end)() INTO idle
IF discharge == 1
    READ_LUA (0) INTO idle
IF idle == 1
    LOG "radar: the day has nothing left to hand out, nothing to help and nothing to march — not going to the board at all"
    TAP radar_mark_window
    STOP

# --- the world, and the squads, before anything is sent ---------------------
GAME WORLD
WAIT 1.5
CALL fill_empty_squads

# The day's FREE march energy, before anything is sent (#2390). The radar's own errands
# spend it — an errand on a fake player is an ordinary attack march — and the operator's
# order for the three sources is «сначала бесплатные, потом за 300 алмазов и только в конце
# из запасов». It is one reading on a day the claim has already been taken, and it is here
# rather than at the top of the file on purpose: everything above this line can end the run
# without touching the game, so a cycle that has nothing to do still asks the game nothing.
CALL claim_free_stamina

# …AND THEN THE REFILL FOR DIAMONDS, which is the second of the three (#2390). The price
# is not readable anywhere in the client, so the recipe buys only while the game says no
# refill has been bought today — the cheap one by the operator's ladder — prices it off
# the diamond purse afterwards, and refuses to buy again if that came out over its
# ceiling. On a day already bought it is one reading and sends nothing.
CALL buy_stamina_refill

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
# ONE CALL, NOT ONE PER QUESTION (#2404). A read is a thread hijack into the
# client at half a second a time whatever it asks, and the machine can make about
# 1.4 of them a second in total (`docs/research/link-contention.md`), so a run of
# readings one statement at a time is that many seconds of everybody's budget for
# answers the game could hand over together. What each one is, and why it is asked,
# is on the comments and LOG lines that follow.
# --- the claim, which is where the two modes part ---------------------------
READ_LUA (function() local __v0 = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetFinishedDetectEventNum() end) return (ok and tonumber(n)) or 0 end)() local __v1 = (function() local cap = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local lvl = 0 pcall(function() lvl = tonumber(M:GetDetectInfoLevel()) or 0 end) if lvl < 1 then return 0 end local inst = LocalController.instance() pcall(function() inst:getTable('detect_level') end) local row = nil pcall(function() row = inst:getLine('detect_level', lvl) end) if type(row) ~= 'table' then return 0 end local md = nil pcall(function() md = row:getMetaData() end) if type(md) ~= 'table' then return 0 end local col = nil pcall(function() local e = md['detect_show_num'] col = e and e[1] end) if col == nil then return 0 end local ld = rawget(row, '_lineData') or {} return tonumber(ld[col]) or tonumber(ld[tostring(col)]) or tonumber(ld[tonumber(col) or -1]) or 0 end)() local now = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() local d = cap - now if d < 0 then d = 0 end return d end)() return __v0, __v1 end)() INTO finished, free

# --- the claim, which is where the two modes part ---------------------------
IF discharge == 1
    TAP radar_claim xall
ELSE
    # WHAT BOUNDS THE CLAIM ON AN ORDINARY DAY IS THE DAY ITSELF (#2390). The operator's
    # rule: «собрать столько, чтобы к серверному сбросу не упереться в лимит, дальше только
    # выполнять». A claim frees a place and the game refills it out of the day's allowance,
    # so the number of places worth opening is never more than what the day has left —
    # `keep_free` is the wish and `left` is the ceiling, and the loop below stops on
    # whichever comes first. After that the cycle only PERFORMS: the marches and the ally
    # errands above have already gone out, and the ripe ones are held for the duel day.
    LOG "radar: an ordinary day — the day has {left} left to hand out, so at most that many place(s) are opened, wanting {keep_free}"
    LUA DataCenter.__lw_radar_hoard_from = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)()
    READ_LUA 0 INTO opened
    WHILE opened < {keep_free} LIMIT 60
        IF finished == 0
            LOG "radar: {free} place(s) open and nothing ripe to spend — the room is not mine to make"
            TAP radar_mark_window
            STOP
        IF left == 0
            LOG "radar: the day has nothing left to hand out — no reason to make room, holding all {finished}"
            TAP radar_mark_window
            STOP
        TAP radar_claim
        # ONE CALL, NOT ONE PER QUESTION (#2404). A read is a thread hijack into the
        # client at half a second a time whatever it asks, and the machine can make about
        # 1.4 of them a second in total (`docs/research/link-contention.md`), so a run of
        # readings one statement at a time is that many seconds of everybody's budget for
        # answers the game could hand over together. What each one is, and why it is asked,
        # is on the comments and LOG lines that follow.
# --- what the game says about it afterwards ---------------------------------
        READ_LUA (function() local __v0 = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetFinishedDetectEventNum() end) return (ok and tonumber(n)) or 0 end)() local __v1 = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetMaxDetectNum() end) return (ok and tonumber(n)) or 0 end)() local __v2 = (function() local cap = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local lvl = 0 pcall(function() lvl = tonumber(M:GetDetectInfoLevel()) or 0 end) if lvl < 1 then return 0 end local inst = LocalController.instance() pcall(function() inst:getTable('detect_level') end) local row = nil pcall(function() row = inst:getLine('detect_level', lvl) end) if type(row) ~= 'table' then return 0 end local md = nil pcall(function() md = row:getMetaData() end) if type(md) ~= 'table' then return 0 end local col = nil pcall(function() local e = md['detect_show_num'] col = e and e[1] end) if col == nil then return 0 end local ld = rawget(row, '_lineData') or {} return tonumber(ld[col]) or tonumber(ld[tostring(col)]) or tonumber(ld[tonumber(col) or -1]) or 0 end)() local now = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() local d = cap - now if d < 0 then d = 0 end return d end)() local __v3 = (function() local now = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() local from = tonumber(DataCenter.__lw_radar_hoard_from) or now local d = from - now if d < 0 then d = 0 end return d end)() return __v0, __v1, __v2, __v3 end)() INTO finished, left, free, opened

# --- what the game says about it afterwards ---------------------------------
# ONE CALL, NOT ONE PER QUESTION (#2404). A read is a thread hijack into the
# client at half a second a time whatever it asks, and the machine can make about
# 1.4 of them a second in total (`docs/research/link-contention.md`), so a run of
# readings one statement at a time is that many seconds of everybody's budget for
# answers the game could hand over together. What each one is, and why it is asked,
# is on the comments and LOG lines that follow.
READ_LUA (function() local __v0 = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() local __v1 = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetFinishedDetectEventNum() end) return (ok and tonumber(n)) or 0 end)() local __v2 = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local n = 0 for _, e in pairs(rawget(M, 'events') or {}) do local t = rawget(e, 'template') if rawget(e, 'state') == DetectEventState.DETECT_EVENT_STATE_NOT_FINISH and t and rawget(t, 'type') == DetectEventType.HELPER and not rawget(e, 'isFrozen') then n = n + 1 end end return n end)() local __v3 = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetMaxDetectNum() end) return (ok and tonumber(n)) or 0 end)() local __v4 = (function() local cap = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local lvl = 0 pcall(function() lvl = tonumber(M:GetDetectInfoLevel()) or 0 end) if lvl < 1 then return 0 end local inst = LocalController.instance() pcall(function() inst:getTable('detect_level') end) local row = nil pcall(function() row = inst:getLine('detect_level', lvl) end) if type(row) ~= 'table' then return 0 end local md = nil pcall(function() md = row:getMetaData() end) if type(md) ~= 'table' then return 0 end local col = nil pcall(function() local e = md['detect_show_num'] col = e and e[1] end) if col == nil then return 0 end local ld = rawget(row, '_lineData') or {} return tonumber(ld[col]) or tonumber(ld[tostring(col)]) or tonumber(ld[tonumber(col) or -1]) or 0 end)() local now = (function() local M = DataCenter.RadarCenterDataManager if not M then return 0 end local ok, n = pcall(function() return M:GetDetectEventCount() end) return (ok and tonumber(n)) or 0 end)() local d = cap - now if d < 0 then d = 0 end return d end)() local __v5 = (function() local ok, n = pcall(function() local om = DataCenter.WorldMarchDataManager:GetOwnerMarches() local c = 0 if om then local e = om:GetEnumerator() while e:MoveNext() do c = c + 1 end end return c end) if not ok then return -1 end return n end)() return __v0, __v1, __v2, __v3, __v4, __v5 end)() INTO onboard, finished, helpable, left, free, marches

TAP radar_mark_window

LOG "radar: done — {onboard} of {capacity} on the board, {finished} ripe held, {helpable} still runnable, {free} place(s) open, {left} of the day left, {marches} march(es) of ours out"

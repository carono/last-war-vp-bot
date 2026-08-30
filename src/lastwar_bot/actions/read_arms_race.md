# Read «Гонка вооружений» — the phase running now, and the whole day's calendar.
# ru: Прочитать «Гонку вооружений» — текущую фазу и календарь дня.
#
# A READ: it presses nothing, opens nothing and spends nothing, so it is safe beside
# anything. It does send ONE message — `activity.hero.calender`, the game's own get,
# the one the client fires when a person opens the event's calendar — because without
# it the calendar is EMPTY and every phase but the current one is unknown.
#
# That ask is the whole point of the first step. `calenderDataDict` starts `{}` on a
# panel-driven client and nothing fills it by itself: a panel that never asked would
# draw «фаза одна, что дальше — неизвестно» over an event whose whole week is already
# decided, and look entirely reasonable doing it. The current phase's own numbers
# (`dataDict`) DO arrive unasked, which is exactly why the gap is easy to miss.
#
# ## What the event is
#
# Six phases a day, four hours each, on a schedule the server has fixed a week ahead.
# Each phase names ONE kind of progress and pays points for it; five kinds exist:
#
#   120000  «Улучшение героя»          hero advancement — recruiting, hero XP
#   120001  «Строительство Города»     city building — construction speed-ups
#   120002  «Прогресс юнита»           unit progression — training soldiers
#   120003  «Исследование технологий»  tech research — research speed-ups
#   120004  «Улучшение Дрона»          drone boost — drone data, rallies, stamina
#
# A phase pays THREE boxes at three point totals, and the DAY pays three more for
# finishing one, two and three phases. That is the «3 сундука за задание и 3 за три
# задания» the person described.
#
# ## The answer
#
# Two variables. `arms` is the phase running now, as `key=value` pairs separated by
# spaces, and **`-` means the game would not answer** — a manager not loaded, a client
# at the login screen, an account that has not unlocked the event. A dash is «nobody
# knows» and must never be drawn as a zero.
#
#     open=1 aid=29 day=7 stage=1 event=120000 name=2000601 sc=800 rules=122,121,103
#     t1=2000 t2=4000 t3=12000 g1=0 g2=0 g3=0 until=8134 done=1 d1=1 d2=0 d3=0
#
#   open     1 while a phase of the event is running right now.
#   aid      the activity's own id, read rather than written down: it is 29 on this
#            account today and there is no promise it is 29 on another.
#   day      which day of the event's week (1..7) the server says it is.
#   stage    which of the day's six phases is running, ZERO-based — the same numbering
#            the server's own `claimStatus` keys (`<day>_<stage>`) use.
#   event    the phase's kind, one of the five ids above. This is what decides WHICH
#            errand the panel plays; the name beside it is only for reading.
#   name     the game's own text key for that kind.
#   sc       points scored in THIS phase. The server owns it, so it counts progress
#            made from anywhere — this panel, the phone, or the person playing.
#   rules    the score rules in force this phase, as ids of the game's `score` table.
#            What each one pays is the game's business and not written down here.
#   t1..t3   the three point totals that pay a box, smallest first.
#   g1..g3   1 once that box has been taken.
#   until    seconds left in the phase. This is what a schedule books its next turn on.
#   done     how many of the day's phases have been finished so far.
#   d1..d3   1 once the day's first, second and third box has been taken.
#
# `arms_day` is the day's calendar, one record per phase, oldest first:
#
#     0:120004:1788055200:1788069600 1:120000:1788069600:1788084000 …
#
# — the phase's zero-based number, its kind, and the server seconds it runs between.
# Empty when the calendar did not arrive.
#
# Who reads it: the panel's «События» tab and the arms-race errand. The reverse
# engineering is docs/research/arms-race.md.

# --- ask for the calendar, then read ----------------------------------------------
LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.ActivityHeroCalender) end)

READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local ok, n = pcall(function() local c = 0 for _ in pairs(M.calenderDataDict or {}) do c = c + 1 end return c end) if not ok then return 0 end return n end)() INTO arms_cal_in

WHILE arms_cal_in == 0 LIMIT 5
    WAIT 0.6
    READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local ok, n = pcall(function() local c = 0 for _ in pairs(M.calenderDataDict or {}) do c = c + 1 end return c end) if not ok then return 0 end return n end)() INTO arms_cal_in

READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local out = {} local function put(k, v) if v == nil then out[#out+1] = k .. '=-' else out[#out+1] = k .. '=' .. tostring(v) end end local aid, d = nil, nil pcall(function() for k, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then aid, d = k, v break end end end) if d == nil then return 'open=0 aid=- day=- stage=- event=- name=- sc=- rules=- t1=- t2=- t3=- g1=- g2=- g3=- until=- done=- d1=- d2=- d3=-' end local function num(v) local n = tonumber(v) if n == nil then return nil end return math.floor(n) end local now = 0 pcall(function() now = math.floor(tonumber(UITimeManager:GetInstance():GetServerSeconds()) or 0) end) local day, stage = num(d.curDay), num(d.curStage) local ends = num(d.stage_end_time) local left = nil if ends ~= nil and now > 0 then left = ends - now if left < 0 then left = 0 end end local name = nil pcall(function() local c = (M.calenderDataDict or {})[aid] local arr = c and c.dayArr and c.dayArr[day] and c.dayArr[day].eventArr if arr and stage ~= nil then local e = arr[stage + 1] if e then name = num(e.name) end end end) local rules = {} pcall(function() for _, v in ipairs(d.scoresList or {}) do rules[#rules+1] = tostring(num(v)) end end) local function box(i, from) local r = nil pcall(function() local b = (d[from] or {})[i] if b then r = b end end) return r end put('open', (left ~= nil and left > 0) and 1 or 0) put('aid', num(aid)) put('day', day) put('stage', stage) put('event', num(d.event_id)) put('name', name) put('sc', num(d.sc) or 0) put('rules', #rules > 0 and table.concat(rules, ',') or nil) for i = 1, 3 do local b = box(i, 'score_rewards') put('t' .. i, b and num(b.target) or nil) end for i = 1, 3 do local b = box(i, 'score_rewards') put('g' .. i, b and (num(b.receive) or 0) or nil) end put('until', left) local done = nil pcall(function() local c = 0 for k, v in pairs(d.claimStatus or {}) do if (num(v) or 0) > 0 then c = c + 1 end end done = c end) put('done', done) for i = 1, 3 do local b = box(i, 'day_rewards') put('d' .. i, b and (num(b.receive) or 0) or nil) end return table.concat(out, ' ') end)() INTO arms

READ_LUA (function() local M = DataCenter.ActivityPersonalArmsDataManager local out = {} pcall(function() local aid, d = nil, nil for k, v in pairs(M.dataDict or {}) do if type(v) == 'table' and v.event_id ~= nil then aid, d = k, v break end end if d == nil then return end local c = (M.calenderDataDict or {})[aid] local day = math.floor(tonumber(d.curDay) or 0) local arr = c and c.dayArr and c.dayArr[day] and c.dayArr[day].eventArr if not arr then return end for i = 1, 6 do local e = arr[i] if e then out[#out+1] = (i - 1) .. ':' .. math.floor(tonumber(e.eventId) or 0) .. ':' .. math.floor(tonumber(e.startTime) or 0) .. ':' .. math.floor(tonumber(e.endTime) or 0) end end end) return table.concat(out, ' ') end)() INTO arms_day

LOG "arms: {arms}"
LOG "arms day: {arms_day}"

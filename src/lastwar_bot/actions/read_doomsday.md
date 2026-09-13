# Read «Судный день»: is it running, until when, and how many of its gifts are still owed.
# ru: Чтение «Судного дня»: идёт ли событие, до какого времени и сколько подарков не забрано.
#
# HEADLESS. No window is opened and nothing is tapped. ONE question goes on the wire —
# `activity.doomsday.quest.info` — and only while the event is ON, because the achievement
# list is the one part of the event the client does not keep: the manager holds the id,
# the end and the red dot and nothing else (`docs/research/doomsday.md`). The reply is
# caught by a wrapper around the manager's own `OnGetQuestInfo`, installed once per client
# and left in place, so a second reading costs the same one question.
#
# WHAT IT LEAVES BEHIND, for the collector and for the card that draws it:
#
#   doomsday   — the whole reading as one line, which is what the panel keeps
#   open       — 1 while the event is on, 0 when it is not
#   quests     — how many achievements the event has
#   taken      — how many of them have already paid out
#   pending    — how many have not, which is the most gifts one run could take
#   ends       — when the current run is over, in seconds
#   starts     — when it began, in seconds
#
# STATE IS THE GAME'S OWN WORD, not ours: a quest the payload marks `state=1` is exactly
# one the event's own window draws as `hasRecieved=true` — measured against the live
# window's VOs, 38 of 41 agreeing in both places at once (`docs/research/doomsday.md`).

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = {known = 0, open = 0, starts = 0, ends = 0, quests = 0, taken = 0, pending = 0, red = 0} DataCenter.__lw_doomsday = M local D = DataCenter.LWDoomsdayManager if type(D) ~= 'table' or D.activityId == nil then return 0 end M.known = 1 pcall(function() local C = getmetatable(D).__index if not C.__lw_doom_ear then C.__lw_doom_ear = true local f = C.OnGetQuestInfo if type(f) == 'function' then C.OnGetQuestInfo = function(self, ...) DataCenter.__lw_doom_quests = ({...})[1] return f(self, ...) end end end end) local now = 0 pcall(function() now = num(UITimeManager.Instance:GetServerTime()) end) if now == 0 then now = os.time() * 1000 end M.ends = math.floor(num(D.activityEndTime) / 1000) pcall(function() for _, list in pairs(DataCenter.ActivityListDataManager or {}) do if type(list) == 'table' then for _, row in pairs(list) do if type(row) == 'table' and tostring(row.id) == tostring(D.activityId) then M.starts = math.floor(num(row.startTime) / 1000) if num(row.endTime) > 0 then M.ends = math.floor(num(row.endTime) / 1000) end end end end end end) local on = false pcall(function() on = (D:IsOpen() == true) end) if on and num(D.activityEndTime) > 0 and now > num(D.activityEndTime) then on = false end if on then M.open = 1 end pcall(function() M.red = num(D:GetRedDotCount()) end) if M.open == 1 then pcall(function() SFSNetwork.SendMessage(MsgDefines.ActivityDoomsdayQuestInfo, D.activityId) end) end return M.open end)() INTO open

IF open == 1
    WAIT 3
    READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = DataCenter.__lw_doomsday or {} local a = DataCenter.__lw_doom_quests local list = ((a or {}).quest_info or {}).doomsday_quests or {} local total, got = 0, 0 for _, q in pairs(list) do total = total + 1 if num(q.state) == 1 then got = got + 1 end end M.quests = total M.taken = got M.pending = total - got return total end)() INTO quests

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = DataCenter.__lw_doomsday or {} return 'known=' .. num(M.known) .. ' open=' .. num(M.open) .. ' starts=' .. num(M.starts) .. ' ends=' .. num(M.ends) .. ' quests=' .. num(M.quests) .. ' taken=' .. num(M.taken) .. ' pending=' .. num(M.pending) .. ' red=' .. num(M.red) end)() INTO doomsday

READ_LUA (function() local M = DataCenter.__lw_doomsday or {} return math.floor(M.quests or 0) end)() INTO quests
READ_LUA (function() local M = DataCenter.__lw_doomsday or {} return math.floor(M.taken or 0) end)() INTO taken
READ_LUA (function() local M = DataCenter.__lw_doomsday or {} return math.floor(M.pending or 0) end)() INTO pending
READ_LUA (function() local M = DataCenter.__lw_doomsday or {} return math.floor(M.ends or 0) end)() INTO ends
READ_LUA (function() local M = DataCenter.__lw_doomsday or {} return math.floor(M.starts or 0) end)() INTO starts

LOG "Судный день: {doomsday}"

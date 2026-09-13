# Take every gift «Судный день» already owes — the achievement rewards of the event.
# ru: Забрать все подарки «Судного дня» — награды достижений события.
#
# HEADLESS and FREE: nothing is opened, nothing is bought, nothing is spent. Each gift is
# one `activity.doomsday.quest.reward` carrying the achievement's own uuid — the shape the
# event's own window uses, read off the message class rather than guessed
# (`docs/research/doomsday.md`).
#
# WHAT ONE RUN DOES:
#
#   1. reads the event (`CALL read_doomsday`) and stops at once when it is not on — the
#      event is a Sunday's, and outside it there is nothing to press;
#   2. asks for every achievement the game has not paid out yet. An achievement that is
#      not earned is answered with an EMPTY reward list and nothing else happens — the
#      server refuses by paying nothing, measured live, so nothing here is spent on a
#      guess;
#   3. reads the event back and reports what MOVED — how many achievements went from
#      «not paid» to «paid» — rather than how many requests were sent.
#
# NOTHING WAITING IS A SUCCESS, not a failure: the ordinary state of the event is «all
# claimed so far», and a run that finds it says so and ends well.

ARGS cap = 60

CALL read_doomsday

IF open == 0
    LOG "Судный день: событие не идёт — ничего не нажато"
    STOP

IF pending == 0
    LOG "Судный день: все подарки уже забраны — нечего забирать"
    STOP

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = DataCenter.__lw_doomsday or {} DataCenter.__lw_doom_taken0 = num(M.taken) local a = DataCenter.__lw_doom_quests local list = ((a or {}).quest_info or {}).doomsday_quests or {} local cap = num({cap}) if cap <= 0 then cap = 60 end local sent = 0 for _, q in pairs(list) do if sent < cap and num(q.state) ~= 1 and q.uuid ~= nil then local ok = pcall(function() SFSNetwork.SendMessage(MsgDefines.ActivityDoomsdayQuestReward, tostring(q.uuid)) end) if ok then sent = sent + 1 end end end return sent end)() INTO asked

LOG "Судный день: запрошено подарков — {asked}"
WAIT 3

CALL read_doomsday

READ_LUA (function() local function num(v) local ok, n = pcall(function() return v + 0 end) if ok and n ~= nil then return math.floor(n) end return 0 end local M = DataCenter.__lw_doomsday or {} return num(M.taken) - num(DataCenter.__lw_doom_taken0) end)() INTO got

LOG "Судный день: забрано подарков {got}, ещё не выдано {pending} из {quests}"

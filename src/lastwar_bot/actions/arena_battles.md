# Play whichever arena event the building is running today.
# ru: Сыграть то событие арены, которое сегодня идёт в здании.
#
# The arena building runs ONE event at a time and swaps it when the old one ends: the 3v3
# challenge («Испытание», five wins out of thirty attempts) and «Арена Шторма» (five
# battles, and a box paid on the count rather than the wins). They are one row on the
# board and one press, because from the person's side they are one building — so this
# recipe asks which of them is open and plays that one.
#
# Neither event is decided here: each recipe keeps its own gates, spends its own attempts
# and stops on its own shut door. What this file adds is the choice between them, and it
# is made from the two managers' own windows rather than from a date written down.

READ_LUA (function() local ok, out = pcall(function() local now = 0 pcall(function() now = math.floor((UITimeManager:GetInstance():GetServerSeconds() or 0) + 0) end) if now <= 0 then return -1 end local function open(a, z) a = math.floor((a or 0) / 1000) z = math.floor((z or 0) / 1000) if a <= 0 or z <= 0 then return false end return now >= a and now <= z end local three = false pcall(function() local m = DataCenter.LW3V3ArenaManager three = open(m.startTime, m.endTime) end) if three then return 1 end local storm = false pcall(function() local m = DataCenter.NewPeakArenaManager storm = open(m.info.startTime, m.info.endTime) end) if storm then return 2 end return 0 end) if not ok then return -1 end return out end)() INTO arena_which

IF arena_which < 0
    FAIL "neither arena could be asked which one is running — the client is not answering"

IF arena_which == 1
    LOG "the arena building is running the 3v3 challenge"
    CALL arena_3v3_battles

IF arena_which == 2
    LOG "the arena building is running the storm arena"
    CALL storm_arena_battles

IF arena_which == 0
    LOG "the arena building has no event running right now"
    STOP "no arena event is open"

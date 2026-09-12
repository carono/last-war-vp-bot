# Raise the 24-hour peace shield over the base — one shield, on its own day, once.
# ru: Поставить 24-часовой щит на базу — один щит, в свой день, один раз.
#
# AN IRREVERSIBLE SPEND. A shield leaves the bag and does not come back, so every gate
# is here rather than in whatever pressed this (`CLAUDE.md`, «a primitive presses one
# thing»), and the errand that plays it ships SWITCHED OFF — the person turns it on
# themselves. What is about to be spent is said in the log BEFORE anything goes on the
# wire, and out of how many the bag holds.
#
# THE THREE GATES, in the order they are asked:
#
#   1. **The day.** `weekday` is the GAME's weekday this shield belongs to, 1 = Monday …
#      7 = Sunday; `0` means «any day», which is what a person's own press passes. The
#      game's day, never this machine's: the warzone's turns at its own 00:00 (about
#      02:00 UTC), so for two hours out of every twenty-four the PC has already moved on
#      while the game is still handing out yesterday. The arithmetic is done on the
#      MIDDLE of the current game day — `GetTomorrowZero()` says when the day ENDS, and
#      the end of a Saturday is a Sunday timestamp.
#   2. **A shield already up.** The game's own `IsInShield()`. A second shield over a
#      live one is exactly the waste this errand exists not to commit, and nothing in
#      the panel can hand the item back afterwards.
#   3. **The bag.** No 24-hour shield in it is a plain answer with a reason, never a
#      silent no-op — «щита нет в сумке» is something a person can act on.
#
# It ENDS, it does not STOP: every «nothing to do» is an `IF` that runs out of lines, so
# a caller that CALLed this keeps going (docs/dsl.md).
ARGS weekday = 6

READ_LUA (function() local want={weekday} if want == 0 then return 1 end local z=0 pcall(function() z=math.floor(UITimeManager:GetInstance():GetTomorrowZero()+0) end) if z<=0 then return -1 end local d=((math.floor((z-43200000)/86400000)+3)%7)+1 if d==want then return 1 end return 0 end)() INTO day_ok

IF day_ok == -1
    LOG "the client cannot say what day the game is on — the shield is left alone"
IF day_ok == 0
    LOG "the game is not on day {weekday} today — nothing is spent"
IF day_ok == 1
    READ_LUA (function() local M=DataCenter.DefenceWallDataManager local up=0 if M~=nil then pcall(function() if M:IsInShield() then up=1 end end) end return up end)(), (function() local n=0 pcall(function() for _,v in pairs(DataCenter.ItemData.ItemInfos or {}) do if math.floor((v.itemId or 0)+0)==200411 then n=n+math.floor((v.count or 0)+0) end end end) return n end)(), (function() local M=DataCenter.DefenceWallDataManager local e=0 if M~=nil then pcall(function() e=math.floor((M:GetDefenceWallData().protectEndTime or 0)+0) end) end return e end)() INTO up, have, ends
    IF up == 1
        LOG "the base is already protected until {ends} on the game's clock — a second shield would be thrown away, so nothing is spent"
    IF up == 0
        IF have == 0
            LOG "no 24-hour shield in the bag — nothing to raise"
        IF have > 0
            LOG "raising a 24-hour shield — one of {have} in the bag is about to be spent"
            TAP use_peace_shield_24h
            WAIT 1.5
            READ_LUA (function() local r=DataCenter.__lw_shield or {} return math.floor((r.used or 0)+0) end)(), (function() local M=DataCenter.DefenceWallDataManager local u=0 if M~=nil then pcall(function() if M:IsInShield() then u=1 end end) end return u end)(), (function() local M=DataCenter.DefenceWallDataManager local e=0 if M~=nil then pcall(function() e=math.floor((M:GetDefenceWallData().protectEndTime or 0)+0) end) end return e end)() INTO used, up_now, ends_now
            IF used == 0
                READ_LUA (function() local r=DataCenter.__lw_shield or {} return tostring(r.why or '') end)() INTO why
                LOG "the shield was not sent — {why}"
            IF used == 1
                LOG "shield sent — the game now says protected={up_now}, until {ends_now} on its own clock"

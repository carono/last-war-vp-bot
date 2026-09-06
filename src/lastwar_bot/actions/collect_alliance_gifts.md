# Claim the alliance gifts — by the list, not blind, and without opening a window.
# ru: Подарки альянса — по списку, а не вслепую, и без открытия окна.
#
# WHAT IT DOES. Asks the server for the alliance gift list, counts what is really
# waiting in each of the two chests — ordinary and premium — claims only a chest
# that has something in it, and reads the counters again to say what was actually
# taken. Nothing is opened, nothing is pressed and nothing is spent.
#
# WHY IT WAS REWRITTEN (#2588). It used to open the game's «Подарки альянса»
# section and press its two «collect all» buttons, because
# `AllianceGiftDataManager.giftInfoList` is empty on a panel-driven client and the
# window is what fills it. So the panel collected blind on a clock: it could not
# say whether there was anything to take, the card could show no number, and a run
# that claimed nothing looked exactly like a run that claimed forty-five gifts.
#
# The list is not window-bound — it is UNASKED. One message fills it:
#
#     SFSNetwork.SendMessage(MsgDefines.AllianceGiftList, 0, 1000)   -- alliance.reward.list
#
# the game's own get, the one the client fires when a person opens the section
# (`index = 0`, `len = 1000`). Same shape as the arms-race calendar
# (`read_arms_race.md`) and the chat history: read once, then the server's own
# `push.alliance.reward.new` keeps the counts up to date — no clock, no polling.
#
# And the CLAIM needs no window either, once the list is in:
#
#     SFSNetwork.SendMessage(MsgDefines.AllianceReceiveAllGift, <type>)  -- alliance.reward.allreceive
#
# type 1 = ordinary gifts, type 2 = premium/privilege ones. Live: six ordinary
# gifts claimed with no window open at all — the manager's per-type unclaimed count
# went 6 -> 0 and `GetGiftNum()` 52 -> 46 within three seconds. (The old note said a
# headless claim «sent nothing»; it was sent over an EMPTY list, which the client
# swallows.)
#
# THE SUCCESS TEST IS THE COUNTER, never «the message left». The run reads the
# unclaimed counts before and after and reports the difference; a claim that changed
# nothing while gifts were waiting FAILS in words instead of writing a cheerful line
# into the log (#2585).
#
# IT TOUCHES NO WINDOW, so it says `SHARE` and steps aside for anything that wants the
# client — the old version could not, because it opened the gift section and pressed into
# it. The two waits here are waits for a SERVER REPLY, and a reply lands in the client's
# own data whether or not we are holding the link, so the seven seconds this run lasts
# cost the rest of the panel nothing. The value it parks (`__lw_algift_before`) is read
# only by this run and nothing else in the bot claims a gift, so a neighbour cutting in
# between the park and the claim cannot make the count lie.
#
# The reverse engineering is docs/research/alliance-gift-collection.md.

SHARE

# Two readings, defined once so the steps below are one call each. `seen` counts the
# gift records the client holds AT ALL — a claimed gift stays in the list, so
# `seen == 0` means «nobody has asked the server yet», which is not the same as «no
# gifts» and must never be collected over. `left(ty)` counts the unclaimed ones of a
# kind, 0 for both kinds together.
LUA pcall(function() local D=DataCenter D.__lw_algift_seen=function() local M=D.AllianceGiftDataManager if M==nil then return -1 end local n=0 for _,t in ipairs({1,2}) do local ok,l=pcall(function() return M:GetGiftInfoList(t) end) if ok and type(l)=='table' then for _ in pairs(l) do n=n+1 end end end return n end D.__lw_algift_left=function(ty) local M=D.AllianceGiftDataManager if M==nil then return -1 end local n=0 for _,t in ipairs({1,2}) do if ty==0 or ty==t then local ok,l=pcall(function() return M:GetGiftInfoList(t) end) if ok and type(l)=='table' then for _,g in pairs(l) do if (tonumber(g.receiveState) or -1)==0 then n=n+1 end end end end end return n end end)

READ_LUA (DataCenter.__lw_algift_seen and DataCenter.__lw_algift_seen() or -1) INTO gifts_seen

IF gifts_seen == -1
    FAIL "the alliance gift manager is not there — the client has not finished loading"

IF gifts_seen == 0
    LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.AllianceGiftList, 0, 1000) end)
    WAIT 1.5

WHILE gifts_seen == 0 LIMIT 5
    READ_LUA DataCenter.__lw_algift_seen() INTO gifts_seen
    WAIT 0.8

IF gifts_seen == 0
    FAIL "the alliance gift list did not arrive — nothing came back to alliance.reward.list"

READ_LUA DataCenter.__lw_algift_left(1), DataCenter.__lw_algift_left(2) INTO gift_ord, gift_prem
LUA pcall(function() DataCenter.__lw_algift_before = DataCenter.__lw_algift_left(0) end)
LOG "alliance gifts: waiting — ordinary {gift_ord}, premium {gift_prem}"

# --- claim only a chest that has something in it -----------------------------------
IF gift_ord > 0
    LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.AllianceReceiveAllGift, 1) end)
    WAIT 2.0

IF gift_prem > 0
    LUA pcall(function() SFSNetwork.SendMessage(MsgDefines.AllianceReceiveAllGift, 2) end)
    WAIT 2.0

# --- what actually changed ----------------------------------------------------------
READ_LUA DataCenter.__lw_algift_left(0) INTO gift_left
READ_LUA ((tonumber(DataCenter.__lw_algift_before) or 0) - DataCenter.__lw_algift_left(0)) INTO gift_took
READ_LUA (((tonumber(DataCenter.__lw_algift_before) or 0) > 0 and (tonumber(DataCenter.__lw_algift_before) or 0) == DataCenter.__lw_algift_left(0)) and 1 or 0) INTO gift_stuck

IF gift_stuck == 1
    FAIL "the alliance gifts were not claimed — {gift_ord} ordinary and {gift_prem} premium are still waiting"

# `gift_took` is also what the panel writes into the day's book — «собрано сегодня» on
# the card is GIFTS and not runs (`panel/runtime/gift_book.py`).
LOG "alliance gifts: took {gift_took}, still waiting {gift_left}"

# Open the explorer's chests in the mobile squad's window, while the keys last.
# ru: Открыть сундуки исследователя в окне мобильного отряда, пока хватает ключей.
#
# The chests live on the same window as our secret tasks, and the keys that open them
# («Ключ исследователя», item 771001) are paid out by our OWN finished tasks and by
# nothing else. So there is no clock worth putting in front of this: the purse cannot
# grow while nobody claims a task, and it grows the instant somebody does — which is why
# the errand is meant to be woken by the claim rather than by a period
# (docs/research/explorer-treasure.md).
#
# WHAT IT SPENDS. One chest costs whatever the game says it costs — five keys, read off
# `GetTreasureOpenNeedItemNum` rather than written down here — and nothing else: no
# diamonds, no daily attempt, no march. The keys have no other use in the game, so an
# unopened chest is a key doing nothing.
#
# NO WINDOW IS OPENED. The send is `hero.dispatch.explorer.treasure.open` and it carries
# no parameter at all, so the whole ability is one message per chest and the player's
# view is never taken away.

# HOW MANY KEYS TO LEAVE IN THE PURSE. 0 spends them all. A person saving up towards the
# guaranteed reward can park a floor here and a scheduled run will never go below it.
ARGS keep = 0

# THE MOST CHESTS TO OPEN IN ONE RUN. 0 = every one the keys will buy.
ARGS max = 0

# 1. Park the floor, so the press itself refuses rather than trusting the loop.
LUA DataCenter.__lw_explorer_keep = math.floor(tonumber('{keep}') or 0)

# 2. …and turn «at most N chests» into the same floor, which is the only gate the press
#    reads. A run that may open three of the seven the purse holds keeps back the keys of
#    the other four.
LUA (function() local m=math.floor(tonumber('{max}') or 0) if m<=0 then return end local M=DataCenter.ExplorerTreasureManager if M==nil then return end local have,need=0,0 pcall(function() have=math.floor((M:GetTreasureHaveItemNum() or 0)+0) end) pcall(function() need=math.floor((M:GetTreasureOpenNeedItemNum() or 0)+0) end) if need<=0 then need=math.floor(tonumber(M.treasureNeedNum) or 0) end if need<=0 then return end local floor=have-m*need local keep=math.floor(tonumber(DataCenter.__lw_explorer_keep) or 0) if floor>keep then DataCenter.__lw_explorer_keep=floor end end)()

# 3. Read the state before anything is spent, and say it out loud — a run that opens
#    nothing must say why, not go quiet.
READ_LUA (function() local M=DataCenter and DataCenter.ExplorerTreasureManager if M==nil then return 'open=0 why=no-manager' end local function num(fn) local v=0 pcall(function() v=math.floor((M[fn](M) or 0)+0) end) return v end local open=false pcall(function() open=M:IsOpen() and true or false end) local have,need=num('GetTreasureHaveItemNum'),num('GetTreasureOpenNeedItemNum') if need<=0 then need=math.floor(tonumber(M.treasureNeedNum) or 0) end local chests=(need>0) and math.floor(have/need) or 0 return 'open='..(open and 1 or 0)..' have='..have..' need='..need..' chests='..chests..' guar='..num('GetGuaranteedTimes')..'/'..num('GetGuaranteedNeedTimes') end)() INTO state
LOG "explorer chests: {state}"
READ_LUA (function() local M=DataCenter and DataCenter.ExplorerTreasureManager if M==nil then return 0 end local open=false pcall(function() open=M:IsOpen() and true or false end) return open and 1 or 0 end)() INTO is_open
IF is_open == 0
    STOP "the explorer's chests are not running on this account right now"
READ_LUA (function() local M=DataCenter and DataCenter.ExplorerTreasureManager if M==nil then return 0 end local have,need=0,0 pcall(function() have=math.floor((M:GetTreasureHaveItemNum() or 0)+0) end) pcall(function() need=math.floor((M:GetTreasureOpenNeedItemNum() or 0)+0) end) if need<=0 then need=math.floor(tonumber(M.treasureNeedNum) or 0) end if need<=0 then return 0 end local keep=math.floor(tonumber(DataCenter.__lw_explorer_keep) or 0) local s=have-keep if s<0 then s=0 end return math.floor(s/need) end)() INTO to_open
IF to_open == 0
    STOP "not enough keys for a chest — they arrive with the next claimed secret task"

# 4. Note the bag down, so «what fell out» can be answered by subtraction: the reward is
#    a picture on screen and the server sends no receipt anything here can read.
TAP note_the_bag

# 5. Open them. `xall` re-reads the purse between presses, so a press the server dropped
#    is pressed again and the loop stops at the floor rather than at a number guessed
#    beforehand.
TAP open_explorer_treasure xall

# 6. Close whatever the opening put on screen and say what changed.
TAP dismiss_reward_popup
# ONE CALL, NOT ONE PER QUESTION (#2404). A read is a thread hijack into the
# client at half a second a time whatever it asks, and the machine can make about
# 1.4 of them a second in total (`docs/research/link-contention.md`), so a run of
# readings one statement at a time is that many seconds of everybody's budget for
# answers the game could hand over together. What each one is, and why it is asked,
# is on the comments and LOG lines that follow.
READ_LUA (function() local __v0 = (function() local was=DataCenter.__lw_bag_was if type(was)~='table' then return 'nothing was noted down first' end local now={} for _,s in pairs(DataCenter.ItemData.ItemInfos or {}) do local id=0 pcall(function() id=s.itemId+0 end) local c=0 pcall(function() c=s.count+0 end) if id>0 then now[id]=(now[id] or 0)+c end end local seen={} for id in pairs(was) do seen[id]=true end for id in pairs(now) do seen[id]=true end local rows={} for id in pairs(seen) do local d=(now[id] or 0)-(was[id] or 0) if d~=0 then local nm='' pcall(function() nm=tostring(DataCenter.ItemTemplateManager:GetName(id)) end) if nm=='' then nm='#'..tostring(id) end rows[#rows+1]={d=d,s=(d>0 and '+' or '')..tostring(d)..' '..nm} end end if #rows==0 then return 'nothing changed' end table.sort(rows,function(a,b) return math.abs(a.d)>math.abs(b.d) end) local out={} for i=1,math.min(#rows,12) do out[#out+1]=rows[i].s end if #rows>12 then out[#out+1]='…and '..tostring(#rows-12)..' more' end return table.concat(out,', ') end)() local __v1 = (function() local M=DataCenter and DataCenter.ExplorerTreasureManager if M==nil then return '?' end local function num(fn) local v=0 pcall(function() v=math.floor((M[fn](M) or 0)+0) end) return v end return 'keys='..num('GetTreasureHaveItemNum')..' guar='..num('GetGuaranteedTimes')..'/'..num('GetGuaranteedNeedTimes') end)() return __v0, __v1 end)() INTO gains, after
LOG "explorer chests done: {after}; the bag gained: {gains}"

# A CHEST WAS OPENED, SO LOOK FOR THE PACKET IT MAY HAVE DROPPED (#2397). Same reason as
# in `use_item.md`: the free-diamond packet a box sometimes gives is announced by nothing
# anybody has named, and it lives for an hour — so the run that opened the box checks for
# it on the spot. The give-away has its own gate and says «делиться нечем» without
# stopping this run.
CALL share_lucky_packet

# Claim every finished secret task, then open the boxes they paid out in.
# ru: Собрать награды за выполненные секретные задания и вскрыть выпавшие ящики.
#
# The income half of the command post, and it spends NOTHING: a finished task's reward is
# already earned and the box in the bag is already yours. So there is no budget here, no
# price to read and no dialog to refuse — which is exactly why it is a separate ability
# from `refresh_secret_tasks.md`, where every step is a price gate.
#
# WHY IT COMES FIRST. A finished task holds its march slot until it is claimed: live on a
# second account, six finished tasks were sitting on six of the nine marches with nothing
# running at all. Claiming them freed every one — `GetSingleTaskIngCount` 6 -> 0 — so the
# refreshing and sending that follows has somewhere to send to. An unclaimed reward is not
# only a reward unread; it is a squad that cannot leave.
#
# HOW IT IS CLAIMED. `TryRewardAll()` on the dispatch manager — the game's own «Получить»,
# which sends `hero.dispatch.batch.reward`. One press for the whole list; measured live,
# six tasks, `GetSingleTaskRewardableCount` 6 -> 0 and every one of them `rewarded = 1`.
#
# THE BOX. A task pays out, among other things, «Загадочный ящик с припасами» — one kind,
# not a family: the resource chests the bag also holds (`SR/SSR/UR сундук с …`) are what
# comes OUT of a box rather than what a task pays in. Opening it is the bag's ordinary
# `item.use` (`use_item.md`, #1702), so nothing new was needed to press it — what is new
# is knowing WHICH item, and saying what came out.
#
# WHAT CAME OUT is a DIFFERENCE and cannot be anything else: the reward window is a
# picture, and the server sends no itemised receipt the panel can read. So the bag is
# noted down before and read again after, and the report is what moved — the boxes down,
# whatever they held up.

# How many boxes to open. 0 opens every one the bag holds; a number opens that many, in
# batches, so a bag with a thousand of them is not one send of a thousand.
ARGS boxes = 0

# The most to open in a single send. The bag keeps one entry per stack and `item.use`
# takes a count, so this is a throttle on the SERVER's side of it, not on the loop's.
ARGS batch = 100

# 1. Claim first — the marches are not free until it is done.
TAP claim_secret_task_rewards xall
TAP dismiss_steal_reward

# 2. Note the bag down, so «what fell out» can be answered by subtraction.
TAP note_the_bag

# 3. Open the boxes, `batch` at a time, while there are any and the run is still owed some.
LUA DataCenter.__lw_box_left = ({boxes} > 0) and {boxes} or 1000000
READ_LUA (function() local left=math.floor(tonumber(DataCenter.__lw_box_left) or 0) local hold=(function() local id=710005 local n=0 for _,s in pairs(DataCenter.ItemData.ItemInfos or {}) do local i=0 pcall(function() i=s.itemId+0 end) if i==id then local c=0 pcall(function() c=s.count+0 end) n=n+c end end return n end)() local n=math.min(left,hold,{batch}) if n<0 then n=0 end DataCenter.__lw_box_round=n return n end)() INTO to_open
WHILE to_open > 0 LIMIT 40
    LUA DataCenter.__lw_use_id = 710005
    LUA DataCenter.__lw_use_num = math.floor(tonumber(DataCenter.__lw_box_round) or 0)
    TAP use_item
    WAIT 1.2
    LUA DataCenter.__lw_box_left = math.max(0, (tonumber(DataCenter.__lw_box_left) or 0) - (tonumber((DataCenter.__lw_use or {}).used) or 0))
    READ_LUA (function() local left=math.floor(tonumber(DataCenter.__lw_box_left) or 0) local hold=(function() local id=710005 local n=0 for _,s in pairs(DataCenter.ItemData.ItemInfos or {}) do local i=0 pcall(function() i=s.itemId+0 end) if i==id then local c=0 pcall(function() c=s.count+0 end) n=n+c end end return n end)() local n=math.min(left,hold,{batch}) if n<0 then n=0 end DataCenter.__lw_box_round=n return n end)() INTO to_open

# 4. Close whatever the opening put on screen, and say what changed.
TAP dismiss_reward_popup
TAP dismiss_steal_reward
READ_LUA (function() local was=DataCenter.__lw_bag_was if type(was)~='table' then return 'nothing was noted down first' end local now={} for _,s in pairs(DataCenter.ItemData.ItemInfos or {}) do local id=0 pcall(function() id=s.itemId+0 end) local c=0 pcall(function() c=s.count+0 end) if id>0 then now[id]=(now[id] or 0)+c end end local seen={} for id in pairs(was) do seen[id]=true end for id in pairs(now) do seen[id]=true end local rows={} for id in pairs(seen) do local d=(now[id] or 0)-(was[id] or 0) if d~=0 then local nm='' pcall(function() nm=tostring(DataCenter.ItemTemplateManager:GetName(id)) end) if nm=='' then nm='#'..tostring(id) end rows[#rows+1]={d=d,s=(d>0 and '+' or '')..tostring(d)..' '..nm} end end if #rows==0 then return 'nothing changed' end table.sort(rows,function(a,b) return math.abs(a.d)>math.abs(b.d) end) local out={} for i=1,math.min(#rows,12) do out[#out+1]=rows[i].s end if #rows>12 then out[#out+1]='…and '..tostring(#rows-12)..' more' end return table.concat(out,', ') end)() INTO gains
READ_LUA (function() local id=710005 local n=0 for _,s in pairs(DataCenter.ItemData.ItemInfos or {}) do local i=0 pcall(function() i=s.itemId+0 end) if i==id then local c=0 pcall(function() c=s.count+0 end) n=n+c end end return n end)() INTO boxes_left
LOG "boxes: {boxes_left} left in the bag; the bag gained: {gains}"

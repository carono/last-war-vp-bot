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

# HOW LONG TO STAND AND WAIT FOR A TASK THAT IS NEARLY RIPE, in seconds (#2073).
#
# A finished task of our OWN is robbable until its reward is taken — the same
# `hero.dispatch.steal` this bot spends on strangers, pointed back at us — so the minutes
# between «выполнено» and «получено» are minutes somebody else is paid for. The schedule
# can only ever wake NEAR the instant (its tick is twenty seconds and the appointment is
# read one run in advance), so the last stretch is waited out HERE, inside the run, and
# the claim is pressed the moment the server turns the task over.
#
# 0 — the default, and what the button on the tab plays: a person pressing «Собрать»
# wants the ripe ones now, not a run that hangs about for two minutes. The day's errand
# passes its own value down (`work_secret_tasks.md`).
ARGS ripe_wait = 0

# How often to look while waiting, in seconds. A poll of the CLIENT's own table, not a
# question to the server: `scan_secret_post` walks the tasks the client already holds.
ARGS ripe_poll = 3

# THE LEAD the next appointment is booked with, in seconds. The run books its own next
# turn on the nearest finish MINUS this, so the panel is already standing there when the
# task ripens instead of arriving after it (`next_run_in`, docs/dsl.md).
ARGS lead = 45

# How many boxes to open. 0 opens every one the bag holds; a number opens that many, in
# batches, so a bag with a thousand of them is not one send of a thousand.
ARGS boxes = 0

# The most to open in a single send. The bag keeps one entry per stack and `item.use`
# takes a count, so this is a throttle on the SERVER's side of it, not on the loop's.
ARGS batch = 100

# 1. Claim first — the marches are not free until it is done.
TAP claim_secret_task_rewards xall
TAP dismiss_steal_reward

# 1a. …and then WAIT OUT whatever is about to ripen, claiming as it does (#2073). The
#     client knows every running task's `completionTime` to the millisecond, so «is one
#     nearly done» costs a walk over a table it already holds. `xall` presses nothing
#     when there is nothing rewardable, so a round that finds the task still counting
#     down spends one scan and a sleep.
TAP scan_secret_post
READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local w={ripe_wait} if w<=0 then return 0 end local n=tonumber(M.__lw_ref_nextfree) or 0 if n<=0 or n>w then return 0 end return n end)() INTO ripe_in
IF ripe_in > 0
    LOG "a task ripens in {ripe_in} s — standing by to claim it on the instant"
WHILE ripe_in > 0 LIMIT 60
    WAIT {ripe_poll}
    TAP claim_secret_task_rewards xall
    TAP dismiss_steal_reward
    TAP scan_secret_post
    READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local w={ripe_wait} if w<=0 then return 0 end local n=tonumber(M.__lw_ref_nextfree) or 0 if n<=0 or n>w then return 0 end return n end)() INTO ripe_in

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

# 5. BOOK THE NEXT TURN BEFORE ANYTHING ELSE CAN FAIL (#2073). Whoever called this — the
#    day's errand, a button, a trigger — the panel now holds a good appointment for the
#    nearest finish even if the spending half that follows never reaches its own line.
#    A run that ends with no appointment falls back on the row's period, and for
#    `secret_tasks_day` that period is a DAY: one failed run used to cost every claim
#    until the next server midnight, which is exactly the window a thief is paid in.
TAP scan_secret_post
READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local free=tonumber(M.__lw_ref_nextfree) or 0 if free<=0 then return 0 end local n=free-{lead} if n<10 then n=10 end return math.floor(n) end)() INTO next_run_in
IF next_run_in > 0
    LOG "the next task ripens soon — coming back in {next_run_in} s, a little before it does"

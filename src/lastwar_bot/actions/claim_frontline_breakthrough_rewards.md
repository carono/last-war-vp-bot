# Claim what the Frontline Breakthrough event already owes — the soldier boxes and the day's tasks.
# ru: Забрать награды «Прорыва обороны» — ящики за общий счёт солдат и задания дня.
#
# Two things the event hands out beside the stages themselves:
#
#   * **soldier boxes** — three of them, unlocked by the SERVER-WIDE tally of soldiers
#     saved that day (`info.globalSoldierNum` against each box's `target`, thresholds
#     1 / 2.5 / 5 billion). By the time an account looks, the warzone has usually passed
#     all three, and they sit there unclaimed with the event's red dot not even lit.
#     `FrontBreakSundayBoxState`: 0 not reached, 1 claimable, 2 taken.
#   * **the day's tasks** — `info.taskArr`, the same three states.
#
# Both are one message each and cost nothing, so this is safe to run at any time — a box
# that is not claimable is simply not asked for. Run it before and after a session of
# `play_frontline_breakthrough.md`: the tally moves while you play.

READ_LUA (function() local M=DataCenter.ActFrontBreakSundayDataManager if not M then return -1 end local aid=M:GetFirstActId() if not aid or aid==0 or not M:IsOpen(aid) then return -1 end local d=M.dataDict[aid] if not d or not d.info then return -1 end local n=0 for _,b in ipairs(d.info.soldierBox or {}) do if tonumber(b.state)==1 then pcall(function() SFSNetwork.SendMessage(MsgDefines.FrontBreakSundaySaveSoliderReward,aid,b.id) end) n=n+1 end end return n end)() INTO fb_boxes

IF fb_boxes < 0
    FAIL "frontline breakthrough: the event is not open for this account"

READ_LUA (function() local M=DataCenter.ActFrontBreakSundayDataManager local aid=M:GetFirstActId() local d=M.dataDict[aid] local n=0 for _,t in ipairs(d.info.taskArr or {}) do if tonumber(t.state)==1 then pcall(function() SFSNetwork.SendMessage(MsgDefines.FrontBreakSundayReward,aid,t.taskId) end) n=n+1 end end return n end)() INTO fb_tasks

WAIT 2

READ_LUA (function() local M=DataCenter.ActFrontBreakSundayDataManager local d=M.dataDict[M:GetFirstActId()] local left=0 for _,b in ipairs(d.info.soldierBox or {}) do if tonumber(b.state)==1 then left=left+1 end end for _,t in ipairs(d.info.taskArr or {}) do if tonumber(t.state)==1 then left=left+1 end end return left end)() INTO fb_unclaimed

LOG "frontline breakthrough: asked for {fb_boxes} soldier box(es) and {fb_tasks} task reward(s), {fb_unclaimed} still unclaimed"

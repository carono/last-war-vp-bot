# Play the Frontline Breakthrough event — chain after chain, as deep and as fat as it can.
# ru: Мини-игра «Прорыв обороны» — гонять этапы подряд, копя солдат и уходя дальше по цепочке.
#
# The event («Прорыв обороны», internally `ActFrontBreakSunday`, activity 2400001) runs
# for one game-day and has NO attempt limit. Each stage drops the squad in the middle of
# a three-lane strip and pours monsters at it; soldiers gather as the run goes and the
# ones still standing when the stage is cleared are converted into real units — up to 60
# a stage. The top-rank criteria the client publishes are **stage 5 with 2 000 soldiers
# left** (`topRankCriteriaStage` / `topRankCriteriaRemainSolder`).
#
# THE CHAIN IS SERVER-SIDE, so this recipe does not manage it: clearing a stage makes the
# client offer the next one, losing one puts the offer back at stage 1, and so does
# leaving the chain alone for a few minutes. Each round therefore plays «whatever the
# client offers next» — a lost chain simply becomes the first stage of a new one — and
# the run only stops early when stage 5 itself is cleared.
#
#     ARGS rounds = 12      how many stages to play in one sitting; a full chain is 5
#     ARGS lane1…lane5      how to play each stage of the chain. A positive number holds
#                           that lane for the whole stage (31.5 left, 36 middle = the
#                           spawn, 40.5 right). Zero lets the game's own auto-play steer,
#                           which never leaves the middle. A negative number picks a
#                           steering policy:
#
#                            -1   avoid the lane with the heaviest wave ahead
#                            -2   feed: stand where the weak monsters are, leaning
#                                 towards the middle, and step off the heavy ones
#                            -3   hold the middle and only step aside for a heavy unit
#                            -5   the same as -2 with no leaning — dodges much more
#                                 eagerly, survives deeper, grows far less
#
# Measured live (see docs/research/frontline-breakthrough.md): holding the middle clears
# stage 1 with ~300–380 soldiers but never survives stage 2; the eager dodge (-5) is the
# only thing that has ever cleared stages 2 and 3, and it arrives there with a handful of
# soldiers. So the defaults feed on stage 1 and dodge from stage 2 on.
#
# Every stage is logged as `BREAKTHROUGH stage=… lane=… win=… left=… peak=…`, one line
# each, so a session can be counted afterwards without watching it.

ARGS rounds = 12
ARGS lane1 = -2
ARGS lane2 = -5
ARGS lane3 = -5
ARGS lane4 = -5
ARGS lane5 = -5

# `{}` is filled in from `ARGS` before the file is parsed, so this is the ONE place those
# numbers can travel from the caller into the game. `frontline_breakthrough_stage.md`
# cannot see this file's `ARGS`, so it reads them back out of the VM — the entry for the
# stage it is about to play, indexed by stage id.
LUA _G.__fb_lanes = { {lane1}, {lane2}, {lane3}, {lane4}, {lane5} }

READ_LUA (function() local M=DataCenter.ActFrontBreakSundayDataManager if not M then return 0 end local aid=M:GetFirstActId() if not aid or aid==0 then return 0 end local ok=M:IsOpen(aid) and M:CanPlay(aid) return ok and 1 or 0 end)() INTO fb_open

IF fb_open != 1
    FAIL "frontline breakthrough: the event is not open for this account"

READ_LUA (function() local M=DataCenter.ActFrontBreakSundayDataManager local d=M.dataDict[M:GetFirstActId()] local e=d.info.extra or {} return string.format('next stage %s of %d, best so far %s soldiers on stage %s',tostring(d.nextStageId),#d.stageIds,tostring(e.maxL),tostring(e.maxS)) end)() INTO fb_intro
LOG "frontline breakthrough: {fb_intro}"

READ_LUA 1 INTO fb_go

WHILE fb_go == 1 LIMIT {rounds}
    CALL frontline_breakthrough_stage
    LOG "BREAKTHROUGH stage={fb_stage} lane={fb_lane_used} win={fb_win} left={fb_left} peak={fb_peak} moves={fb_moves} frames={fb_frames} next={fb_next}"
    READ_LUA (function() if tonumber(_G.__fb_stage)==20455 and tonumber(_G.__fb_won)==1 then return 0 end return 1 end)() INTO fb_go

READ_LUA (function() local M=DataCenter.ActFrontBreakSundayDataManager local e=M.dataDict[M:GetFirstActId()].info.extra or {} return string.format('best %s soldiers, deepest stage %s',tostring(e.maxL),tostring(e.maxS)) end)() INTO fb_done
LOG "frontline breakthrough: done — {fb_done}"

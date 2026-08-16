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
# THE DEFAULTS ARE WHAT WAS MEASURED, stage by stage — and no two stages want the same
# thing (docs/research/frontline-breakthrough.md):
#
#     20451  hold the middle          ~300–400 soldiers, nine wins in ten
#     20452  feed, lean middle (-2)   cleared eight times of eleven, up to 407 left
#     20453  hold the right lane      cleared five of six — but leaves only 1–5 standing
#     20454  hold the left lane       cleared four of six, and always with exactly 17
#     20455  hold the middle          NOT CLEARED by any lane or policy tried; the middle
#                                     is merely the least bad (the squad peaks at 29
#                                     instead of 7–12 before it is wiped)
#
# WHAT A SITTING IS WORTH. A cleared stage converts the soldiers left into units, sixty
# at most — so stage 1 alone pays the full sixty in about forty seconds, and the rest of
# the chain pays less for longer (stage 3 leaves five). Depth is therefore for the event's
# ranking, not for the units: an account that only wants the units can set `lane2` to a
# lane that loses quickly and spend the whole sitting on stage 1.
#
# It also claims what the event owes before and after the session
# (`claim_frontline_breakthrough_rewards.md`): the three soldier boxes ride the
# WARZONE's tally of soldiers saved that day, not this account's, so they come due while
# the session runs and the event's red dot never lights up for them.
#
# Every stage is logged as `BREAKTHROUGH stage=… lane=… win=… left=… peak=…`, one line
# each, so a session can be counted afterwards without watching it.

ARGS rounds = 60
ARGS lane1 = 36
ARGS lane2 = -2
ARGS lane3 = 40.5
ARGS lane4 = 31.5
ARGS lane5 = 36

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

CALL claim_frontline_breakthrough_rewards

READ_LUA 1 INTO fb_go

WHILE fb_go == 1 LIMIT {rounds}
    CALL frontline_breakthrough_stage
    LOG "BREAKTHROUGH stage={fb_stage} lane={fb_lane_used} win={fb_win} left={fb_left} peak={fb_peak} moves={fb_moves} frames={fb_frames} route={fb_route} next={fb_next}"
    LOG "BREAKTHROUGH tail {fb_tail}"
    READ_LUA (function() if tonumber(_G.__fb_stage)==20455 and tonumber(_G.__fb_won)==1 then return 0 end return 1 end)() INTO fb_go

CALL claim_frontline_breakthrough_rewards

READ_LUA (function() local M=DataCenter.ActFrontBreakSundayDataManager local e=M.dataDict[M:GetFirstActId()].info.extra or {} return string.format('best %s soldiers, deepest stage %s',tostring(e.maxL),tostring(e.maxS)) end)() INTO fb_done
LOG "frontline breakthrough: done — {fb_done}"

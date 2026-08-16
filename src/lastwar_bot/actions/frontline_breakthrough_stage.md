# Play ONE stage of the Frontline Breakthrough event and report what came of it.
# ru: Один этап мини-игры «Прорыв обороны» — сыграть и доложить результат.
#
# A helper, not an ability of its own: `play_frontline_breakthrough.md` calls it five
# times in a row, and leaves these behind for the caller to read:
#
#     fb_stage    the stage id that was played (20451…20455).
#     fb_win      1 when the stage was cleared, 0 when the squad died.
#     fb_left     soldiers still standing at the end — what the event counts.
#     fb_next     the stage the client will offer next; the chain restarts at 20451
#                 after a loss.
#
# WHERE THE LANE COMES FROM. `{}` is filled in from `ARGS` before the file is parsed and
# from the live variables only when a line is LOGGED — a `READ_LUA` chunk written with
# `{lane}` in a file that does not declare it reaches the game as the four characters
# `{lane}`, and the run silently stops steering. So the caller parks the number in the
# game's own VM (`_G.__fb_lane`) and every chunk here reads it from there.
#
# WHY IT STEERS AT ALL. The squad holds one of three lanes and the game's auto-play
# leaves it in the middle. Measured live on stage 20451: middle lane → cleared with 332
# soldiers, left lane → wiped at 24. The lane is the only control the run has, and it
# decides the run.
#
# WHY IT LEAVES THE FINISHED BATTLE FIRST: a stage entered while the client still sits in
# the previous battle's scene is refused, silently — the request goes out, no battle
# starts, and the recipe would sit watching a stage that is already over.
#
# WHY IT WAITS FOR THE ANSWER before starting the next stage: the result travels to the
# server and the NEXT stage id comes back with the reply. Enter on the old id — which is
# what the client still holds for a second or two — and the client replays the stage that
# was just cleared.
#
# AND IT MUST NOT DAWDLE either: a chain left alone for a few minutes is dropped by the
# server and the next entry starts back at stage 1 (seen live — a win that reported
# «next 20452» was answered with 20451 four minutes later).

READ_LUA (function() local B=DataCenter.LWBattleManager local U=UIManager.Instance for _,n in ipairs({'UIBattleResultFrontBreakSundayVictory','UIBattleResultFrontBreakSundayDefeat','UIFrontBreakOutSundayNewRecord'}) do pcall(function() if U:IsWindowOpen(UIWindowNames[n]) then U:DestroyWindow(UIWindowNames[n]) end end) end if B:GetCurBattleLogic() then pcall(function() B:Exit() end) end return B:GetCurBattleLogic() and 1 or 0 end)() INTO fb_inbattle

WHILE fb_inbattle == 1 LIMIT 8
    WAIT 2
    READ_LUA (function() return DataCenter.LWBattleManager:GetCurBattleLogic() and 1 or 0 end)() INTO fb_inbattle

READ_LUA (function() local M=DataCenter.ActFrontBreakSundayDataManager local d=M.dataDict[M:GetFirstActId()] M.requestingEnterStage=false local nxt=tonumber(d.nextStageId) or 0 if nxt<=0 then return 0 end _G.__fb_stage=nxt local ok=pcall(function() M:RequestToEnterStage(nxt) end) return ok and nxt or 0 end)() INTO fb_stage

IF fb_stage == 0
    FAIL "frontline breakthrough: the client would not enter a stage"

READ_LUA (function() local B=DataCenter.LWBattleManager local L=B:GetCurBattleLogic() if not L then return 0 end if tonumber(L.levelId)~=tonumber(_G.__fb_stage) then return 0 end return B:IsBattleFinish() and 0 or 1 end)() INTO fb_running

WHILE fb_running == 0 LIMIT 12
    WAIT 2
    READ_LUA (function() local B=DataCenter.LWBattleManager local L=B:GetCurBattleLogic() if not L then return 0 end if tonumber(L.levelId)~=tonumber(_G.__fb_stage) then return 0 end return B:IsBattleFinish() and 0 or 1 end)() INTO fb_running

IF fb_running != 1
    FAIL "frontline breakthrough: the stage never started"

READ_LUA (function() local L=DataCenter.LWBattleManager:GetCurBattleLogic() if not L then return 0 end local lanes=_G.__fb_lanes or {} local idx=(tonumber(_G.__fb_stage) or 20450)-20450 local lane=tonumber(lanes[idx]) or tonumber(_G.__fb_lane) or 0 local LANE={31.5,36,40.5} local AHEAD=18 local NEAR=13 local HEAVY=60 local MIDBIAS=1 local MARGIN=1.5 if lane==-5 then MIDBIAS=0 MARGIN=0.5 end _G.__fb={peak=0,frames=0,lane=lane,moves=0} local st=_G.__fb local cur=2 local old=L.OnUpdate L.OnUpdate=function(self,...) local ok=pcall(old,self,...) st.frames=st.frames+1 local T=self.team if T then local n=(T.teamUnitCount or 0)+(T.overflowUnitCount or 0) if n>st.peak then st.peak=n end if st.frames%3==0 then if lane>0 then pcall(function() T:MoveHorizontalTo(lane) end) elseif lane<0 then pcall(function() local p=T:GetPosition() local tz=p.z local heavy={0,0,0} local food={0,0,0} local sc={0,0,0} for _,u in pairs(self.unitMgr.units or {}) do local mid=rawget(u,'monsterMetaId') if mid then local q=u:GetPosition() local dz=q.z-tz if dz>0 and dz<=AHEAD then local hp=tonumber(rawget(u,'curBlood')) or 1 local best,bi=1e9,2 for k=1,3 do local d=math.abs(q.x-LANE[k]) if d<best then best=d bi=k end end local v if hp<=5 then v=1 elseif hp<=20 then v=0 else v=-hp/10 end sc[bi]=sc[bi]+v if hp>=HEAVY and dz<=NEAR then heavy[bi]=heavy[bi]+hp else food[bi]=food[bi]+1 end end end end local pick if lane==-3 then if heavy[cur]<=0 and (cur==2 or heavy[2]<=0) then pick=(heavy[2]<=0) and 2 or cur else pick=cur local bh,bf=heavy[cur],food[cur] for k=1,3 do if heavy[k]<bh or (heavy[k]==bh and food[k]>bf) then pick=k bh=heavy[k] bf=food[k] end end end elseif lane==-1 then pick=cur local worst=1e18 for k=1,3 do local t=heavy[k]+food[k] if t<worst then worst=t pick=k end end else sc[2]=sc[2]+MIDBIAS local bs=sc[cur] pick=cur for k=1,3 do if sc[k]>bs+MARGIN then pick=k bs=sc[k] end end end if pick~=cur then cur=pick st.moves=st.moves+1 end st.pick=cur T:MoveHorizontalTo(LANE[cur]) end) end end end return ok end return lane end)() INTO fb_lane_used

WHILE fb_running == 1 LIMIT 60
    WAIT 3
    READ_LUA (function() local B=DataCenter.LWBattleManager local L=B:GetCurBattleLogic() if not L then return 0 end return B:IsBattleFinish() and 0 or 1 end)() INTO fb_running

READ_LUA (function() local L=DataCenter.LWBattleManager:GetCurBattleLogic() local T=L and L.team if not T then return (_G.__fb or {}).peak or 0 end return (T.teamUnitCount or 0)+(T.overflowUnitCount or 0) end)() INTO fb_left
READ_LUA ((_G.__fb or {}).peak or 0) INTO fb_peak
READ_LUA ((_G.__fb or {}).moves or 0) INTO fb_moves
READ_LUA ((_G.__fb or {}).frames or 0) INTO fb_frames

READ_LUA (function() local U=UIManager.Instance local M=DataCenter.ActFrontBreakSundayDataManager if U:IsWindowOpen(UIWindowNames.UIBattleResultFrontBreakSundayVictory) then _G.__fb_won=1 return 1 end if U:IsWindowOpen(UIWindowNames.UIBattleResultFrontBreakSundayDefeat) then _G.__fb_won=0 return 0 end local n=tonumber(M.dataDict[M:GetFirstActId()].nextStageId) or 0 if n~=tonumber(_G.__fb_stage) then _G.__fb_won=1 return 1 end _G.__fb_won=0 return -1 end)() INTO fb_win

WHILE fb_win == -1 LIMIT 10
    WAIT 1.5
    READ_LUA (function() local U=UIManager.Instance local M=DataCenter.ActFrontBreakSundayDataManager if U:IsWindowOpen(UIWindowNames.UIBattleResultFrontBreakSundayVictory) then _G.__fb_won=1 return 1 end if U:IsWindowOpen(UIWindowNames.UIBattleResultFrontBreakSundayDefeat) then _G.__fb_won=0 return 0 end local n=tonumber(M.dataDict[M:GetFirstActId()].nextStageId) or 0 if n~=tonumber(_G.__fb_stage) then _G.__fb_won=1 return 1 end _G.__fb_won=0 return -1 end)() INTO fb_win

IF fb_win == -1
    LOG "frontline breakthrough: the game never said whether the stage was cleared — counting it as lost"

READ_LUA (function() local M=DataCenter.ActFrontBreakSundayDataManager return tonumber(M.dataDict[M:GetFirstActId()].nextStageId) or 0 end)() INTO fb_next

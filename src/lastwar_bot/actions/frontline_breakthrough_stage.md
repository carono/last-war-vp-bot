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

READ_LUA (function() local L=DataCenter.LWBattleManager:GetCurBattleLogic() if not L then return 0 end local lanes=_G.__fb_lanes or {} local idx=(tonumber(_G.__fb_stage) or 20450)-20450 local lane=tonumber(lanes[idx]) or tonumber(_G.__fb_lane) or 0 local LANE={31.5,36,40.5} local AHEAD=18 local NEAR=13 local HEAVY=60 local HZ=30 local SPEED=6 local DPS=7.5 local PEN=6 local LOSS=0.5 local PMARGIN=1.5 local PMID=2 local MIDBIAS=1 local MARGIN=1.5 if lane==-9 then MIDBIAS=1 MARGIN=1.5 elseif lane==-5 then MIDBIAS=0 MARGIN=0.5 elseif lane==-6 then MIDBIAS=0 MARGIN=3 AHEAD=25 elseif lane==-7 then MIDBIAS=0.5 MARGIN=1 AHEAD=25 end _G.__fb={peak=0,frames=0,lane=lane,moves=0,tail={},ti=0,rec={},stage=tonumber(_G.__fb_stage) or 0} local st=_G.__fb local cur=2 local RT=_G.__fb_routes if not RT then RT={} _G.__fb_routes=RT end if (lane==-11 or lane==-12) then local best=RT[st.stage] local plan={} local hi=0 if best and best.r then for b,v in pairs(best.r) do plan[b]=v if b>hi then hi=b end end end if hi>0 and lane==-11 then for _=1,2 do local c=math.random(1,hi) local w=math.random(1,3) local nl=math.random(1,3) for b=c,math.min(hi,c+w) do plan[b]=nl end end st.mutated=1 end st.plan=plan st.hi=hi end local old=L.OnUpdate L.OnUpdate=function(self,...) local ok=pcall(old,self,...) st.frames=st.frames+1 local T=self.team if not T then return ok end if T then local n=(T.teamUnitCount or 0)+(T.overflowUnitCount or 0) if n>st.peak then st.peak=n end pcall(function() local b=math.floor((T:GetPosition().z)/2) st.rec[b]=cur end) if st.frames%15==0 then pcall(function() local q=T:GetPosition() local hv,fd=0,0 for _,u in pairs(self.unitMgr.units or {}) do local mid=rawget(u,'monsterMetaId') if mid then local w=u:GetPosition() local dz=w.z-q.z if dz>0 and dz<=18 then local hp=tonumber(rawget(u,'curBlood')) or 1 if hp<=5 then fd=fd+1 else hv=hv+hp end end end end st.ti=(st.ti%10)+1 st.tail[st.ti]=string.format('%d:x%.0f n%d f%d h%.0f',st.frames,q.x,n,fd,hv) end) end if st.frames%3==0 then if lane>0 then pcall(function() T:MoveHorizontalTo(lane) end) elseif lane<0 then pcall(function() local p=T:GetPosition() local tz=p.z local nnow=math.max(1,(T.teamUnitCount or 0)+(T.overflowUnitCount or 0)) local heavy={0,0,0} local food={0,0,0} local sc={0,0,0} for _,u in pairs(self.unitMgr.units or {}) do local mid=rawget(u,'monsterMetaId') if mid then local q=u:GetPosition() local dz=q.z-tz if dz>0 and dz<=AHEAD then local hp=tonumber(rawget(u,'curBlood')) or 1 local best,bi=1e9,2 for k=1,3 do local d=math.abs(q.x-LANE[k]) if d<best then best=d bi=k end end local v if hp<=5 then v=1 elseif hp<=20 then v=0 else v=-hp/10 end sc[bi]=sc[bi]+v if hp>=HEAVY and dz<=NEAR then heavy[bi]=heavy[bi]+hp else food[bi]=food[bi]+1 end end end end if lane==-8 then local wx,ww=0,0 local hx,hw=0,0 for _,u in pairs(self.unitMgr.units or {}) do local mid=rawget(u,'monsterMetaId') if mid then local q=u:GetPosition() local dz=q.z-tz if dz>0 and dz<=AHEAD then local hp=tonumber(rawget(u,'curBlood')) or 1 if hp<=5 then local w=1/(1+dz) wx=wx+q.x*w ww=ww+w elseif hp>=HEAVY and dz<=NEAR then local w=hp/(1+dz) hx=hx+q.x*w hw=hw+w end end end end local want if ww>0 then want=wx/ww else want=36 end if hw>0 then local hc=hx/hw if math.abs(want-hc)<3 then want=want+((want>=hc) and 4.5 or -4.5) end end if want<31 then want=31 elseif want>41 then want=41 end if math.abs(want-(st.want or 36))>0.4 then st.moves=st.moves+1 end st.want=want T:MoveHorizontalTo(want) return end local pick if (lane==-11 or lane==-12) then local b=math.floor(p.z/2) local want=st.plan and st.plan[b] if not want then local dl={[20451]=2,[20453]=3,[20454]=1,[20455]=2} want=dl[st.stage] end if want then if want~=cur then cur=want st.moves=st.moves+1 end st.pick=cur T:MoveHorizontalTo(LANE[cur]) return end end if lane==-98 then local worst,bi=-1,cur for _,u in pairs(self.monsterMgr.showList or {}) do local ux=tonumber(rawget(u,'x')) local uy=tonumber(rawget(u,'y')) local hp=tonumber(rawget(u,'curBlood')) or 0 if ux and uy and hp>0 then local dz=uy-p.z if dz>0 and dz<=25 then local k,bd=2,1e9 for j=1,3 do local dd=math.abs(ux-LANE[j]) if dd<bd then bd=dd k=j end end if bd<2.5 then local v=hp/(1+dz) if v>worst then worst=v bi=k end end end end end if bi~=cur then cur=bi st.moves=st.moves+1 end st.pick=cur T:MoveHorizontalTo(LANE[cur]) return end if lane==-10 then local RW=_G.__fb_rw if not RW then RW={} _G.__fb_rw=RW end local DM=_G.__fb_dm if not DM then DM={} _G.__fb_dm=DM end local inst=LocalController.instance() local function reward(u) local id=rawget(u,'monsterMetaId') local c=RW[id] if c~=nil then return c end local tm=rawget(u,'triggerMeta') local v=0 if type(tm)=='table' then local ty=tonumber(tm.type) if ty==40 then local pa=tostring(tm.para or '') if pa~='' and pa~='nil' then v=1 for _ in pa:gmatch('|') do v=v+1 end end else local tx=tostring(tm.text or '') local nn=tonumber(tx:match('%-?%d+') or '') if nn then v=nn end end end RW[id]=v return v end local function hurt(u) local id=rawget(u,'monsterMetaId') local c=DM[id] if c~=nil then return c end local v=0.5 pcall(function() local sdm=tostring(inst:getValue('lw_monster',id,'collide_damage','')) local last=nil for part in sdm:gmatch('[^|]+') do last=part end local nn=tonumber(last) if nn then v=nn end end) DM[id]=v return v end local by={{},{},{}} for _,u in pairs(self.monsterMgr.showList or {}) do local ux=tonumber(rawget(u,'x')) local uy=tonumber(rawget(u,'y')) local hp=tonumber(rawget(u,'curBlood')) or 0 if ux and uy and hp>0 then local dy=uy-p.z if dy>0.5 and dy<=HZ then local bi,bd=2,1e9 for k=1,3 do local dd=math.abs(ux-LANE[k]) if dd<bd then bd=dd bi=k end end if bd<2.5 then local t=by[bi] t[#t+1]={dy=dy,hp=hp,r=reward(u),d=hurt(u)} end end end end local sc={0,0,0} for k=1,3 do local t=by[k] table.sort(t,function(a,b) return a.dy<b.dy end) local cum=0 local v=0 for _,o in ipairs(t) do cum=cum+o.hp local tav=o.dy/SPEED if cum<=DPS*nnow*tav then v=v+o.r else v=v+o.r*0.3-o.d*nnow*LOSS end end sc[k]=v end sc[2]=sc[2]+PMID local bi=cur local bs=sc[cur] for k=1,3 do if sc[k]>bs+PMARGIN then bi=k bs=sc[k] end end if bi~=cur then cur=bi st.moves=st.moves+1 end st.pick=cur st.sc=string.format('%.1f/%.1f/%.1f',sc[1],sc[2],sc[3]) T:MoveHorizontalTo(LANE[cur]) return end if lane==-9 and st.frames<120 then cur=2 st.pick=2 T:MoveHorizontalTo(LANE[2]) return end if lane==-3 then if heavy[cur]<=0 and (cur==2 or heavy[2]<=0) then pick=(heavy[2]<=0) and 2 or cur else pick=cur local bh,bf=heavy[cur],food[cur] for k=1,3 do if heavy[k]<bh or (heavy[k]==bh and food[k]>bf) then pick=k bh=heavy[k] bf=food[k] end end end elseif lane==-1 then pick=cur local worst=1e18 for k=1,3 do local t=heavy[k]+food[k] if t<worst then worst=t pick=k end end else sc[2]=sc[2]+MIDBIAS local bs=sc[cur] pick=cur for k=1,3 do if sc[k]>bs+MARGIN then pick=k bs=sc[k] end end end if pick~=cur then cur=pick st.moves=st.moves+1 end st.pick=cur T:MoveHorizontalTo(LANE[cur]) end) end end end return ok end return lane end)() INTO fb_lane_used

WHILE fb_running == 1 LIMIT 60
    WAIT 3
    READ_LUA (function() local B=DataCenter.LWBattleManager local L=B:GetCurBattleLogic() if not L then return 0 end return B:IsBattleFinish() and 0 or 1 end)() INTO fb_running

READ_LUA (function() local L=DataCenter.LWBattleManager:GetCurBattleLogic() local T=L and L.team if not T then return (_G.__fb or {}).peak or 0 end return (T.teamUnitCount or 0)+(T.overflowUnitCount or 0) end)() INTO fb_left
READ_LUA ((_G.__fb or {}).peak or 0) INTO fb_peak
READ_LUA (function() local st=_G.__fb or {} local RT=_G.__fb_routes or {} local sid=st.stage or 0 local left=0 local L=DataCenter.LWBattleManager:GetCurBattleLogic() local T=L and L.team if T then left=(T.teamUnitCount or 0)+(T.overflowUnitCount or 0) end local b=RT[sid] local was=(b and b.best) or 0 if left>was and left>0 then local cp={} for k,v in pairs(st.rec or {}) do cp[k]=v end RT[sid]={best=left,r=cp,runs=((b and b.runs) or 0)+1} _G.__fb_routes=RT return left end if b then b.runs=(b.runs or 0)+1 end return -was end)() INTO fb_route
READ_LUA ((_G.__fb or {}).moves or 0) INTO fb_moves
READ_LUA ((_G.__fb or {}).frames or 0) INTO fb_frames
READ_LUA (function() local st=_G.__fb or {} local t=st.tail or {} local o={} local n=#t for i=1,n do local j=((st.ti or 0)+i-1)%n+1 o[#o+1]=t[j] end return table.concat(o,' | ') end)() INTO fb_tail

READ_LUA (function() local U=UIManager.Instance local M=DataCenter.ActFrontBreakSundayDataManager if U:IsWindowOpen(UIWindowNames.UIBattleResultFrontBreakSundayVictory) then _G.__fb_won=1 return 1 end if U:IsWindowOpen(UIWindowNames.UIBattleResultFrontBreakSundayDefeat) then _G.__fb_won=0 return 0 end local n=tonumber(M.dataDict[M:GetFirstActId()].nextStageId) or 0 if n~=tonumber(_G.__fb_stage) then _G.__fb_won=1 return 1 end _G.__fb_won=0 return -1 end)() INTO fb_win

WHILE fb_win == -1 LIMIT 10
    WAIT 1.5
    READ_LUA (function() local U=UIManager.Instance local M=DataCenter.ActFrontBreakSundayDataManager if U:IsWindowOpen(UIWindowNames.UIBattleResultFrontBreakSundayVictory) then _G.__fb_won=1 return 1 end if U:IsWindowOpen(UIWindowNames.UIBattleResultFrontBreakSundayDefeat) then _G.__fb_won=0 return 0 end local n=tonumber(M.dataDict[M:GetFirstActId()].nextStageId) or 0 if n~=tonumber(_G.__fb_stage) then _G.__fb_won=1 return 1 end _G.__fb_won=0 return -1 end)() INTO fb_win

IF fb_win == -1
    LOG "frontline breakthrough: the game never said whether the stage was cleared — counting it as lost"

READ_LUA (function() local M=DataCenter.ActFrontBreakSundayDataManager return tonumber(M.dataDict[M:GetFirstActId()].nextStageId) or 0 end)() INTO fb_next

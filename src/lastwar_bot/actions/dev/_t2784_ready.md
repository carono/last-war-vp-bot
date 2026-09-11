# Measure whether the alliance table shows a secret task as READY, and n/3, with no camera.
# ru: Замер: видно ли из альянсовой таблицы готовность секретки и n/3 без камеры.
#
# READ ONLY (#2784). Nothing is robbed, no window opens, the camera does not move.
SHARE

LUA if not _G.__lw2784_old then _G.__lw2784_old = SFSNetwork.SendMessage _G.__lw2784_seen = {} SFSNetwork.SendMessage = function(name, ...) local t=_G.__lw2784_seen t[#t+1]=tostring(name) return _G.__lw2784_old(name, ...) end end

LUA local M=DataCenter.ActDispatchTaskDataManager pcall(function() M:GetAllAllianceTasksFromServer() end)

WAIT 6

READ_LUA (function() local seen=_G.__lw2784_seen or {} if _G.__lw2784_old then SFSNetwork.SendMessage=_G.__lw2784_old _G.__lw2784_old=nil end local M=DataCenter.ActDispatchTaskDataManager local now=0 pcall(function() now=UITimeManager.Instance:GetServerTime()+0 end) local home=nil pcall(function() home=tostring(LuaEntry.Player.serverId) end) if home==nil or home=='nil' then pcall(function() home=tostring(DataCenter.WorldDataManager.curServerId) end) end local n,away,done,pend,steals,withSteal,live=0,0,0,0,0,0,0 for _,v in pairs(M.allianceTask or {}) do n=n+1 local srv=tostring(v.targetServer or '?') if srv~=tostring(home) then away=away+1 end local ct=0 pcall(function() ct=(v.completionTime or 0)+0 end) local ae=0 pcall(function() ae=(v.actEndTime or 0)+0 end) if ct>0 and ct<=now then done=done+1 else pend=pend+1 end if ae>now then live=live+1 end local c=0 for _ in pairs(v.stealInfoList or {}) do c=c+1 end steals=steals+c if c>0 then withSteal=withSteal+1 end end return 'sent=['..table.concat(seen,' | ')..'] now='..math.floor(now)..' home='..tostring(home)..' count='..n..' away='..away..' ready='..done..' pending='..pend..' actLive='..live..' withSteal='..withSteal..' stealEntries='..steals end)() INTO counts

READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local now=0 pcall(function() now=UITimeManager.Instance:GetServerTime()+0 end) local out={} for _,v in pairs(M.allianceTask or {}) do local ct=0 pcall(function() ct=(v.completionTime or 0)+0 end) local c=0 for _ in pairs(v.stealInfoList or {}) do c=c+1 end local rd=(ct>0 and ct<=now) and 1 or 0 out[#out+1]=tostring(v.targetServer)..':'..tostring(v.pointId)..':'..rd..':'..c end table.sort(out) return table.concat(out,' ') end)() INTO ready

READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local now=0 pcall(function() now=UITimeManager.Instance:GetServerTime()+0 end) local out={} local k=0 for _,v in pairs(M.allianceTask or {}) do local c=0 for _ in pairs(v.stealInfoList or {}) do c=c+1 end if c>0 then k=k+1 local ct=0 pcall(function() ct=(v.completionTime or 0)+0 end) if k<=8 then out[#out+1]='pid='..tostring(v.pointId)..' srv='..tostring(v.targetServer)..' n='..c..' ct='..math.floor(ct)..' ready='..tostring(ct>0 and ct<=now) end end end return 'rows_with_steals='..k..' | '..table.concat(out,' | ') end)() INTO stolen

LOG "t2784_counts {counts}"
LOG "t2784_ready {ready}"
LOG "t2784_stolen {stolen}"

READ_LUA (function() local M=DataCenter.ActDispatchTaskDataManager local now=0 pcall(function() now=UITimeManager.Instance:GetServerTime()+0 end) local n,rd,st=0,0,0 local out={} for _,v in pairs(M.singleTask or {}) do n=n+1 local ct=0 pcall(function() ct=(v.completionTime or 0)+0 end) local c=0 for _ in pairs(v.stealInfoList or {}) do c=c+1 end st=st+c if ct>0 and ct<=now then rd=rd+1 end out[#out+1]=tostring(v.pointId)..':'..((ct>0 and ct<=now) and 1 or 0)..':'..c end table.sort(out) return 'mine='..n..' ready='..rd..' stolen_from_me='..st..' | '..table.concat(out,' ') end)() INTO mine

LOG "t2784_mine {mine}"

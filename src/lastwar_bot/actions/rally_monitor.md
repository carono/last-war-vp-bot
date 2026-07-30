# Read the alliance rallies (стяги) out right now and log who is in them.
# ru: Прочитать выставленные ралли альянса и записать в лог, кто в них.
#
# A rally is an alliance world march with `teamUuid ~= 0`; the game numbers a
# rally's teamUuid as leaderUuid + 1, so the LEADER is the march whose
# `uuid == teamUuid - 1` and it carries the rally's target tile and server.
# Everything is read straight off the game's own march table
# (`DataCenter.WorldMarchDataManager:GetAllMarches()`) through the daemon — no map
# panning and no packet decode, so it works headless.
#
# This is the scenario behind the «rally_monitor» TRIGGER (panel/triggers.py): the
# game announces a banner on the wire (`push.alliance.march.*`), and the trigger
# runs this the instant it lands to record the rally — its leader's teamUuid, the
# target and server, and every member with the squad (formationUuid) they sent and
# the send time. `join_rally.md` CALLs it too, so a join logs who is already there.
#
# The team/leader/point/server/member-count read is the same one tools/rally_join.py
# lists rallies with (docs/research/rally-join.md, proven live). The per-member
# formation and the send time are read best-effort — the march field names for them
# are not yet confirmed live, so they show «?» when the read misses. UNPROVEN as a
# recipe until it has logged a real banner.

READ_LUA (function() local wm=DataCenter.WorldMarchDataManager local col=wm and wm:GetAllMarches() if not col then return "no march data" end local function g(mo,k) local ok,v=pcall(function() return mo[k] end) if ok then return v end return nil end local e=col:GetEnumerator() local R={} local order={} while e:MoveNext() do local mo=e.Current.Value if mo==nil then mo=e.Current end local team=g(mo,"teamUuid") local ts=tostring(team) if team~=nil and ts~="0" and ts~="nil" then local r=R[ts] if not r then r={m={}} R[ts]=r order[#order+1]=ts end local nm=tostring(g(mo,"ownerName")) local fm=tostring(g(mo,"formationUuid") or g(mo,"formation") or "?") r.m[#r.m+1]=nm.."(f="..fm..")" local isL=false pcall(function() isL=(tostring(g(mo,"uuid"))==tostring(team-1)) end) if isL then r.lead=nm r.pt=tostring(g(mo,"targetPos")) r.sv=tostring(g(mo,"serverId") or g(mo,"targetServer")) r.st=tostring(g(mo,"startTime") or g(mo,"createTime") or g(mo,"beginTime") or "?") end end end local out={} for _,ts in ipairs(order) do local r=R[ts] out[#out+1]="team="..ts.." leader="..tostring(r.lead).." point="..tostring(r.pt).." server="..tostring(r.sv).." start="..tostring(r.st).." members="..#r.m.." ["..table.concat(r.m,"; ").."]" end if #out==0 then return "no active rallies" end return table.concat(out," || ") end)() INTO rallies

LOG "Rallies out: {rallies}"

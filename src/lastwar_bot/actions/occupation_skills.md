# Fire every profession skill that is off cooldown and needs no target.
# ru: Применить все профессиональные навыки, вышедшие из отката и не требующие цели.
#
# «Навыки профессии» — the active skills of the profession the account picked
# (Инженер / Военный лидер). Each is a banked charge on a long cooldown (23.5 h for
# most, up to 71.5 h) that pays out on its own: hours of production from the base
# generators, a batch of speed-ups, a random survivor, an instant chunk off the build
# or research queue. Nothing about them accumulates — a charge sitting unspent is a
# day of that income thrown away, which is the whole reason this recipe exists.
#
# Each line is just "tap a button"; the engine calls live in the button library
# tools/lib/game_buttons.py. Behind `use_profession_skill`: one
# `DataCenter.MasteryManager:UseSkill(id)` per press — the same call the in-game
# useBtn makes — which puts a single `use.desert.talent.skill {skillId}` on the wire.
# No window has to be open; the press is headless.
#
# The skill is picked inside the press, not named here, because which skills a
# profession has depends on how far its tree is levelled. `xall` re-reads the ready
# count between presses and walks the whole set, so this one line covers all of them
# whatever the account.
#
# The presses above are the no-target ones (use-position `SkillView`). One TARGETED
# skill is fired further down — «Взаимовыгодное сотрудничество» / Win-Win, which is cast
# on an alliancemate whose profession is War Leader and whose base the client can name
# (#2598). The rest that want a world point — Совместное исследование / Совместное
# строительство (a building) and Осадное знамя (a map tile) — are still skipped: firing
# them blind would aim at nothing, and nothing picks a point for them yet.
#
# Cooldown is set by the SERVER's reply, so a press is invisible client-side until it
# lands (~8 s in the recording). Two things keep `xall` from firing one skill twice:
# the 4 s pause baked into the button, and a re-fire guard inside the press itself
# that ignores any skill it stamped in the last two minutes.
#
# Source: results/traces/20260729_010052_навыки_профессии_trace.log +
# results/traffic/20260729_010053_навыки_профессии_traffic.jsonl.
# The call path is proven against the live VM with the sender stubbed out (it reaches
# SendUseSkillMsg with exactly the recorded arguments) — but no charge was available
# to spend, so the end-to-end press is NOT yet confirmed in a real session. See
# docs/research/occupation-skills.md.

# THE GATE IS THE GAME'S OWN ANSWER, and it is read before anything is pressed. The
# count below is the client's `MasterySkillState == Normal` over the profession's own
# tree — never a list of skill ids written down here, because which skills exist depends
# on the profession and on how far its tree is levelled, and a season adding a node
# would leave a hardcoded list quietly pressing last season's set.
#
# `-1` means the client could not answer at all — no mastery data, which is what a
# client sitting on the login screen looks like (it answers everything and knows
# nothing). That is a FAILED run, not an empty one: the schedule holds the errand for
# its retry instead of writing the turn off as done.
READ_LUA (function() local M=DataCenter.MasteryManager local d=M:GetData() if not d then return -1 end local now=UITimeManager:GetInstance():GetServerTime() local f=M.__lw_fired or {} local n=0 for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do local sid=M:GetCurSkillIdByMasteryId(mid) local t=sid and M:GetSkillTemplate(sid) if t and t.active_skills and t:CheckUsePosition(MasterySkillUsePosType.SkillView) and M:GetMasteryGroupSkillState(mid)==MasterySkillState.Normal and (now-(f[sid] or 0))>120000 then n=n+1 end end return n end)() INTO ready

IF ready < 0
    FAIL "the client cannot answer for the profession tree — not logged in yet"

LOG "profession skills off cooldown and needing no target: {ready}"

TAP use_profession_skill xall  # fire every ready no-target skill, one per press
TAP dismiss_skill_result       # close the "you received …" modal the last use raised

# What is left after the round of presses. A skill that was fired reports `CD` once the
# server's reply lands, so `left` is what the presses could NOT take — normally 0, and a
# number above zero says the press was refused rather than that nothing was ready.
READ_LUA (function() local M=DataCenter.MasteryManager local d=M:GetData() if not d then return -1 end local now=UITimeManager:GetInstance():GetServerTime() local f=M.__lw_fired or {} local n=0 for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do local sid=M:GetCurSkillIdByMasteryId(mid) local t=sid and M:GetSkillTemplate(sid) if t and t.active_skills and t:CheckUsePosition(MasterySkillUsePosType.SkillView) and M:GetMasteryGroupSkillState(mid)==MasterySkillState.Normal and (now-(f[sid] or 0))>120000 then n=n+1 end end return n end)() INTO left

LOG "fired: {ready} ready before, {left} still ready after"

# ------------------------------------------------------------------------------------
# WIN-WIN COOPERATION — the one skill of this profession that is cast ON ANOTHER PLAYER.
#
# «Взаимовыгодное сотрудничество». Everything above fires skills that need no target;
# this one has a use-position of `Building`, so the press names a tile — and the game's
# own description says whose: "Can only be used on the War Leader". Their construction
# and research costs drop for a day; the reward is ours. It spends nothing but the
# charge, and no march leaves the base (proven with both senders stubbed out: the call
# reaches `use.desert.talent.skill {otherUid, serverId}` and never `OnClickStartMarch`).
#
# THE TARGET'S PROFESSION IS IN THE DATA — that was the open question, and the answer is
# yes. Every record the client keeps about another player carries `careerType` (101
# Engineer, 102 War Leader), and the alliance roster is already indexed by it, each row
# holding the base tile the press aims at. Nothing is asked of the server to find a
# candidate; the camera flight a player sees is the client walking its own list.
#
# The reading below is one round trip and says all four things that can stop a press,
# each in its own words rather than as a bare "not now":
#
#   state=-2  the client cannot answer for the tree at all — the login screen
#   state=-1  this account has no such node: a War Leader, or an Engineer who has not
#             learnt it. Not an error and not a cooldown — there is nothing to fire
#   state=3   on cooldown; `next_ms` says for how much longer
#   cands=0   nobody in the alliance is a War Leader the client can name a tile for
READ_LUA (function() local M=DataCenter.MasteryManager local d=nil pcall(function() d=M:GetData() end) if not d then return 'state=-2 charges=0 cands=0 next_ms=0 since_fire=0' end local now=UITimeManager:GetInstance():GetServerTime() local node=nil if d then for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do if M:GetCurSkillIdByMasteryId(mid)==10417 then node=mid break end end end local st=-1 local ch=0 local nxt=0 if node then st=M:GetMasteryGroupSkillState(node) or 0 pcall(function() local c=d:GetSkillChargeData(10417) ch=(c and c.num) or 0 end) local avail=0 pcall(function() avail=d:GetSkillAvailableTime(10417) or 0 end) if avail>0 then nxt=avail-now if nxt<0 then nxt=0 end end end local n=0 pcall(function() for _,v in pairs(DataCenter.AllianceCareerManager:GetAllianceMemberListByCareer(102) or {}) do if type(v)=='table' and (v.pointId or 0)>0 then n=n+1 end end end) local f=M.__lw_fired or {} return 'state='..tostring(st)..' charges='..tostring(ch)..' cands='..tostring(n)..' next_ms='..tostring(math.floor(nxt))..' since_fire='..tostring(math.floor(now-(f[10417] or 0))) end)() INTO winwin

LOG "Win-Win: {winwin} (state 1 = a charge is banked, 3 = on cooldown, -1 = not on this profession's tree, -2 = the client cannot answer)"

READ_LUA (function() local M=DataCenter.MasteryManager local d=nil pcall(function() d=M:GetData() end) if not d then return 0 end local now=UITimeManager:GetInstance():GetServerTime() local node=nil if d then for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do if M:GetCurSkillIdByMasteryId(mid)==10417 then node=mid break end end end if not node then return 0 end if M:GetMasteryGroupSkillState(node)~=MasterySkillState.Normal then return 0 end local f=M.__lw_fired or {} if (now-(f[10417] or 0))<=120000 then return 0 end local n=0 pcall(function() for _,v in pairs(DataCenter.AllianceCareerManager:GetAllianceMemberListByCareer(102) or {}) do if type(v)=='table' and (v.pointId or 0)>0 then n=n+1 end end end) if n<1 then return 0 end return 1 end)() INTO winwin_ready

IF winwin_ready == 1
    LOG "Win-Win: a charge is banked and the alliance has a War Leader to spend it on"
    TAP use_win_win_skill
    TAP dismiss_skill_result

# What the game says AFTER the press. `state=3` here is the success: the server's reply
# landed and put the skill on its cooldown. A `state` still at 1 means the press was
# refused rather than that nothing was ready — the same distinction `left` draws above.
READ_LUA (function() local M=DataCenter.MasteryManager local d=nil pcall(function() d=M:GetData() end) if not d then return 'state=-2 charges=0 cands=0 next_ms=0 since_fire=0' end local now=UITimeManager:GetInstance():GetServerTime() local node=nil if d then for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do if M:GetCurSkillIdByMasteryId(mid)==10417 then node=mid break end end end local st=-1 local ch=0 local nxt=0 if node then st=M:GetMasteryGroupSkillState(node) or 0 pcall(function() local c=d:GetSkillChargeData(10417) ch=(c and c.num) or 0 end) local avail=0 pcall(function() avail=d:GetSkillAvailableTime(10417) or 0 end) if avail>0 then nxt=avail-now if nxt<0 then nxt=0 end end end local n=0 pcall(function() for _,v in pairs(DataCenter.AllianceCareerManager:GetAllianceMemberListByCareer(102) or {}) do if type(v)=='table' and (v.pointId or 0)>0 then n=n+1 end end end) local f=M.__lw_fired or {} return 'state='..tostring(st)..' charges='..tostring(ch)..' cands='..tostring(n)..' next_ms='..tostring(math.floor(nxt))..' since_fire='..tostring(math.floor(now-(f[10417] or 0))) end)() INTO winwin_after

LOG "Win-Win afterwards: {winwin_after}"

# WHEN TO COME BACK — the game's own clock, not a period somebody guessed (`next_run_in`,
# docs/dsl.md). Every one of these charges recovers on a server-side countdown the reply
# to a press carries (`recover.cdEndTime`), so there is nothing to poll for: the soonest
# of those instants, in seconds from now with a minute's margin, is exactly when this
# errand has something to do again. 23.5 hours for most skills, up to 71.5 for the
# banner — a row on an hourly period would ask the game twenty-three times for nothing.
#
# `0` — no active no-target skill on this account, or the reading failed — leaves the
# row's own period standing, which is the safe way for this to fail.
READ_LUA (function() local M=DataCenter.MasteryManager local ok,d=pcall(function() return M:GetData() end) if not ok or not d then return 0 end local now=UITimeManager:GetInstance():GetServerTime() local f=M.__lw_fired or {} local best=-1 for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do local sid=M:GetCurSkillIdByMasteryId(mid) local t=sid and M:GetSkillTemplate(sid) if t and t.active_skills and (t:CheckUsePosition(MasterySkillUsePosType.SkillView) or sid==10417) then local st=M:GetMasteryGroupSkillState(mid) if st~=MasterySkillState.Locked and st~=MasterySkillState.Covered and st~=MasterySkillState.None and (now-(f[sid] or 0))>120000 then local avail=d:GetSkillAvailableTime(sid) or 0 local left=0 if avail>0 then left=avail-now if left<0 then left=0 end end if best<0 or left<best then best=left end end end end if best<0 then return 0 end return math.floor(best/1000)+60 end)() INTO next_run_in

LOG "the next charge lands in «next_run_in» seconds (0 = the row's period stands)"

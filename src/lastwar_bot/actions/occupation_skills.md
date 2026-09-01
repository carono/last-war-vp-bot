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
# Only no-target skills are fired (use-position `SkillView`). The ones that want a
# world point — Совместное исследование / Совместное строительство (a building) and
# Осадное знамя (a map tile) — are skipped: firing them blind would aim at nothing.
# They are the open half of this feature and still need a targeted recipe.
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

# WHEN TO COME BACK — the game's own clock, not a period somebody guessed (`next_run_in`,
# docs/dsl.md). Every one of these charges recovers on a server-side countdown the reply
# to a press carries (`recover.cdEndTime`), so there is nothing to poll for: the soonest
# of those instants, in seconds from now with a minute's margin, is exactly when this
# errand has something to do again. 23.5 hours for most skills, up to 71.5 for the
# banner — a row on an hourly period would ask the game twenty-three times for nothing.
#
# `0` — no active no-target skill on this account, or the reading failed — leaves the
# row's own period standing, which is the safe way for this to fail.
READ_LUA (function() local M=DataCenter.MasteryManager local ok,d=pcall(function() return M:GetData() end) if not ok or not d then return 0 end local now=UITimeManager:GetInstance():GetServerTime() local f=M.__lw_fired or {} local best=-1 for _,mid in ipairs(M:GetHomeDict(d.home_id) or {}) do local sid=M:GetCurSkillIdByMasteryId(mid) local t=sid and M:GetSkillTemplate(sid) if t and t.active_skills and t:CheckUsePosition(MasterySkillUsePosType.SkillView) then local st=M:GetMasteryGroupSkillState(mid) if st~=MasterySkillState.Locked and st~=MasterySkillState.Covered and st~=MasterySkillState.None and (now-(f[sid] or 0))>120000 then local avail=d:GetSkillAvailableTime(sid) or 0 local left=0 if avail>0 then left=avail-now if left<0 then left=0 end end if best<0 or left<best then best=left end end end end if best<0 then return 0 end return math.floor(best/1000)+60 end)() INTO next_run_in

LOG "the next charge lands in «next_run_in» seconds (0 = the row's period stands)"

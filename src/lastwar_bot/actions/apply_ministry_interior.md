# Ask for the Minister of the Interior post, and fail when the application does not take.
# ru: Подать заявку на пост министра внутренних дел — с провалом, если заявка не прошла.

# The scheduled form of submit_ministry.md, written for the panel's 30-minute timer.
# The generic recipe presses and is done; this one has to answer a question the timer
# asks after every run — *did the application actually go through?* — because the clock
# is only allowed to restart on a yes. A run that pressed nothing, or pressed and was
# turned down, has to end as a FAILURE so the timer keeps its place and tries again.
#
# The reading that answers it is the post you hold. Where the President has the server
# grant applications automatically — which is the case on the servers seen so far — an
# accepted application seats you at once, so one round trip after the press the held
# post either is the one asked for or the request did not take. Both directions are
# recorded live: 0 -> 10007 on the application in docs/research/ministry.md, and unmoved
# at 10005 when the server answered «has position».
#
# Three ways this ends without pressing anything:
#
#   * the post is already ours — nothing to ask for, a clean success, look again in
#     half an hour;
#   * ANOTHER ministry post is held — the server refuses a second application
#     («has position»), and the client's own CheckCanApply does NOT cover this: it
#     answers `true` with a post in hand, so without the check the request leaves,
#     comes back rejected, and the player gets a toast for it;
#   * the client's pre-flight says no — on cooldown, or the post is closed.
#
# The last two are failures, so a timer retries rather than sitting out its period.
# «Another post is held» is a state that only clears when that post is lost or given
# up, so the errand will keep failing until then — with the reason in the log, which is
# the point: a timer that quietly reset its clock every half hour would look like it was
# working.
#
# The press itself is the same single headless call as submit_ministry.md — no window is
# opened. Position ids are STRINGS everywhere in the apply manager; the expressions below
# come from tools/lib/lua_actions.py (ministry_own_position / ministry_can_apply) so the
# quoting cannot drift. The engine side is docs/research/ministry.md.

READ_LUA (function() local ok, p = pcall(function() return DataCenter.OfficialApplyManager:GetOwnPositionId() end) if not ok or p == nil then p = DataCenter.GovernmentManager.self_positionId end return tonumber(p) or 0 end)() INTO post

IF post == 10007
    STOP "already the Minister of the Interior — nothing to apply for"

IF post > 0
    FAIL "another ministry post is held — the server refuses a second application"

READ_LUA ((function() local M=DataCenter.OfficialApplyManager local G=DataCenter.GovernmentManager if not M:CheckCanApply('10007') then return false end local t=DataCenter.GovernmentTemplateManager:GetTemplate('10007') if t and t.type==1 then return G:IsConqueror(G.curDataServerId) and true or false end return true end)() and 1 or 0) INTO can

IF can == 0
    FAIL "the client refuses the application right now — on cooldown, or the post is closed"

TAP apply_minister_interior   # «Подать заявку» on Министр внутренних дел (10007)

# Wait for the answer by looking, not by guessing a settle: the reply lands well inside a
# second, so the usual run leaves this loop on its first pass, and a server having a slow
# moment costs a couple of polls instead of a wrongly logged failure and half an hour.
WHILE post != 10007 LIMIT 4
    WAIT 0.5
    READ_LUA (function() local ok, p = pcall(function() return DataCenter.OfficialApplyManager:GetOwnPositionId() end) if not ok or p == nil then p = DataCenter.GovernmentManager.self_positionId end return tonumber(p) or 0 end)() INTO post

IF post != 10007
    FAIL "the application was sent but the post was not granted"

LOG "Minister of the Interior — the post is ours"

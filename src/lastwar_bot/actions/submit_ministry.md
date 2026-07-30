# Apply for a post in the server's ministry (the President's kingdom positions).
# ru: Подать заявку на должность в министерстве сервера.
#
# Reproduces the "министерство / министр внутр. дел" recording: the player opened the
# government screen, picked a post and pressed «Подать заявку». Only the last of those
# is a real action — the application is a single headless call, so this recipe opens
# no window and closes nothing.
#
# Behind the tap: UIOfficialApplyCtrl:SendKingdomPositionApply(positionId), which puts
# `kingdom.position.apply {positionId}` on the wire. The engine calls live in the button
# library tools/lib/game_buttons.py; the reverse-engineering is in
# docs/research/ministry.md.
#
# The eight posts, one button each — swap the line below for the one you want:
#
#     TAP apply_vice_president        10002  Вице-президент
#     TAP apply_minister_strategy     10003  Министр стратегии
#     TAP apply_minister_defence      10004  Министр обороны
#     TAP apply_minister_construction 10005  Министр строительства
#     TAP apply_minister_science      10006  Министр науки
#     TAP apply_minister_interior     10007  Министр внутренних дел
#     TAP apply_commander_military    10008  Военный командир      (zone war only)
#     TAP apply_commander_admin       10009  Административный командир (zone war only)
#
# `xall` here means "press only if the application would be accepted": the button's
# count is the client's own CheckCanApply gate (already holding a post, still on this
# post's cooldown, post closed), capped at one press. Without the gate the request
# still leaves the client and comes back as a server-side rejection with a toast.
#
# WHEN to apply is deliberately NOT decided here. Whether a post is worth asking for
# depends on the queue and on how long its current holder has sat — both readable
# without any window (tools/ministry.py, or straight from a scheduling recipe):
#
#     READ_LUA (DataCenter.OfficialApplyManager:CheckCanApply(10007) and 1 or 0) INTO can
#     READ_LUA (function() local i=DataCenter.GovernmentManager:GetPositionInfoByPositionId(10007) if not i or not i.appointTime or i.appointTime==0 then return -1 end return (UITimeManager.Instance:GetSocketTime()-i.appointTime)/60000 end)() INTO held
#
# Do NOT chain several posts in one run on a server that queues applicants instead of
# granting them: the gate only closes once a post is actually held, so every line would
# fire. Applying for one post per run is the safe shape.
#
# Verified live: one press took the account from no post to Министр внутренних дел
# (GovernmentManager.self_positionId 0 -> 10007) with no UI open.

TAP apply_minister_interior xall   # «Подать заявку» on Министр внутренних дел (10007)

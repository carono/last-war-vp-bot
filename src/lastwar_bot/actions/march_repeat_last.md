# Send the last macro march again — same squad, same target, no screens at all.
# ru: Повторить последний марш макроса — тот же отряд, та же цель, без единого окна.
#
# The keyboard macro behind CapsLock (#1283). `march_selected_squad.md` writes down
# what it sent the moment before it presses the launch; this sends exactly that again.
# Nothing is opened, the camera is not moved, and the target is not clicked: the target
# is addressed by its uuid and the server works the path out for itself — the shape
# proven live for the «Кодовое имя» boss (docs/research/codename-event.md) and used by
# every headless launch in this repository.
#
#   run march_repeat_last
#
# It takes no arguments on purpose. «The same again» is the whole ability, and a run
# that let the squad or the target be changed would be `march_selected_squad.md` with
# extra steps.
#
# The memory lives in the GAME's VM (`DataCenter.__lw_macro_last`), not in the panel:
# it has to outlive the scenario that filled it, and a panel restart must not lose what
# the client still knows. Restarting the CLIENT does clear it — there is nothing to
# repeat until the next macro march, and the run says so instead of sending something
# stale.
#
# Nothing is claimed from a press that returned cleanly. The run ends as a FAILURE when
# no macro march has been sent yet, when the last one was a RALLY, and when the send
# went out and no march appeared — which is the ordinary answer when the squad is still
# out on the last one, or when the target is gone.
#
# A RALLY IS NOT REPEATED, and that refusal is deliberate. A banner is raised through
# the squad screen's own launch, which fills in a wait slot and a disband time the
# screen owns; the plain send this file makes has never been proven for a rally type,
# and the one time #1283 tried it live the client went down in the middle of the run.
# Nothing pins that crash on the send — but «unproven» plus «the client restarted while
# it ran» is not something to keep pointing at somebody's account, and re-raising a
# banner is not what «the same march again» is for. `MarchUtil.IsRallyMarch` — the
# game's own answer — is what decides, so a rally type added next season is covered
# without anybody copying an enum. docs/research/march-hotkeys.md.

READ_LUA (function() local m = DataCenter.__lw_macro_last or {} if m.formation == nil or m.target == nil or m.type == nil then return 0 end local rally = false pcall(function() rally = MarchUtil.IsRallyMarch(m.type) and true or false end) if rally then return -1 end return 1 end)() INTO ready

IF ready == 0
    FAIL "nothing to repeat — no march has been sent by a macro yet"
IF ready == -1
    FAIL "the last march was a rally — a banner is raised through its own screen, not repeated"

TAP macro_repeat

READ_LUA ((function() local ok, n = pcall(function() local om = DataCenter.WorldMarchDataManager:GetOwnerMarches() local c = 0 if om then local e = om:GetEnumerator() while e:MoveNext() do c = c + 1 end end return c end) if not ok then return -1 end return n end)()) - ((DataCenter.__lw_macro_last or {}).before or 0) INTO sent

WHILE sent < 1 LIMIT 8
    WAIT 0.5
    READ_LUA ((function() local ok, n = pcall(function() local om = DataCenter.WorldMarchDataManager:GetOwnerMarches() local c = 0 if om then local e = om:GetEnumerator() while e:MoveNext() do c = c + 1 end end return c end) if not ok then return -1 end return n end)()) - ((DataCenter.__lw_macro_last or {}).before or 0) INTO sent

IF sent < 1
    FAIL "the send went out and no march appeared — the squad is probably still out on the last one, or the target is gone"

LOG "The same squad is on its way to the same target"

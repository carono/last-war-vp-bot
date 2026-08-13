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

# THE PRESS COMES FIRST AND THE QUESTION AFTER IT (#1290). This used to ask whether
# there was anything to repeat, wait ~90 ms for the answer, and only then press — a
# whole round trip standing between CapsLock and the march, for a question the press
# has to answer inside its own chunk anyway. So `macro_repeat` decides for itself and
# parks what it decided, and the reading below only turns that into a sentence.
TAP macro_repeat

READ_LUA (tonumber((DataCenter.__lw_macro_last or {}).result) or 0) INTO ready

IF ready == 0
    FAIL "nothing to repeat — no march has been sent by a macro yet"
IF ready == -1
    FAIL "the last march was a rally — a banner is raised through its own screen, not repeated"

# AND IT DOES NOT STAND HERE COUNTING (#1328). A run holds the game claim for its whole
# length, and this recipe used to spend three and a half seconds after the send proving a
# march appeared — measured live, `TAP=+0.08 … end=+3.42`, of which everything past +0.2
# was the poll. That is exactly the «CapsLock reacts after three seconds» a person feels,
# and the next key waited behind it as well.
#
# The verdict is not dropped, it is DEFERRED: the next press reads the march count this
# one wrote down and says whether this one really marched. So a repeat that quietly
# achieved nothing is still reported — one press later, at no cost to either.
READ_LUA tostring((DataCenter.__lw_macro_last or {}).say or '-') INTO squad

LOG "Squad {squad} is on its way to the same target"

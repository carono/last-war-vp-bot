# Heal every wounded soldier in the base hospital ("Лечение юнитов").
#
# The hospital (`LWUIHospital`) heals wounded soldiers. One press of its cure button
# sends ONE message that heals a whole batch at once — captured whole in traces
# 20260729_152749 / 152841 (docs/research/hospital-heal.md):
#
#     hospital.cure  {armyArray = [ {armyId = <string>, healNum = <int>}, ... ]}
#
# one entry per wounded soldier type. As with the other recipes, the line below is just
# "tap a button": the real Lua (that one hospital.cure, built from the wounded list the
# window reads out of `T11Util.GetSelfCurSoldierData()`) lives in the button library
# tools/lib/game_buttons.py -> `heal_all`.
#
# NB — `TAP heal_all` is NOT a screen tap. It is a headless Lua send: no hospital window
# is opened, the wounded list is read straight off the game state and healed in one
# message. `xall` means "send only if something is actually wounded", so a healthy army
# costs no server round trip; a single press already covers every wounded type, so the
# plain `TAP heal_all` is the usual call.
#
# The message SHAPE is proven on the wire. What is still best-effort (see
# docs/research/hospital-heal.md §4) is the headless enumeration of *all* wounded: one
# field name on `GetSelfCurSoldierData()` is not yet confirmed, so a mismatch heals
# nothing (safe) rather than the wrong thing. Run tools/scratch/_hospital_probe.lua once
# with wounded soldiers present to pin it down, then this recipe is fully proven.
#
# "Select quantity": the in-game window defaults each type's slider to the MAX (all
# wounded), which is exactly what this heals — the whole batch. Heal a specific count
# instead only through the primitive tools/lib/hospital.py `cure([(armyId, n)])`.
#
# "Request help" / "Collect": healing is sped up by the ALLIANCE HELP system, which is
# the same `al.help.all` the `help_ally` recipe already sends — starting a heal registers
# it for help automatically, there is no separate "request help for my heal" message. A
# finished heal returns the soldiers on the queue timer; no distinct "collect" send was
# captured. Both are documented in docs/research/hospital-heal.md §3.

TAP heal_all xall   # heal every wounded soldier type, or no-op if nothing is hurt

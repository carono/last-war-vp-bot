# Fire every profession skill that is off cooldown and needs no target.
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

TAP use_profession_skill xall  # fire every ready no-target skill, one per press
TAP dismiss_skill_result       # close the "you received …" modal the last use raised

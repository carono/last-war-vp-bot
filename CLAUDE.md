# last-war-vp-bot

@docs/skills/sniff-quick.md

## Feature list upkeep

**This rule is binding on every agent working in this repository — dispatcher,
worker, or one-off session. No exceptions, no "someone else will write it up".**

`docs/farming.md` is the record of what the bot can actually do. Once the user
confirms a new ability works in the live game, update it in the same session —
before starting anything else, and before reporting the task done:

1. **`docs/farming.md` (EN) first.** It is the canonical copy. Put the item under
   the section it belongs to, mark it ✅ (proven live) or 🟡 (one step of the flow
   works, or it works but has not been proven in a real session), and say in one
   line what runs by itself and what is still left to the person. Update the
   daily-routine tables at the bottom if the ability appears there too.
2. **`docs/farming.ru.md` (RU) second.** Mirror the same edit — same section, same
   position, same mark, same meaning. The two files are read side by side, so
   they must stay in step; never change one and leave the other.

Confirmation is the trigger: unproven work stays ❌ or 🟡, and a feature is not
finished — and must not be marked done in the tracker — until both files say so.

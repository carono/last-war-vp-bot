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
3. **Redraw the progress bar.** Both files open with a bar between
   `<!-- progress:start -->` and `<!-- progress:end -->` — the share of ✅ among
   all the feature bullets. Any time a mark changes, or an item is added or
   removed, run `python3 tools/farming_progress.py --write` and commit the
   redrawn bar with the same edit. Never hand-count it, and never leave a bar
   that disagrees with the list below it — without `--write` the script only
   reports, and exits non-zero when a file is out of date.

### What a feature description may say

Both farming files are a feature list for the person playing the game, not a
technical reference. Describe only **what the bot does** in the game: what it
collects, what it sends, what it presses, what appears on screen afterwards, and
what the person still has to do.

Never put implementation detail in them — no protocol or message names, no Lua or
C# function names, no class or manager names, no wire field names, no file or
tool paths. If a sentence would only make sense to someone who has read the
code, it does not belong here.

> ❌ heal wounded via `hospital.cure` with an `armyArray` payload, headless
> ✅ heals the wounded in the hospital — one press, no window opened

All of that belongs in `docs/research/` instead — one file per ability. The
farming list does not link there; the two audiences are separate.

Confirmation is the trigger: unproven work stays ❌ or 🟡, and a feature is not
finished — and must not be marked done in the tracker — until both files say so.

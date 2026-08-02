# last-war-vp-bot

@docs/skills/sniff-quick.md

## Everything is a scenario — the panel only plays them

**This rule is binding on every agent working in this repository — dispatcher,
worker, or one-off session. No exceptions, and "there was already a button doing
it this way" is not one.**

Every ability of the bot lives in exactly one place: a scenario under
`src/lastwar_bot/actions/*.md`, written in the DSL (`docs/dsl.md`). The panel is a
**player**, not a bot: it lists scenarios, starts them, and shows what came back.
It decides *when* to press and *how the result is drawn* — never *what the press
is*.

1. **New behaviour → a new `actions/*.md`.** Compose it out of the primitives
   that already exist (`TAP`, `LUA`, `READ_LUA`, `GAME`, `JUMP`, `FIND`, `CLICK`,
   `WAIT`, `CALL`, …), declare its inputs with `ARGS`, and give it a title line
   with its `# ru:` translation. One file, one ability.
2. **A panel button = running that scenario.** `script_engine.run_action(name, …)`
   with the UI's values passed as arguments, and nothing else. Code under
   `panel/` holds widgets, layout, i18n, schedules, settings, persistence and
   presentation.
3. **`tools/lib/lua_actions.py` — and `game_buttons.py`, `script_engine.py` —
   grow only when the DSL lacks a primitive.** Add the primitive, document it in
   `docs/dsl.md`, then write the scenario that uses it. A primitive presses one
   thing or reads one value; the order, the gates and the routine stay in the
   scenario.

Nothing under `panel/` may assemble Lua for the game VM, walk a sequence of game
steps, hold the gates of an ability (quota left, is-it-open-today, cooldowns,
"collect first, then heal"), or retry on a game reply. If a panel change needs any
of that, the ability is not finished: write the scenario and call it.

### What that looks like

```python
# ❌ panel/hospital_tab.py — the game routine lives in the panel
def _on_heal(self) -> None:
    ev = get_evaluator()
    ev.run(lua_actions.collect_healed(), marker="ACT", settle=0.8)
    if self._wounded() > 0:                      # a gate of the ability, in Tk
        ev.run(lua_actions.heal_all(), marker="ACT", settle=1.2)
    ev.run(lua_actions.call_help(), marker="ACT", settle=0.6)
```

```md
<!-- ✅ src/lastwar_bot/actions/heal_units.md — the ability, in one file -->
# Heal the wounded soldiers in the base hospital.
# ru: Лечение раненых в госпитале базы.
TAP collect_healed xall
TAP heal_all xall
TAP call_help xall
```

```python
# ✅ panel/… — the button only plays it
script_engine.run_action("heal_units", hwnd=0, on_event=self._log_put)
```

Values typed in the UI travel the same way and no further: the scenario declares
`ARGS level = 30`, the button passes `variables={"level": self._level.get()}`.

### The code that predates this rule

Most of the panel still speaks to the game directly — `panel/__main__.py`,
`panel/tabs_extra.py`, `panel/dashboard.py`, `panel/command_post.py`,
`panel/triggers.py`, `panel/secret_tasks.py`, `panel/mapsweep.py`. They are debt,
not precedent. Do not rewrite them all at once, but when a task takes you into one
of those paths, move the game logic out into a scenario and leave the panel
calling it. **Never add a new one.**

### Definition of done

A task that delivers an ability is not done — and must not be marked done in the
tracker — until:

- the ability is one runnable scenario in `src/lastwar_bot/actions/`;
- everything the panel does with it goes through `run_action`;
- any primitive added along the way is documented in `docs/dsl.md`;
- and, once the user has confirmed it live, both farming files say so (below).

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

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

Less of it than there was: the panel's tabs are plugins now
(`docs/panel-tabs.md`), and what still speaks to the game directly is down to
`panel/dashboard.py`, `panel/tabs/_data.py` and the reads inside a few tabs. They
are debt, not precedent. Do not rewrite them all at once, but when a task takes
you into one of those paths, move the game logic out into a scenario and leave the
panel calling it. **Never add a new one.**

Two of them are itemised and NOT free, whatever a plan may say: the secret-task
and ghost-recon robberies spawn their tool because the recipe only spends a queue
the tool fills (task #1188). Read that before "just" swapping a spawn for
`rt.actions.run(...)`.

## Every panel tab is a plugin

**Also binding.** A new tab goes in `panel/tabs/`, subclasses `PanelTab`, is named
in the registry, and talks to `PanelRuntime` and nothing else. It must open on its
own with `python -m panel.tabs.<id>` and disappear completely when its profile
switches it off.

**Read [`docs/panel-tabs.md`](docs/panel-tabs.md) before writing one.** It has the
skeleton, what to declare, the runtime's surface, the `ensure_loaded` / `on_show`
distinction that costs a game read per start-up when it is got wrong, and the five
things that are forbidden — chief among them importing `panel/__main__.py`, which
re-executes the whole panel as a second module.

Nothing new goes into `panel/__main__.py`. It is the shell: window, notebook, log,
menu, «Главная». If a change needs something from it, move that something into
`panel/runtime/` first and use it from there.

## An edit travels between the window and the web, in BOTH directions, at once

**Also binding, on every agent, with no exceptions.** The panel has two front-ends now:
the Tk window and the web one a phone opens (`panel/web/`, #1221). They are not a
product and a copy of it — they are two ways of drawing the same runtime, and the
moment one of them is behind, whoever is reading THAT one is being told something that
is not true any more, with no way to know it.

So it travels **both ways, in the same commit**:

* **Window → web.** A tab that grows a button, a field, a reading or a status line
  updates its `web_view()` — and `web_press()` if it is a press.
* **Web → window.** A screen, a card, a button or a fact added to `web_view()` gets its
  counterpart in the tab's `build()`. The web does not run ahead of the window either:
  a control that exists only on the phone is a control the person at the machine cannot
  find, and the next agent reading the tab has no idea it is there.

Neither side catches up with the other once a quarter; they move together. A tab's
screen is data (`docs/panel-tabs.md`, «The phone's copy of this tab»), so mirroring an
addition is usually four lines — and that is the point: it is cheap while the change is
in your head and expensive six months later when nobody remembers which of the two is
right.

### A divergence is never an agent's decision

Sometimes the two sides genuinely should differ — something is impossible on a phone,
or pointless in a window. **That is a conversation with the person, not a judgement
call.** Raise it, get an answer, and write the exception down with its reasoning where
the next agent will read it (`CLAUDE.md` and `docs/panel-tabs.md`). Until it is written
down, it does not exist and the rule stands.

What is forbidden is the quiet version: shipping a change on one side, deciding by
yourself that the other does not need it, and leaving no trace of the decision. Then
there is no way to tell an exception from an omission — and six months on, neither is
there any way to tell which side is the truth.

The three tabs below are exactly what a legal divergence looks like: discussed,
justified, written into both files, and pinned by a test. Any future one is expected to
look the same.

### What that looks like

```python
# ❌ the window learns something the phone will never hear
def build(self) -> None:
    ...
    self.tr(ttk.Button(bar, command=self._heal), "hospital.heal").pack()
    self._wounded = tk_stringvar(self.rt.root)      # a new reading on the tab
```

```python
# ❌ …and the same mistake the other way round: a button only the phone has
def web_view(self) -> dict:
    return {"cards": [...],
            "actions": [{"id": "heal", "label": "hospital.heal"}]}   # nothing in build()
```

```python
# ✅ the same change, both front-ends
def build(self) -> None:
    ...
    self.tr(ttk.Button(bar, command=self._heal), "hospital.heal").pack()
    self._wounded = tk_stringvar(self.rt.root)

def web_view(self) -> dict:
    return {"cards": [{"title": "tab.hospital",
                       "rows": [{"label": "hospital.wounded",
                                 "value": self._wounded.get()}]}],
            "actions": [{"id": "heal", "label": "hospital.heal"}]}

def web_press(self, action, args) -> dict:
    if action != "heal":
        return {"error": "unknown"}
    return {"ok": self.rt.play_async("heal_units", tag="web")}
```

### A press travels only when the ability is a scenario

`web_press` runs what `rt.actions` / `rt.play_async` runs and nothing else. Where a tab
still drives the game by hand — the secret-task and ghost robberies spawn their tool
because the recipe only spends a queue the tool fills (#1188) — **the web gets the
READING and no button**, and the tab's own reading is mirrored as usual.

This is an ORDER OF WORK, not a way out of the rule: first the ability becomes a
scenario, then the button appears in the web. A second copy of a hand-driven press,
reachable from outside the house, is not an improvement — it is the same debt in two
places.

### The three divergences there are, and how they got there

They are the model for the paragraph above: each was **proposed, argued and agreed with
the person**, and then written down here — not decided in passing by whoever was in the
file at the time.

`settings` — paths, interpreters and ports: breaking a profile with one thumb is easier
than fixing it from a bus. `web` — the door the person came in through; managing it from
the far side is how somebody locks themselves out. `develop` — two sniffers for working
on the bot itself, switched off even in the window.

All three declare `WEB_SCREEN = False`, `tests/test_panel_web_screens.py` fails if one
of them quietly grows a screen, and what those three genuinely need on the move goes on
«Состояние» as a switch rather than as a page. A fourth exception is added the same way:
ask, agree, write it in both files, pin it in the test.

### Definition of done

A task that delivers an ability is not done — and must not be marked done in the
tracker — until:

- the ability is one runnable scenario in `src/lastwar_bot/actions/`;
- everything the panel does with it goes through `run_action`;
- any primitive added along the way is documented in `docs/dsl.md`;
- every string it shows is a locale key, present in **all** the shipped locales;
- **anything it changed on ONE front-end is mirrored on the OTHER, whichever way round**
  — a tab edit is not done while the phone still shows the old panel, and a `web_view`
  edit is not done while the window is missing what the phone now has. A deliberate
  difference is agreed with the person first and written down, never left silent;
- nothing it adds is true of this machine only (below);
- and, once the user has confirmed it live, both farming files say so (below).

## Nothing about one machine is written into the code

**Also binding, on every agent, with no exceptions.** This repository is public and it
gets installed on other people's computers. **Anything that has a different answer on a
different machine is asked, never assumed** — where the game is installed, what its
window and its process are called, which Windows account a second client runs as, which
port a daemon listens on, where the Python that drives it lives, which server the player
is on.

The answer lives in exactly one place and every caller asks it there:

1. **Paths and names of the game — [`tools/lib/game_paths.py`](tools/lib/game_paths.py).**
   The launcher, the install folder, the publisher\product folder, the launcher and
   client filenames, the window title, the asset index, the bundle cache, the download
   tree, the Windows interpreter. Every one is a function with an environment variable
   in front of a default, so a machine that is not ordinary sets a variable instead of
   editing code. **Need a new one? Add it there and use it — never re-spell it.**
2. **The player's own values — [`tools/lib/tool_config.py`](tools/lib/tool_config.py)
   and `.env`.** Home server, squad formations, and anything else that belongs to an
   account rather than to a machine. Defaults are empty on purpose: the live game VM is
   the authority, and an empty default fails loudly instead of acting on somebody
   else's number.
3. **A login, a session, an instance — asked, or registered.** A Windows account name
   has no sensible default at all, so a tool that needs one says so
   (`tools/rdp_instance.py --user`, `LW_SECOND_USER`) and a second client is an entry
   in `tools/data/instances.json`, not a line in `instance_manager.py`.

**A personal value is worse than a wrong one, because it looks right.** A default
naming the machine this was written on does not fail with «not configured» — it goes
looking for a folder or a session that cannot exist and reports the ordinary «no client
running», and the person who installed the bot has no way to tell the two apart.

### What that looks like

```python
# ❌ every one of these is one machine's answer, written down as everyone's
info = find_window("Last War-Survival Game", "LastWar.exe")
cache = Path(home) / "FunFly" / "Last War-Survival Game" / "Cache" / "AssetBundles"
DEFAULT_USER = "<the author's own Windows login>"
WIN_PYTHON = r"C:\Python312\python.exe"
GAME_PORT = 17935                          # …until the server moves, and it has
```

```python
# ✅ ask the one place that can answer differently per machine
info = find_window()                       # title + process from game_paths
cache = Path(game_paths.asset_cache())     # LW_ASSET_CACHE, or the ordinary install
DEFAULT_USER = (os.environ.get("LW_SECOND_USER") or "").strip()   # and ask if empty
WIN_PYTHON = game_paths.win_python()
GAME_PORT = game_paths.game_port()         # …and ask the live socket before trusting it
```

**A recording is not a fixture until it is anonymised.** A capture taken from a live
session carries whoever was on screen — nicknames, account ids, alliance tags, device
ids, and they are not all yours to publish. Replace them before the file is committed;
`tests/fixtures/` is as public as the rest of the repository.

Prose is not a value: a comment or a docstring may name the game, the launcher or a
«run it like this» line, and should. What may not come back is a **quoted literal being
used** — to build a path, filter a process list or match a window.

Every new variable is added to [`.env.example`](.env.example) in the same commit, with
a line saying what it is for and that it is optional.

`tests/test_no_hardcoded_values.py` enforces all of it — the quoted literals, the
personal logins, and the «one place decides the interpreter» rule. Run it before you
call this kind of work done:

```
C:\Python312\python.exe tests\test_no_hardcoded_values.py
```

## Not one word of the panel is written in the panel

**Also binding, on every agent, with no exceptions.** Every string a person can read —
a label, a button, a checkbox, a hint, a column head, a window title, a message box, a
line in the log — is a **key** in `panel/locales/`, reached through the runtime:
`self.t(key)`, `self.tr(widget, key)`, `rt.say(tag, key, **fmt)`. A literal handed to a
widget is a bug even when it is written in the language the panel happens to be showing:
it cannot be translated, it cannot be reviewed beside its siblings, and it does not
change when the person changes the language.

**A key goes into every shipped locale at once, translated.** The repository ships
**eleven**: `en` `ru` `de` `fr` `es` `it` `pt` `pl` `tr` `id` `vi`. The change that adds
a key adds it to all eleven in the same commit — not «English now, the rest later». A
locale that is behind falls back to English silently, so the gap breaks nothing and
nobody notices it for months; that is exactly why it is forbidden rather than merely
discouraged. There is still no table of languages anywhere in the code — the set is the
contents of `panel/locales/`, so a twelfth file added tomorrow is a twelfth to fill in.

Eleven is not an arbitrary number: it is the languages the GAME has a table for, minus
the ones this toolkit cannot draw. The client ships nineteen
([`docs/research/game-locale-tables.md`](docs/research/game-locale-tables.md)), and
Chinese, Japanese, Korean, Arabic and Thai are deliberately not panel languages — Tcl/Tk
8.6 does no bidi reordering and no Arabic joining, and nobody here can proofread the CJK
ones. **Anything the game has already named is copied out of its own tables rather than
translated** — the list is [`docs/game-glossary.md`](docs/game-glossary.md), and
`tools/game_locale.py --term "Doom Elite"` prints any other term in all eleven.

Only strings nobody reads as words may be literals: numeric formats (`"(%d–%d)"`),
separators, Tk option values, internal tags. **If it can be translated, it is a key.**

### What that looks like

```python
# ❌ panel/tabs/mything.py — the tab speaks for itself, in one language, for ever
ttk.Button(self.parent, text="Обновить", command=self.refresh).pack()
ttk.Label(self.parent, text="Ничего не прочитано").pack()
messagebox.showerror("Ошибка", f"не удалось прочитать: {exc}")
self.rt.put("[mything] обновлено")
```

```python
# ✅ the tab names a key; the runtime says it, in whatever language is on
self.tr(ttk.Button(self.parent, command=self.refresh), "mything.refresh").pack()
self.tr(ttk.Label(self.parent), "mything.empty").pack()
messagebox.showerror(self.t("mything.error.title"), self.t("mything.error", error=exc))
self.say("mything", "mything.refreshed")
```

```jsonc
// ✅ …and the key lands in ALL ELEVEN in the same commit, translated
// panel/locales/en.json   "mything.refresh": "Refresh",
// panel/locales/ru.json   "mything.refresh": "Обновить",
// panel/locales/de.json   "mything.refresh": "Auffrischen",
// panel/locales/fr.json   "mything.refresh": "Rafraîchir",
// …es it pt pl tr id vi
```

```jsonc
// ❌ en.json only, «the rest later» — the other ten silently show English
// and the tab looks finished in every screenshot anybody takes
```

`tests/test_panel_i18n.py` holds both halves — it fails on a key missing from any
shipped locale, and on a translatable literal handed to a widget, a menu entry or a
dialog anywhere under `panel/`. Run it before you call panel work done:

```
C:\Python312\python.exe tests\test_panel_i18n.py
```

The details a tab author needs — where the keys live, what happens when one is missing,
how to add a language — are in [`docs/panel-tabs.md`](docs/panel-tabs.md).

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

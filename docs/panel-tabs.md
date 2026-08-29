# Adding a tab to the panel

**Every new tab is a plugin. There is no other kind.** The shell (`panel/__main__.py`)
is a window with a notebook and a menu; it does not know what any tab does, and nothing
you add may make it know. (It used to hold the log as well — that pane is «Разработка»'s
now, out of `panel/runtime/log_view.py`, #1391.)

This is the how-to. The reasoning behind it is
[`docs/research/panel-tabs-refactor.md`](research/panel-tabs-refactor.md); read that
when you want to know *why*, and this when you want to write one.

---

## The short version

```
panel/tabs/mything.py          one file — or panel/tabs/mything/ when it grows parts
```

```python
from tkinter import ttk

from .base import PanelTab


class MyThingTab(PanelTab):
    ID = "mything"
    TITLE_KEY = "tab.mything"          # by convention `tab.<ID>`; the registry assumes it
    ORDER = 400
    LOCALE_NS = ("mything",)
    NEEDS = frozenset({"daemon"})

    def build(self) -> None:
        self.tr(ttk.Label(self.parent), "mything.hint").pack(anchor="w", padx=10, pady=10)


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(MyThingTab))
```

Then one line in `panel/tabs/__init__.py`:

```python
TabSpec("mything", "panel.tabs.mything", "MyThingTab", order=400),
```

and two locale keys (`tab.mything`, `mything.hint`) in **every** shipped locale —
**all eleven** files in `panel/locales/`, translated, in this same change
(see «Not a word of it is written in the tab» below). That is the whole registration:
the shell builds it, «Настройки →
Вкладки» lists it, the profile can switch it off, and

```
C:\Python312\python.exe -m panel.tabs.mything --profile main
```

opens it in a window of its own.

---

## What a tab declares

All of these are class attributes with defaults, so declare only what is true.

| | What it is | When to set it |
|---|---|---|
| `ID` | The key in the profile and the name on the command line. | Always. |
| `TITLE_KEY` | Locale key of the tab's label. **Must equal the registry's** — the notebook labels a tab before building it, and the contract test pins the two together. | Always; keep it `tab.<ID>`. |
| `ORDER` | Where it sits. Existing tabs are spaced by tens, so there is room between any two. | Always. |
| `DEFAULT_ENABLED` | Is it in a fresh profile's list. `False` for something most people never use — `develop` is the example. | Rarely. |
| `IN_DEVELOPMENT` | Is the tab still being written? Hidden entirely unless «Разработка» is on. Set the matching `in_development=True` on its registry entry too. | While it is unfinished — see below. |
| `PREFERRED_SIZE` | The standalone window's default geometry. | If `760x600` is wrong for it. |
| `LOCALE_NS` | The locale prefixes this tab owns. | Always — it is what keeps the locale files reviewable. |
| `NEEDS` | `"daemon"` / `"children"` / `"actions"` / `"schedule"`. Shown beside the tab on the «Вкладки» page, so a person can see what switching it on costs. | Always. |
| `SETTINGS` | `{key: default}` the tab adds to the Settings knobs. | If it has knobs of its own. |
| `LEGACY_KEYS` | `{block key: old flat key}` — how the profile spelled this setting before the tab existed. | Only when moving existing settings; see below. |
| `SETTINGS_PAGE_KEY` | Locale key of the page this tab contributes to «Настройки». | If it has a settings page. Then implement `settings_page(parent)`. |
| `AGGREGATES_TABS` | Does this tab draw parts contributed by OTHER tabs? Such a tab is built last, whatever its `ORDER` (below). | Only «Настройки» sets it. Set the matching `aggregates=True` on its registry entry too. |
| `TIMERS` / `TRIGGERS` | Errands the tab brings with it (§3.2). | If it has any; see below. |
| `EAGER` | Load at boot instead of on first show — and be DRAWN at boot with it. | Only if `ensure_loaded` brings up something that must be RUNNING. |
| `LAZY` | Is `build()` allowed to wait until somebody looks at the tab? **True by default**; see the section below for what it asks of you. | Never, unless your tab must exist before it is looked at — and then say why beside it. |
| `WEB_SCREEN` | Does this tab hand the phone a screen (`web_view` / `web_press`)? | Always, and `True`: since #1976 there is no tab that must not (below). |

`DEFAULT_ENABLED` is what a profile that has NEVER opened «Настройки → Вкладки»
behaves by — the code's own constant. A profile that HAS opened that page keeps
its own tick list from then on (`tabs.enabled` in its `config.json`) — except that
"its own" is not "written by itself": every profile but the `default` one stores
only what it overrides, and reads back `tabs.enabled`/`tabs.known` from the
`default` profile's own `config.json` for everything it never touched itself
(`panel/profile.py`, `_deep_merge`/`_deep_diff`, #1246). So the one place that
controls which tabs are on for every profile at once is the `default` profile's
own Settings page — tick a tab there and every profile that never ticked it for
itself picks it up on its next start. A profile that DOES want to differ (its own
tick list) keeps overriding the default exactly as before.

---

## A tab that is still being written

`IN_DEVELOPMENT = True` — plus `in_development=True` on the registry entry — means **this
tab is not finished, so nobody sees it** (#1273). It is not in the notebook, it is not
built, it draws nothing, offers no trigger, starts no capture and hands the phone no
screen. It is not even on «Настройки → Вкладки»: a box for a tab that cannot appear
whatever it says is a control that does nothing and explains nothing, so the page carries
one line saying where those tabs went instead.

**Development mode is «Разработка» being switched on, and nothing else**
(`panel.tabs.DEV_TAB`). There is no second checkbox on purpose. That tab already means
«this profile is for working on the bot» — it ships off, and it holds the sniffers and
the `actions/*.md` list — so a person who has ticked it has already answered the only
question a switch of its own would ask. Two switches would be two answers to one
question, with nothing to settle it the first time they disagreed; this way the mode
lives in the same list that shows what it unhides.

**Two things hang off that one switch, and they are meant to.** Having «Разработка» on
unhides the unfinished tabs (here), and the tab itself carries «Обновлять до dev-версии»
— whether the panel follows release tags or the branch tip (#1274,
`docs/panel-updates.md`). Both are the same answer to the same question: *is this profile
for working on the bot?* If a third thing ever needs it, it goes behind this switch too
rather than beside it.

**The mark hides; it never edits.** The profile's tick list is carried through
untouched and so is the tab's settings block (`tabs.config.<ID>`), so a profile that had
the tab switched on before the mark went on loses nothing — the tab simply stops being
built, and comes back with its settings the moment the mode is on or the mark comes off.
A hidden tab is also kept OUT of `tabs.known`, because «offered and declined» is what
`resolve` uses to tell a tab somebody unticked from one that did not exist yet, and a
tab that was never on the page can honestly claim neither.

**Where it goes.** On the class, beside `DEFAULT_ENABLED` and `WEB_SCREEN`, and on the
registry entry — the registry has to answer before anything is imported, exactly as it
does for `aggregates`. `tests/test_panel_tab_contract.py` pins the two to each other and
fails if one is changed without the other, so the mark cannot be half-removed.

**When it comes off.** When the tab's abilities have been proven in the LIVE game and
said so in `docs/farming.md` / `docs/farming.ru.md` — that confirmation is the whole
definition, the same one `CLAUDE.md` uses for calling any ability done. Take both
declarations off in one commit; `DEFAULT_ENABLED` then decides what happens next, and
every profile that never unticked the tab has it on the following start.

Nothing about this reaches the phone as a control: the mark is set in code, and the page
that lists tabs is a settings page rather than a screen action, so there is nothing to
mirror.

---

## `build()` runs when somebody looks, not when the page is made

**A tab is DRAWN the first time it is shown** (`LAZY`, #1215). The page makes every tab
it has — the class is imported, `__init__` runs, the tab is registered, its errands are
adopted, its saved block is handed over — and then stops. Fourteen of the fifteen are a
frame with nothing in it until somebody clicks.

That is not a micro-optimisation: a page is built when the panel opens and again the
first time a profile is switched to, and drawing every tab cost between one and a half
and eight seconds of a window that answered nothing
([`panel-freezes.md`](research/panel-freezes.md) §3) — 1334 ms → 471 ms measured on a
real page, 16 tabs drawn → 4.

### What it asks of you

Four things reach a tab that nobody has opened. Write for them and the flag needs no
thought at all:

| what reaches it | what that means for you |
|---|---|
| **its saved block** | The container hands it over with `restore()` and asks for it back with `stored_config()`. An undrawn tab hands back exactly what it was given, so nothing is lost. Anything `config()` reads that is not a widget — a plan, a set, a catalogue — goes in `__init__`, and then it is right either way. |
| **a trigger it declared** | It fires on the wire whether or not anybody is looking. Keep the state in `__init__` and guard the repaint: `stats.track` tallies into a file and posts a redraw that returns early with no grid, `DataTab.refresh_live` does nothing until the tab has been opened once. |
| **the phone** | `web_view` / `web_press` go through the runtime, which DRAWS the tab before asking it. The phone must not see less than the window. |
| **the lifecycle** | `panic`, `resume`, `on_profile_switch`, `on_language_change` and `shutdown` are NOT called on an undrawn tab. It started nothing and holds nothing, and it reads what it needs when it is first shown. |

### The state arrives with the BLOCK, not with the drawing (#2063)

`restore()` applies the saved block **whether or not the tab is drawn** — and it did not
until #2063, which is a live bug worth the paragraph. An undrawn tab held whatever
`__init__` guessed while the profile on disk said something else, so anything reading a
tab's state without drawing it read a default and called it the truth. The gear on
«Таймеры» drew `train_tickets = 0` over a profile that says `1`, and because a card saves
all of its knobs together, moving ONE of them wrote its neighbours' defaults down beside
it. From the person's side that is «поменял значение, а оно сбросилось на предыдущее».

**Nothing about `LAZY` changed.** `build()` still waits for a look, and so does every read
that costs the game anything. `apply_config` has always had to work with no widgets — a
panel with no window runs every tab through it with `parent is None` — and this is that
same call, made when the block arrives instead of when somebody opens the page. Applying
every tab's block for a real profile was measured at **3.5 ms for nineteen tabs**, and
none of them was built by it.

**So the trap, and it is the one the next tab author walks into:** the contract «a knob
works for a tab nobody has drawn» (`errand_options`) is broken the moment a value is made
in `apply_config` over state that only `build()` creates. `__init__` makes the state,
`build()` only draws it — and `apply_config` may write to that state and to widgets it
checks for, never to widgets it assumes.

A tab whose `apply_config` genuinely cannot run undrawn raises, is said on the debug
channel (`[tabs] <id>: saved block not applied while undrawn`) and is applied again at
`realize` — nothing is lost except that ITS knobs go on reading defaults until somebody
opens it. **«Командный пункт» is the one such tab today**: its four pages ARE widgets, made
in `build()`, and its state lives on them. It declares no errand knobs and no standing
order, so nothing behind a gear depends on it; a tab that did would have to move that
state into `__init__` instead.

So the rule of thumb is the one the duel already followed: **`__init__` makes the state,
`build()` only draws it.** `VsDuelTab` makes every variable, default and key of its week
in `__init__` and lays the six day frames out in `build()`; the plan its scenarios read
answers the same before and after anybody opens the tab.

### Reaching a tab that may not be drawn

`rt.tabs.get(id)` **draws the tab before handing it over** when you are on the Tk thread,
so ordinary cross-tab code needs no change. Off the Tk thread it hands over whatever is
there — widgets are made nowhere but the event loop — so a background caller that needs
more than the tab's own state hands the work over with `rt.post` first. `rt.tabs.peek(id)`
is the one that never draws (the container and the tests use it), `rt.tabs.drawn` is the
tabs somebody has looked at, and `rt.tabs.realize(tab)` draws one on purpose.

`tests/test_panel_tab_contract.py` covers all of it for your tab the moment it is in the
registry: that it is lazy, that an unopened one keeps its settings, and that a trigger
firing into an undrawn one neither raises nor draws it.

### Never wrap a label to a width you measured

The other half of the same bill. Laying blocks out in columns is ordinary — «Дуэль VS»
stands its six days in two, «Чеклист» its groups in three — and the columns themselves
are cheap: `columnconfigure(i, weight=1, uniform="<tab>.<thing>")` and a `grid`. What is
not cheap is **wrapping the text inside them to the width the column turned out to have.**

That reads as the obviously right thing to do and it is a loop: a wrap re-lays the frame
out, the re-layout fires `<Configure>`, the handler wraps again. «Дуэль VS» paid **2.3
seconds of page build** for it (#1211), and climbing out took an idle-time coalescer, a
style per day frame and a «is it already this wide» guard — machinery that exists only to
survive a decision.

So: **wrap to a constant** (`WRAP_PX` on the checklist), chosen a little narrower than a
column at the tab's usual width, and let `PREFERRED_SIZE` say how wide the tab wants to
be. One measurement per label, no handler, nothing that can feed itself. If a tab
genuinely cannot live with a constant, the coalescer in `vs_duel` is the pattern to copy
— and say in the diff why the constant was not enough.

And **measure the build, before and after, on the same machine** — «it felt the same» is
how 2.3 seconds got in. Building a tab in a throwaway Tk root and timing
`build()` + `update_idletasks()` over twenty rounds takes ten minutes to write and is the
only thing that tells a layout change from a layout accident.

### Columns that follow the width need a dead band

A layout that picks its number of columns from the pane's width has one failure mode
beyond the wrap above: **it flips.** `<Configure>` fires per pixel of a drag, and a
count computed straight off the width crosses a boundary back and forth while the mouse
hovers on it — the whole list redrawn twice a pixel, and unreadable while it happens.

So the count only GROWS once the next block fits with a margin to spare, and only
SHRINKS once the current one is short by the same margin. The band between two layouts
is then about twice that margin wide and a slow drag crosses it once. The redraw itself
is debounced through the profile's own ticker (`rt.tick.arm` under one name cancels the
pending one, so a drag costs exactly one redraw at its end), and the handler returns
without touching a widget when the count has not moved — which is what keeps the
`<Configure>` a redraw provokes from feeding itself.

**«Таймеры» is the worked example** (#1887): `TRIGGER_BLOCK_PX` / `TRIGGER_GUTTER_PX` /
`TRIGGER_HYSTERESIS_PX` and `_trigger_columns`, tiling the listeners 1–4 across. Two
things it gets right and are easy to get wrong:

* **A block, not the row of a table.** Five aligned columns cannot be repeated sideways
  — every copy would have to agree with every other on the width of each column, so the
  widest name anywhere decides the layout everywhere. A block of a constant width tiles.
  `columnconfigure(i, weight=1, uniform="<tab>.<thing>")` keeps the columns equal, and
  the weights are cleared across the whole span before they are handed out again, or a
  list that has just shrunk keeps the empty columns of the layout before it.
* **Column-major order.** The list still reads top to bottom in its own order however
  many columns it is broken into. Row-major scatters consecutive entries sideways, so
  «the next one» changes meaning with the width of the window.

And the phone's half of the same tab wants no arithmetic at all:
`grid-template-columns: repeat(auto-fill, minmax(<floor>, 1fr))` is one line of CSS and
no breakpoint anybody has to keep in step with the window's thresholds.

### A column of blocks silently eats the last one

**`pack` hands out the cavity in PACKING ORDER, and a widget packed after it has run out
gets a height of one pixel and is never mapped.** Not clipped, not scrolled off: absent,
with no error and nothing in the log. `side="bottom"` does not save it either — the side
says where in what is LEFT, not who is served first.

That is how «Разработка» lost its log (#1415). Five blocks packed one under the other —
the sniffers, the update tick, «Занятость», the scenario list with its editor, the log —
asked for **1382 px** on a page that had 620, the two `expand=True` blocks in the middle
took the remainder, and the log, packed last, was drawn and invisible at every window
size. The person reading it saw an empty half of a tab and reasonably concluded the code
had never been written.

So: **if a tab holds more than one screenful of separate things, it is a `ttk.Notebook`,
not a column.** A scrollbar is the other answer and is usually the worse one — hunting
for the log past a twelve-row editor is the same fault in a slower form. And the same
laziness applies one level down: **build a page the first time it is SHOWN, and let only
the visible one work.** `panel/tabs/develop.py` is the worked example — one `_sync_page`
that builds, shows and hides, `BusyView`'s once-a-second read armed only while its page
is on top, the log pane taken off the spool while it is not, and the open page remembered
in the tab's own block (`config()["page"]`). What that asks of you is what `LAZY` already
asks: **the state goes in `__init__`, the page only draws it** — otherwise a saved block,
a timer's run or the Stop button reaches a widget nobody has made yet.

---

## `ensure_loaded` vs `on_show` — the one that bites

They are not the same and the difference costs a game round trip on every start.

* **`ensure_loaded()` — bring up what the tab is FOR.** A capture listening for an event
  that will not wait for a click; a watcher spending a daily budget. Called at boot for
  an `EAGER` tab and on first show otherwise, so **it must be idempotent**. It always
  runs on a DRAWN tab: an `EAGER` one is built at boot for exactly this reason — what it
  starts usually asks its own checkbox whether it is switched on.
* **`on_show()` — somebody is looking.** A read that only draws. Called on every show,
  so a one-time seed gates itself on its own flag.

Putting a read in `ensure_loaded` on an `EAGER` tab makes every profile pay for it at
start-up, for a tab that may never be opened. The contract test asserts an `EAGER`
tab's `ensure_loaded` touches no game, and it is there because that exact thing
happened.

The rest of the lifecycle: `on_hide`, `on_profile_switch` (a different account — bounce
children, re-read files), `on_language_change` (only for what `tr` cannot re-render),
`shutdown` (the window is closing — children, listeners, `rt.tick.disarm(...)`, bus
unsubscribes).

`panic` / `resume` are still on the base class **and nothing calls them** (#1393).
Switching a profile off — the «Профиль работает» box on «Главная» (#1882,
`panel/runtime/power.py`) — is two acts: close the client, stop this profile's daemon; and
everything else holds still as a consequence: with no daemon there is nothing for a
timer, a trigger, the watchdog or the recovery to press through, and
`panel/runtime/gate.py` turns that fact into «and so they do not try». The pair is kept
because it is the right shape for the day something asks a tab to hold still again;
until then, overriding it is writing code nobody runs.

---

## The runtime is the only thing you get

`self.rt` is a `PanelRuntime` (`panel/runtime/host.py`). It is identical in the shell
and standalone, which is what makes a tab launchable at all.

| | |
|---|---|
| `rt.t(key, **fmt)` / `rt.tr(widget, key)` | words; `self.t` / `self.tr` are the same |
| `rt.say(tag, key)` / `rt.put(line)` | the log sink. **No widget of your own**: the line goes to `panel.log`, to the debug log and to the phone's «Лог» whether or not anybody is drawing, and the one pane there is belongs to «Разработка» (`rt.log_spool`, `panel/runtime/log_view.py`) |
| `rt.profiles` | the active profile's paths. **A file your tab wants to keep is asked for HERE, never built** — everything the panel stores is under `<project>/profiles/<name>/`, one file per thing, listed in [`panel-storage.md`](panel-storage.md). Needs a kind of file that is not there yet? Add the accessor to `panel/profile.py` beside its siblings; a path assembled in a tab is how the store came to mean two places at once (#1276) |
| `rt.settings` | knobs: `opt_int` / `opt_str` / `opt_bool` / `opt_float`, `vars[key]` (one Tk variable per knob, made by the runtime before any tab is built), and `changed()`. **Three of them are not knobs**: `launcher`, `game_exe` and `win_python` are `runtime.settings.MACHINE_KEYS` — one answer per machine, from `tools/lib/game_paths.py`, so a value in a profile's file is ignored and never written back (#1252). Read them the same way; do not offer a box for one. The daemon port is not typed either — `panel/runtime/provision.py` hands it out with the Windows session, one client per profile. |
| `rt.game` | `evaluator()`, `client`, `up()`, `claim()` / `release()`, `jump()`, `port()` |
| `rt.actions` | `run(name, args)`, `play(...) -> Outcome`, `run_text`, `resolve`, `problem` |
| `rt.play_async(name, args, …)` | run a scenario on a worker under the claim |
| `rt.children` | `spawn(...)` (a monitored child) / `spawn_raw(...)` (read it yourself). Both are **owned**: the runtime ends every child it started when the window closes, and a run that was killed rather than closed has its leftovers ended on the next start (#1212). Stop yours in `shutdown` anyway — that is what unticks the box and says so in the log; this is only the floor under it. |
| `rt.tick` | `arm(name, ms, fn)` / `disarm(name)` — **named**, so a loop started twice is started once |
| `rt.bus` | `publish(topic, payload)` / `subscribe(topic, fn) -> unsubscribe` |
| `rt.activity` | `with rt.activity.step("activity.x", **fmt):` — what the panel is doing right now, on the strip along the bottom of the window |
| `rt.tabs.get(id)` | another tab, **or `None`** — it may not be in this window |
| `rt.schedule` | the errands; built on first ask, started only by the shell |
| `rt.day` | when THIS profile's warzone starts a new day: `seconds_to_reset()`, `next_reset_epoch(after)`, `day_key()`, `boundary_ms()`. **Anything your tab counts «до сброса» or files under «today» asks here** — the game's day turns at the server's own 00:00 (02:00 UTC on the warzone this was measured on), which is neither this machine's midnight nor the same on every account. Never take a reading yourself and never divide a clock by 86400: the boundary is the client's own `GetTomorrowZero()`, kept per profile and refreshed by the schedule (#1333) |
| `rt.squads` | where every squad is and how much stamina is left: `at_base(n)` (`None` when it could not be read), `read(force=…)` off the Tk thread, `latest()` to draw with, `watch(fn) -> unwatch` — the poll runs only while somebody is watching. Built on first ask; the reading itself is `actions/read_squad_state.md`. |
| `rt.players` | THE ONE ENTRANCE to this profile's register of players (#1371): `sighted(records, source=…)` to write, `rows()` / `get(uid)` / `alliances()` / `servers()` to read, `set_note` and `forget` for the two things a PERSON does. **If your tab is told about a player while doing its own job — a chat line, a banner's members, an alliance roster, the owner of a tile — hand it over and nothing else.** Never ask the game for a top-up (that is the rule the register rests on), never write a field your source cannot actually know (a rally's `power` is a SQUAD's), and never open the file yourself: `panel/runtime/players.py` decides what may be written and stamps every field with who said it and when |
| `rt.post(fn)` | run `fn` on the Tk thread from a background thread. `self.post` is the same. **The only way back from a worker** — see «Coming back from a background thread» below |
| `rt.root` | for `bell()`, and for `after(<delay>, …)` ON THE TK THREAD — **not** to build into (build into `self.parent`), and never for a hand-over (`rt.post`) |

---

## Forbidden

1. **No game logic.** An ability is one `src/lastwar_bot/actions/*.md` scenario and the
   panel plays it — `CLAUDE.md` is binding on this. No assembling Lua, no walking a
   sequence of game steps, no holding an ability's gates (quota left, is-it-open-today,
   "collect first, then heal") in a tab. If the DSL lacks a primitive, add the
   primitive, document it in `docs/dsl.md`, then write the scenario.
2. **No `app`.** There is no app. If you catch yourself wanting `self.app._something`,
   the something belongs on the runtime or on your tab.
3. **No `import panel.__main__`, ever.** `python -m panel` executes that file *as*
   `__main__`, so importing it re-executes the whole panel as a second module. This is
   why the runtime exists. If you need something that lives there, move it into
   `panel/runtime/` first.
4. **No game in `build()`.** A standalone tab opens with no daemon, no client and no
   network. Everything live goes in `ensure_loaded` / `on_show`. The contract test
   builds every tab against a cold runtime and asserts nothing was asked of the game.
5. **No saving by yourself.** Return `config()`, accept `apply_config(raw)`, list
   `persist_vars()`; the container writes the profile. For a control that is not a Tk
   variable (a tri-state button, a combobox), call `rt.settings.changed()`.
6. **When you move a method here, bring its callers.** A method that leaves
   `panel/__main__.py` leaves a `self._whatever()` behind that still parses, still
   imports, and raises the first time that line runs. #1184 left three, and the one in
   `_apply_settings_to_ui` meant the panel did not open at all (#1191). What a tab has
   to re-draw after a restored value, the tab does at the end of its own
   `apply_config` — the shell must never name a widget it does not own. Run
   `C:\Python312\python.exe tests\test_panel_dangling_refs.py`: it fails on any
   `self.x` a class cannot possibly have, in the shell and in every tab.
7. **No words written in the tab.** `text="Обновить"` is a bug — every string a person
   reads is a locale key, in every shipped locale. The next section is the whole rule;
   `CLAUDE.md` is binding on it.
8. **No `rt.root.after(0, …)` from a background thread.** It looks like the free
   hand-over and it is the opposite of one: see the section below. Use `self.post`.

---

## What is NOT forbidden: a button that STARTS something

**«Состояние считается из игры, но выполнение можно вызывать.»** A tab that draws
readings may also offer to run the ability behind them, and that is ordinary rather than
a compromise. The line to hold is between the two verbs:

* **the state is READ.** Nothing a person does to the panel may change what a reading
  says. No box to tick, no «mark done», no counter the panel keeps for itself — the
  moment it kept one, the same errand done in the game, on a phone or by a second client
  would stop being counted, and the board would be confidently wrong instead of merely
  late;
* **the doing is OFFERED.** A press plays a scenario and then re-reads. Whatever the
  reading says next is what the row says next — including «still to do», when the game
  refused. A row that stays red after a press is information, not a bug.

They only look like the same rule. «Чеклист» lost its nine «Выполнить» to that confusion
(#1239 — «a button that starts something is a button somebody expects to have marked the
line»), and the board became something you could read but not use; #1257 put them back.
So when the temptation comes round again: **the objection is to MARKING, never to
pressing.** The way to keep them apart in code is to have exactly one path — the
checklist's `Errand.scenario` + `run(key)` — where a press plays the ability and calls
the refresh, and no path at all where anything writes a state.

Which lines get a button is a decision to be written down: nine of the checklist's
thirteen read errands have one. Two of the rest have no ability at all yet, and the
other two have an ability that has to PARK its targets with a tool before the recipe
can spend them (#1188), so a bare press of the recipe would succeed and rob nothing. That is in `.model`'s comments
beside the catalogue, and pinned by a test — because «no button here» has to be a reason
and not an oversight.

**A press does not need a reading beside it.** The two halves fail apart, and a line that
can be DONE but not SEEN is a real state: the checklist's «resource truck», «alliance
gifts» and «ministry» rows carry a scenario with no field at all (#1247). Such a row says
«состояние неизвестно» before the press and after it — nothing was read, so nothing is
claimed — and the scenario is what knows whether it may run and says so in the log. The
alternative was leaving the ability reachable only from the script list on «Разработка»,
which is off unless a profile asks for it; refusing the button until somebody works out
how to read the state punishes the player for a gap in the reverse-engineering.

### A board that reads the game is put back one group at a time

**A reading nobody has watched being right is not a reading yet.** «Чеклист» grew a whole
day's worth of rows faster than the rows could be checked against a running game, and a
line that quietly answers «готово» when it should say «ещё нет» is exactly the failure a
read-not-ticked board exists to prevent — with a tick beside it, which is worse than
having no line at all.

So the board draws **only the groups that have been confirmed live** (#1275). The rest
are switched off in the catalogue — `model.Group(..., shown=False)` — and switched back
on one at a time, each when its lines have been seen answering truthfully in a real
session. It is the same bar an ability clears before it earns its ✅ in `docs/farming.md`,
applied to a reading instead of to a press, and it is written in both places on purpose.

Two things make it safe to leave the code standing rather than deleting it:

* **off is off everywhere at once.** Everything both front-ends ask goes through
  `model.visible()` / `grouped()`, so a hidden group has no block in the window, no card
  on the phone, no press from either (`run` refuses a key that is not on the board, which
  is what stops `web_press` reaching one), no line in «сделано N из M», and not even the
  round trip that would read it — `refresh` plays only the scenarios the shown groups
  need. A group cannot half-exist;
* **on is one word.** The group keeps its place in `GROUPS`, its errands, its fields and
  its scenarios; bringing it back is `shown=True` and nothing else. A restore that costs
  an afternoon in the git log is a restore nobody performs, which is how «temporarily
  hidden» becomes «silently dropped».

What this costs, and it is a real cost: while a group is off, an ability whose only press
was one of its rows is reachable only from the schedule or «Разработка» — the three of
#1247 (the base's resource truck, the alliance gifts, the ministry application) are in
exactly that position. `tests/test_scenario_homes.py` reads the catalogue as TEXT, so it
still passes and cannot notice. That is accepted while the groups are coming back and is
not a licence to hide a group as a way of avoiding the homes rule: if a group is going to
stay off, its abilities need a press somewhere a person can reach.

### Where an ability's press belongs

**A new `actions/*.md` is not finished when it runs from «Разработка».** That list is the
tab for working on the bot, `DEFAULT_ENABLED = False`, so an ability whose only button is
there is one an ordinary panel does not have. Give it a press on the tab its theme
belongs to — a row on «Чеклист» for a daily errand, «Ралли» / «Карта» /
«Командный пункт» for one that needs a target chosen first — and mirror it into
`web_view` / `web_press` like any other control.

**Nor is a STANDING ORDER's switch, and for the same reason** (#2010). «Автолут отрядов»
— the ghost-recon order that spends five robberies a day — lived on «Командный пункт»,
which is also `DEFAULT_ENABLED = False`: the live profile had that tab off, so the order
was never built at all, and its switch, its level rule and «Ограбить всех» were reachable
from neither the window nor the phone. It is on «Секретки» → «Призрак: карта» now, the
page holding the list it spends, which is where «Автолут ★» has been since #1271. An order
belongs on the page holding its list, and that page has to be one every profile has.

A timer or a trigger is not that home. Both are real ways an ability runs, and neither is
a way for a person to say «сделай это сейчас»; three abilities lived in the timer
catalogue and nowhere else until #1247. `tests/test_scenario_homes.py` fails on a
scenario with no home, and its `EXEMPT` table is where a deliberate exception is written
down with its reason.

---

## One state, several places — a control may be drawn twice, never copied

A switch may appear in more than one place on a tab, and sometimes it should. What may
never appear twice is the STATE behind it.

**Why it comes up.** A control lives where it belongs to — the ★ sniffer's switch on the
★ page, the ghost sniffer's on the page its findings land on. That is correct and it is
not always findable. Live (#1264) the person reported both monitoring switches
«missing»: the ★ one had moved off the frame at the top of the tab, which still stood
there under its old title «Секретные задания» holding only the map sweep, and the ghost
one sat on a fifth page called «Призрак: карта» while the page anyone searches under is
called «Операция Призрак». Both boxes were built, mapped, and 400 px down a notebook
nobody had a reason to open. **A control in the right place that nobody finds is worse
than one in a slightly wrong place, because everything about it looks fine.**

**And a copy is undone when its reason goes.** The ★ one is drawn ONCE again (#1272):
what made it unfindable was a half-empty frame at the top of the tab that still claimed
the subject, and both that frame and the map sweep inside it are gone, so the box lives
with the list it fills and nothing above it is pretending to be about sniffing. The
ghost pair stays, because its reason has not changed — two pages, and the one people
search under is not the one its findings land on. A second copy is a cost (two places
to edit, one variable to keep believing in), so it is paid where it buys findability and
withdrawn where it stops.

**How to draw it twice.** Bind both widgets to the ONE variable the tab already has, and
give both the same `command`:

```python
# ✅ the page its findings land on, and the page people search under — one variable
self.tab.tr(ttk.Checkbutton(bar, variable=self.monitor_var,
                            command=self.tab.ghost_capture.toggle),
            "secret.monitoring.ghost")
self.tab.tr(ttk.Checkbutton(other, variable=self.monitor_var,
                            command=self.tab.ghost_capture.toggle),
            "secret.monitoring.ghost")
```

```python
# ❌ the version that rots: a second variable, kept in step by hand
self._monitor_top = tk.BooleanVar(value=self.monitor_var.get())   # agrees today
```

Tk moves every checkbutton bound to one variable, so the pair cannot disagree even in
the cases nobody wrote code for — a capture that stops on its own, a config restored on
start-up, a press arriving from the phone. A hand-synchronised copy agrees until the
first of those, and then one of the two is lying with no way to tell which.

Same on the phone: the SAME action `id` on both cards, built by one small method rather
than two literals, so the next edit to that button lands in both places
(`_ghost_monitor_action`). And say what it turns on rather than just «Мониторинг» — a
screen with two of them is scrolled past its own card titles.

**A duplicate is a decision, not clutter.** Write beside it why the second one is there
and that it shares the variable; `tests/test_panel_secret_tasks_switches.py` counts the
boxes and asserts they name one variable, so removing a copy as «tidying» fails rather
than quietly returning the tab to the state that was reported as broken.

**This is not the mirror rule.** Window ↔ web is about the same control existing on
BOTH front-ends. This is about the same control appearing more than once on ONE of them
— and both rules end in the same place: one state, however many places show it.

---

## Coming back from a background thread

A tab reads the game off the Tk thread and then has to paint what it found. **That
hand-over is `self.post(fn)`, always.**

```python
def refresh(self) -> None:
    threading.Thread(target=self._work, daemon=True).start()

def _work(self) -> None:
    data = self.fetch()                 # the game, on a worker
    self.post(lambda: self.render(data))   # ✅ back to the Tk thread
    # self.rt.root.after(0, lambda: self.render(data))   ❌ never
```

`after(0, …)` from a thread that is not Tk's does not schedule anything. tkinter
registers a Tcl command for the callback and then makes the `after` call, and from a
foreign thread `_tkinter` runs neither: it queues each as an event for the Tk thread and
**blocks the caller** until the event loop gets round to it. Measured with four profiles
open, that is **8.6 ms on average and 17 ms at the tail, per hand-over** — so a tab of
one profile reporting a reading sits on the thread that draws all the others, and every
other profile's work sits behind it (`tools/dev/panel_thread_bench.py`,
docs/research/multi-profile-panel.md §12). `post` costs 17 µs and touches no Tk at all.

It is also the difference between working and not during the BOOT. While the window is
pumping `update()` by hand — which is most of a panel's start-up — the same call raises
«main thread is not in main loop», and that killed the thread that made it: a monitor
that ended during those seconds left its checkbox ticked for a process that had gone.

The same applies to `rt.settings.opt_*`: read them from wherever you like. They answer
from a thread-safe mirror off the Tk thread and only touch the variable when the caller
IS the Tk thread, so a background read costs a dict lookup rather than a round trip
through the window.

`tests/test_panel_parallel_profiles.py` parses everything under `panel/` and fails on the
next `after(0, …)` written.

---

## Settings, and moving existing ones

A tab's block lives at `tabs.config.<ID>` in the profile. `config()` returns it,
`apply_config()` restores it, `persist_vars()` lists the variables whose change means
"write now". Those three are yours; the container talks to them through `restore()` and
`stored_config()`, which is what makes an unopened tab safe to save (above) — you
implement the first three and never call the last two.

When you are **moving** settings that already exist as flat keys, `LEGACY_KEYS` maps
your block's key to the old flat one, and the binder reads either. Two rules:

* **Do not rename a key in the same change that moves it.** «Secret Tasks» spells all
  fourteen of its keys exactly as the flat profile did, so `LEGACY_KEYS` is an identity
  map. A lost setting and a migration bug look identical; keep them apart.
* The container **dual-writes** for one release — the new block and the old flat keys —
  so a profile touched by the new panel still opens in the old one.

### The page a tab contributes, and why the order matters

`SETTINGS_PAGE_KEY` + `settings_page(parent)` puts a page of your own inside
«Настройки». It travels with the tab: switch the tab off in the profile and its page is
gone too, which is the whole point of the aggregator (§6 of the refactor notes).

**The order tabs are built in is not the order they sit in.** «Настройки» walks
`rt.tabs.live` and asks each tab for its page, so it can only draw the tabs that already
exist — and it sits at `ORDER` 40 while most contributors are in the hundreds. That is
what `AGGREGATES_TABS` is for: a tab that declares it is built LAST
(`panel.tabs.build_order`), keeping its place on the strip.

It is worth knowing because of how it fails. A contributor built after the aggregator
raises nothing and logs nothing — its page is simply not there. «Автосбор» vanished that
way and stayed vanished, and with it the squad list the rally auto-join spends, so the
auto-join read an empty list and refused every time (#1237). If you add a second
aggregator one day, set the flag in both places and let
`tests/test_panel_tab_contract.py` pin the order.

**No tab uses this today**, and that is worth saying rather than leaving to be
discovered. «Автосбор» was the only contributor and it moved onto the «Ралли» tab in
the same task: nothing on it was a knob of the PANEL — not a path, not a port, not an
interpreter — it was all about rallies, and it belongs beside the switches that spend
it. Before you reach for `SETTINGS_PAGE_KEY`, ask whether your page is really a panel
setting or just a setting your tab happens to own. If it is the second, put it on the
tab; «Настройки» is for the things that are true of the installation rather than of the
game.

---

## Listening on the wire — subscribe, never spawn

A tab (or anything else) that wants to hear a game push asks the runtime's one ear:

```python
self._off = self.rt.wire.subscribe("push.alliance.march", self._on_march)
...
self._off()          # in shutdown / on_hide — the ear closes with the last subscriber
```

**Never spawn `wire_event_monitor.py` yourself.** One capture per profile carries the
union of every subscribed pattern and dispatches by substring in Python
(`panel/runtime/wire.py`). A process per listener is what this replaced: each opened its
own npcap handle on the same interface and decoded every packet the game sent to read
one command name out of it, and with a runtime per open profile the bill was
*listeners × profiles* — every term the same work done again.

Three things to know before you subscribe:

* **the callback runs on the child's reader thread**, not on Tk. Hand work to a queue;
  anything that draws goes through `self.post`;
* **it is called with `None` when the ear closes.** That is «the capture died», not a
  command — treat it the way the trigger watcher does, by forgetting the subscription
  and re-subscribing on the next sync;
* **an empty pattern is refused**, because `"" in command` matches everything and a
  typo would quietly subscribe you to the whole of the game's traffic.

A capture that decodes payloads rather than matching command names — the rally monitor's
army archive, the leaderboard collector — is still a child of its own; the hub carries
command NAMES, and folding those in would mean moving their decoding into it.

**A capture you spawn yourself must still be told whose client it is.** Two accounts of
the same game dial the same server port, so the packet filter cannot separate them and a
capture hears both — one profile's auto-join spending squads because the other's alliance
raised a banner. Pass the profile's pids and the capture keeps only those sockets:

```python
for pid in game_process.profile_pids(self.rt.settings):
    cmd += ["--client-pid", str(pid)]
```

An empty answer means «could not tell», and then the capture stays machine-wide on
purpose: losing the separation is a fair price for an unanswerable question, while a
capture that went deaf would make a profile farming nothing look like one with nothing
to do.

**Everything a child prints lands in `panel.log`, so two things never go on its
lines: an identifier, and a heartbeat.** A capture writes for a person watching a
terminal; the panel logs it for months into a file people attach to a bug report. The
leaderboard collector was both at once — a progress line every 15 s and a line per
collected row carrying a player's name and uid: 5 115 ticks and 2 943 named players in
one live profile's log (#1293). The answer is the same on both counts and it is the
PARENT's job:

* **ask the child to be quiet** (`--quiet` on `scan_leaderboard.py` and on
  `wire_event_monitor.py`) so the identifiers never cross the pipe, and let it print
  one machine-readable line of COUNTS per tick instead;
* **roll the counts up in an `on_line` filter**: return `False` to swallow the marker,
  say the first one at once so the person can see the child is alive, and after that a
  line no oftener than a window (`LEADERBOARD_NOTE_SEC`, `HEARD_NOTE_SEC` — ten
  minutes), carrying what piled up inside it.

The data itself is not the problem and does not move: the boards go on being written to
the profile's own `leaderboard_history.db`, the tiles to its checkpoint. It is the LOG
that has no business holding somebody else's account id.

**The one deliberate exception: the rally feed keeps its nicknames.** `[rally]` lines
name the alliancemates in a banner, and that was looked at in #1293 and kept, not
missed. It is a FEED a person reads about their own alliance — who raised the banner and
who is in it is the useful half of the line, and the same names are on screen in the
client. The repository's identifier rule is about what LEAVES the machine: code, tests,
fixtures, docs, examples. A profile's `panel.log` is gitignored and goes nowhere. So do
not «clean» those names out on the next pass; what must never carry a real nickname or
uid is anything committed.

---

## Errands a tab brings with it

If the thing your tab does should also happen on a clock or when a push lands, declare
it rather than wiring it:

```python
TRIGGERS = (TriggerSpec(name="mything_refresh", event="push.some.thing",
                        handler="refresh_live"),)
```

`handler` names a **method on your tab**. The schedule binds it when the tab is built —
which means a trigger whose tab is not in this profile is **not offered**: no listener
is spawned and nothing fires into a tab that is not there. Set `needs_game=True` if the
handler needs the client up; otherwise it runs before the daemon gate, which is right
for a repaint that degrades gracefully.

`scenario=` instead of `handler=` names an `actions/*.md` and stays data — that belongs
to the bot, not to your tab, and is always offered.

---

## Not a word of it is written in the tab

Everything a person can read comes out of `panel/locales/`. Not «most of it», not
«everything except the little ones» — the label, the button, the checkbox, the hint, the
column head, the window title, the message box, the line in the log:

```python
# ❌ the tab speaks for itself
ttk.Button(self.parent, text="Обновить", command=self.refresh).pack()
ttk.Label(self.parent, text="Ничего не прочитано").pack()
messagebox.showerror("Ошибка", f"не удалось: {exc}")
self.rt.put("[mything] обновлено")

# ✅ the tab names a key and the runtime says it
self.tr(ttk.Button(self.parent, command=self.refresh), "mything.refresh").pack()
self.tr(ttk.Label(self.parent), "mything.empty").pack()
messagebox.showerror(self.t("mything.error.title"), self.t("mything.error", error=exc))
self.say("mything", "mything.refreshed")
```

`self.tr(widget, key)` registers the widget, so it re-labels itself when the language
changes; `self.t(key, **fmt)` is for a string you build yourself (a dialog, a treeview
cell, a status line) and has to be re-asked in `on_language_change`. Placeholders are
`{named}` and go through `str.format` — never glue a translated fragment onto another
one, because the order of the pieces is not the same in every language.

**And a key is added to every shipped locale in the same change, translated.** Three
files today: `en.json` (the canonical one), then `ru` `de` `fr` `es` `it` `pt` `pl` `tr`
`id` `vi`. Not English first and the others «when there is time» — a missing key falls
back to English *silently*, so half a tab in the wrong language looks exactly like a tab
that is finished, and nobody finds out for months. Add the key to all eleven or the tab
is not done.

You do not translate the game's own words. Anything the game has already named — a
rally, the Doom Elite, Ghost Ops, a Secretary — is copied out of the client's own
tables: the list is [`game-glossary.md`](game-glossary.md), and
`tools/game_locale.py --term "..."` answers for anything not on it.

The only literals allowed are the ones nobody reads as words — a numeric format
(`"(%d–%d)"`), a separator, a Tk option value, an internal tag such as the `label=`
handed to `run_text`. **If it can be translated, it is a key.**

`tests/test_panel_i18n.py` enforces both halves and takes a second:

```
C:\Python312\python.exe tests\test_panel_i18n.py
```

It fails on a key any shipped locale is missing (in either direction — a key nobody
uses any more has to go from all of them at once), and on a translatable literal handed
to a widget, a menu entry or a dialog anywhere under `panel/`.

The fourth is the phone's copy: that the two exempt tabs still have no screen, that
every word a screen names is a locale key that exists, that a screen is made of nothing
the renderer cannot draw, and that a button offered on a screen has a `web_press` that
answers for it. What it CANNOT check is «one side was edited and the other was not», in
either direction — that is a property of a diff, not of a snapshot, and it rests on the
rule and on review.

---

## A language is a file

There is no list of languages anywhere in the code, and none may be added. The Language
menu IS `panel/locales/`: the code comes from the file name, the label from the
`language.name` key **inside** that file, written in its own script.

So a person who wants the panel in their own language copies `en.json` to `fr.json`,
translates the values, sets `"language.name": "Français"` — and it is in the menu on the
next start. Nothing else is touched. (That is how the other ten got here: each is a file
and nothing else. What changed by shipping them is only the size of the chore — a new
key now has eleven translations to write instead of two.) (The label lives in the file rather than being
derived from the code because only the file can say it in its own script: a table of
`de → Deutsch` somewhere would be the same hard-coded list under another name, and a
bare `de` in the menu is not a language anyone recognises. `language.name` is spelled
like every other key so it is translated, reviewed and diffed with the rest.)

Ask through the runtime, never past it:

```python
self.rt.i18n.available()      # ['en', 'de', 'es', 'fr', …] — codes, default first
self.rt.i18n.name("ru")       # 'Русский' — what ru.json calls itself
self.rt.i18n.known("fr")      # is there a locale for it?
```

What it does when things are missing, because the panel now reads whatever is in that
directory and has to survive it:

| | |
|---|---|
| no `language.name` in the file | it still appears, labelled with its bare code |
| a key the file does not translate | falls back to English — a half-finished locale is usable |
| the file is not valid JSON | an empty locale, everything falls back; not a crash |
| the panel's saved preference names a language with no file | English **and a line in the log** naming it; the remembered choice is not rewritten, so the language returns by itself when the file does |

What this means for a tab author is only what it always meant: put your keys in **every**
shipped file. `tests/test_panel_i18n.py` pins the rest, including that the table of
languages has not come back.

---

## Is the feed arriving? — the flow strip on a grid (#1549)

**A table that is empty says nothing about why.** Four completely different things draw
the same blank page: nothing is being sent, something IS being sent and the tab is not
taking it, it was taken and thrown away, or the source is dead. Telling those apart by
hand is what «грид не заполняется» has cost, repeatedly — the last time, a monster page
showed 1 row while the client's own register held 176.

So a grid that is fed by a stream names its RECEIVER, and the panel draws the answer
above the table:

```python
class MineGrid(WorldGrid):
    INTAKE = "world.checkpoint"        # a name in panel/runtime/intake.py
```

That is the whole declaration. `TaskGrid.build` then draws the strip, `TaskGrid.tick`
rewrites it once a second, and `TaskGrid.web_flow()` hands the same badge to the phone —
attach it to the card as `"flow"` and the browser's one renderer draws it:

```python
{"title": "world.mines", "items": ..., "flow": self.mines.web_flow()}
```

A tab whose list is not a `TaskGrid` (the ★ table, the rally block, the chat pane) asks
`panel/runtime/flow.py` directly and draws the same three things — `flow.badge(rt, name)`
for the record, `flow.line(badge)` for `{key, fmt, colour}`, and `self.t(key, **fmt)` for
the words.

**What the strip distinguishes, and why it is the point:**

| state      | what it means                                            |
|------------|----------------------------------------------------------|
| `flowing`  | something arrived within the last minute                  |
| `quiet`    | it worked, and has said nothing for a while               |
| `refused`  | **the ask is not getting through** — refusals now, no arrivals |
| `never`    | nothing has ever arrived here                             |
| `starving` | **the source IS heard from and we are taking none of it** |
| `losing`   | something was accepted and thrown away — never ordinary   |
| `dead`     | the source ran and is not running any more                |
| `off`      | the source has never been started — a switch, not a bug   |

`refused` against `quiet` is the other half of the same idea, and it was added after the
operator asked «пока таймаут, данные пропадают или как?»: with the client's sockets
half-closed the monster poll recorded 223 refusals in nineteen minutes and the strip said
«тихо», which is the sentence for a map with nothing on it and sends a person to look at
the map instead of at the client.

`starving` against `never` / `quiet` is the distinction the module exists for: «данных
нет, потому что их не присылают» and «данные идут, но мы их не берём» lead a person to do
opposite things, and drawing them alike is what cost the days.

**Freshness is of an ARRIVAL, never of a refusal.** `intake.Counter.last_in` moves on
`seen` and on nothing else, so a poll that records a `dropped` every twenty seconds while
the client is in the base does not paint the page green.

**A receiver with no listener behind it has no source, and says so.** The monster page is
ASKED (nothing on the wire names a monster), so `flow.SOURCES["world.monsters"]` is empty
and the badge never claims a dead capture it does not have. A new receiver is one line in
that table — `tests/test_panel_flow.py` fails on an `INTAKE` the table has never heard of.

## The phone's copy of this tab, and keeping it in step

The panel has two front-ends: this window and the web one a phone opens
(`panel/web/`, docs/research/panel-web.md). A tab hands the second one its screen as
DATA and the browser draws it with a single renderer:

> **While #1976 runs, the web is the MAIN front-end and the window is the copy.** The
> person's words: «Веб теперь главный инструмент, ему и полный функционал». So anything
> NEW is written in `web_view()` / `web_press()` only, and `build()` is touched just
> enough to keep control from being lost before Tk is deleted. Read the mirroring rule in
> `CLAUDE.md` with that inversion in place: window → web still binds, web → window is
> suspended, and a control the phone has and the window has not is now the ordinary case.

```python
WEB_SCREEN = True                       # this tab has a phone screen

def web_view(self) -> dict:
    """What the tab HAS — never a read of the game (see below)."""
    return {"cards": [{"title": "tab.hospital",
                       "rows":  [{"label": "hospital.wounded", "value": "128"}],
                       "items": [{"text": "Иванов", "detail": "30 · 12 480 000",
                                  "facts": [{"label": "rally_tab.soldiers",
                                             "value": "4200"}],
                                  "until": 1785776747.0,
                                  "pill": "squads.kind.home",
                                  "actions": [{"id": "join", "label": "rally.join"}]}],
                       "empty": "tabx.no_game"}],
            "now": time.time(),
            "actions": [{"id": "refresh", "label": "tabx.refresh"}]}

def web_press(self, action: str, args: dict) -> dict:
    return {"ok": True} if action == "refresh" else {"error": "unknown"}
```

**A press has THREE answers and `unknown` is only one of them** (#1331). `{"ok": True}`
is «сделано или запущено»; `{"ok": False}` is «отказано», and add `reason` — a locale key
or the game's own words — when the tab knows why; `{"error": "unknown"}` means **this tab
has no such press** and is answered as a 404, which the page draws as «панель не знает
такого нажатия». Never use the last one for a press that merely did not happen: the panel
would be telling somebody their button does not exist, and the first thing anybody does
about that is press it again. There is a fourth answer the tab never writes — the panel
adds `pending` by itself when the press outlives `panel/web/api.py::PRESS_TIMEOUT_SEC`,
and the page says «принято — выполняется». Nothing is cancelled by that: `web_press` runs
on the Tk thread and is allowed to be slow, but everything slow inside it still sits on
the thread that draws every open profile, so the work belongs on `rt.play_async`'s worker
exactly as it does for the window's own button.

**A press can belong to a card or to an item, not only to the screen.** `actions` at the
top level is the screen's own row of buttons; the same list ON A CARD is drawn as that
card's footer, and on an ITEM beside that row. Pick by what the press belongs to:
«События» puts «Атаковать сейчас» on the event's card (#1257), «Чеклист» puts one on each
errand row that is a scenario. All three reach the same `web_press`, so an id has to be
answered wherever it was offered — and an item's action carries `args`, which is how a
row says WHICH errand it is.

**A card of PLACES is drawn as small buttons, not as a row apiece** (#1999). A card may
say `"layout": "tiles"`, and then its `items` are laid out as a wrapping grid of tiles
instead of full-width rows — two or three columns on a phone, more on a wide screen,
never a breakpoint. A tile carries the item's `text` (a coordinate, which is already the
press that goes there), its `detail`, its first TWO facts as bare values with the
label kept as the tooltip, its `pill` and its own `actions`. Everything else — the
`note`, the third fact — is deliberately left off, and a card that needs the prose is a
card that stays rows.

The person's words, about «Карта»: «делаем не грид с секретками в одну строку, а
небольшие кнопки с минимальной информацией». That screen sends 285 starred tiles, 288
warzones and thousands of monsters, and a row apiece is a page nobody reads to the end
of. Which cards it applies to is a table on the tab (`TILE_CARDS` on «Карта» and on
«Секретный командный пункт»), attached in one loop rather than typed into ten card
literals — the same shape as the flow strip beside it, and for the same reason: an
eleventh page is then one line and not an eleventh place to forget.
`tests/test_panel_web_screens.py` fails on a table naming a card that no longer exists.

**A tile whose name is a coordinate IS the press, and the press is the jump.** Tapping
anywhere on it plays the same `goto_coord` an underlined coordinate in a line of prose
plays (#1982) — one place in the front-end answers for both, so they cannot drift. Never
the robbery: walking the camera costs nothing and undoes itself, where a robbery spends
one of the day's five and does not come back. A press the TAB offered stays a button of
its own on the tile and presses **only** itself; an item whose name is not a place — a
warzone number, a player — is left a plain tile with whatever buttons it came with.
Nothing is guessed here: the panel marks the coordinates it sends
(`panel/web/coordlinks.py`), and a tile is a button exactly when there is a mark to press.

**A card may SET rather than show** (#1976). `fields` is a list of knobs — `key` (the
knob's own id, data), `label` and an optional `hint` (locale keys), `kind` (`switch`,
`number` or `text`, decided by the type the knob was DECLARED with, never guessed from
its name — `panel/runtime/opt_value.py`), `value` in that same type, and `min`/`max` for
a number. The renderer draws the control the kind names and moves it by pressing `set`
with `{"key": …, "value": …}`, so the tab that owns a knob answers for it in `web_press`
and nothing about the knob's MEANING leaves the tab. A card may also carry `note` — a
locale key, drawn under the heading, for the sentence a page needs before its controls.

The renderer draws a card's **fields above its rows**: readings explain a card, knobs
are what a person opened it to move, and «Ралли» carries three switches over a table of
sixty-eight budget lines — a control under that table is a control nobody scrolls to.

**A knob may travel where the PRESS beside it may not.** «Операция Призрак» has its
switch and its minimum level as fields while «Ограбить» is still absent, because the
robbery spawns a tool to park its targets first (`CLAUDE.md`, #1188) and the switch is
merely the rule the panel's own watcher obeys. Ask which of the two a control is before
deciding it cannot travel.

**Which fields are words and which are data is fixed.** `title`, `label`, `empty`,
`pill` are **locale keys** and are said by the browser out of the panel's own table;
`text`, `value`, `detail`, `note`, `head` and a fact's `value` are **data** — a player's
name, a count, a date.

That is what puts a screen in eleven languages by construction:
the i18n test only reads `t()` calls in `.py`, so a sentence written into a dict would
sail past it. `tests/test_panel_web_screens.py` reads the views instead and fails on a
label that is not a key.

**A press may ask for a WORD** (#1335). An action with `prompt` — a locale key — opens
the phone's own text box before it fires, filled with whatever `value` the action
carried (data: somebody's note), and what is typed arrives as `args.text`. Cancelling
presses nothing at all. It exists because the renderer could otherwise only ever READ a
free-text field and never write one, which would have made every such field a
window-only control — an omission dressed as a divergence. The register's own mark on a
player is the first of them.

**A press that DELETES asks first** (#1976). An action with `confirm` — a locale key,
with `confirm_fmt` filling its placeholders — opens the phone's own «are you sure?» in
the panel's language before it fires, and a cancel presses nothing. It is for the
destructive ones only: «Удалить набор» on «Дуэль» asks in the same sentence the window's
message box asks in. An ordinary press wearing a confirmation is a press that arrives a
second late every single time, which is why «Стоп» deliberately has none.

**A picture is a LINK, never bytes.** An item may carry `avatar` — a URL into the
panel's own picture route, `"/api/avatar?face=<file name>"` — and the browser draws it
before the title and drops it silently if it will not load (#1324, «Ралли» draws the
face of everybody standing in a banner). It is a link and not a payload because
`web_view` runs on every poll: twenty photos inside the view would be a megabyte a
minute to leave a screen open, where a link is fetched once and then cached. Build it
with `panel.tabs.rally.roster.face_url`, which sends only the file's NAME — the route
serves one folder (`game_paths.avatar_cache()`) and `player_faces.file_named` checks the
name three ways rather than trusting it.

`until` is an epoch and `now` is the PANEL's clock: the phone counts down against the
panel's time rather than its own, because a tablet an hour out would otherwise call
every deadline expired.

**`web_view` must be CHEAP, and since #1272 that is load-bearing rather than polite.**
It runs on the Tk thread every time a phone opens the screen **and on every poll while
the phone is still looking at it** — about every 2.5 s with the screen up, every 15 s
with the phone in a pocket. Before that it ran once per opening and the screen then sat
frozen for as long as anybody read it: countdowns stopped, counts stopped, standing
orders stopped. So it returns what the tab already holds, and a `web_view` that reads
the game is now a client polled all day rather than a slow screen. Reading the game
belongs in the tab's own refresh, which the phone asks for by pressing «Обновить». The
six `DataTab` tabs get this for free: the base class caches the last reading and only
the mapping (`web_cards`) is each tab's own.

### It travels in the same commit, in BOTH directions — this is binding

`CLAUDE.md`, «An edit travels between the window and the web, in BOTH directions, at
once». Two front-ends that drift are worse than one, because whoever is reading the
stale one has no way to know that is what they are reading.

| you changed | you also change, in the same commit |
|---|---|
| `build()` — a button, a field, a reading, a status line | `web_view()`, and `web_press()` if it is a press |
| `web_view()` — a card, a row, a fact, an action | `build()`, so the window has it too |

The second row is the one people forget. A control that exists only on the phone is a
control the person at the machine cannot find, and the next agent reading the tab has
no idea it is there — the drift is simply pointing the other way.

Three things bound it:

* **A press travels only when the ability is a scenario.** `web_press` runs
  `rt.actions` / `rt.play_async` and nothing else. Where a tab still drives the game by
  hand — or half by hand, pressing through a scenario but spawning a tool to park its
  targets first — the web gets the reading and no button. First the whole ability through
  `rt.actions`, then the button. Both robberies were in that state and neither is: the
  queue is an `ARGS` of the recipe now (#1272 the secret task, #1976 the ghost), so a
  «recipe cannot fill the queue it spends» is a fact about `TAP`, not about a recipe.
* **A DIVERGENCE IS NOT YOURS TO DECIDE.** When the two sides genuinely should differ —
  something impossible on a phone, something pointless in a window — that is a
  conversation with the person, not a judgement call. Ask, agree, then write the
  exception with its reasoning into `CLAUDE.md` and into this file. Until it is written
  down it does not exist, and the rule stands. What is forbidden is the silent version:
  shipping one side, deciding alone that the other does not need it, leaving no trace —
  after which nobody can tell an exception from an omission.
* **NO tab is without a screen any more, and `develop` was the last one (#1976).** It
  was a legal exception — proposed, argued, agreed — and it was ended by the same
  conversation that made it, which is the only way one may end. «Two sniffers for working
  on the bot» was true of the SNIFFERS and never of «Занятость» on the same tab: the
  threads, the queue, the claims and who waits for whom answer «почему панель ничего не
  делает», the one question somebody away from the machine cannot ask any other way. So
  the tab has a screen, and what does NOT travel is written inside it: starting a
  recording asks for a label in a message box, stopping it asks whether to keep the run,
  and a phone cannot answer either — the screen shows what is being recorded and a press
  naming a sniffer is answered «unknown». `tests/test_panel_develop_screen.py` pins both
  halves. **A new exception is still added the same way: ask, agree, write it in both
  files, pin it in the test.**
* **`settings` used to be the second, and #1976 ended it.** That exception — «breaking a
  profile with one thumb is easier than fixing it from a bus» — held while there were
  two front-ends and the window was the safe one. The panel is going to have ONE (the
  window is being retired, `docs/research/panel-service-and-spa-plan.md`), and a knob
  with no screen is then a knob nobody can reach, which is worse than one somebody can
  get wrong. **What survives of the reasoning lives inside the screen:** the four values
  that decide WHICH CLIENT a profile drives — the two machine paths, the daemon port and
  the Windows session — are readings there and never fields, and a `set` press naming one
  is answered «unknown». The test pins that too.
* **There were THREE, and «Веб» is now a section of «Параметры» rather than a tab
  (#1313, #1509).** The divergence did not change — the door the person came in
  through is still not opened from the far side of it — but its subject did: one
  server answers for every open profile, so the port, the token and the certificate
  are the WINDOW's and live in the panel-wide `profiles/settings.json`.
  `panel/runtime/web_control.py` owns them, `panel/runtime/web_dialog.py` draws them —
  first as its own menu entry, and since #1509 as one row in the sidebar of the single
  «Параметры» modal (`panel/runtime/settings_dialog.py`) beside «Профиль», «Язык» and
  «Автозапуск», every switch of that kind behind one door instead of four — and the
  same test pins both halves: no `web` tab in the registry, and no route in
  `panel/web/api.py` that can reach the setting. Anything else a screenless corner of
  the panel needs on the move goes the way «⟳ Перезапустить панель» did — onto
  «Состояние» as a press.
* **A control added to the one standing divergence («Веб») is covered by it, not by a
  new one** — but say so where you add it, or the next reader cannot tell. «Обновлять
  до dev-версии» on «Разработка» (#1274) used to be the worked example of that, and is
  now the worked example of a divergence ENDING: the tick is a `switch` field on the
  tab's screen since #1976, written through the same `set_dev_updates`, and what the
  phone already had — the version line on «Состояние» carrying the `+N-dev` mark — is
  still there beside it. See `docs/panel-updates.md` §4.

## Reaching another tab

Through the runtime, and tolerating absence:

```python
other = self.rt.tabs.get("secret_tasks")
if other is not None:
    other.refresh()
```

If it is a fact rather than a call, publish it: `rt.bus.publish("inventory.changed")`.
The bus is deliberately tiny — no wildcards, no ordering, no replay. `subscribe` returns
the unsubscribe callable, and `shutdown()` must call it.

---

## Saying what you are doing

Anything of yours that takes more than about a quarter of a second — a read of the game,
a child being started, a list being rebuilt — says so while it runs:

```python
with self.rt.activity.step("mything.reading", n=len(rows)):
    rows = self.fetch()
```

The shell paints the newest live step of every open profile on the strip along the
bottom of its window; a tab launched on its own has nobody listening and pays a
dictionary insert. **A step is a locale key and its arguments, never a sentence** — the
words are said by whoever draws them, in whatever language that window is showing, which
is also what lets a worker thread report without knowing the language at all. Several
steps may be live at once and the newest wins; when it ends, whatever is still running
underneath comes back into view.

Use it for work, not for state: it is «reading the roster», never «12 members». What a
tab has FOUND belongs on the tab, and what has HAPPENED belongs in the log.

---

## Before you call it done

```
C:\Python312\python.exe tests\test_panel_tab_contract.py
C:\Python312\python.exe tests\test_panel_dangling_refs.py
C:\Python312\python.exe tests\test_panel_i18n.py
C:\Python312\python.exe tests\test_panel_web_screens.py
```

The second one is source-only and takes a second: no class in the panel may mention a
`self.x` it cannot have. The first covers your tab the moment it is in the registry: it must import, build cold, request no
game during `build()` (nor during `ensure_loaded` if `EAGER`), survive
`apply_config` → `on_show` → `on_hide` → `panic` → `shutdown`, and leave no armed `after`
chain and no bus subscription behind. The third is the words: no literal a person can
read anywhere under `panel/`, and every key in every shipped locale.

Then check the two things a test cannot:

* `python -m panel.tabs.<id> --profile <name>` opens and works;
* unticking it in «Настройки → Вкладки» and restarting leaves no trace of it — no
  widgets, no settings page, no listener, no capture.

## One state, several places that draw it

A switch a person can reach from two screens must be ONE state with two views — never
two variables that happen to mean the same thing. The panel has been bitten by the other
arrangement three times: two sets of autoloot rules (#1272), two counters for the rally
budget, and the rally auto-join's own two boxes (#1281) — the «Ралли» tab's
«Присоединяться сам», stored in the profile's `config.json`, beside the
«rally_auto_join» row on the «Таймеры» tab, stored in `triggers.json`. Each drove a
different half of the same ability and neither could see the other, so «какая из них
настоящая» had no answer in the code.

The shape that works:

* **The state lives in exactly one file** — for a standing order that is the profile's
  `triggers.json`, read through `Schedule.trigger_enabled(name)` and moved through
  `Schedule.set_trigger_enabled(name, on)`. Those two know the one rule that matters:
  while the «Таймеры» tab is drawn its boxes ARE the configuration, and the file is the
  configuration when it is not.
* **Every other place is a VIEW**: it reads the state when it draws, writes through the
  setter when it is clicked, and re-reads on `on_show` — otherwise two screens show
  different things until one of them is rebuilt.
* **Nothing keeps a copy.** A tab that stored the value in its own block drops it and
  carries an old profile's value over ONCE, so a refactor loses nobody's switch.
* **The words say so.** Where two boxes genuinely mean two things, they are named so that
  a person does not have to guess: «Слушать стяги (места и цель)» is the capture,
  «Присоединяться сам (поручение «Автостяг»)» is the standing order — and the Timers row
  says «та же галка, что на вкладке «Ралли»».

## Picking squads is ONE widget, everywhere (#2062)

**A rule, not a suggestion**, and it is the person's own decision in their words: «Новый
виджет, там, где у нас выбор чекбоксов наших 4х отрядов, делаем отдельным виджетом,
должны быть 4 картинки в ряд с нашими героями, именно те, что в игре у данного игрока,
они меняются в зависимости от героев в отряде, клик по картинке должен включать и
отключать этот отряд, выключенный делаем серым. Везде где есть выбор отрядов вставляем
этот виджет и берем за правило».

So: **anywhere a person chooses which squad or squads something spends, the field declares
`kind = "squads"` and nothing draws its own row of boxes.** The panel's side is
`panel/runtime/squad_picker.py` and the control is
`panel/web/app/src/ui/SquadPicker.tsx` — four tiles in a row, the heroes standing in each
squad, grey when it is switched off.

```python
from ...runtime import squad_picker

def web_view(self) -> dict:
    return {"cards": [{"title": "tab.mything",
                       "fields": [squad_picker.field(self.rt, "squads", "squads.title",
                                                     self._chosen())]}]}

def web_press(self, action, args) -> dict:
    if action == "set" and args.get("key") == "squads":
        self._choose(squad_picker.chosen_from(args.get("value")))   # «1,3» -> [1, 3]
        return {"ok": True}
```

* **The value is the slots that are ON**, comma-joined — the whole list, never a diff.
  `squad_picker.chosen_from` parses whatever a front-end sent.
* **`single=True`** for a place that picks ONE (the golden-zombie hunt, the treasure dig):
  the same control, and a click moves the choice instead of clearing it.
* **`squads=`** when the slots are not 1..4 (the treasure page digs with 1..3).
* **It owns no value.** Like the gear on «Таймеры», a picker is a VIEW of whatever
  variable the tab already kept — see «One state, several places that draw it» above.

**The faces are read ONCE and never polled.** A squad's composition changes when the
player rearranges it, which announces itself to nobody, so `actions/read_squad_heroes.md`
runs on first need and then only when a page's «Обновить» asks — the rule this repository
works to (`CLAUDE.md`, «Read once, then LISTEN»). The picker never blocks a `web_view`: it
answers with what it has and asks for a reading in the background.

**The faces are the player's own, and the client names them itself.** A formation does
NOT hold hero ids — its hero list answers with positions — so the read joins
`localIndexToHeroDic` (position → hero uuid) against `HeroDataManager:GetAllHeroList()`
(uuid → heroId), and then asks the running client's own config what the portrait is
called: `lw_hero.appearance` → `lw_hero_appearance.half_icon_path`, which is literally the
extracted file's stem (`docs/research/hero-icons.md`, #2062). The encrypted on-disk table
is not needed at all and the repository's ten confirmed ids are only the fallback.

**It degrades honestly and never guesses a face.** When neither the client nor the
fallback can name a hero — or the machine never ran `tools/extract_hero_icons.py` — the
tile draws the squad's NUMBER and its state. A picture that belongs to somebody else's hero is worse than no
picture, and the same rule the monster and errand icons keep.

**Where it is drawn today** (a new site joins this list rather than inventing its own):
the rally auto-join and the gear on its «Таймеры» row, the manual rally form, the
golden-zombie hunt on «События», and the treasure dig on «Командный пункт» — which is the
one that had no way in at all from the phone, so a press that spends a squad was decided
by a knob only the window could show (#2010).

## The knobs an errand carries — the gear on «Таймеры» (#2017)

A standing order is never only a switch. «Автолут ★» spends the day's five robberies at
whatever minimum level it was told; the rally auto-join sends whichever of the four
squads it was allowed, above a soldier floor, up to a daily ceiling. Those knobs lived on
the page holding the LIST the order spends — «Секретки», «Ралли» — so «Таймеры», the one
tab that says what runs by itself, showed a row of names with nothing a person could act
on, and «почему автолут не грабит» could only be answered by knowing which tab owned it.

They are drawn in both places now and stored in exactly one. `panel/runtime/errand_options.py`
is a register of **views**, not a new home: the value goes on living in the owning tab's
own variable (or in this profile's settings, when it was already one), so the number
typed behind the gear is the number that page shows the moment somebody looks at it.

### What a tab declares

Two methods on `PanelTab`, both called **with the tab and not with its widgets** — a gear
on a page nobody has opened still has to work (`LAZY`), so whatever they reach must be
made in `__init__`:

```python
from ...runtime import errand_options as errandopts

def errand_options(self) -> dict:
    """{errand name: (Option, …)} — a timer, a trigger, or a standing order."""
    return {"secret_autoloot": (
        errandopts.Option("autoloot_level_min", "secret.autoloot.level_min",
                          errandopts.TEXT,
                          get=lambda: self.rule("level_min_var"),
                          set=self.set_autoloot_level),)}

def standing_orders(self) -> tuple:
    """A watcher this tab owns that is in nobody's catalogue."""
    return (errandopts.Order("secret_autoloot", "secret.autoloot",
                             get=lambda: bool(self.autoloot_var.get()),
                             set=self.set_autoloot,
                             state=self._autoloot_line),)
```

* `Option(key, label_key, kind, …)` — `kind` is `SWITCH` / `NUMBER` / `TEXT` / `CHOICE`
  (the four the web already draws). Either `get`/`set`, the owner's own variable, **or**
  `setting="…"`, a knob that was already a profile setting — never both, because a knob
  with two homes is a knob with two answers. `low`/`high` bound a number, `hint_key` puts
  a line under it, `label_fmt={"n": squad}` fills the label's placeholders (four squads
  are one locale key, not four strings in eleven files), `options=({"value":…,"text":…},)`
  fills a choice.
* `Order(name, label_key, get=, set=, state=)` — a watcher drawn among the listeners,
  because that is what it is to a person. `state` is a callable answering one phrase in
  the panel's own words («жду звезду», «лимит исчерпан»): without it a silent order and a
  stopped one look identical, which is what «автолут не работает совершенно» turned out
  to be (#1227).

`Schedule.register(tab)` collects both when the tab is registered, and
`rt.schedule.options` answers `has` / `fields` / `write` / `orders` for either front-end.

### One setter, whoever pressed

The gear, the tab's own page and the phone's card are three drawings of one value, so
they call **one setter** — and that setter writes the variable *and* `remember`s the
block, because an unbuilt tab hands its SAVED block back on save and a write past it is
gone at the next restart (#2010):

```python
def set_autoloot_level(self, value) -> None:
    raw = self._level_rule(value)          # a half-typed box is «any level», NEVER 0
    self.level_min_var.set(raw)
    self.remember({"autoloot_level_min": raw})
    self.rt.settings.changed()
    self._refresh_rule_hints()
```

A blank number never becomes a `0`: for «минимальный уровень» a 0 is not «no bound», it
is every tile on the map (#1256).

### Both front-ends

* the window — `panel/runtime/errand_gear.py` draws the ⚙ window off the same `Option`s;
  `panel/tabs/timers.py` puts the gear on a timer's row, a listener's block and an
  order's block, and paints each order's switch and state on the ordinary refresh;
* the phone — `/api/timers` and `/api/triggers` carry each row's `options`, `/api/triggers`
  also carries `orders`, and the two presses are `/api/errand/option`
  (`{errand, key, value}`) and `/api/orders/set` (`{name, enabled}`). `FieldRow.tsx`
  draws one field wherever it is drawn — a tab screen's knob and a gear's are the same
  control over the same `Field`, differing only in which route it posts to.

### …and on the phone they open in ONE modal, which nobody re-writes

**The person's decision, in their words: «Модалки да, переиспользуем и берем за правило»**
(#2061), after having asked for the shape itself a task earlier: «сделай, чтобы при клике
на шестеренку открывалась модалка с параметрами, а не коллапс, это везде» (#2051).

So, for every gear in the web front-end — an errand's, a listener's, a standing order's,
a rally group's, and whatever grows one next:

* it opens a **modal**, a sheet over the page. Never a collapse that unfolds the block
  downwards: that slides the row being edited away under the thumb and jumps everything
  below it, which on a phone means the knobs land wherever the scroll happened to be;
* it opens **the one component**, `panel/web/app/src/ui/Modal.tsx` — written for the rally
  cards in `56ba8e6b` and reused by the errands page since #2061. It closes three ways (the
  ✕, the dark outside it, Esc) and holds the page still behind itself, so the gesture is
  learnt once;
* **a second modal is not written.** If the one there is does not fit a new place, improve
  it and say what changed. A fork with its own margins and its own way of closing is
  indistinguishable from an accident by the time anybody notices.

A tab does not build any of this: it declares `options` (or `options_title`) on an item and
the renderer draws the gear and the sheet (`views/ScreenView.tsx`, `useItemGear`). Nothing
in a tab may name a modal, and nothing in the front-end may define a second one.

Pinned by `tests/test_panel_errand_options.py`, and the one-modal half by
`tests/test_panel_web.py`.

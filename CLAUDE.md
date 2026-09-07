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

### A button that STARTS something is not the thing being forbidden

**«Состояние считается из игры, но выполнение можно вызывать.»** The rule above is about
where an ability LIVES, not about whether a panel may offer to run it. A tab that draws
readings may put a button beside them, and pressing it plays the scenario and then
re-reads — that is ordinary and wanted.

What may never happen is a press that MARKS: a tick, a «done», a count the panel keeps
for itself. Anything a person could do to the panel instead of to the game is a second
version of the truth, and the first time the two disagree the panel's is the wrong one.
So the row moves when the READING moves, and a row that stays red after a press is
telling the truth about the game.

The two got confused once: «Чеклист» lost its nine «Выполнить» because a button that
starts something looked like a button somebody expects to have marked the line (#1239),
and a board of readings you could not act on is exactly half a tool. #1257 put them back.
**When in doubt: object to marking, never to pressing.**

### The code that predates this rule

Less of it than there was: the panel's tabs are plugins now
(`docs/panel-tabs.md`), and what still speaks to the game directly is down to
`panel/dashboard.py`, `panel/tabs/_data.py` and the reads inside a few tabs. They
are debt, not precedent. Do not rewrite them all at once, but when a task takes
you into one of those paths, move the game logic out into a scenario and leave the
panel calling it. **Never add a new one.**

Two of them were itemised here as NOT free, whatever a plan said: the secret-task and
ghost-recon robberies. **The robbery itself is a scenario (#1188)** — both orders play
`actions/steal_secret_task.md` / `actions/steal_ghost_recon.md`.

**The secret-task one is now ONE step, and the way it got there is the lesson (#1272).**
It used to spawn its tool first, with `--queue-only`, on the grounds that a recipe cannot
name its own victim: `TAP` takes no arguments. True of `TAP`, and not true of the recipe,
which takes `ARGS` — the queue travels as an argument and the recipe parks it in the call
it was going to make anyway (`join_rally.md` had been doing exactly that with its squads
all along). What forced the question was a measurement: **the parking child costs five
seconds**, and the race it was in the middle of is decided in fractions of one.

So the warning that stood here — do not "just" swap the spawn for `rt.actions.run(...)`,
because the one-line version plays a recipe over an empty queue, robs nothing and says
nothing — was right about the ONE-LINE version and wrong as a verdict. The swap costs
what it always costs: the recipe has to grow the argument, park what it is given, and say
in its own words what the caller used to read off the tool's stdout. **The ghost robbery
went the same way in #1976**, for the same measured reason and at the same price: `ARGS
queue`, a park in the opening `LUA`, and the two lines the panel used to read off the
child's stdout said by the recipe instead (`ghost_taken`, `ghost_steals_spent`). Neither
robbery spawns anything now. The lesson stands for whatever is next: measure the child
before deciding it is affordable, and do not ship the one-line version.

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

**And `build()` runs when somebody first LOOKS at the tab, not when the page is made**
(`LAZY`, #1215 — a page drew fifteen tabs so that one could be read). So `__init__`
makes the state and `build()` only draws it: the saved block, a trigger the tab
declared and the phone's screen all reach a tab nobody has opened, and the contract
says how each of them answers.

Nothing new goes into `panel/__main__.py`. It is the shell: window, notebook, menu,
«Главная». If a change needs something from it, move that something into
`panel/runtime/` first and use it from there.

**The log is the worked example** (#1391). It had been the shell's since the panel had
one page — the widget, its filter, its colours, its history, its sash — and it is a tab's
now: the pane and the stamped spool behind it moved into `panel/runtime/log_view.py`, the
«Разработка» tab draws one, and what the shell kept is the clock that pumps the queue,
because the drain is what writes `panel.log` and most profiles have no pane at all. That
is the shape every such move takes: the thing goes to `panel/runtime/`, the tab draws it,
and the shell keeps only what has to happen whether or not anybody is looking.

## An edit travels between the window and the web, in BOTH directions, at once

**Also binding, on every agent, with no exceptions.** The panel has two front-ends now:
the Tk window and the web one a phone opens (`panel/web/`, #1221). They are not a
product and a copy of it — they are two ways of drawing the same runtime, and the
moment one of them is behind, whoever is reading THAT one is being told something that
is not true any more, with no way to know it.

### …and for the length of the migration it travels ONE way: into the web

**The person has decided, in these words: «Веб теперь главный инструмент, ему и полный
функционал» (#1976).** The web is not the mobile copy of the window any more — it is the
front-end, and the window is kept only until it is deleted. So while the migration runs,
read the rule below like this:

* **NEW GOES ONLY INTO THE WEB.** A button, a field, a reading, a screen — it is written
  in `web_view()` / `web_press()` and the tab's `build()` is left alone. Where the two
  ways of doing something would cost the same, choose the web every time.
* **The window gets an edit only when control would otherwise be LOST before Tk goes** —
  a fix to something already there, not a new ability.
* Everything the window has and the web has not is a GAP TO CLOSE IN THE WEB, never a
  reason to add to the window.

That inverts the second bullet below and nothing else: the first still stands whole,
because the web must never be the side that is behind. When Tk is deleted (P3 of
`docs/research/panel-service-and-spa-plan.md`) this section is replaced by the single
front-end's contract and both bullets go.

So it travels **both ways, in the same commit** — until the paragraph above applies,
which for the duration of #1976 it does:

* **Window → web.** A tab that grows a button, a field, a reading or a status line
  updates its `web_view()` — and `web_press()` if it is a press.
* **Web → window.** A screen, a card, a button or a fact added to `web_view()` gets its
  counterpart in the tab's `build()`. The web does not run ahead of the window either:
  a control that exists only on the phone is a control the person at the machine cannot
  find, and the next agent reading the tab has no idea it is there. **Suspended by the
  decision above for the length of the migration** — a control the phone has and the
  window has not is now the ordinary case, and it is how the window empties.

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

The divergences below are exactly what a legal one looks like: discussed, justified,
written into both files, and pinned by a test. Any future one is expected to look the
same.

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

### The knobs open in ONE modal, and nobody writes a second one

**Binding, and it is the person's decision rather than anybody's taste**, in their words:
**«Модалки да, переиспользуем и берем за правило»** (#2061), after the same person had
already asked for the shape once: «сделай, чтобы при клике на шестеренку открывалась
модалка с параметрами, а не коллапс, это везде» (#2051).

Three sentences, and each is a separate prohibition:

1. **Parameters behind a gear open as a MODAL** — a sheet over the page. Everywhere:
   errands, listeners, standing orders, the rally caps, and whatever grows a gear next.
2. **A collapse that unfolds the block downwards is not used any more.** It opens INSIDE
   the list it belongs to, so the row being edited slides away under a thumb and
   everything below it jumps; on a phone the knobs land wherever the scroll happened to
   be.
3. **No second modal is written.** There is exactly one component —
   `panel/web/app/src/ui/Modal.tsx` — and every gear renders into it. It closes three
   ways (the ✕, the dark outside it, Esc), it holds the page still behind itself, and a
   person learns that gesture once.

**If the one modal does not fit a new place, IMPROVE IT — never fork it**, and say what
changed. A second sheet with its own margins and its own way of closing is the thing this
rule exists to prevent, and it is indistinguishable from an accident six months later.

It is a worked example of the rule its neighbour states — «A control that exists twice is
written once». The component was written for the rally cards (`56ba8e6b`, #2051/#2055) and
the errands page reuses that one rather than growing its own (#2061); the reuse went the
same way round the other time, and either direction is right as long as there is only one.
`tests/test_panel_web.py` fails on a second modal component and on a gear that renders
anything but this one.

### A press travels only when the ability is a scenario

`web_press` runs what `rt.actions` / `rt.play_async` runs and nothing else. Where a tab
still drives the game by hand — or half by hand: it presses through a scenario but spawns
a tool to PARK the targets first — **the web gets the READING and no button**, and the
tab's own reading is mirrored as usual. Both robberies used to be in that state; neither
is (#1272 the secret task, #1976 the ghost), and «Операция Призрак» has its «Ограбить
всех» on the phone because the ability is one recipe now, not because an exception was
made for it.

**And a press the phone can reach only on a tab the profile has switched OFF is a press
the phone cannot reach** (#2010). The ghost order — its switch, its «минимальный уровень»
and «Ограбить всех» — was on «Командный пункт», which is dev-only: the live profile had it
off, so five robberies a day were decided by a knob neither front-end could show. It is on
«Секретки» → «Призрак: карта» now, the page holding the list it spends, which is where
«Автолут ★» has been since #1271. **An order belongs on the page holding its list, and
that page has to be one every profile has** — true of WHERE the list is, and no longer
true as an exclusive home: the paragraph below replaces it.

**…and since #2017 it also belongs on «Таймеры», because BOTH is the answer.** «An order
belongs on the page holding its list» was right about the LIST and wrong as an exclusive
home: the tab that lists everything running by itself showed a name, a box and nothing
that decides what the box does, so «почему автолут не грабит» could only be answered by
knowing which tab owns the autoloot. The person's decision, in their words: «настройки
дублируются и в триггерах, и на страницах списков». So an errand's knobs are drawn twice
and stored ONCE — `panel/runtime/errand_options.py` is a register of VIEWS, never a new
home: a tab declares `errand_options()` (and `standing_orders()` for a watcher that is in
no catalogue), each `Option` says where the value really lives, and the gear on «Таймеры»
writes the owner's own variable through the owner's own setter. Nothing is copied and
nothing is migrated, so the level typed behind the gear is the level that page shows a
second later. **Two drawings of one value are wanted; two values are still the bug** — the
same rule «One state, several places that draw it» has always stated
(`docs/panel-tabs.md`).

**What the rule forbids is the PRESS, and never the standing order behind it** — a
distinction #1976 had to make out loud, and it is what let the ghost card carry its switch
and its minimum level on the phone as FIELDS through the months when «Ограбить» could not
go. A switch is the rule OUR OWN watcher obeys, exactly like the rally auto-join the phone
has been able to move through the schedule all along, and a knob nobody can reach once the
window is deleted is worse than one somebody can get wrong. **Joining a rally used to be
where that bit**, and #1976 finished it the way the robberies were finished: the join is
one recipe and always was, so what was actually missing was its ARGUMENT — the squads it
spends could be ticked only at the machine, and a press that sends whatever was last
chosen is precisely the «wrong squad from a bus» it was held over. The four squad boxes
travel as switches on the same card, and «Присоединиться» went with them, asking first
because troops leave the base when it is answered.

**Nothing is held back by the order-of-work rule any more.** The next thing that is will
be held for the same reason and let go the same way: make the ability one recipe, give it
whatever the press has to choose, then put the button on the phone.

This is an ORDER OF WORK, not a way out of the rule: first the ability becomes a
scenario, then the button appears in the web. A second copy of a hand-driven press,
reachable from outside the house, is not an improvement — it is the same debt in two
places.

### The divergences there are, and how they got there

They are the model for the paragraph above: each was **proposed, argued and agreed with
the person**, and then written down here — not decided in passing by whoever was in the
file at the time.

**`develop` WAS the first one, and #1976 ended it too — by asking the question the
divergence had left open.** «Two sniffers for working on the bot itself» was true of the
SNIFFERS and never of «Занятость», the block on the same tab that answers «почему панель
ничего не делает»: the threads, the queue, the claims and who is waiting for whom. That
is the one question somebody away from the machine cannot ask any other way, and it was
behind a `WEB_SCREEN = False` written for its neighbours. So the tab has a screen — the
busy grids whole, the update channel as a switch. The tab is still
`DEFAULT_ENABLED = False`, so a panel that never asked for it is handed nothing.

**And the half that was held back — the SNIFFERS — travels since #2072**, which is the
order of work finishing rather than an exception ending. What was written here was that
starting a recording asks for a label in a message box and stopping it asks whether to
keep the run, two modals raised on a machine nobody is standing at, so the phone got the
reading and no switch. The person then hit the consequence: «не могу включить снифер в
разработке». The live panel has no window at all, so a switch only Tk could throw was a
switch NOBODY could throw — the same shape as the ghost order behind a dev-only tab
(#2010) and the profile press only Tk could make (#2024). The cure is the one this file
already named: **the typed word becomes an argument of the press.** «Записать» carries
the label, «Остановить» carries the description, «Удалить запись» carries the verdict and
asks the phone's own «are you sure?» first. No dialog is raised on either path, and a
window-less panel that is stopped by nobody KEEPS the run — losing a recording must take
a deliberate press.

**So there are NO divergences left**, and the next one is added exactly the way the three
were: ask, agree, write it in both files, pin it in the test. What is written down now is
the opposite shape — what a screen deliberately does NOT carry, and why — and it is pinned
the same way (`tests/test_panel_web_screens.py`, `tests/test_panel_develop_screen.py`).

**`settings` WAS the second one, and #1976 ended it — which is what a divergence looks
like when its reason expires.** «Paths, interpreters and ports: breaking a profile with
one thumb is easier than fixing it from a bus» was true while there were two front-ends
and the window was the safe one. The person has decided there will be ONE (the window is
being retired, `docs/research/panel-service-and-spa-plan.md`), and from that decision a
knob with no screen is a knob NOBODY can reach — worse than one somebody can get wrong.
So «Настройки» has a screen, and the part of the old reasoning that still holds lives
inside it: the four values that decide WHICH CLIENT a profile drives — the two machine
paths, the daemon port and the Windows session — are READINGS there and never fields, and
a press naming one is answered «unknown». The test pins that in place of what it used to
pin. Note the shape of this: the exception was not quietly dropped by whoever was in the
file, it was ended by the same conversation that created it, and the replacement rule was
written down in the same commit.

**THERE WERE THREE, and the third teaches the OTHER lesson (#1313).** (It is the one of
the three whose reasoning has NOT expired — see below.) «Веб» — the door
the person came in through; managing it from the far side is how somebody locks
themselves out — is no longer a tab at all. It never should have been one: there is one
server per WINDOW and it answers for every profile that window has open, so the port,
the token and the certificate are the machine's, and a page inside one account held one
copy of them per account and obeyed whichever profile switched on first. Ask the two
questions in the order this file gives them («A profile is a whole panel of its own»)
and the answer was «per machine» all along. So the knobs are a panel-wide block in
`profiles/settings.json` (`panel/profile.py`), `panel/runtime/web_control.py` turns them
into the one running server, and `panel/runtime/web_dialog.py` draws them. **The
divergence itself did not change** and the same test pins it from the other side: no
`web` tab in the registry, and nothing in `panel/web/api.py` that can reach the setting.

**What DID change is the other side of it, and it is what a live divergence looks like
when the code around it moves (#1976).** «Not from the web» was never «only from the
window» — it only looked that way while the window was the sole thing on the machine that
could write the block. The window is being deleted, and a knob nobody can reach once it is
gone is worse than one somebody can get wrong (the same sentence that ended the «Настройки»
divergence, arrived at from the opposite direction). So the knobs got a way in that is
neither the window nor the door: `python -m panel.web_settings` on the machine itself —
`--on` / `--off` / `--port` / `--host` / `--token new` / `--cert` / `--key` / `--address`
— which is precisely the access the divergence was keeping them for. The rule is
unchanged, the test is unchanged, and `panel/runtime/web_dialog.py` may now be deleted
with the rest of the window instead of taking the front door with it.

**«Веб» was its own menu entry for a while, and then «Профиль» and «Автозапуск» grew
entries of their own beside it (#1506) — and a fourth command on the menu bar for a
fourth switch of the exact same kind is where "one menu bar, one command per knob"
becomes indistinguishable from never having organised it at all (#1509).** All four —
«Веб», «Профиль», «Язык», «Автозапуск» — answer the same question the same way: a
switch that belongs to the WINDOW rather than to an account. So one modal replaced the
four commands, `panel/runtime/settings_dialog.py` (the sidebar shape, and nothing about
any one switch), with each switch's own content unchanged and merely reused as a
section — `web_dialog.py` and `autostart_dialog.py` now build INTO a frame the modal
hands them instead of owning a `Toplevel`, and «Профиль» / «Язык» stay methods on
`Panel` because they reach the shell's own state (the workspace, the translator). The
modal is called «Параметры», deliberately not «Настройки» — a profile's own tab already
has that name (`tab.settings`), and the same word over two different doors is exactly
the confusion this file exists to prevent.

**«⟳ Перезапустить панель» is what a legal exception looks like in practice** (#1258).
Python edits reach a running panel only through a fresh interpreter, and the person
making them is usually holding a phone rather than standing at the machine — so the
press went onto «Состояние», beside the client's three, and the remote control's own
settings still have no page. Both front-ends read one table
(`panel/runtime/panel_control.py`) exactly as they do for the client's lifecycle, both
ask the same question first, and the shell registers the one thing that can carry it
out. Anything else a screenless corner of the panel needs on the move goes the same
way. **And it is not only a convenience: pressing it is MANDATORY after every fix —
see «A fix that has not restarted the panel has not been delivered» below.**

**AN ACCOUNT HAS ONE STATE, AND IT IS «РАБОТАЕТ / НЕ РАБОТАЕТ» (#2068).** The person's
own words: «никаких режимов открыт/закрыт, только работает или нет». Open and closed are
MECHANICS — a page in a notebook, a lock on a client — and the profiles screen offered
nothing else, so somebody read «закрыт» about an account that was farming perfectly in a
second panel process and pressed «Открыть» to be told «занято». Two sentences in a row,
neither of them about the game. So the row on «Профили» carries ONE switch called
«Работает» and a pill saying which of the three it is; there is no «Открыть» and no
«Закрыть» on the phone at all.

Two things follow, and neither is optional:

* **The wish is written BEFORE the page is touched** (`profile_control.set_working` →
  `panel/profile.py::keep_add`/`keep_drop`). The standing list is what the machine brings
  up and what the service supervises, so a press this panel cannot honour this second is
  answered «принято, идёт» and the keeper carries it out within a tick. **«Включить» may
  never come back refused** — a switch that flips itself back is a switch nobody trusts.
* **A profile another panel is holding is consolidated SILENTLY** — the person asked for
  it in those terms — by the keeper of 92c618b3, never by telling the person «у вас две
  панели», which is not something anybody can act on.

Whatever grows a state next is drawn the same way: what the account DOES, in the words a
person uses about it, and never the panel's own bookkeeping.

## A new ability ships SWITCHED ON

**Binding, and it is the person's decision**, in their words: «Все новые механики по
умолчанию включай и по дефолту включенные» (#2390). An ability that ships switched off is
an ability nobody uses — the panel that has it does nothing until somebody happens to open
the page and tick the box, and the agent who wrote it is the only person who knows it is
there.

So a new errand or trigger is added with no `enabled=` at all and inherits `True`
(`panel/timers.py`, `panel/triggers.py`), and a new tab is `DEFAULT_ENABLED = True` unless
it is for working on the bot itself. **This is about what is ADDED — the rows written under
the old opt-in rule keep their explicit `enabled=False`**, because turning an existing
account's errands on behind its back is the panel changing behaviour nobody asked it to
change.

**The one exception is an irreversible spend.** Anything that can spend diamonds, a
purchase, or a daily quota that cannot be earned back is shipped OFF and named to the
person, who switches it on themselves. The energy refill is the worked example: the person
has already allowed it, and it still gates on a price it can read (#2390).

## A control that exists twice is written once

**Binding, and it is how the panel stops growing a second version of every widget.** When
the same thing is chosen on several screens, it is ONE reusable control declared by each
site — never markup copied into each one. Two sites that draw the same choice differently
are two things a person has to learn, and the day one of them grows a feature the other
silently has not.

**«Какие отряды» is the worked example, and it is the person's own decision (#2062)**, in
their words: «Новый виджет, там, где у нас выбор чекбоксов наших 4х отрядов, делаем
отдельным виджетом, должны быть 4 картинки в ряд с нашими героями, именно те, что в игре у
данного игрока, они меняются в зависимости от героев в отряде, клик по картинке должен
включать и отключать этот отряд, выключенный делаем серым. **Везде где есть выбор отрядов
вставляем этот виджет и берем за правило**». So a field says `kind = "squads"`
(`panel/runtime/squad_picker.py`) and the front-end draws the player's own four squads with
the heroes standing in them — the rally auto-join, its gear on «Таймеры», the manual rally,
the golden-zombie hunt and the treasure dig, and whatever asks next. The details a caller
needs are in [`docs/panel-tabs.md`](docs/panel-tabs.md), «Picking squads is ONE widget».

Two things that rule does NOT relax:

* **Read once, then listen.** A squad's composition is read on first need and when a page's
  «Обновить» asks, never on a clock — there is no event behind it, and a picture is not
  worth a background question at the game.
* **Never a stand-in picture.** A hero the live config would not name draws the squad's
  NUMBER, not a face that belongs to somebody else's hero. The same contract every other
  picture route keeps, and the reason the icons are a link into `/api/heroicon` rather than
  a guess in the code.

## A fix that has not restarted the panel has not been delivered

**Also binding, on every agent, with no exceptions, and it is not a suggestion.** The
panel reads the scenarios, `tools/lib/lua_actions.py` and `panel/…` once, at import. A
running panel therefore keeps playing the code it was started with, however many commits
land afterwards. **A committed fix that has not been followed by a restart does not exist
for the live game**, and nothing in the window or the log says so — the panel goes on
reporting success against the old behaviour.

That is not a hypothesis. #1322 fixed the per-kind budget; the panel ran the previous
code for seven hours after the commit, every report in that window lacked the line the
fix prints, and the bug was reported again as «не работает вообще» while the fix sat in
`master` doing nothing.

So the rule is one sentence: **after ANY bug fix, restart the panel — immediately, as
part of the same piece of work, without asking whether it is worth it.** Not «if the
change looks like it matters», not «the next restart will pick it up». It applies to a
one-line edit as much as to a new module, because the cost of an unnecessary restart is
seconds and the cost of a skipped one is a fix that silently is not there.

How, and how not:

* Press **«⟳ Перезапустить панель»** on «Состояние», or `POST /api/panel` with
  `{"action": "restart"}` on the web port — the same table
  (`panel/runtime/panel_control.py`) from either front-end.
* **A NEW HTTP ROUTE NEEDS THE OTHER RESTART (#2579).** The web paths live in the
  SERVICE (`LastWarBot`, which binds the port); the panel only answers what they ask,
  over the door. So `panel/web/api.py` and everything behind it reach the phone on a
  PANEL restart, and a new `path ==` in `panel/web/server.py` reaches it only on
  `POST /api/service {"action": "restart"}` — the service's own press
  (`panel/service/self_control.py`), which asks the SCM rather than killing anything.
  The tell is the 404: a route the service has never heard of answers JSON
  `{"error": "not_found"}`, while a real picture route with nothing to send answers an
  empty `text/plain`. It has cost a day twice — the resource icons and the arms-race
  ones — and both times the hunt was for an orphan process that does not exist. The whole
  of it is `docs/research/panel-web.md` §3.14, including how to ask which commit each
  process is on (`GET /api/panels`).
* **Never `taskkill`, never kill the process by hand.** The user has forbidden it: the
  orderly restart takes every open profile down and brings them back, and a killed panel
  leaves locks, children and a client nobody let go of.
* Then **read the log and say what you saw**. A restart is claimed when a line proves it —
  a new pid in `panel_alive.json`, the boot lines in the profile's log, and, where the fix
  prints something the old code could not, that line appearing in a run. «Перезапустил» on
  its own is a sentence, not evidence.

**And the restart now costs the warm VM too (#1911).** There is no Lua daemon process
any more: the panel holds the game's Lua VM itself (`panel/runtime/lua_service.py`),
so a restart drops the attach and pays for a new one — seconds, once, per profile whose
client is on this desktop. It changes nothing about the rule: a fix nobody restarted into
is a fix that is not there.

The one process that still exists is the connector for a client in ANOTHER Windows
session (`tools/lua_daemon.py`), started and owned by the panel that needs it. It is not
supervised, not re-elected and not «warm» or «stale» — a panel that cannot reach it
starts another one.

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
- **the live panel has been restarted since the fix was committed, and the log says so**
  — a running panel plays the code it was imported with, so a fix nobody restarted into
  is not delivered, whatever the diff says (above);
- **not one identifier of a real account is anywhere in what it adds** — no nickname,
  Windows login, uid, uuid, alliance id or tag, device id, account-bound server number,
  base coordinate, IP or user-named path, in code, tests, fixtures, docs, comments or
  example commands. A live reply used as an example is rewritten with invented values of
  the same shape BEFORE it is committed, never after (below);
- **the work was done on its own branch, in its own worktree, and the branch is gone**
  — merged into `master`, tested AFTER the merge, deleted local and remote (below);
- and, once the user has confirmed it live, both farming files say so (below).

## A task is done on its own branch, in its own worktree

**Binding on every agent, and it is the person's decision**, in their words: «С этого
момента делай задачи в своих ветках, по завершению мерж, тестируй и удаляй ветки».

Why, and it is not hypothetical: several workers share this checkout at the same time.
Working straight on `master` in the shared tree is how a neighbour's half-written files
got swept into somebody else's commit, and once that broke `HEAD` for everybody.

**NEVER `git checkout`/`git switch` a branch in the shared checkout.** It rewrites files
under a neighbour who is mid-edit. A branch is entered by making a WORKTREE of it, and
the user's rule says where those live: `~/worktrees/task-NNN`, never inside the
repository.

```bash
# 1. a branch and a tree of its own — off the CURRENT master, fetched first
git -C <the shared checkout> fetch origin
git -C <the shared checkout> worktree add -b task-NNN ~/worktrees/task-NNN origin/master
cd ~/worktrees/task-NNN
# 2. work here; stage BY PATH, commit atomically (`git add -A` and `git stash` stay forbidden)
git add path/one.py path/two.md && git commit -m "fix(area): … (#NNN)"
# 3. merge back, in the shared checkout, without switching anything
git -C <the shared checkout> merge --no-ff task-NNN
# 4. TEST AFTER THE MERGE (see below), then push
git -C <the shared checkout> push
# 5. take the tree and the branch away — both ends
git -C <the shared checkout> worktree remove ~/worktrees/task-NNN
git -C <the shared checkout> branch -d task-NNN
git -C <the shared checkout> push origin --delete task-NNN   # only if it was pushed
```

A merge that reports a conflict is not force-resolved and history is never rewritten: fix
the conflict in the worktree, merge again, and if it is a neighbour's file — ask them.

### What counts as «протестировано»

Tested means, after the merge and before the push:

* the areas the change touched are green — the specific test files, run by name
  (`tests/test_<area>.py`), not «it looked fine»;
* the panel still imports (`python3 -c "import panel.headless"` at minimum, and the
  registry when a tab moved);
* the numbers are stated in the report, with any failure that also fails on the merge
  base named as pre-existing — a suite that was already red is not a licence to add red,
  and it is not a reason to hold the merge either;
* **the live panel is restarted** when the change is a fix, because a fix nobody
  restarted into is not delivered (above).

A branch is deleted only after that. A branch left behind is indistinguishable from work
in progress, and the next agent has no way to tell whether it is safe to build on.

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

Prose is not a value: a comment or a docstring may name the game, the launcher or a
«run it like this» line, and should. What may not come back is a **quoted literal being
used** — to build a path, filter a process list or match a window.

Every new variable is added to [`.env.example`](.env.example) in the same commit, with
a line saying what it is for and that it is optional.

No test knows the forbidden VALUES any more: `tests/test_no_hardcoded_values.py` was
deleted with #1234, because the only way it could recognise one was to carry a copy of
it — the file guarding the repository against personal data held the largest collection
of it in the repository. What is checkable without knowing a single value still is:
`tests/test_game_paths.py` fails on a module that spells the install or the interpreter
out for itself, and `tests/test_repository_hygiene.py` fails on anything committed that
is not text, on a private tree that has slipped out of `.gitignore`, and on the three
values a tool must ask for rather than know. The rest holds because you read your own
diff before you commit it.

## Not one identifier of a real account is written down

**Also binding, on every agent, with no exceptions.** This repository is public.
**Never write a real identifier into it — yours or anybody else's.** Not a player
nickname, not a Windows login, not a game uid or an account uuid, not an alliance id or
tag, not a device id, not a server number that belongs to an account, not the
coordinates of a particular base, not an IP address, not a path with somebody's user
name in it. Not in code, not in tests, not in fixtures, not in documentation, not in a
comment, and not in an example command line. There is no file in this repository where
one of them is allowed to be, and no reason that makes one of them worth keeping.

Half of them are not even yours to publish. A capture, a screenshot or a chat log
records whoever happened to be on screen — other players, their alliances, their
account ids. They never agreed to be in a public repository and cannot ask to be taken
out of one, because a git history does not forget.

### Why an example may not «just use the real answer»

This is how they get in, and it is not carelessness — it is diligence pointed the wrong
way. An agent runs the ability, the game answers, and the answer goes into the docstring
or the fixture *because it is true*: it is what the server really said, so it must be the
most honest example there is.

It is the one thing that must never be pasted. **What makes an example useful is its
SHAPE — field names, types, lengths, the order things arrive in — and the shape survives
having the values replaced.** The real numbers add nothing a reader can use and carry
somebody's account for ever. So invent values of the same shape as you paste, not later:
«later» is precisely why they are still here.

**A recording is not a fixture until it is anonymised.** The place for a genuine one is
a git-ignored tree — `results/`, `screenshots/`, `profiles/`; they are ignored for
exactly this reason. Anything that comes out of one of them and into a tracked file gets
its identifiers replaced on the way, in the same edit, or it does not come out.

**And no screenshot is ever committed, for any reason.** Take as many as you like — they
land behind `.gitignore` and stay on the disk that made them. A `.png` in a diff reads as
`Bin 41k` and in a review as nothing at all, while carrying a nickname, an alliance tag,
a coordinate or a taskbar with a login on it. `tests/test_repository_hygiene.py` fails on
anything tracked that is not text: it works off an allow-list of source suffixes, so an
image, a capture, a screen recording, a browser trace or a database fails whether or not
anybody thought to ban that particular extension.

### When a test genuinely needs the data

A test that parses a server reply needs a reply **of the right shape**, not a real one.
The contract it is checking is the field names, the types, the nesting and the edge
cases — never the digits inside. So write the fixture by hand: a made-up id that looks
made up, `Player1` and `Player2`, an alliance called `AL1`, zeros for a device id,
`<user>` in a path. It reads better too — a reviewer can see at a glance which value the
test is about.

**If a test only passes against a real value, it is testing the account, not the code.**
That is a broken test, and pasting a live reply into it hides the breakage instead of
fixing it.

### What that looks like

```python
# ❌ the live reply, pasted in because it is what really came back
ROLES = [_role(100, "1544820371002087", 35, "NightHollow", 241514404, "QRt")]
# ❌ …and the same mistake in prose, in a comment and in a command line
#    base at @[512,377|1832], device 7c1a44e90b6d4f27a5e3110cc84b2d55_n3d
#    run: python tools/rdp_instance.py --user gtaylor
```

```python
# ✅ the same shape, invented — a reviewer can see at a glance these are not real
ROLES = [_role(100, "1000000000000001", 35, "Player1", 241514404, "AL1")]
# ✅ …and prose says what the field IS, not what one account's happened to be
#    base at @[<x>,<y>|<server>], device 00000000000000000000000000000000_n3d
#    run: python tools/rdp_instance.py --user <the Windows login of that session>
```

Even the ❌ block is invented — a file that teaches this rule cannot be the one place
that breaks it, and «but it is only an example of the mistake» is how the last set got
in.

If you find one already in the tree, replace it in the commit you are making — do not
open a task for it and move on.

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

## A profile is a whole panel of its own

**Also binding, on every agent, with no exceptions.** One window holds several profiles
at once, and the operator's rule for them is one sentence: **«профиль — это полностью
независимый инстанс панели».** Its own threads, its own log, its own captures, its own
daemon, its own budgets. Nothing one profile does may be visible, audible or felt in
another.

So before you write down a value, ask the two questions in this order — the second is
where the mistakes are:

1. **Is there one of this per MACHINE or one per ACCOUNT?** A port, a socket, the
   desktop's foreground, the keyboard are the machine's, and they are shared on purpose
   through `panel/runtime/claims.py`, which hands out an OWNER rather than a wait. A
   log, a schedule, a capture, a daily budget, a commentary sink are an account's, and
   holding one in a module-level global is the bug this rule exists to stop.
2. **If it is an account's, what identifies the account AT THE MOMENT IT IS NEEDED?**
   Never «what is running right now»: most of this is wired up during the boot, when a
   profile whose client lives in its own Windows session has no client yet. Use
   something durable — the profile's name, its Windows session, its daemon port.

Getting (1) right and answering (2) with a snapshot is how the worst of these happened:
every capture the panel spawned was narrowed by a pid list read once, so three of four
profiles ran all day decoding all four accounts — a trigger firing off another account's
push, and the ★ auto-loot spending THIS account's five daily robberies on a tile
announced in somebody else's alliance. **A capture is narrowed by
`game_process.capture_narrowing(rt.settings)` and by nothing else** (#1306).

A line in a log obeys the same rule: `rt.say` / `rt.dbg` for a profile's own, and
`debug_log.panel_logger` for the handful of things that belong to the WINDOW — the
remote-control server, and a fallback nobody handed a logger to. Never the unscoped
tree, which is the FIRST open profile's file and therefore an account's.

The whole inventory — what leaked, what is shared deliberately, and what was measured —
is [`docs/research/profile-isolation.md`](docs/research/profile-isolation.md), and
`tests/test_profile_isolation.py` fails when one of them comes back.

## Read once, then LISTEN — and nothing runs in the background unasked

**This rule is binding on every agent working in this repository — dispatcher, worker, or
one-off session. No exceptions.** It is the operator's, in their own words:

> «Берем за правило, не долбить сервер любыми запросами, работаем в той же парадигме как и
> клиент, читаем один раз, остальное слушаем изменения, никаких активных действий просто в
> фоне быть не должно, все подобные моменты проговариваются отдельно».

Three sentences, and each of them is a separate prohibition.

1. **Read once, then subscribe.** Work the way the CLIENT works. The game client does not
   ask the server what it already knows: it is told the state once and kept up to date by
   the server's own updates. #1990 measured exactly that — over 45 s of an idle base the
   client's resource writers fired **zero** times and the numbers came back
   byte-identical, and one harvest fired 25 updates. So the panel reads a thing when it
   first needs it and then SUBSCRIBES (`panel/runtime/wire.py`); a clock is a safety net
   with a long interval and a stated reason, never the mechanism.
2. **Nothing active in the background.** No poll for the sake of polling, no periodic
   prod at the game, no «на всякий случай» round every few seconds. The game link is
   exclusive: every question asked in the background is a robbery, a rally join or an
   errand that did not happen. A reading that only exists because a timer went off is
   forbidden even when it is cheap.
3. **Anything that can ONLY be had by asking is a conversation, not a decision.** If a
   thing has no event behind it and cannot be learnt without a repeated question, that is
   **not** a licence to write the poll. It is a reason to go to the person, name the cost
   and the interval you propose, and **wait for an answer before putting it in**. Ask
   BEFORE, never report after.

The shape a compliant reading has: one play on first need → the answer held in memory →
a subscription (or a hook, or a signal) that says when it moved → the page showing HOW OLD
the reading is, so a stale one is visibly stale instead of quietly wrong. When there is no
signal to subscribe to, the honest thing is one reading with its age on it — and a door
for the signal to arrive through later, called by an event and never by a timer.

**#2016 is the worked example, and it got it wrong first.** The status strip is drawn
above every screen of the web panel, so its reading would have been the most frequent
question in the panel — and it shipped with a 10-second refresh, "paced" and measured and
argued for in a docstring, which is precisely this rule's definition of a background poll.
It reads once now (`panel/runtime/header.py`), holds what it read with its age beside it,
and exposes `mark_stale()` for the signal that does not exist yet. The scene and the open
window are CLIENT state — nobody tells the server that a player opened a screen — so
there is nothing on the wire to subscribe to, and what to do about that is the person's
call, not an agent's (docs/research/player-place.md).

What is NOT forbidden: reading in response to a person's press, reading once when a page
is first opened, and a scenario doing whatever it needs while it runs. The rule is about
what the panel does when nobody asked it to do anything.

## Game data lives only in the database

**This rule is binding on every agent working in this repository — dispatcher, worker,
or one-off session. No exceptions.** Anything the game told the panel — a tile, a task,
a squad, a tally, a history of what happened — is a row in a database, never a JSON file
somebody wrote by hand or a scenario left behind. `panel/runtime/store.py` is the one
door for a profile's own data (`panel.db`, `rt.store`); a store opened by something
outside a profile — a standalone collector, a report tool — keeps its own database with
the same discipline, not a plain file either.

**A new kind of game data gets a table with a migration, not a file.** Either a
dedicated table, the way `players` earned its own columns and indexes because a lap of
the map sorts and searches it by name, alliance, level, power — or, when the store is
read and written WHOLE and never queried by a `WHERE` clause, a named row in the shared
`blobs` table (`store.blob_get`/`store.blob_set`), the way the ★ tile list
(`secret_tasks_state`), the ghost map's own list (`ghost_map_state`), the daily rally
counts (`rally_counts`) and the daily resource tally (`resource_stats`) do since #1465.
**Only ONE of the four world pages ever had a list of its own** — the mine, train and
truck pages are re-read from `world_map.json` (the capture checkpoint named below) and
were never a separate store to move.

**And that one page is the worked example of a blob OUTGROWING itself (#1963).** The
monster list was `world_state_monsters` in `blobs` from #1465, and «read and written
WHOLE» stopped being true of it: 31 828 rows, 9.8 MB of JSON, re-serialised and written
**from the Tk thread** on every poll of its follow clock — 0.20–0.32 s, five times a
minute, per profile, which is what «панель тормозит» was. It has a table of its own now
(`monsters`), written a ROW at a time through `store.submit`. The question to ask before
choosing is not «is this a list» but **«what is the unit of a WRITE, and who is on the
thread doing it»**: a store whose every change rewrites the whole of it, off the Tk
thread, is a blob; one that grows without bound, is touched a few rows at a time, or is
narrowed by a `WHERE`, is a table. Either way the schema is a HISTORY — append a migration, never edit one that has
shipped — and an OLD file a profile still has is brought across exactly once
(`panel.runtime.store.blob_import_once` / `import_once`) and kept beside the database as
`<name>.imported`, never deleted: an import that turns out to have misread a field is
answered by opening the file, and a delete is answered by nothing.

**A SETTING IS IN THE DATABASE TOO, since #2017 — this half of the rule was reversed by
the person, in these words: «Никаких json, все должно быть в базе, еще раз услышу, что
что-то хранится в файлах — получишь по жопе».** What used to be written here — that a
setting stays a file because somebody may want to hand-edit it — is no longer true, and
it is spelled out rather than quietly deleted so that the next agent can tell an
exception from an omission. The timer catalogue, the trigger catalogue and the rally
caps are rows of `blobs` under `settings:<name>` (`panel/runtime/settings_files.py`); a
profile written before that has its file carried across ONCE and kept beside the
database as `<name>.imported`.

**`profiles/settings.json` has moved too, since #2025** — it was named here as a store
that could not, «because there is no machine-wide database». There is one now: the person
decided there would be ONE database for everything, so the panel's own settings are rows
in it under a scope no account can be named (`:panel`), and the file is carried across
once and kept beside as `settings.json.imported`. **`config.json` went with it**, which
did mean redefining what a profile IS: **a profile is a ROW in the `profiles` table**
(name, config, created_at), not a directory with a file in it (#1306's rule, replaced).
The directory stays and holds what is not settings and not game data — the logs, the
locks, the heartbeat, the capture checkpoints — and a directory with no row is a STRAY
the panel says out loud about, exactly as before. A profile that still has a
`config.json` is adopted once, on the first start, and the file is kept beside it as
`config.json.imported`. What this bought is the thing the person asked for: creating,
renaming and deleting an account is ONE transaction with that account's own data, not a
directory move that can half-happen. The two shipped TEMPLATES (`panel/timers.json`, `panel/triggers.json`) stay files for a different
reason again: they are code, part of the repository rather than of an account.

**What counts as game data:** a tile, a task, a squad, a tally, a count, a history of
findings — anything the SERVER said or the panel derived from what it said. **What does
not, and stays a file:** a log
(`panel.log`, `debug.log*`, an append-only `.jsonl` that was never rewritten whole and
so never had the cost a database exists to remove), session bookkeeping
(`panel.lock`, `panel_alive.json`, `children-<pid>.json`, and `timers_last_run.json` —
the panel's own record of when ITS OWN schedule last fired, not a fact the server told
it), or a CAPTURE CHECKPOINT — a channel between the panel and a child process it
spawned, rewritten whole every tick and worth nothing after a restart on purpose
(`secret_tasks.json`, `ghost_recon_tiles.json`, `world_treasures.json`,
`world_map.json`). Moving one of those into the database would not be progress; it would
make durable the one thing that must not be, and hide a stale reading behind the same
trust a database's other rows have earned. `day_reset.json` is the same shape by a
different route: one game reading (`GetTomorrowZero()`), re-askable in under a second
and asked at most four times a day, kept only so a fresh panel does not have to ask
before it can decide anything — nothing accumulates in it and nothing is lost by asking
again.

**THERE IS ONE DATABASE, AND IT IS `profiles/panel.db` (#2025)** — one level above the
profile directories, holding every profile's settings and every profile's data. It was
one file per profile until then, and the person ended that in these words: «Давай сделаем
одну базу на всех и конфиги и профили, вынеси ее на уровень выше, из профилей, меньше
проблем с целостностью и консистентностью будет». A rename and a delete are one
transaction now instead of a directory move that can half-happen.

**The isolation rule did not soften — only what enforces it changed, and the new
enforcement is the point.** «A profile is a whole panel of its own» still holds word for
word. What used to hold it was the FILE; what holds it now is that forgetting is
impossible: every table is `all_…` with a `profile` column first in its primary key, a
store is built for one profile (`Store(path, profile)` — no default, because «the active
profile» as a module-level answer is the mechanics of #1306), and every connection
carries TEMP VIEWS under the OLD table names scoped to that profile. A read that forgets
the profile is already filtered; a WRITE that forgets it fails loudly instead of landing
in every account at once. Two tests in `tests/test_panel_store.py` fail if either half
comes undone. **Never reach a scoped table by its `all_…` name outside
`panel/runtime/store.py` without passing the profile** — that is the one way back in.

Not everything is in it, and the exceptions are the same as they always were, for the
same reasons: `cache/servers.json` is the list of warzones the game itself has, identical
for every profile on the computer (`tools/lib/server_list.py`), refreshed by a person's
press rather than rewritten on a tick — a file, not a table, because the cost `panel.db`
exists to remove was never its. `leaderboard_history.db` and `chat_history_<uid>.db` keep
their own databases with the same discipline, because a standalone collector and a
per-character store have no profile to ask. A new store outside this database is the same
conversation as any other exception below — asked, agreed, written down here.

**Nothing here is a licence to invent new tables for their own sake.** A store still
gets to decide it does not need one — a checkpoint, a log stays exactly what
it is. The rule is about where GAME DATA that is meant to survive a restart and be read
back whole may live, not a demand that every file in `profiles/<name>/` become SQL.

The audit that found #1465's gap, what moved and what did not (and why), is
[`docs/panel-storage.md`](docs/panel-storage.md) — read it, and its Russian mirror
[`docs/panel-storage.ru.md`](docs/panel-storage.ru.md), before deciding where a new
store belongs. Both are kept in step with the code in the same commit that changes it,
the same rule every other doc in this file already follows.

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

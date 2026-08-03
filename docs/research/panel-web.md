# The panel from a phone (#1221)

The bot runs where the game runs: a Windows machine with the client on it, a warm Lua
daemon beside it and a Tk window in front. Its owner is somewhere else — at work, on a
bus, in another room — and the questions they have are small ones. *Did the base get
collected? Is the client still up? Turn the alliance upkeep on. Run the gift claim now.*

None of those need the machine. They need the panel's ANSWERS, and a way to press three
of its buttons.

This is the write-up of what was built for that, why it is shaped the way it is, and
what was deliberately left out.

---

## 1. What it is

A small HTTP server inside the panel — one per WINDOW, answering for every profile
that window has open — serving a single page:

```
panel/web/api.py        the JSON surface — state, timers, scenarios, log, words
panel/web/server.py     the socket, the token, the static files
panel/web/static/       index.html · app.js · style.css — the page itself
panel/tabs/web.py       «Веб»: the switch, the address, the token
```

The page has four screens: **state** (is the client up, is the daemon up, what is the
panel doing, what is due next), **timers** (every errand with its switch, its period, when
it last ran and a «run now»), **scenarios** (all of `actions/*.md`, searchable, one press
each) and **log** (the panel's own lines, coloured by severity, with a browser
notification when one of them is an error).

Default port **9761** — and the number lives in `tools/lib/game_paths.py` like every
other value that has a different answer on a different machine. Three layers: the
profile's own knob wins, `LW_WEB_PORT` is the machine's answer, 9761 is everybody's. Off
until somebody switches it on.

## 2. Why it is not a bot, and cannot become one

`CLAUDE.md` is binding: an ability is one `src/lastwar_bot/actions/*.md` scenario and the
panel plays it. The web front-end is a SECOND player of the same scenarios, not a second
panel — and the file that keeps that honest is `panel/web/api.py`, where every route is
one call onto the runtime:

| route | what it is |
|---|---|
| `/api/profiles` | `rt.workspace.sessions` — which accounts are open |
| `/api/state` | `rt.game.up()`, `game_process.status(...)`, `rt.activity.current()` |
| `/api/timers` | `rt.schedule.timer_catalogue` + `timer_config()` + the last-run store |
| `/api/timers/run` | `rt.schedule.timers.request(timer)` — the scheduler's own queue |
| `/api/actions` | `panel.runtime.actions.list_actions()` |
| `/api/actions/run` | `rt.play_async(name)` — under the claim, on a worker thread |
| `/api/log` | the log bus, tapped |
| `/api/i18n` | `panel/locales/` |

There is no Lua here, no step sequence, no gate. A phone cannot ask this server to do
anything the window cannot, which is the point: the abilities stay in one place and both
front-ends are windows onto it.

## 3. Decisions worth the words

### 3.1 One server per WINDOW, and it answers for every profile in it

The first draft was one server per profile: profile A on 9761, profile B on 9762 if it
wanted one at all. That was wrong, and the reason is worth writing down because it is the
same reason a bug had already been found at the machine that week.

**A front-end that shows one of two open accounts, and does not say which, is worse than
no front-end.** The panel holds two profiles at once (#1206) and that is how this bot is
actually run; a page that says «база собрана» without saying whose is a page you cannot
act on. The identical confusion had already cost a live session — one profile reading the
other one's client and looking perfectly healthy doing it.

So: one socket, owned by the window. `/api/profiles` says what is open and which one the
window itself is showing; every other route takes `?profile=<name>` (a field in the body
on a POST); the page has a native `<select>` in its header and starts on the account the
window is showing. A press lands on the client of the account it names — that is the
whole point of naming one.

The way back up is an attribute the workspace sets on each session's runtime as it opens
it (`rt.workspace`). It is deliberately NOT declared on `PanelRuntime`: it is a fact about
a session opened *into* a workspace, and a runtime built on its own — a standalone tab, a
test — has none. Every reader asks with `getattr`, and a runtime without one answers for
itself and lists exactly one profile, which is the same code path with one session in it.

The tab is then the switch for the window rather than for the profile: the first session
whose switch goes on binds the socket, and a sibling profile's tab says «обслуживает
профиль X» and shows *that* server's address — including its token, since showing its own
would be an address that answers 401. A second PANEL is a second process with its own
registry: it binds its own port, or says the port is taken, which is then a real clash.

### 3.2 A tab, so switching it off means switching it off

Every panel tab is a plugin (`docs/panel-tabs.md`), and a tab that is off is not built —
it starts none of its captures and holds none of its state. Making the remote control a
tab makes «no remote control» reachable by unticking one box, and puts the switch, the
address and the token where a person already looks for a tab's settings.

The tab is `EAGER`, because what it is FOR is being reachable: a remote control that only
came up once its tab had been clicked in the window would be a remote control for
somebody standing at the machine.

### 3.3 The token, and what it is not

One string per profile, generated by the panel (`secrets.token_urlsafe`), shown on the
tab, carried either in a cookie or as `?token=…` on the URL — which is what makes the
link on the tab work in one tap. Compared with `hmac.compare_digest`.

**There is no TLS.** This is a home network: the phone, the router and the machine that
farms. The tab says so in all eleven languages, and the reason it is not hidden behind a
«secure» word anywhere is that a person who forwards this port to the internet should
know exactly what they are forwarding. Anyone who needs it from outside puts it behind
something that terminates TLS properly.

Two routes answer without the token: `/api/ping` (how the page asks whether it has one)
and `/api/i18n` — the same eleven files this repository publishes, and without them the
login box would be the one screen in the panel written in locale keys.

### 3.4 The log is tapped, not drained

`LogBus.drain()` empties the queue: there can be exactly one drawing side, and it is the
window. A second reader that drained would take lines away from it. So `LogBus.tap()`
was added — every line is handed to the taps as well, on whatever thread produced it —
and the web api keeps a ring of the last 400, numbered.

The phone polls `/api/log?since=N` and is handed only what is new. A phone that has been
in a pocket long enough to fall off the end of the ring gets `reset: true` rather than a
silent gap. On start-up the ring is seeded from the profile's `panel.log`, so connecting
after an hour of farming shows the hour rather than a blank screen.

### 3.5 Which thread, and the two things that cannot cross

An HTTP worker may not touch a Tk variable or a widget: reading one off the Tk thread
raises «main thread is not in main loop» whenever the main thread is not inside the event
loop, and a worker never is. So:

* a knob is read by handing the read to the Tk thread (`rt.tick.on_tk`, 1.5 s), falling
  back to the profile's saved values when nobody is pumping — the same fallback the
  schedule already makes;
* a timer's switch is moved through `TimersTab.set_enabled` **on the Tk thread**, because
  while that tab exists its boxes ARE the configuration and a switch written straight to
  `timers.json` would be overwritten by the next save — from the phone that looks like a
  switch that does not stay;
* the process scan (`game_process.status`) is done on the HTTP thread, never handed to
  the drawing one, and cached for five seconds: it walks every process on the machine,
  and a phone polling every two seconds must not repeat that (#1211 is what a frozen
  window looks like).

### 3.6 Not one word of the page is written in the page

Every readable string in `index.html` is a `data-i18n` key and every string in `app.js`
comes out of `T(key)`; the table is `/api/i18n`, which is `panel/locales/` — the same
eleven files the window uses. So the phone speaks whatever language the panel is set to,
a key added for the window is on the phone in the same commit, and a twelfth locale file
is a twelfth language in both.

`tests/test_panel_web.py` walks the HTML and the JavaScript for keys and asserts every
one of them is in every shipped locale, with matching placeholders — the Python i18n test
cannot see this, because it only parses `.py`.

### 3.7 The phone is the case, not a case

The page is written mobile-first and then MEASURED — Chromium mobile at 360×640 and
WebKit iPhone 15 at 393×852, through the real engines, with the screenshots looked at
rather than assumed (`~/playwright-tests/shot-panel-web.js`). The first pass found seven
things wrong that reading the source would never have shown, and the two worth
remembering are:

* **the switches were 26 px.** Drawn by the browser, which on WebKit is a white square in
  a dark theme, and impossible to be sure of with a thumb. They are toggles now — 56×32
  of control inside a label that is 48 px tall and the width of the card, so the title
  toggles the errand as surely as the switch does. The audit measures the EFFECTIVE
  target (a control inside a `<label>` is hit anywhere on the label), which is why an
  iOS-sized switch passes and a bare 26 px checkbox does not;
* **the log was a wall of green.** The severity classifier calls «готов», «запущен»,
  «включён» ok, so every ordinary line was coloured and the one red line was lost among
  them. Only the bad news is coloured now, with a bar down the left edge so it is findable
  while scrolling past.

What a static reading can keep honest is pinned in `tests/test_panel_web.py`: the viewport
and the safe area, no `:hover` anywhere (a phone has no cursor, so a rule that only shows
on hover never shows), a 44 px floor on every declared control height, 16 px on every
field (or iOS zooms the page on focus), every media query WIDENING rather than narrowing,
and no fixed width above 360. The engine run stays outside the repository — there is no
node in this project and there should not be one for this.

## 4. What was left out, and why

* **An Android application.** The original idea, dropped: `tkinter` does not exist on
  Android, the game does not run there either, and a browser page reaches iOS as well
  for nothing.
* **Server push (websockets, SSE).** A poll every 2.5 seconds is a handful of bytes and
  survives a phone that sleeps, a Wi-Fi handover and a proxy. The notification the person
  actually wants — «something failed» — is raised by the browser off the poll that found
  the line.
* **Editing.** Scenarios cannot be written from the phone and settings cannot be changed:
  the phone is for watching and for the three presses above. A text editor on a phone is
  a way to break a profile with one thumb.
* **A QR code for the link.** Would need a generator or a dependency; the address is
  short and the token is twelve characters.
* **Accounts and passwords.** One token per profile, regenerable. There is one person.

## 5. Trying it

```
python -m panel.tabs.web --profile main
```

opens the tab on its own: tick the switch, and the address it shows is the one to open on
a phone that is on the same network. In the panel it is «Веб», between «Настройки» and
«Чат».

```
C:\Python312\python.exe tests\test_panel_web.py
```

covers the routes, the token, the traversal, the log numbering and the words — with no
display and no game.

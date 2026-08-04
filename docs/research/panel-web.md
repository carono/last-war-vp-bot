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

The page has four screens of its own: **state** (is the client on the line, is the daemon
up, what is the panel doing, what is due next — and the client's own lifecycle, §3.10:
start it, close it, put it back), **timers** (every errand with its switch, its period,
when it last ran and a «run now»), **scenarios** (all of `actions/*.md`, searchable, one
press each) and **log** (the panel's own lines, coloured by severity, with a browser
notification when one of them is an error).

Everything past those four comes from the TABS, which hand the phone their own screens
(§3.9) — the profile and its resources, the accounts, the alliance, the heroes, the
inventory, the chat, the rallies and where the squads are, the starred secret tiles with
their countdowns, the command post's three pages, today's duel plan, the statistics.
Three tabs deliberately have none: «Настройки», «Веб» and «Develop».

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
| `/api/state` | `rt.game.up()`, `game_process.probe(...)`, `rt.activity.current()` |
| `/api/timers` | `rt.schedule.timer_catalogue` + `timer_config()` + the last-run store |
| `/api/timers/run` | `rt.schedule.timers.request(timer)` — the scheduler's own queue |
| `/api/actions` | `panel.runtime.actions.list_actions()` |
| `/api/actions/run` | `rt.play_async(name)` — under the claim, on a worker thread |
| `/api/game` | the client's lifecycle — `runtime/game_control.py`, which is `rt.play_async` of one of three recipes |
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

### 3.2a Reaching it from outside the home network

**Forward the port on the router.** That is the whole of it: the server already listens
on every interface, so nothing in the panel has to change, and WHO may connect is the
filter on the router — which is where that question belongs and where the operator
already answers it. A VPN in front is better still and is not this repository's to
configure.

**TLS is available and is nobody's default.** Point the two knobs at a certificate and
its key in PEM and the server speaks HTTPS instead of HTTP; the address the tab shows
follows the scheme, because an `http://` link to a TLS-only server fails in a way nobody
diagnoses on a phone. A certificate that will not load takes the server DOWN rather than
falling back to plain HTTP — believing you have TLS and not having it is the one failure
worse than having none. The panel does not generate one: that needs a library this
project does not depend on, and a self-signed certificate warns in every browser once
per device anyway. The tab prints the `openssl` line that makes one.

The scheme is decided by the SOCKET, not by the fields on the tab, and both the link and
the warning under it follow it. The certificate that matters belongs to the server that
is actually bound — which on a sibling profile's socket (§3.1) is not the one named here —
so a tab whose own fields are empty still hands out `https://` when the server answering
has a certificate, and a tab whose fields are full still says `http://` when the socket
answering has none. `tests/test_panel_web.py` pins the server's scheme AND the tab's,
because the first was true and the second was not: the tab spelt `http://` into the link
whatever the server was doing, which is the failure this paragraph exists to prevent.

### 3.3 The token, and what it is not

One string per profile, generated by the panel (`secrets.token_urlsafe`), shown on the
tab, carried either in a cookie or as `?token=…` on the URL — which is what makes the
link on the tab work in one tap. Compared with `hmac.compare_digest`.

**The token is the whole of the authentication, and by default it travels in clear.**
This is a home network: the phone, the router and the machine that farms. TLS exists
(§3.2a) but is nobody's default and needs a certificate this project will not generate,
so the tab says in all eleven languages what the address it is showing actually is. The
reason none of it is hidden behind a «secure» word is that a person who forwards this
port to the internet should know exactly what they are forwarding: a token on a URL, over
plain HTTP, unless they pointed the two knobs at a certificate.

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
* the process scan (`game_process.probe`) is done on the HTTP thread, never handed to
  the drawing one, and cached for five seconds: it walks every process on the machine
  and its socket table too, and a phone polling every two seconds must not repeat that
  (#1211 is what a frozen window looks like). What it caches is now the TRIPLE
  `(running, link, label)` — the phone paints the link (`online` / `lost` / `unknown` /
  `offline`, §3.8) and not the process, because a client that lost the server is running
  and doing nothing at all.

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

### 3.8 The pill says CONNECTED, never «the process is there» (#1223)

The state page's first pill used to be `state.game.running` — the process list, in two
colours. That is the reading a stranded client passes: it keeps its window, its pid and
every number it read yesterday, so «работает» stayed green over an account that had not
spoken to the server since the small hours, while every errand went on reporting success.

`/api/state` now carries `game.link` beside `game.running`, and the page paints the link:

| link | pill | what it means |
|---|---|---|
| `online` | green | an ESTABLISHED connection to the game server — the only green one |
| `lost` | red | the client is up and its sockets are half-closed: the server hung up |
| `unknown` | amber | the client is up and its sockets say nothing yet — one still coming up, or a machine that will not attribute them. NOT a fault |
| `offline` | red | no client at all |

`running` is left exactly as it was, because it is what the watchdog acts on: a client
that lost the server must not be killed and relaunched from under the person. The word on
the pill is `web.ui.link.*` in all eleven locales, and the window's own strip is coloured
from the same four ids (`panel/__main__.py`, `LINK_COLOURS`) — the mirror rule, both ways,
in one commit. The reasoning behind the four is `docs/research/server-link-status.md`.

### 3.9 A tab hands the phone its own screen

The four screens above are the panel's; everything else on the phone belongs to a TAB.
`PanelTab.web_view()` returns the tab AS DATA — cards, rows, items, pills — and one
renderer in `app.js` draws all of them; `web_press(action, args)` is the same tab's
button. A tab that has both and says `WEB_SCREEN = True` appears under «Ещё» with no
markup written for it anywhere.

Two rules make that safe, and both are pinned by `tests/test_panel_web_screens.py`:

* **keys, not sentences.** `title`, `label`, `empty` and `pill` are locale keys the
  browser says out of `/api/i18n`; `text`, `value`, `detail`, `note` and `head` are data
  — a player's name, a count, a date. Get it backwards once and a Russian sentence
  reaches somebody running the panel in Turkish, with nothing to catch it: the Python
  i18n test reads `.py` for `t()` calls, and a string returned in a dict is neither.
* **cheap.** `web_view` runs on the Tk thread every time a phone opens the screen, so it
  returns what the tab ALREADY has and never reads the game. A phone left on a screen
  would otherwise poll the client all day. The reading is refreshed by a press, which is
  the same «Обновить» the window has.

The tabs that offer one: the profile and its resources, the accounts, the alliance, the
heroes and the inventory (all five through `DataTab`, which is a reading and an
«Обновить» and therefore a screen by construction), the chat, the rallies and the squads,
the starred secret tiles with their countdowns, the command post's three pages, today's
duel plan and the statistics.

The tabs that do NOT, on purpose, and the reason each was argued rather than assumed:
«Настройки» is paths, interpreters and ports — breaking a profile with one thumb is
easier than fixing it from a bus; «Веб» is the door the person came in through, and
managing it from the far side is how somebody locks themselves out; «Develop» is two
sniffers for working on the bot itself, off even in the window. That is the whole list,
a fourth is added the same way (ask, agree, write it in `CLAUDE.md` and
`docs/panel-tabs.md`, pin it in the test), and the test fails if one of the three quietly
grows a screen.

Where a tab still drives the game by hand rather than through a scenario — the
secret-task and ghost robberies spawn their tool, because the recipe only spends a queue
the tool fills (#1188) — the phone gets the READING and no button. That is an order of
work, not an exemption: the ability becomes a scenario first, and the button follows.

The contract a tab author writes against is `docs/panel-tabs.md`, «The phone's copy of
this tab, and keeping it in step».

### 3.10 The client's life, from the phone — and the table that keeps the two in step

The state screen's first card ends in three buttons: **«Запустить игру»**, **«Закрыть
игру»**, **«Перезапустить игру»**. They are the window's own three, and the reason they
are worth a section is not that they exist but *how* they were made to be the same three.

**All three are scenarios.** `launch_game.md`, `quit_game.md`, `restart_game.md` — the
last of which is the first two with an `ATTACH_GAME` between them. So a press from the
phone is `rt.play_async(<recipe>)` and nothing else, which is the only reason a remote
button of this weight is allowed at all (`CLAUDE.md`: an ability is a scenario and a
front-end plays it). «Закрыть игру» is the newcomer — until it there was a button to
start a client and a button to replace one, and the only way to *stop* one was the Task
Manager.

**Four things had to agree between the window and the browser**, and every one of them
would have been written down twice: which scenario each press plays, what the log says
before it starts, the word on the button, and when the press is meaningless. So they are
written down once, in `panel/runtime/game_control.py`, and both front-ends read it —
the window builds its row by walking `CONTROLS` and greys each button through
`available()`, the page draws `game.controls` off `/api/state` and obeys the `enabled` it
is handed. `tests/test_panel_web.py` fails if `app.js` so much as names one of the three
recipes: a press travels as an id, and the table resolves it.

**Availability is decided on the LINK, not on `running`.** The interesting client is the
stranded one — the process is there, the server has hung up (§3.8) — and it is exactly
the client somebody reaches for a phone about. So `lost` and `unknown` are both "there is
a client": «Закрыть» and «Перезапустить» are live, «Запустить» is not. Only `offline`
flips that round.

**The press is re-checked when it lands.** A phone out of a pocket is showing a
minute-old page, and a thumb is faster than the next poll — so `/api/game` reads the
client's state again and answers `unavailable` rather than running a recipe to no
purpose. The other two answers a press can get are `busy` (the claim is held: a timer
errand is mid-run, and a remote press must never cut in front of one) and plain `ok`.

**Two of the three ask first**, out of the same locale key in both front-ends: closing a
client and replacing one are each a minute of an account's evening if the thumb slipped.
The browser uses its own `confirm()` — the one dialog that is already the right size for
a thumb on every phone and cannot be mis-tapped through. «Запустить» asks nothing; the
worst it can do is start a client.

**The one thing the phone draws that the window does not** is a mark on the press that is
being played right now. That is presentation, not a control (`CLAUDE.md` gives each
front-end how a thing is *drawn*): the window says the same thing on its activity strip
and in its log, both of which are on screen the whole time, and a phone showing one card
at a time has neither in view — a restart is half a minute in which nothing else appears
to happen.

Measured live at 360×640 (Chromium mobile) and 393×852 (WebKit, iPhone 15), against the
running panel rather than a stub: no horizontal overflow, three buttons of 44 px, 16 px
type, nothing clipped in Russian — which is the longest of the eleven for these three
words. They stack rather than share a row: «Перезапустить игру» at 16 px does not fit
beside anything on a 360-wide screen, and a row that squeezed them would have ended in
three buttons of clipped text.

## 4. What was left out, and why

* **An Android application.** The original idea, dropped: `tkinter` does not exist on
  Android, the game does not run there either, and a browser page reaches iOS as well
  for nothing.
* **Anything that reaches the panel through a third party.** No service outside this
  machine belongs in the path to a game account, whatever it is called and however free
  it is. Reaching it from elsewhere is the router's job: a forwarded port, and the
  filter on the router deciding who may.
* **Server push (websockets, SSE).** A poll every 2.5 seconds is a handful of bytes and
  survives a phone that sleeps, a Wi-Fi handover and a proxy. The notification the person
  actually wants — «something failed» — is raised by the browser off the poll that found
  the line.
* **Editing.** Scenarios cannot be written from the phone and settings cannot be changed:
  the phone watches, and presses what is already a press in the window — a timer's
  switch, a «run now», a scenario, a tab's own button (§3.9). A text editor on a phone is
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

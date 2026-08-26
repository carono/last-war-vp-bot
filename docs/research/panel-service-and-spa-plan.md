# Plan: the panel becomes a Windows service, the interface becomes a React SPA (#1976)

Status: **approved 2026-08-25**, in progress. What was approved differs from the first
draft in one decisive way — see «The door, not the supervisor» below.

## 0. What the person asked for, as a number

> «Если работает сервис, значит мне нужно только запустить игру, и все связи должны
> быстро и без проблем с игрой устанавливаться.»

That is the acceptance criterion of the whole piece of work, and it is measurable:

**From the game client appearing to the light being green — the game server answering —
with not one action by the person. Measured today: 37 s (a watchdog relaunch on the live
`default` profile: the client process appeared at 16:07:27 and the link went green at
16:08:04; most of it was attach attempts refused while the client was still loading its
own code, retried on a five-second watch and an eight-second poll). Target: the client's
own boot plus a couple of seconds — no wait that belongs to the panel.**

The panel now SAYS the number itself, once per appearance of a client
(`log.game.link_ready`), so the criterion is checked by reading the log rather than by
anybody's impression. First live reading after the change, on `default`:
**«связь с игрой поднялась за 18 с после появления клиента»** — a panel restart against
a client that was already up, which is the other half of the same measurement.

Three consequences that are part of the criterion and not decoration:

* the attach happens the moment a client is there — not on the next tick of a slow poll,
  and never after a wait that grows;
* the trap of «the first look after the client appears does not take it» does not come
  back: the look repeats at ONE fixed short rate while nothing is held;
* a link that cannot be made is a loud failure with its reason, said ONCE — not silence,
  and not the same sentence every eight seconds.

## What the person decided, 2026-08-26

Four questions had been accumulating across three relays, each blocking a piece of P2.
They were asked together and answered together, and the answers are written here so that
nobody has to ask them again:

| question | answer |
|---|---|
| the emoji picker and the sticker grid on a phone — serve the sprites over the panel's own port? | **yes, serve the pictures.** The phone gets the same two grids the window has, out of the same extracted sprites (`tools/chat_assets.py`), by a route shaped like `/api/avatar` and `/api/itemicon` |
| «Разработка» / «Занятость» — the written-down divergence, or a screen? | **a screen** — done, see the row above. The sniffers stay in the window because their start and stop are message boxes, and that is written inside the screen rather than kept as a divergence |
| renaming and deleting a PROFILE from the phone — destructive | **allowed, behind a typed name** — done, see the row above |
| joining a rally from the phone — real troops leave the base | **build it, WITH the squads chosen** — a screen listing the squads and what is in them, not a bare «join» that sends whatever was last used |
| is the service a door the panels knock on, or the thing that BRINGS THEM UP? | **«Не, не пойдет, центр правды — это служба, если я её поднял, значит все уже должно работать»** — the fifth decision, 2026-08-26, and it reverses what §«The OWNER, not the door» used to say. One thing to start on this machine; the panels are the service's doing |

The two that are still to build are the first and the last, and each needs one thing this
repository already has a shape for: a picture route for the sprites, and a screen (rather
than a button) for the squads.

## The OWNER, not the door (reversed 2026-08-26)

**This section used to say the opposite and the person overruled it, in these words:**

> «Не, не пойдет, центр правды — это служба, если я её поднял, значит все уже должно
> работать»

What it said was that the service **does not start the panel and does not supervise it** —
the panel comes up with its Windows session and CONNECTS, and «there is no process anybody
has to bring up, so there is nothing that can fail to come up». The reasoning was sound
about session 0 and wrong about the machine: it left TWO things to bring up, and the one
that survives a reboot was the one that did nothing on its own. A person who has installed
a service has already said what they want to happen.

So the service OWNS the panels (`panel/service/keeper.py`):

* **it starts them** — at boot, and whenever a wanted profile has no panel serving it;
* **it outlives them** — a panel that dies is started again, and a panel restarting ITSELF
  («⟳ Перезапустить панель», which is how a code fix reaches a running panel) is given a
  grace window so nobody overtakes it;
* **it puts them down properly** — stopping the service asks each panel it started to quit
  through `panel/runtime/panel_control.py`, the same shutdown the window's ✕ runs, and
  waits. Nothing is killed. A panel a PERSON started is not the service's to stop and is
  left alone;
* **which profiles is a setting** — `service.json` → `keep`, and an empty list means the
  ones this machine's panel last had open. No name is written into the code.

### The one honest limit, and it is not a shortcoming to fix

A service lives in session 0: no desktop, no window station, no foreground, no screen. The
panel needs all four the moment it touches the game. So the service starts the panel in a
SIGNED-IN session (`panel/service/session.py`: `WTSQueryUserToken` → `DuplicateTokenEx` →
`CreateProcessAsUserW` on `winsta0\default`, which needs `SeTcbPrivilege` — LocalSystem
has it, an ordinary account does not).

**With nobody signed in there is no session to start it in.** The service says so once and
keeps looking. There is no flag that fixes this and no cleverness that gets around it: a
game that draws needs a session that draws, and a panel in session 0 would come up, dial
in, and fail at everything it exists for. Windows' own answer is «sign in», or «leave a
session logged on and disconnected» — which is what a second client already does here
(`docs/research/multi-instance-rdp.md`). Everything else about the machine — the port, the
token, the routing, the page — is up before anybody signs in, exactly as it was.

Installing it is `service_install.bat` and removing it `service_uninstall.bat` — what
they register is `tools/run_service.py --service` under the repository they sit in, run by
a windowless interpreter. Running the installer again on a machine that already has the
service REWRITES its command line and RESTARTS it, which is how new code gets in.

What the service is: the port, TLS, the token, the SPA, the register of panels, the
routing to them, and the panels themselves. What it is not: anything that touches the
game.

## What is done, and what it cost

| step | state | evidence |
|---|---|---|
| acceptance criterion measured and said by the panel | **done** | `log.game.link_ready`; live 18–19 s on a panel restart, 37 s measured before the change on a client start |
| link caught at one fixed short rate | **done** | two rates, `CATCH_SEC` / `WATCH_SEC`, no backoff (#1976) |
| a probe nobody sent stops earning green | **done** | `Recovery.probe_unstarted` |
| P1 — React SPA at parity with the old page | **done** | `/app/`, five views, thirteen screens, live on WebKit 390×844 |
| «/» is the SPA; the old page frozen at «/old/» | **done** | the redirect, and the tests read the React source now |
| P2 — «Настройки» on the phone | **done** | fields, and the four which-client values kept as readings |
| P2 — an errand's schedule from the phone | **done** | `/api/timers/edit`, period and weekdays |
| P2 — the panel's language | **done** | screen, every open profile switches at once |
| P2 — which profiles are open | **done** | `panel/runtime/profile_control.py`, shell-registered |
| the web is the MAIN front-end | **decided** | «Веб теперь главный инструмент, ему и полный функционал» — `CLAUDE.md` and `docs/panel-tabs.md` rewritten; new goes to the web only |
| P2 — the ghost standing order from the phone | **done** | switch + level as fields |
| P2 — renaming and DELETING a profile from the phone | **written, not yet live** | the two presses the shell held back: `profile_control` grew `rename` / `delete`, and each carries the guard the message box used to be — the new name typed for a rename, the profile's OWN name typed back for a delete |
| P2 — the rally MANUAL RUN from the phone | **written, not yet live** | target, level, repeats and squads as fields; «Запустить» asks first, «Стоп» sets the same event the window's button does |
| P2 — the rally JOIN from the phone | **written, not yet live** | the four squad switches first, then the press: `join_rally` was always one recipe, and what was missing was the argument it spends |
| P2 — the emoji picker and the sticker grid | **written, not yet live** | `/api/chatsprite` serves the extracted art; an emoji pre-fills the send box, a sticker goes as its own message |
| P2 — «Ограбить» beside ONE ghost row | **written, not yet live** | the card is drawn from the page's own list, so a row carries a uuid and the game's own verdict |
| P2 — «Разработка»: the jam board on the phone | **written, not yet live** | the third divergence ended: `WEB_SCREEN = True`, «Занятость» whole as one card per grid, the update channel as a switch, the sniffers a READING (their start and stop are two message boxes) |
| P2 — the ghost ROBBERY from the phone | **written, not yet live** | the ability became one recipe first: `ARGS queue` on `actions/steal_ghost_recon.md`, the panel hands the squads over and spawns nothing. «Ограбить всех» is a screen action; nothing here has been pressed in a real game |
| P2 — the Windows-session block | **done** | diagnosis is state now, «Проверить» and «Поднять сессию» are presses |
| P2 — the picture quality | **done** | a `choice` field plus the client's own reading; the read verified live |
| P2 — switching character | **done** | typed confirmation replaces the window's dialog; the row's own fields fixed |
| P2 — the errand's rule from the phone | **done** | five fields on «Свои задания»; live-checked, and a bad number is refused |
| P2 — the rally switches from the phone | **done** | fields on «Ралли»; the capture re-points, the auto-join is the standing order |
| P2 — the errand EDITOR from the phone | **done** | `/api/timers/save` · `/copy` · `/delete`; add, rename, copy, delete, steps, args, title — the dialog's four refusals, off its own keys |
| P2 — «Дуэль»: the whole week and the sets | **done** | six day cards of switches, ceilings, details and picks; the sets card creates, renames and deletes; a screen action may `confirm` now |
| P2 — the rally kind filter's «все / никакие» | **done** | two screen actions; `set_all_kinds` moves the STATE and the boxes after it, so it works with no drawn tab |
| P2 — answering in CHAT from the phone | **written, not yet live** | the ability became one recipe first: `CHAT_SEND` in the DSL, `actions/send_chat_message.md` over it, the tool kept as the command line. The panel was down and Windows interop from WSL with it, so nothing here has been sent in a real game — the window's three sends and the phone's two are the first thing to try when it is up |
| P2 — the treasure feed's own filter | **done** | four switches on «Сокровища (отладка)»; the clipboard press stays at the machine |
| P2 — what is still window-only | see below | |
| P0 — the service, and the panel dialling out to it | **live** | `panel/service/` + `panel/runtime/service_link.py`; measured on this machine: the door on 9762, the web on 9763, one panel dialled in with four profiles, and `/api/profiles` through the SERVICE answered by that panel |
| P0 — installed as a Windows service | **live** | RUNNING under LocalSystem, `--service`, auto-start; see «A service is a protocol» below |
| P0 — the service OWNS the panels | **written; the session-0 launch needs one elevated press to confirm** | `panel/service/keeper.py` + `session.py`; the fifth decision above. Measured live in the foreground: the keeper started a panel by itself, the panel dialled in and `/api/panels` showed it. `CreateProcessAsUserW` from session 0 is the half only the installed service can run |
| P3 — the panel runs with NO WINDOW | **live** | `panel/headless.py` + `headless.bat`; measured beside the running window: it opened a profile, attached the game's Lua VM, dialled the service and answered through it — `/api/state`, `/api/screens` and four tab screens drawn by a panel that has no window |
| P3 — a tab's STATE survives Tk | **done** | `panel/runtime/statevar.py`; 97 tab variables and the settings binder go through it. With a window they ARE Tk variables, so nothing about the window changed |
| P3 — the clock without Tk | **done** | `ThreadTicker`: one thread, FIFO hand-overs. A rootless runtime used to get a `Ticker` that armed nothing |
| P3 — the RUNTIME imports no tkinter | **done** | the log spool split from the pane (`panel/runtime/log_spool.py`); `import panel.runtime` and `import panel.headless` both work with `tkinter` unimportable |
| P3 — the DRAWING deleted | not started | the order is written below |
| P4 — the rules and the parity tests | partly | the `settings` divergence is already rewritten |

**Nothing is window-only any more.** JOINING a rally was the last one, and it went the
way the two robberies went: the ability was already one recipe, so what was missing was
its ARGUMENT. The squads a join spends are four switches on the same card now, and
«Присоединиться» travels beside them behind a typed-free confirmation, because troops
leave the base when it is answered. The ghost robbery lost its spawned tool the same way
in #1976, the secret-task one in #1272.
The errand EDITOR is no longer among them: adding,
renaming, copying, deleting an errand and rewriting its steps, its args and its title all
travel now (`/api/timers/save`, `/copy`, `/delete`), and the panel refuses the same four
things the window's dialog refuses, off the same locale keys. What made it the largest
piece of P2 was that it had been a divergence («a phone that rewrites a recipe by a
mistyped character is not a remote control») and stopped being one the moment the person
said the web gets the whole function. Renaming and deleting a PROFILE are no longer among them either, and they went the way
that sentence said they should: destructive, so they wanted a TYPED CONFIRMATION like the
character switch has, and got one rather than an exemption. A delete happens only when the
profile's own name is typed back, a rename only when a new name is; and a rename is not
offered for a profile open on ANOTHER page — that session holds its log files and its page
carries the old name, so moving the directory under it would leave both pointing at
nothing. Opening the profile's FOLDER stays at the machine, because a directory listing is
not a thing a phone can be handed. Sending a CHAT message is no longer among them, and it is the
worked example of the ORDER OF WORK the rule states rather than an exception to it: the
window spawned a tool, so the phone had the reading and no box; `CHAT_SEND` made the
ability one recipe, `panel/tabs/chat.py` plays it from both sides, and the phone answers
into the room its own card is showing (never «wherever the window is looking» — outgoing
chat cannot be unsent). The emoji picker and the sticker grid have travelled
too, and they are the worked example of a GAP AWAITING AN ANSWER being answered: they are
grids of sprites the client extracted onto THIS machine's disk, so putting them on a phone
meant serving those images over the remote-control port. Asked, agreed, built —
`/api/chatsprite`, the third route of the shape `/api/avatar` and `/api/itemicon` already
had, behind the same token and taking no profile. A tap on an emoji opens the send box
with its `{e:<id>}` token in it; a sticker goes as its own message, because the game
allows no text beside one. Chat PHOTOGRAPHS are deliberately not reachable through that
route: they are somebody's own pictures, and the phone draws them from the link the
message carries. «Разработка» HAS its screen now (#1976): «Занятость» whole
and the update channel as a switch, with the sniffers a reading and the recipe editor
still in the window. The remote control's own port, token and certificate:
the standing divergence, and the one thing that will need an answer before the window
goes — see the note in the risks below.

## A service is a protocol, not a program Windows starts

The first registration worked and the service hung: `sc query` said `STOPPED`, `sc start`
never came back, and the System log said what it always says —

    7009  Превышение времени ожидания (120000 мс) при ожидании подключения службы …
    7000  Сбой при запуске службы … из-за ошибки

which is error 1053. **Nothing was wrong with the service's own work.** What was missing
was the dialogue: within seconds of being launched, a service must connect to the Service
Control Manager (`StartServiceCtrlDispatcher`), register a control handler and report
`SERVICE_RUNNING`. `tools/run_service.py` ran a loop and never said a word, so the SCM
waited its whole timeout and declared the start failed. A program that is correct and
silent is, to Windows, a program that is hung.

**The fix is `--service`**, and it is what the registration points at now:

    "<pythonw>" "<repo>\tools\run_service.py" --service

With the flag the process speaks the protocol; without it — run by hand, from
`service.bat` — it runs in the foreground exactly as before. `StartServiceCtrlDispatcherW`
failing with 1063 IS «you were not started by Windows», so a hand-run with the flag says
so and carries on in the foreground rather than exiting mute.

**Written in `ctypes` against `advapi32`, not with `pywin32`.** The machine this was
written on has `pywin32`; other people's do not, and a service that only starts where
somebody already had a package is the hard-coded-path mistake in another costume
(`CLAUDE.md`, «Nothing about one machine is written into the code»). The whole dialogue is
about a hundred lines of standard library. The panel is imported INSIDE `ServiceMain`, for
the reason the bug teaches: every second spent before the dispatcher connects is a second
the SCM spends waiting.

**Where it says things.** A service has no console and, under `pythonw.exe`, no useful
stdout, so the log is a file whose path is COMPUTED — `LW_SERVICE_LOG`, or `service.log`
beside `service.json` in the repository root (git-ignored, rolls once at 4 MB). It is
deliberately not a panel's log: this process runs as LocalSystem in session 0, belongs to
no account, and a line of its landing in somebody's `panel.log` would be a lie about who
wrote it. A start that fails now leaves a traceback there instead of silence.

**LocalSystem is the right account**, and the reason is what the service IS: it listens on
`127.0.0.1:9762` for panels that dial OUT to it, serves the web port, reads and writes
`service.json` beside its own code, and never touches the game, a window, a desktop or a
user's profile. Session 0 costs it nothing. The one requirement is a path LocalSystem can
see — a local disk, never a mapped network drive; a junction on a local volume is fine,
which is what this machine has.

**Running the installer again REPAIRS an old registration** (`sc config` with the new
binPath) instead of saying «already there, uninstall first»: the hung version is already on
a machine, and one click should be enough to fix it. Windows is also told to restart the
service by itself if it ever dies (`sc failure`, 5 s / 15 s / 60 s, counter forgetting after
a day), and the elevated window now STAYS OPEN (`cmd /k`), because everything it says —
the state, the log path, a refusal — used to flash past and close.

**What is verified and what is not.** Verified from a session without administrator rights:
both dry-runs, the exact `sc create` line, the SCM dialogue's own failure path (running
`--service` by hand logs «not started by Windows» and continues in the foreground), and the
System-log evidence of the original 1053. **Not verifiable here: the real start.** That
takes one elevated press — `service_install.bat`, «Да» in the UAC prompt — and then
`sc query LastWarBot` saying `RUNNING`.

## The eight panels, and why nobody could see them (#1994, 2026-08-27)

**One profile, eight `panel.headless` processes, for hours.** Found while #1993 was being
delivered: the commit was in `master`, the tests were green, the panel had been restarted
— and the live panel went on answering with the code from before the fix. The proof that
it was not delivered was a probe, not a reading: `press set` answered `unknown` (new code)
while `press carriage_next` answered `{"ok": true}` (old code), from the same port,
seconds apart, because the two presses reached two different processes.

**Every guard against «two panels on one account» was blind to the windowless one.** The
window has taken the profile's instance lock and beaten its heartbeat since #1206
(`panel/runtime/host.py::start_heartbeat`). `panel/headless.py` took neither — and
`autostart._panel_profile`, the reading behind `panel_pids`, matched the module argument
against `"panel"` exactly, so `-m panel.headless` was not a panel to it either. Three
independent guards, all of them looking straight through the only kind of panel the
machine's own service starts.

**And the keeper's question was narrower than the answer it wanted.** `Keeper.serving()`
asks the register — which panels are TALKING to the service — and the keeper read that as
which panels exist. A panel that is up but not connected read as an empty account and got
another one started on top of it, every time the grace ran out.

What was done: the headless panel takes the lock per profile and refuses to open one that
another panel holds (exit code `HELD_EXIT`, so «already running» can be told from
«broken»); it beats per profile and leaves a farewell on the way out; `PANEL_MODULES`
names both panels; `autostart.locked()` answers about a profile that does not exist
without CREATING one — `ProfileManager.dir` creates what it is asked about, which is right
for opening an account and wrong for a question the keeper now asks every five seconds;
and the keeper asks the kernel (`held()`) before starting anything.

**The version string is not proof of a restart, and this is the general lesson.**
`/api/state`'s `panel.version` is computed off git every time it is asked, so it changes
the moment somebody commits — from the same process, running the same imported code. Both
the before and the after read `v1.0.0+612-dev`, and that was taken as evidence. The state
now carries `panel.boot` beside it (`panel/runtime/updates.py::boot`, stamped once while
the runtime is built): the pid that answered, when its code was imported, and the commit
it was imported from. Two polls that name the same pid are the same code, whatever the
version says.

## 1. Target architecture

**Built and measured, 2026-08-26.** What follows was the design; this is what it is now,
and the shape is unchanged bar one simplification worth writing down. The routing is the
PANEL'S OWN API: `panel/web/api.py::WebApi.dispatch` already answers
`(method, path, query, body)` for the whole surface and `panel/web/server.py::WebServer`
already takes an `api=` object, so the service is a register of connected panels and an
`api` that forwards to one of them (`panel/service/api.py`). Not one route is written
twice, and a route added to the panel tomorrow is served by the service the same day.

The transport is line-delimited JSON on a loopback socket the PANEL dials
(`panel/service/wire.py`): session 0 may not reach into an interactive session, and a
program in a session may always dial a loopback port — so the direction is forced by
Windows rather than chosen, and it needs no ACL, no per-session token and no firewall
hole. The door refuses to listen anywhere but the loopback; the world's half is the HTTP
port, behind the same token the panel's own server uses.


Two processes, and the split is forced by Windows, not chosen for taste.

```
  Windows service  "LastWarBot"   (session 0, LocalSystem, starts at boot)
      ├─ HTTP/HTTPS endpoint, token, TLS, the SPA bundle
      ├─ a register of the PANELS that have connected to it, and routing to them
      ├─ its own log (Event Log + file), start/stop/restart through `sc` / services.msc
      └─ starts nothing, restarts nothing, watches nothing

  Panel  (one per interactive Windows session, started BY THE SESSION — a logon task,
          exactly the way the session's own programs come up)
      ├─ everything today's panel process is, minus Tk:
      │    PanelRuntime per profile, schedule, triggers, stores, captures, children
      ├─ the Lua VM held in-process (#1911: lua_service.py, link.py) + the lease socket
      ├─ foreground input (pydirectinput), screenshots (mss), window search, il2cpp attach
      └─ CONNECTS OUT to the service and answers what it is asked; nothing connects in
```

The panel is what it is today with the window taken off. Nothing about scenarios, the
link's three statuses, the profiles, the stores or the schedule changes shape.

## 2. Session 0 — the honest answer

A Windows service runs in session 0. It has **no desktop, no window station of a user,
no foreground, no screen**. The bot needs all four:

| what the bot needs | works from session 0? | consequence |
|---|---|---|
| `pydirectinput` foreground input (the game ignores `PostMessage`) | **no** | must live in the agent |
| screenshots (`mss`) | **no** (black / access denied) | must live in the agent |
| finding the game window by title | **no** (different window station) | must live in the agent |
| il2cpp attach / thread hijack of the client | technically yes as SYSTEM (SeDebug), but the client is in a user session and ACE is hostile to foreign tokens (see the multi-instance wall) | keep it in the agent, where it is proven |
| a client in ANOTHER Windows session (RDP) | already solved by a small process over there, started by the panel | unchanged: agent per session |

So: **the service never touches the game.** It supervises, serves the web and routes.
This is the same shape the repository already uses for a second client, so it is not a
new mechanism, it is the existing one made the rule.

**What the service genuinely buys:** an endpoint that is up before anybody signs in and
stays up when they sign out, clean `start/stop/restart` by Windows, one process nobody
closes by accident — and, the one that matters most, **the cure is no longer locked
behind the illness**: a panel that will not talk is still reachable and still restartable
from the outside.

**What it does NOT buy, and must not be promised:** the bot still cannot play without an
interactive session — the GAME CLIENT itself needs one. If the user logs off, the client
dies with the session. Mitigation is the one already in the tree: the service keeps the
session alive / re-creates it by connecting to the machine's own RDP address with stored
credentials (one credential slot per address, so one address per account). Price:
credentials must be stored on the machine, and a disconnected session costs GPU
(measured earlier: a disconnected session is roughly three times the cost, 10 FPS floor).

**Other prices:** the service runs as SYSTEM, so every launch of a child must carry an
explicit user token and an explicit elevation; a crashed agent is silent unless the
service reports it; there is no window and no console to look at while debugging — only
the log and the web.

## 3. What is removed, and in what order (control is never lost)

The rule for the whole migration: **the old way of driving the panel is deleted only
after the new one has been used to drive it.**

* **P0 — the door and the panel, Tk still there.** The panel connects to the service;
  the service starts nothing. Nothing about the interface changes; the existing web page and
  the Tk window both keep working. Done when: the machine reboots, nobody logs in, the
  service is running, and the web endpoint answers `/api/profiles` with all four profiles.
* **P1 — React SPA at parity with today's web.** New bundle served by the service on the
  same routes; the old `panel/web/static/*` stays until the SPA covers it. Done when: the
  SPA does everything the current page does on a phone, on the `default` profile, live.
* **P2 — the gap (section 4) is filled.** Every tab, screen and control that only the
  window has appears in the SPA. Done when: the inventory list below is empty.
### The order the drawing comes out in

Everything above is done and changed nothing about the window on purpose: state, clock,
runtime and a windowless way to run. What is left is the DELETION, and it is destructive
by nature — a tab that loses `build()` has a blank page in the window and a complete
screen on the phone. So it goes in this order, each step its own commit with the tier
green after it:

1. **the shell stops being the only way in.** `headless.bat` exists (done); `panel.bat`
   keeps opening the window until the person has driven a day's farming from the SPA.
   That is the plan's own rule — the old way goes only after the new one has been used —
   and it is the one step an agent must not take on its own;
2. **the dialogs.** `servers_dialog`, `autostart_dialog`, `settings_dialog` — each
   already has a screen (§«Настройки», «Серверы», «Автозапуск», «Параметры»), so each is
   a delete plus the shell's call site. **`web_dialog` is the exception and the line above
   used to be wrong about it**: the remote control's own knobs — the port, the host, the
   token, the certificate — deliberately have NO screen (#1313: the door is not managed
   from the far side of it), so deleting that dialog with nothing in its place is the one
   deletion that would take the panel's front door with it. The way in that is neither
   the window nor the door is a command on the machine itself,
   `python -m panel.web_settings` (`panel/web_settings.py`, `--on` / `--off` / `--port` /
   `--host` / `--token new` / `--cert` / `--key` / `--address`), and it exists now — so
   step 2 is a plain delete again, and the divergence is unchanged and still pinned;
3. **the splash** (`panel/splash.py`), which exists only because a window takes seconds
   to draw;
4. **the tabs, one per commit**, in the order they are least used at the machine:
   `alliance`, `profile`, `heroes`, `inventory`, `accounts`, `stats`, `players`,
   `recruit`, `events`, `checklist`, `timers`, `treasure_debug`, `chat`, `command_post`,
   `rally`, `secret_tasks`, `vs_duel`, `develop`. Each loses `build()`, `settings_page()`
   and its `tkinter` import; each keeps `web_view` / `web_press` and its state;
5. **the shell itself** — `panel/__main__.py`, `panel/widgets.py`, `panel/runtime/
   log_view.py`, `panel/runtime/*_dialog.py` — and `panel.bat` becomes `headless.bat`;
6. **P4**: the parity rule in `CLAUDE.md` and `docs/panel-tabs.md` is replaced by the
   single front-end's contract, and `tests/test_panel_web_screens.py` and relatives stop
   comparing two front-ends and start pinning one.

* **P3 — Tk is deleted.** `panel/__main__.py` (the shell), `panel/widgets.py`, every
  `build()`, `settings_page()`, the dialogs, `log_view`, the splash. Tab state moves from
  Tk variables to plain runtime state; the clock moves from the Tk `after` queue to the
  agent's own loop (only 5 files use `after`, so the clock is the small half; the 164 Tk
  variables in tabs are the large one). Done when: the agent imports no `tkinter`.
* **P4 — the rules follow the code.** The «both front-ends» sections of `CLAUDE.md` and
  `docs/panel-tabs.md` are rewritten for one front-end, and the parity tests
  (`tests/test_panel_web_screens.py` and relatives) are replaced by tests of the single
  contract: every tab produces a screen, every screen is keys and data, every declared
  action has a handler.

## 4. Volume of stage 2, measured

* **20 tabs** in the registry. **12** offer a web screen today; the `default` profile
  shows **8** tab screens + 2 non-tab screens (`servers`, `autostart`).
* **~203 interactive Tk controls** across the tabs (buttons, checkbuttons, entries,
  combos) — the first, crude count. **The press surface is much closer than that number
  reads**, and the reason it looked so far apart is that the two sides were counted by
  different rules: a window control is a widget, a web control is an action id OR a field
  in a card, and a screen mirrors a whole table of window boxes with one toggle action.

  Counted by NAME instead — every control the window draws with a locale key, against
  every `label` a tab's own `web_view` declares — what the phone genuinely does not have
  is a short list, and most of it is deliberate:

  | tab | window-only | what it needs |
  |---|---|---|
  | «Таймеры» | — | **done**: add / edit / copy / delete and the steps, the args and the title, through `/api/timers/save` · `/copy` · `/delete` and an editor that opens under the row it edits |
  | «Разработка», «Занятость» | the sniffer pair, the recipe editor | **«Занятость» travels whole** and so does the update channel (#1976). The sniffers stay: start asks for a label and stop asks whether to keep the run, two message boxes — they travel when the typed word becomes an argument, the way «Аккаунты» and the profile presses did. The editor is a text editor, and running a recipe never needed it |
  | «Дуэль» | — | **done**: a card per day of switches, ceilings, details and picks, plus a sets card that creates, renames and deletes |
  | «Чат» | clear, monitor | **the send and the PICKER travel**: `CHAT_SEND` made the send one recipe, and `/api/chatsprite` serves the extracted sprites so the phone chooses by looking (#1976) |
  | «Командный пункт» | jump, scan | **both robberies travel** (#1976): «Ограбить всех» takes its queue as an `ARGS` of the recipe, and the per-row press followed once the card was drawn from the page's own list — those rows carry a uuid and the game's own «may this be robbed» |
  | «Ралли» | — | **all of it travels** (#1976): the join, behind the four squad switches it spends; the MANUAL RUN as a card of its own — target, level, repeats, squads, «Запустить» and «Стоп»; and the kind filter's «все / никакие» |
  | «Сокровища (отладка)» | «Копировать» | **the filter travels** as four switches; the clipboard is the MACHINE's and means nothing on a phone — «Сохранить» is the same fragment kept as a file |
  | «Профили» (the shell's own list) | — | **done**: open, close, create, rename and delete, the last two behind a typed word (#1976). The folder button stays at the machine |
  | «Секретки», «Профиль», «Инвентарь», «Аккаунты», «Игроки» | nothing of substance | — |

  So the remaining P2 work is **tens of controls, not two hundred**, and half of what is
  left is a decision rather than code.
* **API:** 21 routes today; the SPA needs roughly 40 (settings read/write, timers editing,
  tab toggles, per-tab settings pages, parameters).
* **i18n:** 2153 keys × 11 locales, already served whole by `/api/i18n`. The SPA keeps the
  rule unchanged — no literal in a component; a lint test scans the JSX exactly as
  `tests/test_panel_i18n.py` scans the tabs today.
* **Replaced:** 1169 lines of hand-written JS + 165 HTML + 460 CSS.

Rough size: ~25 screens, ~200 controls, ~20 new API routes, plus the Tk removal
(~15 k lines of tab code loses its drawing half and keeps its reading half).

## 5. Stack and delivery

* React + TypeScript + Vite; a small state layer (React Query-style polling over the
  existing routes — the API is already poll-shaped); one mobile-first design system.
* Built bundle committed under `panel/web/app/` and served by the service as static files;
  no Node on the target machine, no CDN, works on a LAN with no internet.
* Update: the bundle travels with the repository, exactly as the panel does now; the
  service serves whatever is on disk after a restart.

## 6. Access from outside

Unchanged in principle, stricter in practice: token in a cookie, HTTPS when a certificate
is configured. What changes with the service: the port and the certificate stop being a
per-window setting stored under a profile and become the SERVICE's configuration; the
service can bind before any user logs in; and the token becomes rotatable from the SPA
itself (which is safe once the panel is no longer reachable another way, and a locked-out
person can still reset it from the machine with `sc stop` + a config file).

## 7. Risks

1. **No session, no game.** The service is up and reports healthy while nothing can be
   played, if the interactive session is gone. The status must say this explicitly, in the
   link colours it already has.
2. **The panel's own start.** It comes up with the session, so «the session came up and
   the panel did not» is the one remaining way to have no panel. It is the same failure
   as today's — the hourly task exists for exactly it — and it is visible from the
   service, which can say «no panel has connected from that session» in words.
3. **Debugging gets harder.** No window, no console. Everything a person could see by
   looking at the window must be readable in the log and in the SPA before Tk is deleted.
4. **Tk state removal is wide, not deep.** 164 Tk variables hold tab state; each is a
   small mechanical change, but there are many, and a missed one is a setting that stops
   persisting.
5. **The parity rule disappears** — approved by the person for this work. Until P4 lands,
   the rule still stands and both front-ends must be kept in step.

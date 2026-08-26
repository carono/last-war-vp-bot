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

## The door, not the supervisor

The service **does not start the panel and does not supervise it**. The panel comes up
with the Windows session, exactly as the session itself does, and CONNECTS to the
service; the service never reaches into a session. This is the whole answer to «will it
be the daemon all over again»: there is no process anybody has to bring up, so there is
nothing that can fail to come up. Starting a panel into a session stays as a rare manual
button, if it is built at all.

What the service is: the port, TLS, the token, the SPA, the register of panels that have
connected, and the routing to them. What it is not: a watchdog, a retry loop, a thing
that owns a lifecycle.

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
| P0 — the service | **blocked** | Windows interop from WSL is down; not written blind |
| P3 — Tk removed | not started | after P2 |
| P4 — the rules and the parity tests | partly | the `settings` divergence is already rewritten |

**Still window-only, and why.** JOINING a rally — the three switches of the automatic
side travel, the join itself does not, because it is a send with SQUADS chosen for it and
a wrong squad sent from away is a squad that is not home when the next rally lands. That
is now the ONLY press held back by the order-of-work rule: the ghost robbery was the other
one, and #1976 finished the ability instead of excepting it — its queue is an argument of
the recipe, exactly as the secret-task one's became in #1272, so no child is spawned and
the press travels.
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
chat cannot be unsent). The emoji picker and the sticker grid have NOT travelled
yet, and that is a GAP AWAITING AN ANSWER rather than a divergence anybody decided: they
are grids of sprites the client extracted onto THIS machine's disk, so putting them on a
phone means serving those images over the remote-control port. Ask before building it —
and until it is asked, a phone can still send an emoji, because `{e:<id>}` tokens are
resolved inside the recipe and the ids are printable with the tool. «Разработка» HAS its screen now (#1976): «Занятость» whole
and the update channel as a switch, with the sniffers a reading and the recipe editor
still in the window. The remote control's own port, token and certificate:
the standing divergence, and the one thing that will need an answer before the window
goes — see the note in the risks below.

## 1. Target architecture

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
  | «Чат» | clear, monitor, the emoji picker, the sticker grid | **the send travels**: `CHAT_SEND` made it one recipe. The picker and the grid are sprites on THIS machine's disk — a gap awaiting an answer, not a divergence |
  | «Командный пункт» | «Ограбить» on ONE row, jump, scan | **«Ограбить всех» travels**: the queue became an `ARGS` of the recipe (#1976). A per-row press would have to re-derive the gates the page applies, so it waits for a row that carries its own uuid |
  | «Ралли» | join now, launch / stop a run | the join needs squads chosen for it — a screen, not a button. The kind filter's «все / никакие» travel now |
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

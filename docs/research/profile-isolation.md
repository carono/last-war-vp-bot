# A profile is a whole panel of its own — the inventory of where it was not

One window holds several profiles (`multi-profile-panel.md`). That design is sound and
mostly delivered: each profile has its own runtime, daemon, port, schedule, settings,
`panel.log` and `debug.log`. This file is the audit of what was still held by the
PROCESS when it belonged to ONE account — measured on a live four-profile panel on
2026-08-09 — and what was decided about each.

The operator's words, which are the specification:

> Потоки у разных профилей должны быть разделены и изолированы, и не мешали друг другу
> … Считаем, что профиль это полностью независимый инстанс панели.

Every leak below has the same shape, and it is worth naming because the next one will
too: **a value that belongs to one account, held somewhere there is only one of.** None
of them fails loudly. A capture that hears too much reports MORE, not less; a log line
in the wrong file is a real line about a real event; a sink restored to another thread's
value goes on working. That is why they survived months of daily use.

---

## 1. The captures heard every client on the machine — **fixed**

The worst of them, because it is not only logs: it is data the panel then ACTS on.

Two clients of the same game dial the same server ports, so the packet filter cannot
separate them; the local port can, and `map_capture.OwnPorts` is that lookup. The panel
was passing it a **pid list read once, at spawn**.

A profile whose client lives in its own Windows session has no client at the moment the
panel boots — the session is not logged on yet. So the list came back empty, and empty
means «could not tell», which the decoder correctly reads as «keep everything». It then
meant it for the rest of the run.

What that looked like live, read out of `profiles/<name>/children-<pid>.json`:

| profile | rally monitor | wire ear | secret scan | leaderboard |
|---|---|---|---|---|
| the one whose client is in this session | `--client-pid` | `--client-pid` | none | none |
| the three in their own sessions | **none** | **none** | none | none |

So three of four profiles were decoding all four accounts: another alliance's rally
banners in this profile's `rally_log.jsonl`, another account's pushes firing this
profile's triggers, another account's boards filed into this profile's leaderboard
history — and, worst, `secret_share_autoloot.py`, which does not merely record: it
**spends this account's five daily robberies** at a tile announced in somebody else's
alliance chat.

**The fix: a pid is a seed, a session is the anchor.** `panel/runtime/game_process.py`
gained `capture_narrowing(settings)`, which every capture spawn now uses, and it never
comes back empty:

* a profile with a Windows session of its own → `--client-user <login>`;
* a profile without one → `--client-own-session`;
* plus `--client-pid N` for each pid that IS known, as a head start.

`OwnPorts` re-resolves through `game_link.pids` (the session table —
`WTSEnumerateProcesses`, ~27 ms, and it answers for another account's session, which
`psutil.process_iter` neither does reliably nor cheaply) on its own five-second clock.
A client that starts late, dies and comes back, or was never up is picked up by the next
refresh instead of never.

Every capture the panel spawns takes it: the rally monitor, the wire ear, the
secret-task and ghost scans, the treasure scan, the leaderboard collector and both
auto-loot listeners.

Measured after the fix, on the same live panel, with two accounts up:

```
anchor = the second account's session   →  local ports {49534}
anchor = this session                   →  local ports {60525, 64455}
```

Disjoint, which is the whole claim.

### 1a. …and «could not tell» was not «nothing»

The first fix was not enough, and the panel said so within ten minutes of coming back
up: a profile whose client is not running at all was still firing its triggers off a
live account's pushes — the same `al.help.new`, in two profiles' logs, at the same
second, twice.

`OwnPorts` had two answers where there are three, and the missing distinction is the one
this repository keeps rediscovering (`«пусто»` against `«не смог прочитать»`):

| answer | means | the decoder |
|---|---|---|
| a set of ports | these are ours | drop everything else |
| `None` | **could not tell** — no psutil, a socket table that refuses, no session table | keep everything |
| the empty set | **asked; this account has no client running** | drop everything |

The last two were one answer, and «keep everything» was the wrong half of it. A profile
with no client is not an edge case: it is the ordinary state of a panel that has just
started, and of every account whose Windows session is not logged on.

A session that is not logged on IS an answer — `game_link.pids` says so by raising
`LookupError`, and that account demonstrably has no client. Any other exception is the
question failing to be put, which stays «could not tell». The rule itself is
`live_sniffer.is_foreign`, extracted so it can be read and tested without a live
capture: the test that used to re-spell the condition beside the code went on passing
after the condition changed.

**Still machine-wide on purpose:** the two sniffers on the «Разработка» tab. They are
research tools whose job is to record everything that crosses the wire, the tab is off
even in the window, and narrowing them would quietly remove the traffic somebody started
them to find.

## 2. `tools/rdp_instance.py` had one commentary sink for the whole process — **fixed**

`spoken_to(say)` redirected the module's `log()` through a module-level `_SAY`. It is a
sink rather than a `say=` parameter for a good reason (the bring-up talks from six
places), and it was process-wide, which is exactly one sink for however many accounts a
panel has open.

A panel brings its profiles' clients and daemons up **at the same time, each on its own
worker thread**. Two overlapping bring-ups therefore wrote into each other's logs — and
the `finally` restored whichever value the OTHER thread had left behind, so the sink
could stay pointed at a profile that had since closed. This is the «запуск демона»
in the operator's report.

Now `threading.local()`. A bring-up talks to whoever asked for it and to nobody else.

## 3. The remote-control server logged into whichever profile switched it on — **fixed**

There is one web server per window and it answers for **every** open profile
(`panel/web/api.py`), but it logged through `server.rt`, which is the runtime of the
profile whose tab happened to bind the socket. Read live out of one profile's file:

```
[DEBUG] [web] "GET /api/state?profile=default HTTP/1.1" 200 -
```

— in another account's `debug.log`, with nothing on the line to say it is not that
account's. The same defect as «пусто» against «не смог прочитать»: a line you cannot
attribute is worse than no line, because it will be believed.

`panel/debug_log.py` gained `panel_logger(component)` and `PANEL_SCOPE = "_window"`: the
scope for things that belong to the WINDOW rather than to an account. Its file is
`profiles/panel_debug.log` — panel-wide, beside the profile directories rather than
inside one. The leading underscore matters: `panel/profile.py::sanitize` refuses such a
name, so no profile can ever collide with it.

## 4. The three module-level fallback loggers were the FIRST profile's file — **fixed**

`panel/timers.py`, `panel/triggers.py` and `panel/dashboard.py` each held
`_dbg = debug_log.get_logger(...)` at import, used when a caller hands in no logger of
its own. Unscoped means the shared tree, and **the first session opened deliberately has
no scope** (`panel/runtime/session.py`) — so the shared tree IS the first profile's
`debug.log`. A line nobody handed a logger to was filed under an account it had nothing
to do with.

They are `_dbg_window()` now and go to the window's own file. One of them was not merely
a fallback: `triggers.load_catalogue` is a module function with no runtime to ask, and it
logs whenever it grows a profile's `triggers.json`. It named the file's basename — which
is `triggers.json` for every profile there is — and now names the profile directory.

## 5. Named, and left alone

* **`game_clock`'s offset is process-wide.** Every client's offset is a drift between
  this PC's clock and the game's, so the number is the same for all of them, and
  `plausible()` refuses a sample that is not. The GATE that matters — `session_ready` —
  takes an evaluator and reads live, per profile.
* **`leaderboard_store._WRITE_LOCK` is one lock over every profile's database.** Writes
  are a handful a minute, so the coupling is real and costs nothing measurable. Worth
  remembering only if the collector ever becomes chatty.
* **The keyboard macros are one low-level hook per window** and fire into the profile
  whose page is showing, not the profile whose client is in front. One keyboard, one
  foreground; the two agree whenever the person is looking at the account they are
  playing, which is the case the macros exist for.
* **A profile with no `daemon_port` of its own drives the default client** — i.e. another
  profile's. The panel already says so in as many words when it notices two profiles on
  one port. It is a настройка to get right, not a bug to fix in code.

## 6. Shared ON PURPOSE, so nobody «fixes» them later

Pinned in `tests/test_profile_isolation.py` for exactly that reason.

* **`panel/runtime/claims.py`** — one client may be driven by one thing at a time, and
  one desktop has one foreground. Profiles TAKE TURNS over these; they do not each get
  one. A profile whose client is in its own Windows session is exempt from the
  foreground claim, because its desktop is its own.
* **`interrupt.set_handler` / `panel_control` / `panic`** — presses about the PROCESS.
  «Прервать» stops every open profile on purpose: the run that has to stop is not
  reliably the one being looked at. «Перезапустить панель» is all of them at once
  because it is one interpreter.
* **`children._SWEPT`** — the machine-wide orphan sweep. The second profile would only
  walk the same process list to find the first had tidied it.
* **`web._SERVING`** — one socket per window. A second panel is a second process and
  gets its own registry.
* **The relaunch lock is NOT one of these.** `PanelRuntime._relaunch_at_lock` is an
  instance attribute and always was: a relaunch in one profile has never blocked
  another's. It was suspected in the report and the suspicion did not survive reading.

---

## What to do when the next one turns up

Ask the two questions in this order, because the second is where the mistakes are:

1. **Is there one of this per machine, or one per account?** A port, a socket, a
   desktop, a keyboard is a machine's. A log, a schedule, a capture, a budget, a
   commentary sink is an account's.
2. **If it is an account's, what identifies the account at the moment it is needed?**
   Not «what is running now» — that answer is empty during the boot, which is precisely
   when most of this is wired up. Something durable: the profile name, its Windows
   session, its daemon port.

Answering (1) right and (2) with a snapshot is how §1 happened, and it is the failure
that will happen again.

# A second account that relaunches for ever, and never starts (#2578)

Measured on 2026-09-06 against a live panel driving two accounts on one machine: one
client on this desktop, one in a Windows session of its own.

## What the person saw

«Аккаунт работает не стабильно, сессия поднята.» The Windows session was up — that had
been the previous fault, and it was fixed — and the profile still farmed nothing.

## What the numbers said

Counted out of that profile's own `panel.log`:

| reading | value |
|---|---|
| `watchdog: starting the game again` | 12 an hour, every hour, 00:00 → 15:00 |
| launcher starts | 62 in the day |
| distinct clients that ever came up | 20 |
| clients the panel took hold of (`ATTACH_GAME`) | 4 after the session came up |
| daemon starts on the profile's own port | 329 |
| `daemon … did not come up` | 19 |
| `nothing is running in the client … restarting` | 8 in 2.7 h |
| Windows `Application Error` for the client (`UnityPlayer.dll`) | 2 |

Two halves, split at the moment the session came up:

* **before it** — every start failed at once with «nobody is logged on», ~150 of them.
  Not a bug: nothing to start a client inside.
* **after it** — a launcher started, ran, was killed at ~400 s «with no client», and a
  new one started. Twelve times an hour, and no client ever finished coming up.

## The loop

Two constants in `tools/lib/game_client.py` were the same number, and that was the whole
of it:

```
START_TIMEOUT_SEC   = 300.0     # how long a start waits for the client
LAUNCHER_STALE_SEC  = 300.0     # how old a launcher may be before it counts as stuck
```

1. A start begins a launcher and waits 300 s.
2. No client. It gives up with «no client after 300s (the launcher may still be
   updating)» and leaves the launcher running — correctly.
3. Five minutes later the watchdog tries again. It finds that same launcher, now aged
   `>= 300 s`, calls it stuck, and **ends it**.
4. Back to 1, with the download it had made thrown away.

A launcher that only has to spawn the client takes a minute and never meets the limit. A
launcher that has to DOWNLOAD a build takes tens of minutes, so it met the limit on every
single attempt. The panel was killing the only thing that could have ended the outage,
and the message it printed while doing so said out loud that this was what it was doing.

The log carried a second, smaller version of the same waste: `clear_stale_launchers`
would say «a launcher is up (pid …, 149s) — leaving it to finish» and the next line
started another one anyway. The launcher is single-instance, so that start could never do
anything — the new process writes «Launcher is already running» into its own log and
exits.

## The fix

* `LAUNCHER_STALE_SEC` is 1800 s, and `launcher_stale_sec()` will not return a value at
  or under `START_TIMEOUT_SEC` whatever is configured. The two waits can no longer cancel
  out — the invariant, not the number, is what is pinned.
* A launcher that survives the stale sweep is WAITED for: `_start_in_session` falls
  through to `_wait_for_client` instead of making a start that cannot work.
* `tests/test_launcher_is_left_to_finish.py` fails if either comes undone.

## The line that could not report it

`log.link.attach_stuck` is the once-a-minute «how long has the client been out of reach»
line, and it names an `{error}`. One of its three callers — the silent-daemon path —
carries a port and no error, so the whole line fell back to its own template and the
person read `уже {minutes} мин: {error}` for hours. The repeat now picks a key its `fmt`
can actually fill (`log.link.attach_stuck_quiet`), and
`tests/test_link_speaks_while_stuck.py` pins it.

## What was NOT the cause

Worth writing down, because each of these is the obvious first guess:

* **Not two profiles fighting over one client.** They hold different ports and different
  Windows sessions, confirmed on the live `netstat` and in the stored configs.
* **Not the machine running out of GPU.** 2128 MiB of 8192 in use, 36 % utilisation, with
  both clients up. The session was CONNECTED, so it did not pay the tripled cost a
  disconnected one does (`docs/research/`, headless GPU).
* **Not session kicks.** Every `session_kick` line in the window is the listener
  registering itself, not a kick arriving.
* **Not only the client crashing.** It did crash twice in `UnityPlayer.dll`, and the
  watchdog is right to restart after that — but a crash every few hours cannot produce a
  relaunch every five minutes.

## Still open, and not this task's

The panel process itself was restarted five times in twenty minutes while this was being
measured. Each restart drops every profile's attach and re-spawns its captures, so no
profile can hold a link across one. If that rate is ordinary rather than an artefact of
several agents working at once, it is a second cause of the same complaint.

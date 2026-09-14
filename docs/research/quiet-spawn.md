# Nothing the panel starts draws a console — #2874

The report was one sentence: «Рестарт клиента сопровождается постоянным мельканием CMD».

## Why it happens

The panel runs windowless — as the `LastWarBot` service, or under `pythonw.exe`. It has
no console. On Windows a console program started from a process that has no console is
**given one**, and a given console comes with a window: a black box over whatever is on
screen, for as long as the child runs.

So every one of these drew a box:

| what | how often |
|---|---|
| `powershell.exe` in front of each elevation (`rdp_instance.run_elevated`) | twice per SYSTEM hop — the hop itself, and the `schtasks` driver inside it |
| `taskkill.exe` ending a client by pid | once per stop |
| the launcher spawned on this desktop | once per start |
| `dumpcap.exe` | once per interface, per capture |
| `git.exe` (`repo_git.run`) | once per question about the checkout |
| `sc.exe` (`self_control`) | once per reading of the service's state |
| `tasklist.exe` (`launch_as_user`) | once per client enumeration |
| `crash_report.py`, `tools/crash_report.py`'s own powershell | once per crash |

A client restart goes through several of them in a row, which is what «постоянное
мелькание» is. None of it is an error, so none of it is in any log.

## The cure

`tools/lib/quiet_proc.py` — one place, two flags, and the difference between them:

* **`CREATE_NO_WINDOW`** — the child still has a console, that console has no window.
  This is what a CONSOLE program needs; stdout and the exit code are untouched.
* **`STARTUPINFO.wShowWindow = SW_HIDE`** — the first window of a GUI program comes up
  hidden. Does nothing to a console program, and is deliberately not the default:
  hiding a GUI somebody asked for is a different decision.

`quiet_proc.run` / `quiet_proc.popen` are the ordinary calls with the first flag on, and
`quiet()` ORs it into whatever `creationflags` the caller already asked for, so
`DETACHED_PROCESS` and `CREATE_NEW_PROCESS_GROUP` survive.

One other shape mattered: `tools/session_launch.py` started a hidden payload with
`CREATE_NEW_CONSOLE | SW_HIDE`, which asks Windows to DRAW a console and then hide it.
The gap between the two is the flash. `--hidden` now asks for `CREATE_NO_WINDOW`, which
never draws one; a visible launch (the game launcher) keeps its console unchanged.

## What still shows, and why

Two, both deliberate, both named in `tests/test_quiet_spawn.py::VISIBLE`:

* **`mstsc.exe`** (`rdp_instance._one_connect`) — it IS the window: it draws the other
  session's desktop, and Windows may put a credential dialog on it.
* **`cmdkey /pass`** (`rdp_instance.seal_credential`) — it reads the password from the
  console it inherits, so there has to be one. A panel never reaches it: an `isatty`
  guard turns it away first.

**And the game's own launcher keeps its own window.** `LastWarLauncher.exe` is a GUI
program that draws its updater; `CREATE_NO_WINDOW` stops the console it would have been
given as well, and nothing here hides the launcher itself — that is the game's window,
not one of ours.

## Keeping it

`tests/test_quiet_spawn.py` walks `panel/`, `src/lastwar_bot/` and `tools/` (not `dev`,
`archive`, `scratch` — a person's own command line) and fails on a `subprocess` spawn
with no `creationflags`, no `quiet_proc`, no `startupinfo`. A spawn that must be seen is
added to `VISIBLE` with its reason; one the rule cannot reach — the helper itself, the
test runner, the two Linux-only tools — to `EXEMPT`. Those two lists are the whole record
of what the rule does not cover.

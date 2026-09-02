# What happens when «⟳ Перезапустить панель» is pressed — and how it used to fail

Task #1897. A restart of the live panel closed four profiles and started nothing: the web
port refused for nine minutes, no `panel.log` grew, and not one line anywhere said the
replacement had not landed. The hourly autostart check brought the panel back.

## The sequence

1. A press on either front-end lands in `panel/runtime/panel_control.py`, which arms the
   shutdown a moment later so the answer can be written first.
2. `Panel._restart_now` (window) / `HeadlessPanel._restart_now` (service) shuts the panel
   down FIRST — that is what writes the profiles out and drops each profile's instance
   lock — and only then starts the replacement.
3. `panel.runtime.updates.relaunch()` starts `python -m panel` (or `-m panel.headless`)
   from the repo, and the old process ends.

## The three ways step 3 disappeared

**No streams.** The replacement was started with no stdin, stdout or stderr of its own.
A `pythonw.exe` has no console, so `sys.stderr` is `None`, and the first `print` on the
way up raises `AttributeError` into nothing. `panel/runtime/streams.py::ensure` now runs
at the top of both entrypoints, and `relaunch` gives the child a real file
(`profiles/panel_relaunch.out`).

**The lock.** The old panel drops each profile's lock on the way out, but the replacement
is started from INSIDE that shutdown, and a profile whose heartbeat never started keeps
its lock until the process itself ends. The replacement read that as «another panel holds
this account» and exited 0. The pid of the panel being replaced now travels in
`LW_PANEL_RELAUNCH_OF`, and exactly that one process waits for the lock — 30 s, and only
while that pid is alive. Everybody else is still refused instantly.

**`DETACHED_PROCESS`.** #2069 measured the same flag on the service restarter, one flag at
a time: with it the child exits **0** having done nothing at all; without it the same
command line runs and reports. It was never what makes a child outlive its parent — on
Windows nothing kills a child when the parent goes. `relaunch` uses `CREATE_NO_WINDOW |
CREATE_NEW_PROCESS_GROUP` now.

## What a restart leaves behind

* `profiles/panel_relaunch.log` — the notes: the command, the cwd, the pid, and either
  «still up after 8s — booting» or the exit code plus the last 40 lines the dead child
  said. Written by the panel that is going away, which is the only process that can.
* `profiles/panel_relaunch.out` — the replacement's own stdout and stderr, truncated at
  each relaunch. A SEPARATE file on purpose: a handle opened for append in the parent is
  inherited by the child as a plain file pointer, so the child's first write lands on the
  notes and overwrites everything said after it.

The capture is a BOOT's, not a lifetime's: the panel prints tens of kilobytes an hour once
it is running (measured live: 16 KB in 30 s, some 47 MB a day), so the replacement closes
its own capture after three minutes (`LW_PANEL_CAPTURE_SEC`) by handing fds 1 and 2 to
`os.devnull`. Everything this is for — an import error, a refused profile, a traceback on
the way up — happens in the first seconds.

## Verified live

Four consecutive restarts of the live panel through `POST /api/panel {"action":"restart"}`,
each one coming back on the commit that had just been made (`/api/panels` reports `head`),
with the notes above written every time and the capture frozen at 101 KB three minutes
after the boot.

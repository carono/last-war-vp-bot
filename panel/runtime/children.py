"""Spawning the panel's child processes — the captures, the sniffers, the tools.

`panel/childmon.py` is the monitor (start it, stream its output, notice it died). This
is the factory that wires one to a runtime: the Python that runs it, the environment it
inherits, where its lines go — and, since #1212, WHO OWNS IT.

The four monitors used to carry a copy each of "spawn a child, stream it into the log,
untick the box when it dies" — four places for every fix to be made, or forgotten in
three. What differs between them is the command, the tag, what a line means and what its
death means; that is exactly the signature here.

THE ENVIRONMENT IS THE INTERESTING PART. Two variables travel with every child:

* ``LW_DAEMON_PORT`` — a profile pointed at the second client's daemon
  (tools/rdp_instance.py) drives THAT client from its captures and robberies too, not
  just from the panel's own presses.
* ``LW_GAME_LEASE`` — for as long as the runtime is holding the game
  (tools/lib/game_lease.py). Auto-loot claims the lease and *then* spawns the tool that
  does the robbing; without the token that child would wait for a lease its own parent
  is holding. It is READ OFF THIS RUNTIME'S GAME LINK, not off `os.environ`: with two
  profiles open the environment can only hold one of the two live tokens, and a child
  carrying the other profile's would have its every run refused (#1206). An unheld
  lease removes the variable rather than passing an empty one, so a stale token
  inherited from whoever launched the panel cannot leak into a child either.

NOTHING THE PANEL STARTS MAY OUTLIVE IT (#1212). A monitor is a sniffer with a robbery
budget attached: two of them listening to the same stream spend the day's five raids
between them, and neither knows the other is there. Three things keep that from
happening:

* **the factory remembers what it started.** Every child — monitored or raw — is tracked
  here, so :meth:`ChildFactory.stop_all` at shutdown ends all of them, whether or not
  the tab that spawned it remembered to. A tab stopping its own children is still right
  and still first; this is the floor under it.
* **and it writes them down**, one file per owner process in the profile's directory
  (`children-<pid>.json`). A panel that was killed rather than closed — a crash, the task
  manager, a machine going down — leaves that file behind with its children still
  running, and the next run on that profile reads it and ends them (:func:`reap`). Only
  a file whose OWNER IS GONE is acted on: a second panel, or a standalone tab open
  beside the panel, holds its own children and must not have them taken away.
* **and, for what no file can reach**, every child carries :data:`OWNER_VAR` — the pid
  of the panel that started it — so a stamped process whose owner is gone can be found
  wherever it is and whether or not a record of it survived (:func:`sweep`). That is
  what clears the runs from before any of this existed. The Lua daemon is deliberately
  NOT stamped: it is detached on purpose and outlives the panel by design.

PER PROFILE, because the children are. The file lives in the profile's own directory, so
a panel with three profiles open leaves three of them and cleans up exactly the ones
that belong to the profile being opened.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time

import lua_client
import proc_table

from .. import childmon as childmonmod

# Windows: no console window for a child the panel is reading through a pipe.
NO_WINDOW = 0x08000000        # CREATE_NO_WINDOW

#: The variable a child reads its inherited lease from (tools/lib/lua_client.py).
LEASE_VAR = lua_client.LEASE_ENV_VAR

#: Stamped on everything the FACTORY spawns, with the pid of the process that owns it.
#: Not part of `env()`: the Lua daemon is launched with that environment and is detached
#: on purpose (`panel/runtime/daemon.py`) — a daemon carrying this stamp would be swept
#: up as an orphan the moment the panel that warmed it closed, which is the opposite of
#: what it is for.
OWNER_VAR = "LW_PANEL_CHILD"

#: `children-<owner pid>.json` in the profile's directory. One file per PROCESS, not one
#: per profile: the panel, a standalone tab and a second panel may all have children on
#: the same profile, and a shared file would have them rewriting each other's list.
REGISTRY_PREFIX = "children-"
REGISTRY_SUFFIX = ".json"

#: How long a child is given to go on its own before it is killed outright.
GRACE_SEC = 3.0

#: How far a recorded start time may be from the live one and still be the same process
#: (psutil reports it in float seconds; the file has been through JSON).
CTIME_SLACK = 1.0


# ---------------------------------------------------------------------------
# what a live child looks like to this module
# ---------------------------------------------------------------------------
class _Raw:
    """The handle for a child spawned by :meth:`ChildFactory.spawn_raw`.

    A `ChildMonitor` is already this shape (`tag`, `cmd`, `proc`, `stop`); a bare
    `Popen` is not, and the registry wants one shape.
    """

    def __init__(self, proc, tag: str, cmd: list) -> None:
        self.proc, self.tag, self.cmd = proc, tag, list(cmd)

    @property
    def pid(self) -> "int | None":
        return self.proc.pid if self.proc is not None else None

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception:             # noqa: BLE001 — already gone is a fine outcome
            pass


# ---------------------------------------------------------------------------
# the processes themselves
# ---------------------------------------------------------------------------
def _psutil():
    """psutil, or ``None`` on a machine that has none.

    Without it a pid cannot be identified and must therefore not be killed: on Windows
    `os.kill` is `TerminateProcess` whatever signal it is handed, so a "is it alive?"
    probe written the POSIX way would kill the very process it was asking about.
    """
    try:
        import psutil
    except Exception:                 # noqa: BLE001 — not installed here
        return None
    return psutil


def _create_time(pid: "int | None") -> "float | None":
    ps = _psutil()
    if ps is None or not pid:
        return None
    try:
        return float(ps.Process(int(pid)).create_time())
    except Exception:                 # noqa: BLE001 — gone already, or not ours to see
        return None


def _same_process(pid: int, entry: dict) -> bool:
    """Is the process now holding ``pid`` still the child this entry recorded?

    A pid is reused, and the panel may be started days after the run that wrote the
    file, so the answer has to be positive evidence rather than "something is there".
    The start time settles it when we have one; failing that, the command line must
    still be the tool we launched.
    """
    ps = _psutil()
    if ps is None:
        return False
    try:
        proc = ps.Process(int(pid))
        if not proc.is_running() or proc.status() == ps.STATUS_ZOMBIE:
            return False
        recorded = entry.get("ctime")
        if recorded:
            return abs(float(proc.create_time()) - float(recorded)) <= CTIME_SLACK
        script = _script_of(entry.get("cmd") or [])
        return bool(script) and script in " ".join(proc.cmdline() or []).lower()
    except Exception:                 # noqa: BLE001 — gone, or not ours to look at
        return False


def _script_of(cmd) -> str:
    """The tool a command line runs, lower-cased — what identifies it among pythons."""
    for part in list(cmd)[1:]:
        text = str(part)
        if text.lower().endswith(".py"):
            return text.lower()
    return ""


def _kill_tree(pid: int, *, grace: float = GRACE_SEC) -> bool:
    """End ``pid`` and everything it started. ``True`` if it is gone afterwards.

    The grandchildren matter: a robbery tool that shells out to a capture would
    otherwise survive its parent and go on spending the day's budget by itself.

    EVERY psutil call here is guarded, including the waits. A process ending of its own
    accord in the middle of being killed is the ordinary case, not the exceptional one —
    and the one unguarded wait threw `NoSuchProcess` out of the whole reap, which left
    the rest of a dead run's children alive and its record on disk. It was invisible
    until the failure got a log line of its own (#1212).
    """
    ps = _psutil()
    if ps is None:
        return _taskkill(pid)
    try:
        proc = ps.Process(int(pid))
    except Exception:                 # noqa: BLE001 — already gone is a success
        return True
    try:
        family = [proc] + list(proc.children(recursive=True))
    except Exception:                 # noqa: BLE001
        family = [proc]
    for member in family:
        try:
            member.terminate()
        except Exception:             # noqa: BLE001
            pass
    alive = _wait(ps, family, grace)
    for member in alive:
        try:
            member.kill()
        except Exception:             # noqa: BLE001
            pass
    if alive:
        _wait(ps, alive, grace)
    try:
        return not proc.is_running() or proc.status() == ps.STATUS_ZOMBIE
    except Exception:                 # noqa: BLE001 — gone
        return True


def _wait(ps, procs: list, timeout: float) -> list:
    """Wait for ``procs``; answer with the ones still standing. Never raises."""
    try:
        _gone, alive = ps.wait_procs(procs, timeout=timeout)
        return list(alive)
    except Exception:                 # noqa: BLE001 — one of them vanished mid-wait
        return [p for p in procs if _alive(getattr(p, "pid", None))]


def _taskkill(pid: int) -> bool:
    """The fallback for a machine with no psutil. Windows only; elsewhere, give up."""
    if os.name != "nt":
        return False
    try:
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                       capture_output=True, timeout=15,
                       creationflags=NO_WINDOW)
        return True
    except Exception:                 # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# the file the next run reads
# ---------------------------------------------------------------------------
def registry_path(directory: str, pid: "int | None" = None) -> str:
    return os.path.join(directory,
                        f"{REGISTRY_PREFIX}{int(pid or os.getpid())}{REGISTRY_SUFFIX}")


def _owner_of(path: str) -> "int | None":
    stem = os.path.basename(path)[len(REGISTRY_PREFIX):-len(REGISTRY_SUFFIX)]
    return int(stem) if stem.isdigit() else None


def _owner_alive(pid: int, since: "float | None" = None) -> bool:
    """Is the process that started a child still running?

    ``True`` whenever the answer cannot be had — no psutil, no permission. An unknown
    owner is treated as a live one on purpose: the cost of being wrong that way is a
    stale file, and the cost of being wrong the other way is the running panel's
    monitors killed out from under it.

    ``since`` is when the CHILD started, and it is what makes this survive a busy
    machine. Windows hands a pid back within minutes, and this box spawns pythons by
    the dozen: a dead panel's pid reappearing as somebody else's python reads as «the
    owner is still running», and the orphan is then spared for ever. A parent cannot
    have started after its own child, so an owner younger than the child it supposedly
    spawned is a different process wearing the same number. Caught live: an orphan
    survived a start-up because the number had been reissued in the seconds before it
    (#1212).
    """
    ps = _psutil()
    if ps is None:
        return True
    try:
        proc = ps.Process(int(pid))
        if not proc.is_running() or proc.status() == ps.STATUS_ZOMBIE:
            return False
        # A recycled pid belonging to something that is not a python is not a panel.
        if not (proc.name() or "").lower().startswith("py"):
            return False
        if since and float(proc.create_time()) > float(since) + CTIME_SLACK:
            return False              # younger than its «child»: a reissued number
        return True
    except Exception:                 # noqa: BLE001 — gone, or not ours to look at
        return False


def _write(path: str, data) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:                   # noqa: BLE001 — bookkeeping never stops the panel
        pass


def _forget(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def reap(directory: str, *, say=None) -> int:
    """End the children a PREVIOUS run left behind in this profile. Returns how many.

    Reads every `children-*.json` in the profile's directory and acts only on the ones
    whose owner process is gone. Ours is skipped (we are still using it) and so is a
    live neighbour's — a second panel, or a standalone tab running beside this one, is
    entitled to its own children.

    ``say(tag, key, **fmt)`` is the log; a run with no log at all is still allowed to
    clean up, which is what lets a test drive this.
    """
    mine = os.getpid()
    killed = 0
    try:
        names = sorted(os.listdir(directory))
    except OSError:                   # noqa: BLE001 — no profile directory yet
        return 0
    for name in names:
        if not (name.startswith(REGISTRY_PREFIX) and name.endswith(REGISTRY_SUFFIX)):
            continue
        path = os.path.join(directory, name)
        owner = _owner_of(path)
        if owner is None or owner == mine:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                entries = json.load(fh).get("children") or []
        except Exception:             # noqa: BLE001 — an unreadable file is a stale one
            entries = []
        # The file is read BEFORE the owner is judged: the oldest child in it is when
        # that owner must already have been running, and that is what tells a live panel
        # from a number the machine has since reissued (see `_owner_alive`).
        started = min((float(e.get("ctime") or 0) for e in entries), default=0.0)
        if _owner_alive(owner, started or None):
            continue
        for entry in entries:
            # One entry at a time, each on its own: a child that cannot be judged or
            # killed must not take the rest of the list — or the removal of the file
            # below — with it.
            try:
                pid = entry.get("pid")
                if not pid or not _same_process(int(pid), entry):
                    continue
                if not _kill_tree(int(pid)):
                    continue
                killed += 1
                if say is not None:
                    # `name`, not `tag`: `LogBus.say(tag, key, **fmt)` already has a
                    # parameter of that name and a format field would collide with it.
                    say("panel", "log.children.orphan",
                        name=entry.get("tag") or "?", pid=int(pid))
            except Exception:         # noqa: BLE001 — one orphan, not the cleanup
                continue
        _forget(path)
    return killed


#: The machine-wide sweep is about the MACHINE, so it is run once per panel process
#: however many profiles that panel has open — the second profile would only walk the
#: same process list to find that the first one had already tidied it.
_SWEPT = threading.Lock()
_SWEPT_DONE = False

#: What the out-of-process sweep prints for each orphan it ended, so the panel can say
#: it in the operator's language instead of logging the child's own words.
SWEEP_MARKER = "##SWEPT##"

#: …and how that process is started (:meth:`ChildFactory._sweep`). Run by hand with
#: `python -m panel.runtime.children`, which does the same thing.
SWEEP_ENTRY = "from panel.runtime.children import _cli; raise SystemExit(_cli())"


def sweep(*, say=None) -> int:
    """End every panel child anywhere on the machine whose panel is gone. How many.

    The registry is the first way home and this is the second. It exists for the two
    cases a file cannot cover: a run whose file was lost (a profile directory moved, a
    disk full at the wrong moment), and — once — every run that happened BEFORE any of
    this was written, which is the mess the operator is looking at today.

    It is a stamp, not a guess: :attr:`ChildFactory.OWNER_VAR` is put in the environment
    of everything the factory spawns and of nothing else, so a tool a person started
    from a console by hand is invisible here, and so is the Lua daemon — which is
    detached ON PURPOSE and must go on living between panels
    (`panel/runtime/daemon.py`). A stamped process whose owner is still running belongs
    to that panel and is left alone.

    NARROW FIRST, THEN OPEN (#1214). The names come from `tools/lib/proc_table.py`, which
    does not open a handle per process; only the pythons among them are then asked for
    the three things this needs — the stamp, the tool and the start time. Asking all four
    hundred was 7.2 seconds of held interpreter lock and is the walk the stall sampler
    caught starving the window (docs/research/panel-freezes.md §1); asking the four that
    can possibly be ours is 0.03 s.
    """
    ps = _psutil()
    if ps is None:
        return 0
    mine, killed = os.getpid(), 0
    for pid, name in proc_table.names():
        if not pid or pid == mine:
            continue
        if not (name or "").lower().startswith("py"):
            continue
        try:
            proc = ps.Process(int(pid))
            owner = (proc.environ() or {}).get(OWNER_VAR) or ""
            script = _script_of(proc.cmdline() or [])
            started = float(proc.create_time())
        except Exception:             # noqa: BLE001 — gone, or not ours to look at
            continue
        # …and the child's own start time settles a reissued number, exactly as in
        # `reap`: an «owner» younger than this process never started it.
        if not owner.isdigit() or int(owner) == mine \
                or _owner_alive(int(owner), started):
            continue
        try:                          # one orphan, never the rest of the walk
            if not _kill_tree(pid):
                continue
            killed += 1
            if say is not None:
                say("panel", "log.children.orphan",
                    name=os.path.basename(script) or name, pid=pid)
        except Exception:             # noqa: BLE001
            continue
    return killed


# ---------------------------------------------------------------------------
# the factory
# ---------------------------------------------------------------------------
class ChildFactory:
    """Makes :class:`panel.childmon.ChildMonitor`s bound to one runtime.

    …and owns them afterwards: see the module docstring. ``registry`` is a callable
    answering with the directory this runtime's children are written down in (the
    profile's). A factory built without one keeps its children in memory and writes
    nothing, which is what a test wants.
    """

    def __init__(self, log, cwd: str, python, port, schedule, token=None,
                 registry=None) -> None:
        self._log = log                 # the LogBus
        self._cwd = cwd
        self._python = python           # callable: the interpreter to run children with
        self._port = port               # callable: this profile's daemon port
        self._schedule = schedule       # widget.after — how a child gets onto the Tk thread
        # callable: the lease this runtime's game link is holding, or "". A factory
        # built without one passes no lease at all, which is what a harness wants.
        self._token = token or (lambda: "")
        self._registry = registry       # callable: the profile directory, or None
        self._live: list = []           # every child started here and not yet gone
        self._files: set = set()        # every registry file this factory has written
        self._written: list = []        # …and the pids it last wrote, so a no-op is one
        self._lock = threading.Lock()   # tabs spawn from their own threads

    def python(self) -> str:
        return self._python()

    def env(self) -> dict:
        """The environment every child is launched with (see the module docstring)."""
        env = dict(os.environ, PYTHONIOENCODING="utf-8",
                   LW_DAEMON_PORT=str(self._port()))
        token = str(self._token() or "")
        if token:
            env[LEASE_VAR] = token
        else:
            env.pop(LEASE_VAR, None)
        # Dropped for the same reason a stale lease is: a panel started BY a panel
        # inherits the outer one's stamp, and the daemon it then warms would be swept up
        # as an orphan the moment that outer panel closed.
        env.pop(OWNER_VAR, None)
        return env

    def child_env(self) -> dict:
        """:meth:`env`, stamped with who owns the child (:data:`OWNER_VAR`).

        Only the factory's own children are stamped — see the note on the constant.
        """
        return dict(self.env(), **{OWNER_VAR: str(os.getpid())})

    def spawn(self, tag: str, cmd: list, *, on_line=None, on_exit=None,
              capture_stderr: bool = True) -> "childmonmod.ChildMonitor":
        return childmonmod.ChildMonitor(
            cmd, tag, log=self._log.put, cwd=self._cwd, on_line=on_line,
            on_exit=on_exit, schedule=self._schedule, env=self.child_env(),
            capture_stderr=capture_stderr, on_spawn=self.track)

    def spawn_raw(self, cmd: list, tag: str) -> "subprocess.Popen | None":
        """A bare `Popen` whose stdout+stderr the caller reads itself. ``None`` if it
        would not start.

        For the children whose output is streamed by a reader thread rather than by a
        ChildMonitor: the robberies, the raw sniffers, the chat reader. utf-8 is forced
        because a piped stdout would otherwise fall back to the ANSI code page and
        mangle its glyphs under our utf-8 decode.
        """
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", bufsize=1, cwd=self._cwd,
                env=self.child_env(), creationflags=NO_WINDOW)
        except Exception as exc:                  # noqa: BLE001 — it is a child, not us
            self._log.say(tag, "log.launch_failed", error=exc)
            return None
        self.track(_Raw(proc, tag, cmd))
        return proc

    # -- owning them ---------------------------------------------------------
    def track(self, child) -> None:
        """Remember one started child — the monitor calls this itself on its way up.

        Anything with `tag`, `cmd`, `pid`, `alive` and `stop()` will do, which both a
        `ChildMonitor` and :class:`_Raw` are.
        """
        with self._lock:
            self._live.append(child)
            self._flush()

    @property
    def live(self) -> list:
        """The children still running, freshest last — and the file says the same.

        A child that ended on its own is nobody's to stop, so asking is also when the
        list is tidied: the record must not name a pid that has been handed back to the
        machine, or a later run would be deciding whether to kill a stranger.
        """
        with self._lock:
            self._flush()
            return list(self._live)

    def stop_all(self) -> int:
        """End every child this factory started. Returns how many were still running.

        Asked politely first — a `ChildMonitor` knows it was told to go and stays quiet
        about its own death, so nothing tries to untick a checkbox on a window that is
        already closing. What has not gone by the end of the grace period is killed
        along with its grandchildren.
        """
        with self._lock:
            children, self._live = self._live, []
            files, self._files = self._files, set()
            self._written = []
        pids = [c.pid for c in children if c.alive and c.pid]
        running = len(pids)
        for child in children:
            try:
                child.stop()
            except Exception:         # noqa: BLE001 — one child, never the shutdown
                pass
        deadline = time.time() + GRACE_SEC
        while pids and time.time() < deadline:
            pids = [pid for pid in pids if _alive(pid)]
            if pids:
                time.sleep(0.05)
        for pid in pids:
            _kill_tree(pid, grace=1.0)
        for path in files:
            _forget(path)
        return running

    def reap(self) -> int:
        """End what a previous run left behind: this profile's file, then the machine.

        Two passes because they answer different questions. :func:`reap` reads the
        record and is exact — a directory listing and a handful of pid lookups, so it
        happens here and now. :func:`sweep` looks at every process on the machine and
        goes into a process of its own (:meth:`_sweep`); nothing waits for it, because
        an orphan ended a second late has cost nothing.

        Neither pass may stop a start-up — but a pass that fails SAYS SO. Both were
        silent to begin with, and a live run where an orphan died with nothing in the
        log cost an hour of working out which of the two had done it and why the other
        had not. A cleanup nobody can see is a cleanup nobody can trust.
        """
        killed = 0
        directory = self._dir()
        if directory is not None:
            try:
                killed += reap(directory, say=self._log.say)
            except Exception as exc:  # noqa: BLE001 — cleaning up never stops a start-up
                self._log.say("panel", "log.children.failed", error=exc)
        if killed:
            self._log.say("panel", "log.children.reaped", count=killed)
        self._sweep()
        return killed

    def _sweep(self) -> None:
        """The machine-wide pass — IN ITS OWN PROCESS, and once per panel.

        A thread would not do, and the reason survives #1214 having made the walk itself
        cheap. What that change removed is the cost on a box that can be asked the cheap
        way; where `proc_table.names` has to fall back to `psutil.process_iter` — no
        pywin32, or not Windows — it is six or seven seconds of Python holding Python's
        lock again, and while that runs everything the Tk thread does is ten to forty
        times slower: one ttk widget goes from 1 ms to 37–74 ms, and a tab that builds in
        180 ms takes nine seconds (docs/research/panel-freezes.md §1, measured by the
        stall sampler that named this very sweep). A separate process has its own lock
        and costs the panel nothing but the pipe it reads, whichever machine it is on —
        which is exactly what a cost that depends on the machine wants.

        The child says what it killed with :data:`SWEEP_MARKER` and the panel says it in
        the operator's language — a marker rather than words, exactly like the wire
        listeners, because a child cannot know which language the window is in.
        """
        global _SWEPT_DONE
        with _SWEPT:
            if _SWEPT_DONE:
                return
            _SWEPT_DONE = True
        killed: list = []

        def on_line(line: str):
            if not line.startswith(SWEEP_MARKER):
                return None                       # the child's own words, logged as usual
            parts = line.split(None, 2)
            pid = parts[1] if len(parts) > 1 else "?"
            killed.append(pid)
            self._log.say("panel", "log.children.orphan",
                          name=parts[2] if len(parts) > 2 else "?", pid=pid)
            return False                          # the marker is machinery, not for the log

        def on_exit() -> None:
            if killed:
                self._log.say("panel", "log.children.reaped", count=len(killed))

        try:
            # `-c` rather than `-m`: `panel.runtime` imports this module, so running it
            # as a module imports it twice and runpy says so on stderr — a warning the
            # panel would then print into its log at every start.
            mon = self.spawn("panel", [self.python(), "-u", "-c", SWEEP_ENTRY],
                             on_line=on_line, on_exit=on_exit)
            mon.start()
        except Exception as exc:      # noqa: BLE001 — cleaning up never stops a panel
            self._log.say("panel", "log.children.failed", error=exc)

    # -- the file ------------------------------------------------------------
    def _dir(self) -> "str | None":
        if self._registry is None:
            return None
        try:
            directory = self._registry()
        except Exception:             # noqa: BLE001 — no profile yet
            return None
        return str(directory) if directory else None

    def _flush(self) -> None:
        """Write down what is running now. Called under the lock, never on its own."""
        self._live = [c for c in self._live if c.alive]
        directory = self._dir()
        if directory is None:
            return
        # The directory is part of it: a profile switch moves the record even when the
        # same children are still running under it.
        pids = [(directory, c.pid) for c in self._live if c.pid]
        if pids == self._written:       # nothing started, nothing ended: no write
            return
        self._written = pids
        path = registry_path(directory)
        self._files.add(path)
        entries = [{"pid": c.pid, "tag": c.tag, "cmd": [str(p) for p in c.cmd],
                    "ctime": _create_time(c.pid)}
                   for c in self._live if c.pid]
        if entries:
            _write(path, {"owner": os.getpid(), "written": time.time(),
                          "children": entries})
        else:
            _forget(path)


def _alive(pid: "int | None") -> bool:
    """Is that pid still running? ``False`` when there is no way to tell."""
    ps = _psutil()
    if ps is None or not pid:
        return False
    try:
        proc = ps.Process(int(pid))
        return proc.is_running() and proc.status() != ps.STATUS_ZOMBIE
    except Exception:                 # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# `python -m panel.runtime.children` — the sweep, in a process of its own
# ---------------------------------------------------------------------------
def _cli() -> int:
    """Walk the machine, end the orphans, print one marker line for each.

    This is what :meth:`ChildFactory._sweep` starts. It prints rather than logs: the
    panel that reads this pipe knows what language the window is in, and this process
    does not.
    """
    def say(_tag, _key, *, name="?", pid="?", **_rest) -> None:
        print(f"{SWEEP_MARKER} {pid} {name}", flush=True)

    try:
        sweep(say=say)
    except Exception as exc:          # noqa: BLE001 — the panel logs what it reads
        print(f"sweep failed: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())

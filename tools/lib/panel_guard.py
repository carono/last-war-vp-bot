r"""The panel has a watchdog, and it lives in the daemon — because nothing else survives.

**A panel that has fallen over cannot report that it has fallen over.** The only thing
that could is a process that outlives it, and after #1910 there is exactly one: this
profile's Lua daemon, which now starts unconditionally, holds a warm VM across every
panel restart, and is deliberately untouched by one.

WHAT WAS THERE ALREADY, AND WHY IT WAS NOT ENOUGH. `panel/runtime/autostart.py` registers
a Windows scheduled task that looks once an HOUR (`CHECK_EVERY = "PT1H"`) and opens the
panel when the heartbeat says it is not there. That is the right mechanism for «the
machine rebooted» and far too slow for «the orderly restart did not come back»: measured
on this installation, six orderly restarts took **23–31 seconds**, and an incident where
the panel was down for **nine minutes** fell entirely inside one hourly gap without
leaving a trace anybody would look at.

So this does not reimplement any of it. It watches the beat every :data:`POLL_SEC`, and
when the beat has been silent long enough it runs **the very same check** in a child
process — locks, hung-panel handling, the open-profile set, the farewell note, all of it
stays in one place. The guard's whole contribution is *noticing sooner*.

THE THRESHOLD, AND WHY IT IS NOT THE 31 SECONDS IT WAS MEASURED FROM. The panel writes
its beat **once a minute** (`autostart.beat`), so the floor is 60 s whatever a restart
costs: a single missed write means nothing at all. :data:`SILENT_SEC` is three missed
beats — and five and a half times the slowest restart observed — which is the shortest
number that cannot be confused with either.

TELLING «IT FELL OVER» FROM «SOMEBODY CLOSED IT». This is the one thing a guard must not
get wrong, and until #1910 it was not recordable: the panel DELETED its heartbeat on the
way out, so «closed on purpose» and «never started» were the same absence. Now it leaves
a farewell note (`autostart.clear`), and the rule is simply:

===========================  ===========================================  =============
what the beat file says      what happened                                 what to do
===========================  ===========================================  =============
a beat younger than the bar  the panel is answering its own event loop     nothing
``left: closed``             a person closed it                            nothing, ever
``left: restarting``         it is coming back on fresh code               wait it out
a stale beat, no ``left``    it stopped without saying anything            run the check
no file at all               it has never run here                         nothing¹
===========================  ===========================================  =============

¹ deliberately: an install nobody has opened is not an incident, and the hourly task is
what starts a panel after a reboot. This guard only ever answers for a panel that WAS up.

ONE GUARD PER MACHINE, ELECTED BY THE KERNEL. There is one panel and there may be four
daemons — and four daemons that each opened a panel would be the exact failure this is
supposed to prevent. So the same instrument the panel already uses for «is a panel on
this profile» decides it: an exclusive lock on one file, held for the process's life
(`profiles/panel_guard.lock`). Whoever takes it is the guard; a daemon that does not get
it does nothing and tries again later, so the guard survives its holder dying without
anybody arranging a hand-over.

Nothing here imports the panel. It reads two files and spawns one command.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

WINDOWS = os.name == "nt"

#: How often the beat is looked at. Far below :data:`SILENT_SEC`, so the verdict is never
#: a whole poll late, and cheap: two small reads per profile.
POLL_SEC = 20.0

#: HOW LONG THE BEAT MAY BE SILENT before the panel is considered gone.
#:
#: The beat is written once a minute, so 60 s is the floor below which the number would
#: be measuring luck. Measured against the thing it must not fire on — six orderly
#: restarts of this installation, 23 / 26 / 27 / 23 / 31 / 25 seconds — this is 5.8× the
#: slowest of them and three missed beats.
SILENT_SEC = 180.0

#: …and how long the guard says nothing after running the check, so a panel that is
#: starting is never counted as one that is missing. The check's own wait for a first
#: beat is 45 s (`autostart.LAUNCH_WAIT_SEC`); this is that with room for a slow boot.
QUIET_AFTER_SEC = 120.0

#: The file whose exclusive lock elects the one guard on this machine.
LOCK_NAME = "panel_guard.lock"

#: What the guard runs when the beat has gone quiet — the panel's own hourly check, early.
CHECK_MODULE = "panel.runtime.autostart"

# Windows creation flags: no console flash, and the child outlives this daemon.
NO_WINDOW = 0x08000000
DETACHED = 0x00000008


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _lock_exclusive(handle) -> bool:
    """Take the lock on byte 0 without blocking. ``False`` when somebody else holds it.

    Byte 0 explicitly, and the seek is load-bearing for the same reason it is in
    `panel/runtime/autostart.py`: `msvcrt.locking` locks from the current position, and a
    handle that has been written to would lock a different byte each time and grant
    everybody.
    """
    try:
        handle.seek(0)
        if WINDOWS:
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


class PanelGuard:
    """Watch the panel's heartbeat from outside it, and put it back when it stops.

    One per daemon process; only the one that wins the lock does anything. Started with
    :meth:`start` and left to run — there is nothing to stop it for, and it dies with the
    daemon exactly as the election intends.
    """

    def __init__(self, repo: str, say=None) -> None:
        self._repo = repo
        self._profiles = os.path.join(repo, "profiles")
        #: Where the guard's own sentences go. The daemon's stdout is its log file
        #: (`results/logs/lua_daemon_<port>.log`), which is what the panel now quotes
        #: when a daemon will not start — so the two ends of #1910 read as one story.
        self._say = say if say is not None else (
            lambda msg: print(f"[guard] {msg}", flush=True))
        self._handle = None
        self._quiet_until = 0.0

    # -- the election ---------------------------------------------------------
    def _elected(self) -> bool:
        """Am I the guard? Asked every tick, because the holder may have just died."""
        if self._handle is not None:
            return True
        path = os.path.join(self._profiles, LOCK_NAME)
        try:
            os.makedirs(self._profiles, exist_ok=True)
            handle = open(path, "a+", encoding="utf-8")     # noqa: SIM115 — held for life
        except OSError:
            return False
        if not _lock_exclusive(handle):
            try:
                handle.close()
            except OSError:
                pass
            return False
        self._handle = handle
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(f"{os.getpid()}\n")
            handle.flush()
        except OSError:                     # noqa: BLE001 — the LOCK is the fact
            pass
        self._say(f"watching the panel from pid {os.getpid()}")
        return True

    # -- the reading ----------------------------------------------------------
    def _beats(self) -> list:
        """``(profile, age_or_None, farewell)`` for every profile that has a beat file."""
        out = []
        try:
            names = sorted(os.listdir(self._profiles))
        except OSError:
            return out
        now = time.time()
        for name in names:
            path = os.path.join(self._profiles, name, "panel_alive.json")
            if not os.path.isfile(path):
                continue
            saved = _read_json(path)
            if not saved:
                continue
            left = str(saved.get("left") or "")
            if left:
                out.append((name, None, left))
                continue
            try:
                age = max(0.0, now - float(saved.get("ts") or 0))
            except (TypeError, ValueError):
                continue
            out.append((name, age, ""))
        return out

    def verdict(self, now: float) -> str:
        """``""`` when nothing is wrong, otherwise why the panel needs putting back.

        Split out so a test can drive every branch without a thread, a clock or a child
        process — the same shape `panel/runtime/recovery.py` is built in, and for the
        same reason: this decides something expensive and must be provable.
        """
        if now < self._quiet_until:
            return ""
        beats = self._beats()
        if not beats:
            return ""                       # never run here; not this guard's business
        if any(left for _n, _a, left in beats):
            # EITHER FAREWELL SILENCES IT. «closed» is a person's decision and is
            # honoured for as long as it stands; «restarting» is a panel that is coming
            # back, and racing it would open a second window on top of the first.
            return ""
        ages = [age for _n, age, _l in beats if age is not None]
        if not ages:
            return ""
        # The FRESHEST beat, because a window holds a page per profile and any one of
        # them beating proves the window is up (`autostart.check` says the same).
        youngest = min(ages)
        if youngest < SILENT_SEC:
            return ""
        return f"no beat for {int(youngest)}s (bar {int(SILENT_SEC)}s)"

    # -- the act --------------------------------------------------------------
    def _put_back(self, why: str) -> None:
        """Run the panel's own check, in a child, and say what was seen and done."""
        self._quiet_until = time.time() + QUIET_AFTER_SEC
        self._say(f"THE PANEL IS NOT ANSWERING: {why} — running the panel's own check")
        try:
            subprocess.Popen(
                [sys.executable, "-m", CHECK_MODULE], cwd=self._repo,
                creationflags=(NO_WINDOW | DETACHED) if WINDOWS else 0,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL)
        except Exception as exc:            # noqa: BLE001 — a guard, never the daemon
            self._say(f"could not run the check: {exc}")

    # -- the loop -------------------------------------------------------------
    def _loop(self) -> None:
        while True:
            try:
                if self._elected():
                    why = self.verdict(time.time())
                    if why:
                        self._put_back(why)
            except Exception as exc:        # noqa: BLE001 — never take the daemon down
                self._say(f"tick failed: {exc}")
            time.sleep(POLL_SEC)

    def start(self) -> None:
        """Run the watch on a daemon thread. Never raises: a guard is not the job."""
        threading.Thread(target=self._loop, name="panel-guard", daemon=True).start()

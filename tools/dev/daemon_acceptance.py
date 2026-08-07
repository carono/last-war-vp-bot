r"""Does «green» mean a call will reach the game right now? (task #1287)

The acceptance run for the daemon's heartbeat. Everything it checks is a LIVE fact — a
chunk that ran, a port that answered, a pid that exists — because the whole failure this
replaces was an offline-plausible reading that was live-false: `up()` said warm over a
daemon whose client had gone, for half an hour at a time.

Three forms, and the point is that the verdict differs in all three:

    1  daemon alive, client alive        -> live,  and a real chunk comes back
    2  daemon alive, client killed       -> stale within seconds, then the port is FREED
                                            by the daemon itself and a fresh one is up
    3  no daemon, port free              -> none

Run it beside the panel, with the Windows interpreter, from the repo root:

    C:\Python312\python.exe tools\dev\daemon_acceptance.py            # forms 1 and 3
    C:\Python312\python.exe tools\dev\daemon_acceptance.py --contention
    C:\Python312\python.exe tools\dev\daemon_acceptance.py --kill-client

FORM 2 KILLS THE GAME CLIENT and is therefore behind `--kill-client`, which nothing here
passes by itself. Ask the person first: a restart takes the account off whoever is
holding it, costs a login, and on a farming account it costs whatever was mid-flight.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "lib"))

import daemon_pulse  # noqa: E402
import lua_client  # noqa: E402

PROBE = "CS.UnityEngine.Debug.LogError('ACC ok')"
MARK = "ACC"

#: A port nothing is on, for form 3. Not a second daemon's (47655) and not the default.
FREE_PORT = 47699

#: How long the machine must have been untouched before form 2 may kill anything. The
#: person plays on this computer, and a client killed under them is the harm #1259 did
#: once already — eight seconds after a link reading, with somebody in the game.
IDLE_BEFORE_KILL_SEC = 300.0


class Run:
    def __init__(self) -> None:
        self.failed = 0

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        if not passed:
            self.failed += 1
        print("  %-4s %-56s %s" % ("ok" if passed else "FAIL", name, detail))
        return passed

    def note(self, text: str) -> None:
        print("       %s" % text)


def _running_pid() -> "int | None":
    try:
        import game_client

        return game_client.running_pid()
    except Exception as exc:                              # noqa: BLE001
        print("       (cannot read the running client: %s)" % exc)
        return None


def _ms(fn, n: int = 10):
    xs = []
    for _ in range(n):
        started = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - started) * 1000)
    xs.sort()
    return statistics.median(xs), xs[0], xs[-1]


# ---------------------------------------------------------------------------
# form 1 — both alive
# ---------------------------------------------------------------------------

def form_alive(run: Run, port: int) -> None:
    print("\nform 1 — daemon alive, client alive")
    client = lua_client.DaemonClient(port=port, token="")
    reply = client.status()
    if not run.check("the daemon answers a ping", bool(reply.get("ok")), json.dumps(reply)):
        return
    pid = _running_pid()
    said = daemon_pulse.verdict(reply, running_pid=pid)
    run.check("the verdict is live", said == "live",
              "verdict=%s held=%s running=%s" % (said, reply.get("pid"), pid))

    age = reply.get("last_ok_age")
    run.check("the ping carries the age of the last landed chunk",
              isinstance(age, (int, float)),
              "last_ok_age=%s (None means a daemon older than this change)" % age)

    # The claim itself: a chunk sent NOW comes back. This is what «green» promises, and
    # nothing weaker is accepted here.
    try:
        lines = client.run(PROBE, marker=MARK, settle=1.0, early=True)
    except Exception as exc:                              # noqa: BLE001
        lines = []
        run.note("the run raised: %s: %s" % (type(exc).__name__, exc))
    run.check("a chunk sent now comes back", lines == ["ACC ok"], repr(lines))

    med, lo, hi = _ms(lambda: client.status())
    run.check("a ping stays cheap", med < 20.0, "%.2f ms (%.2f–%.2f)" % (med, lo, hi))
    med, lo, hi = _ms(lambda: client.run(PROBE, marker=MARK, settle=0.5, early=True), n=5)
    run.note("a live chunk costs %.0f ms (%.0f-%.0f)" % (med, lo, hi))

    # An errand that lands must reset the age — that is what makes the guarantee free
    # while the panel is working.
    after = lua_client.DaemonClient(port=port, token="").status().get("last_ok_age")
    if isinstance(after, (int, float)):
        run.check("a real errand refreshes the proof", after < 2.0,
                  "last_ok_age=%.2f s right after a run" % after)


# ---------------------------------------------------------------------------
# form 3 — nothing there
# ---------------------------------------------------------------------------

def form_none(run: Run, port: int = FREE_PORT) -> None:
    print("\nform 3 — no daemon, port free")
    client = lua_client.DaemonClient(port=port, token="")
    reply = client.status()
    run.check("nothing answers", reply == {}, repr(reply))
    run.check("the verdict is none", daemon_pulse.verdict(reply, running_pid=1) == "none")
    med, lo, hi = _ms(lambda: lua_client.is_running(port=port, timeout=0.35), n=3)
    run.note("asking a dead port costs %.0f ms (%.0f-%.0f) - the timeout, every time"
             % (med, lo, hi))


# ---------------------------------------------------------------------------
# form 2 — the client is killed under the daemon
# ---------------------------------------------------------------------------

def form_killed(run: Run, port: int, wait: float = 90.0) -> None:
    print("\nform 2 — daemon alive, client killed under it")
    pid = _running_pid()
    if not run.check("there is a client to kill", bool(pid), "pid=%s" % pid):
        return

    # IS SOMEBODY AT THE MACHINE? The same gate the recovery keeps in front of its own
    # restarts (#1259, `panel/runtime/recovery.py`), and for the same reason: this once
    # closed a window a person was playing in, eight seconds after a link reading. A
    # check run beside the announcement is not enough — they may have sat down since.
    import game_link

    idle = game_link.idle_sec()
    if idle is not None and idle < IDLE_BEFORE_KILL_SEC:
        run.check("nobody is at the machine", False,
                  "somebody used it %.0f s ago — not killing anything" % idle)
        return
    run.note("nobody has touched this machine for %.0f s" % (idle or -1))

    import psutil

    print("       killing pid %s — the panel's watchdog will bring the game back" % pid)
    psutil.Process(int(pid)).kill()
    killed_at = time.monotonic()

    saw_stale = saw_free = saw_back = None
    while time.monotonic() - killed_at < wait:
        reply = lua_client.DaemonClient(port=port, token="").status()
        now_pid = _running_pid()
        said = daemon_pulse.verdict(reply, running_pid=now_pid)
        if saw_stale is None and said != "live":
            saw_stale = time.monotonic() - killed_at
        if saw_free is None and not reply:
            saw_free = time.monotonic() - killed_at
        if saw_stale is not None and said == "live" and now_pid:
            saw_back = time.monotonic() - killed_at
            break
        time.sleep(1.0)

    run.check("the verdict stops being live", saw_stale is not None,
              "after %.0f s" % saw_stale if saw_stale else "never — this is the bug")
    run.check("the daemon lets go of the port by itself", saw_free is not None,
              "after %.0f s" % saw_free if saw_free else
              "never — it went on answering for a client that had gone")
    run.check("everything is green again without anybody helping", saw_back is not None,
              "after %.0f s" % saw_back if saw_back else "not within %.0f s" % wait)


# ---------------------------------------------------------------------------
# the lock
# ---------------------------------------------------------------------------

def contention(run: Run, port: int, readers: int = 3, settle: float = 1.2) -> None:
    """What a foreground call costs behind background readers holding patient settles."""
    print("\nthe lock — a call in front of %d patient readers" % readers)
    free_med, _, _ = _ms(
        lambda: lua_client.DaemonClient(port=port, token="").run(
            PROBE, marker=MARK, settle=0.5, early=True), n=5)
    stop = threading.Event()

    def worker() -> None:
        client = lua_client.DaemonClient(port=port, token="")
        while not stop.is_set():
            try:
                client.run(PROBE, marker=MARK, settle=settle)
            except Exception:                             # noqa: BLE001
                return

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(readers)]
    for thread in threads:
        thread.start()
    time.sleep(0.6)
    busy_med, lo, hi = _ms(
        lambda: lua_client.DaemonClient(port=port, token="").run(
            PROBE, marker=MARK, settle=0.5, early=True), n=8)
    stop.set()
    time.sleep(settle + 0.5)
    run.note("free %.0f ms | behind %d readers %.0f ms (%.0f-%.0f) - x%.1f"
             % (free_med, readers, busy_med, lo, hi, busy_med / max(free_med, 0.001)))
    run.check("a background reader no longer stands in front of a press",
              busy_med < free_med + 1000,
              "the settle is out of the lock when this passes")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=lua_client.PORT)
    ap.add_argument("--kill-client", action="store_true",
                    help="also run form 2 — KILLS the game client (ask the person first)")
    ap.add_argument("--contention", action="store_true",
                    help="also measure a call behind patient background readers")
    args = ap.parse_args()

    run = Run()
    print("daemon acceptance — port %d" % args.port)
    form_alive(run, args.port)
    form_none(run)
    if args.contention:
        contention(run, args.port)
    if args.kill_client:
        form_killed(run, args.port)
    print("\n%s" % ("all checks passed" if not run.failed
                    else "%d check(s) FAILED" % run.failed))
    return 1 if run.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

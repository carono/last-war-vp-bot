r"""What a background call of one profile costs, with N profiles open (#1226).

`panel_switch_bench.py` beside this measures the freeze a PERSON sits through. This
measures the other side of the same wall: what a profile's own background work — the
scheduler, the status poll, the dashboard, a scenario — pays to talk to the window, and
therefore how long every other profile's work is stuck behind it.

Four things are timed, in the same conditions, against a Tk thread that is doing what a
page build does (a burst of widget work per turn):

  * ``var.get`` — reading a settings knob off its Tk variable. From a thread that is not
    Tk's, tkinter does not read anything: it queues the call for the Tk thread and
    blocks until the event loop runs it. This is what `SettingsBinder.opt()` used to do,
    on every port check, every child spawn and every status poll.
  * ``shadow`` — the same read off the thread-safe mirror it does now
    (`panel/runtime/settings.py`).
  * ``after(0)`` — handing a repaint back with `root.after(0, …)`: two blocking trips
    into Tcl, and «main thread is not in main loop» while the boot is pumping by hand.
  * ``post`` — the same hand-over through the window's queue
    (`panel/runtime/tick.py::TkPost`), which touches no Tk at all.

Read the WORKER columns. The window's own turn count barely moves between the four —
the event loop was always going to get its slice — and that is the point: the cost was
never the drawing, it was every profile's background work queueing up behind it.

    C:\Python312\python.exe tools\dev\panel_thread_bench.py
    C:\Python312\python.exe tools\dev\panel_thread_bench.py --profiles 4 --rate 50

Measured on the machine this was written on, four profiles at fifty calls a second:

    what a worker does   window turns/2s   worker mean us      p95 us
    var.get                           76           9352.1     19052.1
    after(0)                          79           8566.0     17137.9
    shadow                            81              1.6         2.2
    post                              75             16.9        39.3

Nine milliseconds to ask which port you are on, nineteen at the tail — per read, and a
status poll makes several. That is «панель парализована на 3-4 аккаунтах», seen from
inside the profile rather than from the glass.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import tkinter as tk                                   # noqa: E402

from panel.runtime import tick as tickmod              # noqa: E402

#: What one turn of the "window is busy" loop does. A page build is thousands of small
#: Tcl calls; forty widgets a turn is the same shape at a size that fits in a bench.
WIDGETS_PER_TURN = 40
#: How many of them are kept before the oldest is destroyed, so the window does not grow
#: without bound over a run.
WIDGET_CEILING = 200

CALLS = ("var.get", "after(0)", "shadow", "post")


def _measure(root, var, ticker, shadow, kind: str, *,
             seconds: float, workers: int, rate: int) -> dict:
    """One call kind, timed from ``workers`` threads at ``rate`` calls a second each."""
    stop = threading.Event()
    turns = [0]
    frames: list = []
    costs: list = []
    lock = threading.Lock()

    def turn() -> None:
        if stop.is_set():
            root.quit()
            return
        turns[0] += 1
        for _ in range(WIDGETS_PER_TURN):
            frames.append(tk.Frame(root))
            if len(frames) > WIDGET_CEILING:
                frames.pop(0).destroy()
        root.after(1, turn)

    def work(index: int) -> None:
        end = time.perf_counter() + seconds
        gap = 1.0 / max(1, rate)
        mine: list = []
        while time.perf_counter() < end:
            began = time.perf_counter()
            if kind == "var.get":
                var.get()
            elif kind == "shadow":
                shadow["daemon_port"]                  # noqa: B018 — the read IS the work
            elif kind == "after(0)":
                root.after(0, lambda: None)
            elif kind == "post":
                ticker.post(lambda: None)
            mine.append(time.perf_counter() - began)
            time.sleep(gap)
        with lock:
            costs.extend(mine)
        if index == 0:
            stop.set()

    threads = [threading.Thread(target=work, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    root.after(1, turn)
    root.mainloop()
    for thread in threads:
        thread.join(seconds + 10)
    costs.sort()
    return {"kind": kind, "turns": turns[0], "calls": len(costs),
            "mean": sum(costs) / max(1, len(costs)) * 1e6,
            "p95": costs[int(len(costs) * 0.95)] * 1e6 if costs else 0.0}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profiles", type=int, default=4,
                    help="how many open profiles to imitate (one worker each)")
    ap.add_argument("--rate", type=int, default=50,
                    help="background calls per second, per profile")
    ap.add_argument("--seconds", type=float, default=2.0, help="per call kind")
    args = ap.parse_args(argv)

    root = tk.Tk()
    root.withdraw()
    var = tk.StringVar(master=root, value="47654")
    ticker = tickmod.Ticker(root)
    shadow = {"daemon_port": "47654"}

    rows = [_measure(root, var, ticker, shadow, kind, seconds=args.seconds,
                     workers=args.profiles, rate=args.rate) for kind in CALLS]
    root.destroy()

    print(f"{args.profiles} profiles x {args.rate} calls/s, "
          f"{args.seconds:g}s each\n")
    print(f"{'what a worker does':<20} {'window turns':>13} {'calls':>8} "
          f"{'mean us':>10} {'p95 us':>10}")
    for row in rows:
        print(f"{row['kind']:<20} {row['turns']:13d} {row['calls']:8d} "
              f"{row['mean']:10.1f} {row['p95']:10.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

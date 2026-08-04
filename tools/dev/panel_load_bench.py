r"""Is the panel still answering with four profiles open and all of them working? (#1226)

The complaint this exists to settle:

> Панель блочится от действий других профилей. Если их будет хотя бы 3-4, панель
> парализуется.

`panel_switch_bench.py` beside this measures ONE thing a person does (switching pages).
`panel_thread_bench.py` measures ONE call in isolation. This measures the thing the
complaint is actually about: a REAL panel, N profiles open, every one of them doing what
a profile does in the background, and **how late the event loop is** all the way through.

## What «responsive» is measured as

A heartbeat armed with `after(20ms)` from inside the loop, and how late each beat
actually fires. That number IS responsiveness: a click, a keystroke, a repaint and a
tab change are all dispatched by the same loop, so a beat that is 300 ms late is a
click that would have been 300 ms late. It is measured from inside the loop on purpose
— `panel/runtime/stall.py` samples the same thing from OUTSIDE to say what is holding
it, and both are printed.

Read `p95` and `worst`. A mean stays pretty while every twentieth click hangs, and
every twentieth click is what «панель парализуется» means.

## The load

Each profile gets a worker doing what a profile's background work does to the PANEL —
not to the game, so this never presses anything:

  * reads its settings (`daemon_port`, `game_exe`, `rdp_session`) — what a status poll,
    a child spawn and every socket check do;
  * says a line into its log;
  * reports an activity step;
  * hands a repaint back to the Tk thread.

That is the whole of a profile's panel-side traffic. The panel's own real background
work — status polls, the dashboard, tab reads, the child sweep — runs underneath it
regardless, because this is the real panel.

## The A/B

``--legacy`` puts the pre-#1226 code paths back on the SAME build: `opt()` reading its
Tk variable from whatever thread asks, hand-overs through `root.after(0, …)`, and the
machine-wide walks taken once per profile instead of once. So the two runs differ in
the fix and in nothing else — not in the machine, not in what else was open, not in
which day it was.

    C:\Python312\python.exe tools\dev\panel_load_bench.py --profiles 4 --legacy
    C:\Python312\python.exe tools\dev\panel_load_bench.py --profiles 4

`--legacy queue` and `--legacy blocking` put back one half each, which is how the two
were told apart. Measured with four profiles on the machine this was written on:

    what is reverted        boot          steady state (loaded)
    nothing (fixed)         8.4–8.8 s     p95 4.6–5.2 ms, worst 31–60 ms
    the queue half         79.8 s         p95 3.9–4.3 ms
    the blocking half       8.9 s         p95 4.3 ms
    both                   81.5–81.9 s    p95 3.9–4.3 ms

**The whole of the boot number is the queue half** — a profile's background work talking
to the window on the window's thread. Four boot threads each blocking on the one event
loop, which is itself building four pages, is not four times one profile: it is ninety
seconds against nine.

The blocking half barely shows in the boot total and is not therefore small — what it
costs is not spread evenly. It is a second of dead window per press of a button while a
daemon is down, a second to bind the web server, a third of a second per profile to reap
the last run's children, and the stalls it leaves are during a page build, which is when
somebody is looking. `--threshold` and the stall reports are where those show up, not
here.

The STEADY STATE is the same either way, and that is worth saying plainly: this load
does not make an idle window late, before or after. What the fix changes is what happens
when the Tk thread is BUSY — booting, building a page, switching a profile — which is
exactly when a person is waiting for it.

Profiles are COPIES under a temporary directory, minus the two errand catalogues, so a
bench cannot fire a timer or a wire trigger into the live game. `--live` uses the real
ones. The daemon is not started by default (`--daemon` to allow it): a profile whose
daemon is not up spends thirty seconds of boot finding that out, four times, and none of
it is what is being measured.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

#: What a copied profile does NOT get — the same list `panel_switch_bench.py` uses, and
#: for the same reason: no errand catalogue means no timer and no wire trigger can fire
#: into the live game from a bench.
_LEAVE_BEHIND = {"timers.json", "timers_last_run.json", "timers_seen.json",
                 "triggers.json", "panel.lock", "panel_alive.json"}

#: How often the responsiveness probe asks to be woken. Small enough that a stall of a
#: tenth of a second is several missed beats.
BEAT_MS = 20


class Beat:
    """How late the event loop is, sampled from inside it.

    One `after(BEAT_MS)` chain that records the gap between when it asked to be woken
    and when it was. Everything above `BEAT_MS` is the loop being busy with something
    else — which, from the person's side of the glass, is the panel not answering.
    """

    def __init__(self, root, every_ms: int = BEAT_MS) -> None:
        self._root = root
        self._every = every_ms
        self._late: list = []
        self._at = None
        self._job = None
        self.recording = False

    def start(self) -> None:
        self._at = time.perf_counter()
        self._tick()

    def stop(self) -> None:
        job, self._job = self._job, None
        if job is not None:
            try:
                self._root.after_cancel(job)
            except Exception:                    # noqa: BLE001 — the window is going
                pass

    def _tick(self) -> None:
        now = time.perf_counter()
        if self._at is not None and self.recording:
            self._late.append(max(0.0, (now - self._at) * 1000 - self._every))
        self._at = now
        try:
            self._job = self._root.after(self._every, self._tick)
        except Exception:                        # noqa: BLE001
            self._job = None

    # -- reading it ---------------------------------------------------------
    def reset(self) -> None:
        self._late.clear()

    def summary(self) -> dict:
        late = sorted(self._late)
        if not late:
            return {"beats": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "worst": 0.0,
                    "over100": 0, "over500": 0}
        return {
            "beats": len(late),
            "p50": late[len(late) // 2],
            "p95": late[int(len(late) * 0.95)],
            "p99": late[int(len(late) * 0.99)],
            "worst": late[-1],
            "over100": sum(1 for v in late if v > 100),
            "over500": sum(1 for v in late if v > 500),
        }


def _stage(names: list, source: Path, dest: Path, want: int) -> list:
    """Copy each profile whole, minus its errands; clone to reach ``want`` of them.

    The clones matter: the operator has two profiles today and the complaint is about
    four, so a bench that can only measure what is already there cannot answer the
    question. A clone carries the same weight as what it was cloned from — the same
    tabs, the same chat store, the same checkpoints — which is the point.
    """
    made = []
    for i in range(want):
        name = names[i] if i < len(names) else f"{names[i % len(names)]}-bench{i}"
        (dest / name).mkdir(parents=True, exist_ok=True)
        src = source / names[i % len(names)]
        if src.is_dir():
            for item in src.iterdir():
                if item.name in _LEAVE_BEHIND or not item.is_file():
                    continue
                shutil.copy2(item, dest / name / item.name)
        made.append(name)
    return made


def _repoint(folder: Path, names: list, base_port: int) -> None:
    """Give every copy a daemon port of its own — as four real accounts would have.

    Two copies of one profile share its port, and then they are two views of one client
    and take turns (docs/research/multi-profile-panel.md §4.3) — which is correct, and
    is not what this bench is measuring.
    """
    for i, name in enumerate(names):
        path = folder / name / "config.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:                        # noqa: BLE001 — a profile with no config
            raw = {}
        raw["daemon_port"] = base_port + i
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# the A/B: the code as it was before #1226
# ---------------------------------------------------------------------------
def _wear_legacy(part: str = "all") -> None:
    """Put the pre-#1226 paths back, so a run differs in the fix and nothing else.

    ``part`` splits the fix in two, because they are two different faults and the
    difference between them is worth being able to see:

    * ``queue`` — a profile's background work talking to the window ON the window's
      thread: `opt()` off a Tk variable, hand-overs through `after(0, …)`, and the
      machine-wide walks taken once per profile.
    * ``blocking`` — blocking calls made ON the Tk thread: the one-second daemon check,
      the reverse DNS lookup in the web bind, the child reap, the settings file written
      once per profile opened, and the full redraw forced per reported build step.
    """
    from panel.runtime import game_process as gp
    from panel.runtime import tick as tickmod
    from panel.runtime.host import PanelRuntime
    from panel.runtime.settings import SettingsBinder

    def opt(self, key: str):                     # …as it read before the shadow
        var = self.vars.get(key)
        if var is not None:
            try:
                return var.get()
            except Exception:                    # noqa: BLE001
                pass
        if key in self._values:
            return self._values[key]
        return self.defaults.get(key)

    def post(self, call) -> None:                # …as a hand-over was made before
        try:
            self.root.after(0, call)
        except Exception:                        # noqa: BLE001 — the window is gone
            pass

    def ticker_post(self, func) -> None:
        if func is None:
            return
        try:
            self._w.after(0, func)
        except Exception:                        # noqa: BLE001
            pass

    if part in ("all", "queue"):
        SettingsBinder.opt = opt
        PanelRuntime.post = post
        PanelRuntime._on_tk = post
        tickmod.Ticker.post = ticker_post
        # …and the machine-wide walks, once per profile rather than once for all.
        gp.MACHINE_TTL_SEC = 0.0
    if part == "queue":
        print("A/B: the QUEUE half is back (Tk-variable reads, after(0), no sharing)")
        return

    # THE BLOCKING CALLS THAT WERE ON THE TK THREAD. Each of these was found by running
    # this bench and reading the stall reports, and each is put back here so an A/B
    # measures the whole of #1226 rather than half of it.
    import socket
    import socketserver
    from http.server import HTTPServer

    import lua_client

    from panel import splash as splashmod
    from panel.runtime import workspace as wsmod
    from panel.runtime.daemon import GameLink
    from panel.runtime.host import PanelRuntime as _RT
    from panel.web import server as websrv

    GameLink.up = lambda self, fresh=False: lua_client.is_running(port=self.port())
    _RT._reap = lambda self: None            # …and put it back on the Tk thread:
    websrv._Server.server_bind = HTTPServer.server_bind      # the reverse DNS lookup
    # A DATA DESCRIPTOR, because `restore` sets `self._quiet` on the instance and an
    # instance attribute would win over a plain class one. This makes the deferral
    # impossible to turn on, which is what the old code was.
    wsmod.Workspace._quiet = property(lambda self: False, lambda self, v: None)

    def say(self, text: str) -> None:        # a full flush per reported build step
        try:
            self._step_lbl.configure(text=text)
            self.update_idletasks()
        except Exception:                    # noqa: BLE001
            pass

    splashmod.SplashScreen.say = say
    _reaping = _RT.__init__

    def init(self, *a, **kw):
        _reaping(self, *a, **kw)
        try:
            self.children.reap()             # …on the Tk thread, as it used to be
        except Exception:                    # noqa: BLE001
            pass

    _RT.__init__ = init
    print(f"A/B: the {part!r} half of #1226 is back")


# ---------------------------------------------------------------------------
def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="is the panel responsive with N profiles?")
    ap.add_argument("--profiles", type=int, default=4, help="how many to open")
    ap.add_argument("--seconds", type=float, default=20.0, help="measured, under load")
    ap.add_argument("--idle", type=float, default=6.0,
                    help="measured first, with no load — the floor to compare against")
    ap.add_argument("--rate", type=int, default=20,
                    help="background calls a second, per profile")
    ap.add_argument("--threshold", type=int, default=200,
                    help="ms a Tk-thread stall must last to be reported")
    ap.add_argument("--legacy", nargs="?", const="all", default="",
                    choices=["all", "queue", "blocking"],
                    help="A/B: put the pre-#1226 code paths back on this same build — "
                         "all of them, or just the queue half or the blocking half")
    ap.add_argument("--daemon", action="store_true",
                    help="let the profiles bring their daemons up (slow, and not what "
                         "is being measured)")
    ap.add_argument("--live", action="store_true", help="the real profiles, not copies")
    ap.add_argument("--base-port", type=int, default=47700,
                    help="the first port handed to a copy (default 47700 — deliberately "
                         "not a real one, so a bench cannot drive a live client)")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                        # noqa: BLE001 — a redirected stream
            pass

    os.environ.setdefault("LW_PANEL_STALL_MS", str(args.threshold))

    from panel import profile as profilemod

    real = Path(profilemod.PROFILES_DIR)
    names = profilemod.ProfileManager().open_profiles() or [profilemod.DEFAULT_PROFILE]
    tmp = None
    if not args.live:
        tmp = Path(tempfile.mkdtemp(prefix="panel-load-"))
        names = _stage(names, real, tmp, args.profiles)
        _repoint(tmp, names, args.base_port)
        profilemod.PROFILES_DIR = str(tmp)
        profilemod.SETTINGS_FILE = str(tmp / "settings.json")
        (tmp / "settings.json").write_text(
            json.dumps({"active_profile": names[0], "open_profiles": names}),
            encoding="utf-8")
    else:
        names = names[:args.profiles]

    if args.legacy:
        _wear_legacy(args.legacy)

    if not args.daemon:
        from panel.runtime.daemon import GameLink
        GameLink.ensure = lambda self: self.up()
        print("daemons: not started (--daemon to allow it)")

    from panel import __main__ as pm

    print(f"profiles: {names}   ({'live' if args.live else tmp})")
    boot0 = time.perf_counter()
    app = pm.Panel()
    boot = time.perf_counter() - boot0
    print(f"boot: {int(boot * 1000)} ms")
    watch = getattr(app, "_stall", None)

    beat = Beat(app)
    beat.start()
    stop = threading.Event()
    calls = [0]
    lock = threading.Lock()

    def load(session, index: int) -> None:
        """What one profile's background work does TO THE PANEL, at `rate` a second."""
        rt = session.rt
        gap = 1.0 / max(1, args.rate)
        mine = 0
        while not stop.is_set():
            try:
                rt.settings.opt_int("daemon_port", low=1, high=65535)
                rt.settings.opt_str("game_exe")
                rt.settings.opt_bool("rdp_session")
                with rt.activity.step("activity.action", name="bench"):
                    rt.log.put(f"[bench] profile {index}: reading {mine}")
                    rt.post(lambda: None)
                mine += 1
            except Exception:                    # noqa: BLE001 — the legacy path raises
                pass
            stop.wait(gap)
        with lock:
            calls[0] += mine

    def pump(seconds: float) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            app.update()
            time.sleep(0.002)

    rows = []

    def bench() -> None:
        try:
            # 1. the floor: the panel with N profiles open, doing only its OWN work.
            if watch is not None:
                watch.note(f"idle, {len(names)} profiles")
            beat.recording = True
            beat.reset()
            pump(args.idle)
            beat.recording = False
            rows.append(("idle", beat.summary()))

            # 2. …and the same panel with every profile working.
            threads = [threading.Thread(target=load, args=(s, i), daemon=True)
                       for i, s in enumerate(app._workspace.sessions)]
            for thread in threads:
                thread.start()
            if watch is not None:
                watch.note(f"loaded, {len(names)} profiles x {args.rate}/s")
            beat.recording = True
            beat.reset()
            pump(args.seconds)
            beat.recording = False
            rows.append(("loaded", beat.summary()))
            stop.set()
            for thread in threads:
                thread.join(3)
        finally:
            beat.stop()
            app.after(0, app._on_close)

    app.after(1500, bench)
    app.mainloop()

    mode = f"BEFORE ({args.legacy} reverted)" if args.legacy else "AFTER (#1226)"
    print(f"\n== how late the event loop was — {mode}, "
          f"{len(names)} profiles ==")
    print(f"{'phase':<8} {'beats':>7} {'p50':>8} {'p95':>9} {'p99':>9} {'worst':>9} "
          f"{'>100ms':>7} {'>500ms':>7}")
    for phase, s in rows:
        print(f"{phase:<8} {s['beats']:7d} {s['p50']:7.1f}m {s['p95']:8.1f}m "
              f"{s['p99']:8.1f}m {s['worst']:8.1f}m {s['over100']:7d} {s['over500']:7d}")
    print(f"\nbackground calls made: {calls[0]}"
          f"   (asked for {int(args.rate * args.seconds) * len(names)})")
    if watch is not None:
        print(f"\n== stalls over {args.threshold} ms: {len(watch.stalls)} ==")
        for stall in watch.stalls[:12]:
            print(stall.report())
    if tmp is not None:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

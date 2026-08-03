r"""Switch profiles in a LIVE panel and print what the freeze consisted of (#1211).

The panel is opened for real — the same `Panel(tk.Tk)` a person opens, the same
profiles, the same boot — and then driven: a switch to each profile in turn, several
rounds of it, with the clock stopped only once the window answers again. Two numbers
come out per switch and they are not the same number:

  * **call** — how long `_switch_profile` itself took. This is what a stopwatch wrapped
    around the handler measures, and it is misleading on purpose: `Notebook.select()`
    QUEUES `<<NotebookTabChanged>>`, so the handler returns before the switch has
    happened at all.
  * **settle** — until the event queue is empty and the window redraws. That is the
    freeze a person sits through, and it is the number to look at.

Alongside them, `panel/runtime/stall.py` samples the Tk thread from its own thread and
prints every freeze over the threshold with the stacks that held it.

    C:\Python312\python.exe tools\dev\panel_switch_bench.py --rounds 3

By default the profiles are COPIES under a temporary directory — everything but the
timer and trigger catalogues, so the bench carries the real weight (the chat store, the
logs, the map checkpoints) and still cannot fire an errand into the game. `--live` runs
the real ones instead: closer to the operator's panel, and it does everything the
operator's panel does, in the real game.

What each finding here was worth is written up in `docs/research/panel-freezes.md`.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


#: What a copied profile does NOT get. The two errand catalogues, so a bench cannot
#: fire a timer or a wire trigger into the live game; the lock and the heartbeat, so a
#: copy is never mistaken for the real profile being open somewhere.
_LEAVE_BEHIND = {"timers.json", "timers_last_run.json", "timers_seen.json",
                 "triggers.json", "panel.lock", "panel_alive.json"}


def _stage(names: list, source: Path, dest: Path) -> None:
    """Copy each profile whole — minus its errands — so the bench measures real weight.

    Everything but the catalogues above: the settings that say which tabs the profile
    shows, and ALSO the chat store, the logs, the map checkpoints and the ranking
    history the tabs read. A profile stripped to its `config.json` switches in a
    fraction of the time the operator's does, and a bench that measures the fraction is
    the reason a freeze can be «fixed» twice and still be there (#1211).
    """
    for name in names:
        (dest / name).mkdir(parents=True, exist_ok=True)
        src = source / name
        if not src.is_dir():
            continue
        for item in src.iterdir():
            if item.name in _LEAVE_BEHIND or not item.is_file():
                continue
            shutil.copy2(item, dest / name / item.name)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="drive profile switches in a live panel")
    ap.add_argument("--profiles", default="", help="comma-separated; default: what the "
                                                   "panel would open by itself")
    ap.add_argument("--rounds", type=int, default=3, help="switch cycles (default 3)")
    ap.add_argument("--threshold", type=int, default=150,
                    help="ms a Tk-thread stall must last to be reported (default 150)")
    ap.add_argument("--settle", type=float, default=1.5,
                    help="seconds to keep pumping after each switch, so what the switch "
                         "STARTED is caught too (default 1.5)")
    ap.add_argument("--warmup", type=float, default=0.0,
                    help="seconds to let the panel run before the first switch — a "
                         "freeze an operator meets is met by a panel that has been "
                         "open a while, not one three seconds old")
    ap.add_argument("--enable-tabs", default="",
                    help="write this tab set into the COPIED profile before opening it "
                         "(comma-separated ids) — the knob a bisection turns")
    ap.add_argument("--tab-loop", type=int, default=0,
                    help="switch back and forth between the profile's first two tabs "
                         "this many times and report the times: the cheapest possible "
                         "interaction, so whatever it costs is the page's own weight")
    ap.add_argument("--tabs", action="store_true",
                    help="after each switch, click through that profile's own tabs and "
                         "time every show — the other half of «переключение вкладок»")
    ap.add_argument("--open-only", default="",
                    help="comma-separated: open ONLY these at boot, so a switch to any "
                         "of the others has to BUILD its page — which is what a switch "
                         "does whenever a profile was not restored (a stale lock is "
                         "enough)")
    ap.add_argument("--no-sweep", action="store_true",
                    help="A/B: do not start the machine-wide child sweep — the psutil "
                         "process walk a fresh panel does on a thread of its own. It "
                         "holds the GIL, so it is not free just because it is not on "
                         "the Tk thread (#1211)")
    ap.add_argument("--trace-build", action="store_true",
                    help="time every staged build step and print the ones over 50 ms — "
                         "which tab, and how long the loop was held by it")
    ap.add_argument("--no-force-redraw", action="store_true",
                    help="A/B: take the FORCED redraw out of the activity strip — the "
                         "`update_idletasks` the panel does per reported step, on the "
                         "Tk thread, from inside a page build. Everything else stays. "
                         "The difference is what the strip costs")
    ap.add_argument("--live", action="store_true",
                    help="use the real profile directory instead of copies")
    args = ap.parse_args(argv)

    # The console this runs in is cp1251 under Windows; a report is not worth an
    # encoding crash, and a profile may well be named in Russian.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                    # noqa: BLE001 — a redirected stream
            pass

    os.environ.setdefault("LW_PANEL_STALL_MS", str(args.threshold))

    from panel import profile as profilemod

    real = Path(profilemod.PROFILES_DIR)
    names = [n for n in (s.strip() for s in args.profiles.split(",")) if n]
    if not names:
        names = profilemod.ProfileManager().open_profiles() or [profilemod.DEFAULT_PROFILE]
    tmp = None
    if not args.live:
        tmp = Path(tempfile.mkdtemp(prefix="panel-bench-"))
        _stage(names, real, tmp)
        profilemod.PROFILES_DIR = str(tmp)
        profilemod.SETTINGS_FILE = str(tmp / "settings.json")
        import json
        opened = [n for n in (s.strip() for s in args.open_only.split(",")) if n] or names
        (tmp / "settings.json").write_text(
            json.dumps({"active_profile": opened[0], "open_profiles": opened}),
            encoding="utf-8")

    if tmp is not None and args.enable_tabs:
        import json as _json
        wanted = [t.strip() for t in args.enable_tabs.split(",") if t.strip()]
        for name in names:
            path = tmp / name / "config.json"
            try:
                raw = _json.loads(path.read_text(encoding="utf-8"))
            except Exception:                # noqa: BLE001 — a profile with no config yet
                raw = {}
            block = raw.setdefault("tabs", {})
            block["enabled"] = wanted
            path.write_text(_json.dumps(raw, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"tabs enabled: {wanted}")

    from panel import __main__ as pm

    if args.no_sweep:
        from panel.runtime import children as childrenmod
        childrenmod.ChildFactory._sweep = lambda self: None
        print("A/B: machine-wide child sweep OFF")

    if args.trace_build:
        _stage_one = pm.Panel._stage_one

        def timed(self, session, step):
            name = getattr(getattr(step, "func", step), "__name__", "?")
            what = getattr(getattr(step, "args", [None])[0], "id", "")
            t0 = time.perf_counter()
            _stage_one(self, session, step)
            held = time.perf_counter() - t0
            if held > 0.05:
                print(f"    build {name}({what}): {int(held * 1000)} ms", flush=True)

        pm.Panel._stage_one = timed

    if args.no_force_redraw:
        from panel import splash as splashmod

        def _say(self, text: str) -> None:          # the splash, without the flush
            try:
                self._step_lbl.configure(text=text)
            except Exception:                        # noqa: BLE001
                pass

        def _changed(self) -> None:                  # the strip, without the flush
            import threading as _t
            if _t.current_thread() is _t.main_thread():
                self._paint_activity()
                return
            if self._activity_pending:
                return
            self._activity_pending = True
            try:
                self.after(0, self._paint_activity)
            except Exception:                        # noqa: BLE001
                self._activity_pending = False

        splashmod.SplashScreen.say = _say
        pm.Panel._activity_changed = _changed
        print("A/B: forced redraw OFF")

    print(f"profiles: {names}   ({'live' if args.live else tmp})")
    boot0 = time.perf_counter()
    app = pm.Panel()
    print(f"boot: {int((time.perf_counter() - boot0) * 1000)} ms")
    watch = getattr(app, "_stall", None)

    rows: list = []
    tabs: list = []

    def pump(seconds: float) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            app.update()
            time.sleep(0.005)

    def pump_until_idle(limit: float) -> float:
        """Pump until the window reports nothing in flight — a page built to the end."""
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < limit:
            app.update()
            time.sleep(0.005)
            if app._activity.current() is None:
                break
        return time.perf_counter() - t0

    def walk_tabs(where: str) -> None:
        """Click through the profile's own tabs, timing each show.

        «Переключение вкладок» is the other half of the complaint and a different code
        path: the outer notebook moves a whole page, this one runs `on_hide`,
        `ensure_loaded` and `on_show` — where a tab is allowed to read the game, on the
        Tk thread, with the daemon of a profile that may live in another Windows
        session on the other end of it.
        """
        nb = getattr(app, "_main_nb", None)
        if nb is None:
            return
        for tab_id in nb.tabs():
            label = str(nb.tab(tab_id, "text"))
            if watch is not None:
                watch.note(f"tab {label} ({where})")
            t0 = time.perf_counter()
            try:
                nb.select(tab_id)
            except Exception:                    # noqa: BLE001 — a tab that went away
                continue
            app.update()                         # …and the queued <<NotebookTabChanged>>
            held = time.perf_counter() - t0
            tabs.append((where, label, held))
            print(f"      tab {label:<22} {int(held * 1000):5d} ms", flush=True)
            pump(0.3)

    def tab_loop(times: int) -> None:
        """Bounce between two tabs, timing each show. The page's own weight, nothing else."""
        nb = getattr(app, "_main_nb", None)
        if nb is None:
            return
        ids = list(nb.tabs())[:2]
        if len(ids) < 2:
            return
        held = []
        for i in range(times):
            t0 = time.perf_counter()
            nb.select(ids[i % 2])
            app.update()
            held.append(time.perf_counter() - t0)
            time.sleep(0.05)
        held.sort()
        print(f"  tab bounce x{times}: median {int(held[len(held)//2]*1000)} ms, "
              f"worst {int(held[-1]*1000)} ms, best {int(held[0]*1000)} ms", flush=True)

    def bench() -> None:
        try:
            if args.tab_loop:
                pump(1.0)
                tab_loop(args.tab_loop)
            if args.warmup:
                if watch is not None:
                    watch.note(f"warm-up ({args.warmup:.0f}s)")
                pump(args.warmup)
            for round_no in range(args.rounds):
                for name in names:
                    if watch is not None:
                        watch.note(f"switch to {name} (round {round_no + 1})")
                    was_open = app._workspace.get(name) is not None
                    t0 = time.perf_counter()
                    app._switch_profile(name)
                    call = time.perf_counter() - t0
                    app.update()             # drain the queued <<NotebookTabChanged>>
                    settle = time.perf_counter() - t0
                    whole = settle
                    if not was_open:         # a switch that had to BUILD the page
                        whole = settle + pump_until_idle(120)
                    rows.append((round_no + 1, name, call, settle, whole,
                                 "built" if not was_open else "open"))
                    print(f"  round {round_no + 1}  -> {name:<20} "
                          f"call {int(call * 1000):5d} ms   settle {int(settle * 1000):5d} ms"
                          + ("" if was_open else
                             f"   BUILT in {int(whole * 1000):6d} ms"),
                          flush=True)
                    pump(args.settle)        # …and what the switch set off behind it
                    if args.tabs:
                        walk_tabs(f"{name} r{round_no + 1}")
        finally:
            app.after(0, app._on_close)

    app.after(1500, bench)
    app.mainloop()

    print("\n== switches ==")
    for round_no, name, call, settle, whole, how in rows:
        print(f"  {round_no}  {name:<20} {how:<6} call {int(call * 1000):5d} ms   "
              f"settle {int(settle * 1000):5d} ms   whole {int(whole * 1000):6d} ms")
    if tabs:
        print("\n== tab shows (slowest first) ==")
        for where, label, held in sorted(tabs, key=lambda r: -r[2])[:20]:
            print(f"  {int(held * 1000):6d} ms  {label:<24} {where}")
    if watch is not None:
        print(f"\n== stalls over {args.threshold} ms: {len(watch.stalls)} ==")
        for stall in watch.stalls:
            print(stall.report())
    if tmp is not None:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

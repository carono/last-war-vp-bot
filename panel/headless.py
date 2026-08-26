r"""The panel with no window — the same panel, minus the drawing (#1976, P3).

    C:\Python312\python.exe -m panel.headless                # every profile that was open
    C:\Python312\python.exe -m panel.headless --profile main # one, by name

WHAT IT IS. Everything `panel/__main__.py` builds around a Tk window, built around
nothing: the workspace, a runtime per profile, its schedule and triggers, its tabs (their
state, their errands, their screens — everything but their widgets), the remote control
and the link to the machine's service. What it is not is a second kind of panel: it opens
the same profiles, reads the same settings, plays the same recipes and answers the same
API. The window is a FRONT-END, and this is the panel without one.

WHY IT EXISTS BEFORE TK IS DELETED. Because the plan's own rule for the migration is that
the old way of driving the panel is deleted only after the new one has been used to drive
it (`docs/research/panel-service-and-spa-plan.md` §3). This is the new one. Every tab that
still draws goes on drawing in the window; run this instead and the drawing simply never
happens — which is exactly what P3 removes, one tab at a time, with something already
running that proves the rest still works.

WHAT A TAB IS HERE. Built, registered, holding its state and its errands, and never
drawn: `PanelTab.realize` skips `build()` when there is no frame to put widgets in and
applies the saved block all the same, because a tab's settings are its state. A screen
(`web_view`) is data off that state, so the phone sees what it always saw.

THE CLOCK IS `ThreadTicker` (`panel/runtime/tick.py`): one thread, FIFO hand-overs, the
two guarantees everything in the panel leans on. The main thread here does nothing but
wait, exactly as it does under a `mainloop`.
"""
from __future__ import annotations

import argparse
import signal
import sys
import threading
import time

from . import profile as profilemod
from . import runtime as runtimemod
from . import tabs as tabsreg
from .runtime import service_control as servicectl
from .runtime import web_control as webctl
from .runtime.workspace import Workspace

#: How often the main thread looks up to see whether it has been asked to stop. Nothing
#: happens here — every clock is its own thread — so this is only the size of the pause
#: between «стоп» and the process ending.
IDLE_SEC = 0.5


class HeadlessPanel:
    """One process, several profiles, no window."""

    def __init__(self, names=None, *, web: bool = True) -> None:
        self.workspace = Workspace(root=None, defaults=runtimemod.DEFAULTS)
        self._names = list(names or [])
        #: Whether to bring this process's OWN port up. On by default, because a panel
        #: nobody can reach is a panel nobody can use — and off for the machine that has
        #: the service (`panel/service/`), where one door already answers for every panel
        #: and a second one is a second port to remember. Also off for a trial run beside
        #: a panel that already holds the port: the settings say ONE port per machine, and
        #: a second process failing to bind it would switch that setting off for both.
        self._web = bool(web)
        self._stop = threading.Event()

    # -- lifecycle ----------------------------------------------------------
    def open(self) -> list:
        """Open the profiles asked for — or the ones the panel last had open."""
        names = self._names or _last_open()
        opened = []
        for name in names:
            try:
                session = self.workspace.open(name, make_current=not opened)
            except Exception as exc:              # noqa: BLE001 — one profile, not the lot
                print(f"panel: {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            self._build_tabs(session)
            opened.append(session)
        return opened

    def start(self) -> None:
        """Bring up what a panel does while nobody is looking, per profile."""
        for session in self.workspace.sessions:
            try:
                session.rt.tick.start()
            except AttributeError:                # a Tk ticker: the window pumps it
                pass
        self.workspace.start_all()
        rt = self.workspace.current.rt
        # The remote control and the service link are the WINDOW's in `panel/__main__.py`
        # — one per process, not per profile — and they are this process's here for the
        # same reason and through the same two modules.
        if self._web:
            webctl.apply(rt)
        servicectl.start(rt, self.workspace)

    def run(self) -> int:
        opened = self.open()
        if not opened:
            print("panel: no profile could be opened", file=sys.stderr)
            return 1
        self.start()
        for name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, name, None)
            if sig is not None:
                try:
                    signal.signal(sig, lambda *_a: self._stop.set())
                except (ValueError, OSError):     # not the main thread, or no such signal
                    pass
        print("panel: headless, profiles: "
              + ", ".join(s.name for s in self.workspace.sessions), flush=True)
        while not self._stop.wait(IDLE_SEC):
            pass
        self.shutdown()
        return 0

    def shutdown(self) -> None:
        if self._web:
            webctl.stop(quiet=True)
        servicectl.stop()
        for session in list(self.workspace.sessions):
            try:
                session.rt.tick.stop()
            except AttributeError:
                pass
        self.workspace.shutdown()

    # -- the tabs -----------------------------------------------------------
    @staticmethod
    def _build_tabs(session) -> None:
        """Make this profile's tabs — state, errands and screens, and no widgets.

        The same table the window builds from (`panel/tabs/resolve`) and the same order,
        so a profile's own tick list decides here what it decides there. A tab whose
        import or `__init__` raises is skipped and said, exactly as it is in a window: a
        panel that would not come up because one tab is broken is the failure this
        arrangement exists to avoid.
        """
        rt = session.rt
        block = (rt.profiles.load(session.name) or {}).get("tabs") or {}
        specs = tabsreg.resolve(enabled=block.get("enabled"), order=block.get("order"),
                                known=block.get("known"),
                                on_unknown=lambda tab_id: rt.log.put(
                                    f"[panel] no such tab any more: {tab_id}"))
        for spec in tabsreg.build_order(specs):
            try:
                tab = spec.load()(rt, None)
                rt.tabs.add(tab)
                saved = rt.settings.tab_config(spec.id, getattr(tab, "LEGACY_KEYS", {}))
                if saved:
                    tab.restore(saved)
                if getattr(tab, "EAGER", False):
                    rt.tabs.realize(tab)
                    tab.ensure_loaded()
            except Exception as exc:              # noqa: BLE001 — one tab, not the panel
                rt.log.put(f"[panel] {spec.id}: {type(exc).__name__}: {exc}")


def _last_open() -> list:
    """Which profiles the panel had open when it last ran — the shell's own list."""
    manager = profilemod.ProfileManager()
    try:
        names = [n for n in (manager.open_profiles() or []) if manager.exists(n)]
    except Exception:                             # noqa: BLE001 — a reading
        names = []
    return names or [manager.active or profilemod.DEFAULT_PROFILE]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="panel.headless", description=__doc__)
    ap.add_argument("--profile", action="append", default=[],
                    help="open this profile (repeatable); default is what was last open")
    ap.add_argument("--no-web", action="store_true",
                    help="do not bring this process's own port up (the service has one)")
    args = ap.parse_args(argv)
    return HeadlessPanel(args.profile, web=not args.no_web).run()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

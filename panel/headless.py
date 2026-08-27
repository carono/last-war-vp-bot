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
from .runtime import autostart as autostartmod
from .runtime import panel_control as panelctl
from .runtime import service_control as servicectl
from .runtime import updates as updatesmod
from .runtime import web_control as webctl
from .runtime.workspace import Workspace

#: How often the main thread looks up to see whether it has been asked to stop. Nothing
#: happens here — every clock is its own thread — so this is only the size of the pause
#: between «стоп» and the process ending.
IDLE_SEC = 0.5

#: What this process exits with when every profile it was asked for is already held by
#: another panel. Its own code, so whatever started it can tell «one is already running»
#: — which is the ordinary answer and not a fault — from «it could not come up» (#1994).
HELD_EXIT = 3

#: How often a profile's log queue is drained onto its disk. The window does it every
#: 120 ms because it is also drawing; here nothing is drawn, so the only deadline is
#: `panel.log` being current enough to read while something is going wrong.
LOG_PUMP_MS = 500


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
        self._down = False
        #: Profiles whose `panel.log` is open and being drained (see `_pump_log`).
        self._logging: set = set()
        #: THE INSTANCE LOCK, one handle per profile this process holds (#1994).
        #:
        #: The window has taken it since it had one (`panel/runtime/host.py`,
        #: `start_heartbeat`) and a panel with no window took NOTHING — no lock, no beat,
        #: and a command line (`-m panel.headless`) that `autostart._panel_profile` did
        #: not recognise as a panel either. So every guard against «two panels on one
        #: account» was blind to this process, and live on 2026-08-27 there were EIGHT of
        #: them on one profile: one `panel.log`, one `config.json` and one game written
        #: over by eight schedules, and a restart that reached whichever of the eight
        #: happened to answer — which is how a committed fix went undelivered for hours
        #: while every reading said it had been restarted.
        self._locks: dict = {}
        #: Profiles this process refused to open because another panel holds them.
        self._held: list = []

    # -- lifecycle ----------------------------------------------------------
    def open(self) -> list:
        """Open the profiles asked for — or the ones the panel last had open.

        A profile ANOTHER panel process already holds is not opened here: the lock is
        taken first and a refusal is the kernel saying «somebody is on this account».
        Skipped rather than waited for, and said on stderr — the two panels would
        otherwise share one log, one settings file and one client, and the profile that
        loses that fight loses it silently (#1994).
        """
        names = self._names or _last_open()
        manager = profilemod.ProfileManager()
        opened = []
        for name in names:
            handle = autostartmod.take_lock(manager, name)
            if handle is None:
                who = autostartmod.holder(manager, name)
                whose = f" (pid {who})" if who else ""
                print(f"panel: {name}: another panel already holds this profile{whose}"
                      f" — not opening a second one here", file=sys.stderr, flush=True)
                self._held.append(name)
                continue
            self._locks[name] = handle
            try:
                session = self.workspace.open(name, make_current=not opened)
            except Exception as exc:              # noqa: BLE001 — one profile, not the lot
                print(f"panel: {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
                autostartmod.drop_lock(self._locks.pop(name, None))
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
        # THE READINGS (#1984). A window polls the client every eight seconds — is it
        # there, does a chunk land, does the server answer — and writes the verdict every
        # front-end draws, feeding the recovery on the way. With no window nothing took
        # them at all: live on 2026-08-26 this panel played for hours while the phone
        # said «клиент игры не запущен», because `ProfileHealth` had never been written
        # once. It is the profile's own poll now (`panel/runtime/status.py`), so it runs
        # here exactly as it does there.
        for session in self.workspace.sessions:
            try:
                session.rt.status.start()
            except Exception as exc:          # noqa: BLE001 — one profile, not the lot
                print(f"panel: {session.name}: status poll: {exc}", file=sys.stderr)
            # …AND THE PROFILE'S OWN LOG, for the same reason (#1984). A line goes into
            # the sink from any thread and waits in a queue somebody has to drain: the
            # drain is what writes `panel.log` — the person's record of the session —
            # and what keeps the queue from growing all night. The window pumped it
            # every 120 ms and nothing did here, so `panel.log` simply stopped at the
            # hour this panel last had a window.
            try:
                self._pump_log(session)
            except Exception as exc:          # noqa: BLE001 — the log, never the panel
                print(f"panel: {session.name}: log pump: {exc}", file=sys.stderr)
            # …AND THE BEAT (#1994). The lock says a panel process is on this profile;
            # the beat says it is still ANSWERING, and the hourly check reads both to tell
            # a working panel from a wedged one (`panel/runtime/autostart.py`). A window
            # has beaten since #1206 and this had never beaten at all, so every hour the
            # check saw an account with no panel on it and was one guard away from opening
            # a second one on top of this process.
            try:
                self._beat(session)
            except Exception as exc:          # noqa: BLE001 — a reading, never the panel
                print(f"panel: {session.name}: heartbeat: {exc}", file=sys.stderr)
        rt = self.workspace.current.rt
        # The remote control and the service link are the WINDOW's in `panel/__main__.py`
        # — one per process, not per profile — and they are this process's here for the
        # same reason and through the same two modules.
        if self._web:
            webctl.apply(rt)
        servicectl.start(rt, self.workspace)
        # THE TWO PRESSES ON THE PANEL ITSELF. The shell registers these while it builds
        # the window (`panel/runtime/panel_control.py`), so a panel with no window used to
        # answer «unavailable» to both — and «⟳ Перезапустить панель» is not a convenience
        # here, it is the rule: a fix nobody restarted into is a fix that is not there
        # (`CLAUDE.md`). With no window there is also nobody at the machine to end the
        # process by hand, so «Заглушить» is the only orderly way down.
        panelctl.set_handler(self._restart_now, panelctl.RESTART)
        panelctl.set_handler(self._quit_now, panelctl.QUIT)

    def run(self) -> int:
        opened = self.open()
        if not opened:
            # EVERY profile was held, or none could be opened. Either way this process has
            # nothing to do and says so with a code of its own, so whatever started it can
            # tell «already running» from «broken» (#1994).
            print("panel: no profile could be opened", file=sys.stderr)
            return HELD_EXIT if self._held else 1
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

    # -- the profile's own log ----------------------------------------------
    def _pump_log(self, session) -> None:
        """Drain this profile's log queue onto its disk, and keep doing it.

        `LOG_PUMP_MS` rather than the window's 120 ms: nothing is being drawn, so the
        only deadline is the record, and a pump ten times a second over several profiles
        is a thread waking up for nothing.
        """
        rt = session.rt
        if session.name not in self._logging:
            self._logging.add(session.name)
            rt.log.open_file(rt.profiles.panel_log(session.name))

        def turn() -> None:
            try:
                rt.log_spool.pump(cap=rt.settings.opt_int("log_max_lines",
                                                          low=200, high=200000))
            except Exception:                 # noqa: BLE001 — the log, never the panel
                pass
            if not self._down:
                rt.tick.arm("log", LOG_PUMP_MS, turn)

        turn()

    # -- «I am still here», per profile -------------------------------------
    def _beat(self, session) -> None:
        """Say once a minute that this profile's panel is still turning its clock."""
        rt = session.rt
        name = session.name

        def turn() -> None:
            try:
                autostartmod.beat(rt.profiles, name)
            except Exception:                 # noqa: BLE001 — a reading, never the panel
                pass
            if not self._down:
                rt.tick.arm("heartbeat", int(autostartmod.BEAT_SEC * 1000), turn)

        turn()

    # -- the panel's own two presses ----------------------------------------
    def _quit_now(self) -> None:
        """Put this panel down — the same orderly shutdown a closing window runs.

        Only the flag: `run` is waiting on it, and the shutdown then happens on the MAIN
        thread rather than on the clock that called this. Every profile is written out,
        every tab's children stopped, the service link and the port let go.
        """
        self._stop.set()

    def _restart_now(self) -> None:
        """Put this panel back on the code that is on disk. The question was already put.

        The order is the window's and it matters: shut down FIRST — that is what writes
        the profiles out — and only then start the replacement, which reads them on the
        way up. `module="panel.headless"` because a panel that had no window must not come
        back with one: this process may be running in a session with no desktop at all.
        """
        try:
            self.shutdown(why=autostartmod.RESTARTING)
        except Exception:                     # noqa: BLE001 — a tab that fails to stop
            print("panel: restart shutdown failed", file=sys.stderr)  # must not strand it
        try:
            updatesmod.relaunch(module="panel.headless")
        except Exception as exc:              # noqa: BLE001
            print(f"panel: relaunch failed: {exc}", file=sys.stderr)
        self._stop.set()

    def shutdown(self, why: str = autostartmod.CLOSED) -> None:
        """Put this panel down. ``why`` is the farewell each profile's beat is left with.

        :data:`autostartmod.RESTARTING` when the replacement is about to be started — the
        guards must not race a relaunch — and :data:`autostartmod.CLOSED` when this is the
        end of it. The locks go LAST of all, after the profiles are written out: a
        replacement that took one before this process had finished writing would read a
        settings file half-saved.
        """
        # ONCE. A restart shuts down and then `run` shuts down again on its way out of the
        # wait; a workspace closed twice is a profile written by something that has already
        # let go of it.
        if self._down:
            return
        self._down = True
        panelctl.set_handler(None, panelctl.RESTART)
        panelctl.set_handler(None, panelctl.QUIT)
        if self._web:
            webctl.stop(quiet=True)
        servicectl.stop()
        for session in list(self.workspace.sessions):
            try:
                session.rt.tick.disarm("log")
                session.rt.log_spool.pump()   # …and the tail, so nothing is lost
                session.rt.log.close_file()
            except Exception:                 # noqa: BLE001 — going down, never a fault
                pass
            try:
                session.rt.status.stop()
            except Exception:                 # noqa: BLE001 — going down, never a fault
                pass
            try:
                session.rt.tick.stop()
            except AttributeError:
                pass
            try:
                session.rt.tick.disarm("heartbeat")
                autostartmod.clear(session.rt.profiles, session.name, why=why)
            except Exception:                 # noqa: BLE001 — going down, never a fault
                pass
        self.workspace.shutdown()
        for name in list(self._locks):
            autostartmod.drop_lock(self._locks.pop(name, None))

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
                # …AND WHAT THE TAB BROUGHT WITH IT — its wire-driven errands, the knobs
                # its errands carry and the standing orders it owns (#2017). After the
                # block, exactly as the window does it, so a tab that decides its knobs
                # off its saved state declares the ones it really has. Nobody made this
                # call here at all: on the front-end that actually runs the panel every
                # gear was empty, and every trigger a tab binds a HANDLER to was
                # listening to nothing.
                rt.schedule.register(tab)
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

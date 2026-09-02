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

from . import i18n as i18nmod
from . import profile as profilemod
from . import runtime as runtimemod
from . import tabs as tabsreg
from .runtime import autostart as autostartmod
from .runtime import streams as streamsmod
from .runtime import panel_control as panelctl
from .runtime import profile_control as profilectl
from .runtime import provision as provisionmod
from .runtime import rally_orders as rallyorders
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
        #: ONE PROFILE PRESS AT A TIME (#2024). With no window there is no Tk thread to
        #: hand a press to, so `panel/web/api.py::_hand_over` runs it inline on whichever
        #: thread the request came in on — and two of them arriving together would open,
        #: close and rename profiles in the same workspace at once.
        self._press = threading.RLock()

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
            self._start_session(session)
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
        # …AND THE FOUR ON A PROFILE (#2024). Same hole, one door along: opening,
        # closing, renaming and deleting a profile are the SHELL's presses
        # (`panel/runtime/profile_control.py`), the window has registered them since
        # #1976, and a panel with no window registered nothing — so every one of them
        # was answered «web.ui.refused» on the front-end that actually runs the panel,
        # and no profile could be opened from a phone at all. Which accounts are being
        # farmed is not a knob to lose while the window is being retired.
        profilectl.set_handler(self._profile_press)

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

    # -- one profile, up and down -------------------------------------------
    def _start_session(self, session) -> None:
        """Bring one open profile's own systems up — at boot, and on «Открыть» (#2024).

        THE READINGS (#1984). A window polls the client every eight seconds — is it
        there, does a chunk land, does the server answer — and writes the verdict every
        front-end draws, feeding the recovery on the way. With no window nothing took
        them at all: live on 2026-08-26 this panel played for hours while the phone said
        «клиент игры не запущен», because `ProfileHealth` had never been written once. It
        is the profile's own poll now (`panel/runtime/status.py`), so it runs here exactly
        as it does there.

        …AND THE PROFILE'S OWN LOG, for the same reason. A line goes into the sink from
        any thread and waits in a queue somebody has to drain: the drain is what writes
        `panel.log` — the person's record of the session — and what keeps the queue from
        growing all night. The window pumped it every 120 ms and nothing did here, so
        `panel.log` simply stopped at the hour this panel last had a window.

        …AND THE BEAT (#1994). The lock says a panel process is on this profile; the beat
        says it is still ANSWERING, and the hourly check reads both to tell a working
        panel from a wedged one (`panel/runtime/autostart.py`). A window has beaten since
        #1206 and this had never beaten at all, so every hour the check saw an account
        with no panel on it and was one guard away from opening a second one on top of
        this process.
        """
        try:
            session.rt.status.start()
        except Exception as exc:              # noqa: BLE001 — one profile, not the lot
            print(f"panel: {session.name}: status poll: {exc}", file=sys.stderr)
        try:
            self._pump_log(session)
        except Exception as exc:              # noqa: BLE001 — the log, never the panel
            print(f"panel: {session.name}: log pump: {exc}", file=sys.stderr)
        try:
            self._beat(session)
        except Exception as exc:              # noqa: BLE001 — a reading, never the panel
            print(f"panel: {session.name}: heartbeat: {exc}", file=sys.stderr)

    def _stop_session(self, session, why: str = autostartmod.CLOSED) -> None:
        """Let go of everything one profile's systems hold, and say why it is going.

        The order matters and is the shutdown's own: the log tail is drained and the file
        closed FIRST, because on Windows a directory with an open handle in it cannot be
        renamed or removed and both of those happen right after this on a «Переименовать»
        or an «Удалить».
        """
        rt = session.rt
        try:
            rt.tick.disarm("log")
            rt.log_spool.pump()               # …and the tail, so nothing is lost
            rt.log.close_file()
        except Exception:                     # noqa: BLE001 — going down, never a fault
            pass
        self._logging.discard(session.name)
        try:
            rt.status.stop()
        except Exception:                     # noqa: BLE001 — going down, never a fault
            pass
        try:
            rt.tick.stop()
        except AttributeError:
            pass
        try:
            rt.tick.disarm("heartbeat")
            autostartmod.clear(rt.profiles, session.name, why=why)
        except Exception:                     # noqa: BLE001 — going down, never a fault
            pass

    # -- the four presses on a profile ---------------------------------------
    def _profile_press(self, action: str, name: str, text: str = "") -> bool:
        """Open, close, rename or delete one profile, with no window (#2024).

        The window's own half is `panel/__main__.py::_profile_press`, and it runs on the
        Tk thread because every branch of it builds or destroys widgets. There are none
        here, and no Tk thread to hand the press to either — `panel/web/api.py` runs a
        press inline when a runtime has no root — so two presses arriving at once are
        serialised by this process's own lock instead.

        The typed word that guards a rename and a delete is checked by the CALLER, which
        is the only side that knows what the row said. Nothing here opens a message box:
        a modal raised for somebody who is not at the machine is a panel that stops. A
        refusal is a line in a profile's log and a ``False``.
        """
        with self._press:
            if action == profilectl.OPEN:
                return self._open_profile(name)
            if action == profilectl.CLOSE:
                return self._close_profile(name)
            if action == profilectl.RENAME:
                return self._rename_profile(name, text)
            if action == profilectl.DELETE:
                return self._delete_profile(name)
        return False

    def _open_profile(self, name: str) -> bool:
        """Open one more profile beside the ones already running. Creating it if new.

        THE LOCK FIRST, exactly as `open` does it at boot (#1994): a profile another
        panel process holds is not opened a second time here, because the two would
        write one `config.json`, drive one daemon and share one client.

        A name with no directory behind it is CREATED, which is what `Workspace.open`
        has always done and what «Создать» on the phone relies on. A profile made that
        way has no `daemon_port` of its own and would drive the default profile's client
        until one is set — `Workspace._warn_client_shared` says so in both profiles'
        logs, as it does in the window.
        """
        name = profilemod.sanitize(name)
        if not name:
            return False
        if self.workspace.get(name) is not None:
            self.workspace.switch_to(name)
            return True
        handle = autostartmod.take_lock(self.workspace.profiles, name)
        if handle is None:
            self._say("log.profile.held_elsewhere", name=name)
            return False
        self._locks[name] = handle
        try:
            session = self.workspace.open(name)
        except Exception as exc:              # noqa: BLE001 — one profile, not the lot
            autostartmod.drop_lock(self._locks.pop(name, None))
            self._say("log.profile.open_failed", name=name,
                      error=f"{type(exc).__name__}: {exc}")
            return False
        self._build_tabs(session)
        try:
            session.rt.tick.start()
        except AttributeError:                # a Tk ticker: the window pumps it
            pass
        session.start()
        self._start_session(session)
        session.rt.say(profilectl.TAG, "log.profile.opened", name=name)
        return True

    def _close_profile(self, name: str) -> bool:
        """Stop one profile and let go of it — its errands, its readings, its lock.

        The last open one is refused, exactly as the workspace refuses it: a panel with
        no profile open is a panel with nothing to do, and «Закрыть» must not be the way
        to get there.
        """
        name = profilemod.sanitize(name)
        session = self.workspace.get(name)
        if session is None:
            return False
        if len(self.workspace) <= 1:
            self._say("log.profile.last_one", name=name)
            return False
        self._stop_session(session)
        if self.workspace.close(name) is None:
            return False
        autostartmod.drop_lock(self._locks.pop(name, None))
        # The web server keeps ONE runtime as its fallback and its log; if that was the
        # profile just closed, point it at one that is still open (#1313).
        if self._web:
            webctl.follow(self.workspace)
        self._say("log.profile.closed", name=name)
        return True

    def _rename_profile(self, name: str, newname: str) -> bool:
        """Rename a profile — closing it first when it is open, and opening it again.

        The window renames the profile it is SHOWING and re-points the one runtime under
        it; there is no showing page here and every open profile is equally live, so the
        honest version is the plain one: stop the profile, move the directory, bring it
        back under the new name. On Windows it is also the only version that works — a
        directory holding an open `panel.log` cannot be renamed at all.
        """
        name = profilemod.sanitize(name)
        if not name or not str(newname or "").strip():
            return False
        reopen = self.workspace.get(name) is not None
        if reopen and (not self._make_room(name) or not self._close_profile(name)):
            return False
        try:
            newn = self.workspace.profiles.rename(name, newname)
        except ValueError as exc:
            self._say("log.profile.rename_failed", name=name, error=self._error_text(exc))
            if reopen:
                self._open_profile(name)
            return False
        # The hourly autostart names no profile since #1207 — it opens ONE panel with
        # whatever set the panel itself saved, and that set already knows the new name.
        # This only sweeps away a per-profile task from #1203, if the machine has one.
        autostartmod.rename(name, newn)
        if reopen:
            self._open_profile(newn)
        self._say("log.profile.renamed", old=name, new=newn)
        return True

    def _delete_profile(self, name: str) -> bool:
        """Delete a profile: everything it is running, then its whole directory.

        The order is the window's and every step of it is load-bearing (#1253): refuse
        early, keep a profile open, let the daemon go while the link that can reach it is
        still alive, close the session so nothing holds a file inside the directory, and
        only then remove it — through the WORKSPACE's unpinned manager, the one allowed
        to write which profiles are open.
        """
        profiles = self.workspace.profiles
        name = profilemod.sanitize(name)
        if not name or not profiles.exists(name):
            self._say("profile.error.missing", name=name)
            return False
        if len(profiles.list()) <= 1:
            self._say("profile.error.last_one")
            return False
        note = None
        if self.workspace.get(name) is not None:
            if not self._make_room(name):
                return False
            # Worked out while the link is alive, SAID once the profile is gone: a line
            # about the daemon put into the log of the profile being deleted is a line
            # written into a file that is about to be removed.
            note = self._let_link_go(name)
            if not self._close_profile(name):
                return False
        if note is not None:
            self._say(note[0], **note[1])
        try:
            now_active = profiles.delete(name)
        except ValueError as exc:
            self._say("log.profile.delete_failed", name=name, error=self._error_text(exc))
            return False
        left = autostartmod.drop_legacy(name)
        if left:
            self._say("log.autostart.leftover", name=name, error=", ".join(left))
        self._say("log.profile.deleted", name=name, active=now_active)
        return True

    def _make_room(self, name: str) -> bool:
        """Make sure something will still be open once ``name`` is not. ``False`` = refuse.

        `Workspace.close` will not close the last open session and is right not to. So
        the profile that is about to go stops being the only one open: another is opened
        beside it first. When there is no other this panel may open — every one of them
        held by a second panel — the honest answer is to say so and do nothing.
        """
        if len(self.workspace) > 1:
            return True
        profiles = self.workspace.profiles
        other = next((n for n in profiles.list()
                      if n != name and not autostartmod.locked(profiles, n)), None)
        if other is None:
            self._say("profile.error.no_replacement", name=name)
            return False
        self._open_profile(other)
        return len(self.workspace) > 1

    def _let_link_go(self, name: str):
        """Ask this profile's daemon to exit — nothing will ever ask it for anything again.

        A daemon deliberately outlives the panel, because a profile CLOSED is a profile
        that will be opened again. A profile DELETED is not: leaving its link up leaves
        something holding a client, a game lease and a port that `provision` would then
        step around for ever. Unless somebody else is on that port — two profiles on one
        client is a state older installs are still in, and shutting it down from under
        the other one would take its game with it.

        Returns ``(key, fmt)`` for the caller to say once the profile is gone, or ``None``.
        """
        rt = getattr(self.workspace.get(name), "rt", None)
        if rt is None:
            return None
        try:
            port = rt.daemon_port()
            others = provisionmod.clients(self.workspace.profiles, exclude=name)
        except Exception:                     # noqa: BLE001 — a reading, never the delete
            return None
        sharing = sorted(n for n, client in others.items() if client.port == port)
        if sharing:
            return ("log.profile.link_kept", {"port": port, "others": ", ".join(sharing)})
        try:
            if not rt.game.up():
                return None
        except Exception:                     # noqa: BLE001 — a reading
            return None

        def work() -> None:
            try:
                rt.game.let_go()
            except Exception:                 # noqa: BLE001 — a link, not the panel
                pass

        threading.Thread(target=work, name="panel-link-let-go", daemon=True).start()
        return ("log.profile.link_stopped", {"port": port})

    def _say(self, key: str, **fmt) -> None:
        """Say one line in whichever profile is still there to hear it.

        A refusal about a profile that is closed, or about one that has just been
        deleted, has no log of its own to land in — so it lands in the panel's current
        one, which is where a person reading this process looks.
        """
        rt = getattr(self.workspace.current, "rt", None)
        try:
            rt.say(profilectl.TAG, key, **fmt)
        except Exception:                     # noqa: BLE001 — before there is a log
            print(f"panel: {key}: {fmt}", file=sys.stderr)

    def _error_text(self, exc: Exception) -> str:
        """A refusal in the person's language when it named one, its own words if not."""
        rt = getattr(self.workspace.current, "rt", None)
        try:
            return i18nmod.translated(rt.t, exc)
        except Exception:                     # noqa: BLE001 — a message, never the panel
            return str(exc)

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
        profilectl.set_handler(None)
        if self._web:
            webctl.stop(quiet=True)
        servicectl.stop()
        for session in list(self.workspace.sessions):
            self._stop_session(session, why=why)
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
        # …AND SOMEBODY TO WRITE IT DOWN (#2017). `settings.changed()` is how every tab
        # says «this belongs to the profile now» — a switch moved from the phone, a
        # number typed behind a gear — and it does nothing at all until a container
        # answers it. The window has answered since it had tabs; here nobody did, so on
        # a machine with no window EVERY knob a phone moved was gone at the next
        # restart, silently, which is the hole #2010 found in one tab and this is in all
        # of them.
        #
        # ONLY THE TABS' OWN BLOCKS. The window's saver also collects its geometry, its
        # settings widgets and the offered-tab bookkeeping; none of that exists here, and
        # a headless panel writing `tabs.enabled` off a list it did not build is how a
        # tab a person switched off would come back.
        rt.settings.on_change = lambda: HeadlessPanel._save_tab_blocks(rt)
        # …AND THE RALLY AUTO-JOIN'S FOUR STANDING RULES (#2051). Same hole again, one
        # door along from #2017 and #2024: its arguments, the hook that writes the count
        # down and its two preconditions were registered by the WINDOW alone, so on the
        # front-end that actually farms the accounts every banner arrived with no target
        # (classified as the fallback «monster»), the press was handed no per-kind budget
        # at all, the day's ceiling and the soldier floor fell back to their defaults and
        # nothing ever moved `rally_counts` — which is why the counter on the screen read
        # almost nothing while the log showed hundreds of joins.
        rallyorders.wire(rt)

    @staticmethod
    def _save_tab_blocks(rt) -> None:
        """Write every live tab's block into this profile, and nothing else."""
        try:
            for tab in list(rt.tabs.live):
                rt.settings.set_tab_config(tab.ID, tab.stored_config(),
                                           type(tab).LEGACY_KEYS)
            rt.settings.save()
        except Exception as exc:                  # noqa: BLE001 — a save, never the panel
            rt.log.put(f"[panel] save failed: {type(exc).__name__}: {exc}")


def _last_open() -> list:
    """Which profiles the panel had open when it last ran — the shell's own list."""
    manager = profilemod.ProfileManager()
    try:
        names = [n for n in (manager.open_profiles() or []) if manager.exists(n)]
    except Exception:                             # noqa: BLE001 — a reading
        names = []
    return names or [manager.active or profilemod.DEFAULT_PROFILE]


def main(argv=None) -> int:
    # BEFORE ANYTHING PRINTS — see `panel/runtime/streams.py`. This entrypoint is the
    # one most often started detached, and it says everything it has to say on stderr.
    streamsmod.ensure()
    ap = argparse.ArgumentParser(prog="panel.headless", description=__doc__)
    ap.add_argument("--profile", action="append", default=[],
                    help="open this profile (repeatable); default is what was last open")
    ap.add_argument("--no-web", action="store_true",
                    help="do not bring this process's own port up (the service has one)")
    args = ap.parse_args(argv)
    return HeadlessPanel(args.profile, web=not args.no_web).run()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

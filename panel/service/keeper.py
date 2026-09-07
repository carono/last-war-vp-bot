r"""The service is the OWNER of the panels, not a door they happen to knock on (#1976).

    «Не, не пойдет, центр правды — это служба, если я её поднял,
      значит все уже должно работать»            — the person, 2026-08-26

Before this file the service was a switchboard: a person started a panel by hand, the
panel dialled in, and the page had something to show. Which meant the machine had TWO
things to bring up and the one that survives a reboot was the one that did nothing on its
own. Now there is one: **the service is up, therefore the panels are up.**

## What it does

* **Starts them.** At boot, and whenever a wanted profile has no panel serving it.
* **Outlives them.** A panel that dies is started again; a panel that restarts ITSELF
  («⟳ Перезапустить панель», which is how a code fix reaches a running panel) is given
  :data:`GRACE_SEC` to come back before anybody else starts anything.
* **Puts them down properly.** Stopping the service asks each panel it started to quit —
  the same orderly shutdown the window's ✕ runs, through `panel/runtime/panel_control.py`
  — and waits. Nothing is killed: a killed panel leaves locks, children and a client
  nobody let go of.
* **Leaves a person's own panel alone.** Only what THIS service started is stopped by it.
  Somebody who opens `panel.bat` to look at a window keeps their window.

## What it may not do, and this is not a shortcoming to fix

A service lives in session 0 and the game needs a desktop, so the panel is started in a
signed-in session (`panel/service/session.py`). **With nobody signed in there is no
session to start it in** — the service says so once and keeps looking. No flag helps: a
game that draws needs a session that draws. Sign in, or leave a session logged on and
disconnected (`docs/research/multi-instance-rdp.md`).

## Which profiles, and how that is asked rather than assumed

`service.json` → `keep`:

    "keep": {"enabled": true, "profiles": [], "session": -1}

* `profiles` empty means **the ones this machine wants farmed** — the standing list a
  person writes by opening and closing accounts (`panel/profile.py::keep_profiles`),
  which is the machine's own answer and not a name in the code. It is deliberately NOT
  «what was open last», because a panel started to look at something for ten minutes
  rewrites that and would otherwise rewrite what the machine brings up at boot (#2068).
* `session` `-1` means «wherever somebody is signed in, the machine's own screen first».
* `enabled` `false` is the old behaviour exactly: a door, supervising nothing.

## ONE PANEL PER MACHINE, and it holds every account

    «Никаких других панелей у нас нет, есть одна, и она управляет всеми»
                                                   — the person, 2026-08-31

That is the rule, not a description of the usual case. A profile is an independent
instance INSIDE the one panel (`CLAUDE.md`) — its own log, schedule, budgets and daemon —
and the process is shared on purpose.

**This file used to break it while claiming it.** `launch(missing)` started a panel for
exactly the profiles that had none, so a machine wanting three accounts with a panel on
one of them got a SECOND process for the other two. On Windows both then bound the same
web port and neither said so (`panel/web/server.py::_Server`), the browser reached
whichever the kernel picked, and an account that was farming perfectly showed as «закрыт»
with a press that answered «отказано» (#2068).

So the keeper now, in this order: undoes any second panel it finds
(:meth:`Keeper.consolidate`), ASKS the one that is up to open what it lacks
(:meth:`Keeper.adopt`), and starts a panel only when the machine has none at all.
"""
from __future__ import annotations

import threading
import time

from . import session as sessionmod

#: How often the keeper looks at what is up. Short enough that a panel that died is back
#: before anybody refreshes the page twice; long enough to cost nothing.
CHECK_SEC = 5.0

#: How long a profile may have no panel before one is started for it. This is what makes
#: a panel's OWN restart invisible: it shuts down, spawns its replacement and the
#: replacement dials in — all inside this window, with nobody starting a second one.
GRACE_SEC = 30.0

#: A launch that fails is retried, more slowly each time, up to this. «Nobody is signed
#: in» is the ordinary reason and it may last all night; it must not fill the log.
BACKOFF_SEC = (10.0, 30.0, 60.0, 120.0)

#: How long a panel is given to close itself when the service is going down.
STOP_WAIT_SEC = 25.0

#: How long a profile the panel REFUSED to open is left alone before it is asked again.
#: Some refusals are permanent until a person changes something — a profile with no
#: Windows session and no daemon port of its own drives somebody else's client and is
#: turned down for it (#2024) — and a supervisor asking every five seconds would say the
#: same line all night. Long enough to be quiet, short enough that fixing the profile is
#: followed by it coming up without anybody restarting anything.
ASK_AGAIN_SEC = 120.0


def _profiles_screen() -> str:
    """The id of the screen whose presses open and close profiles.

    Asked of `panel/runtime/profile_control.py`, which is where the presses themselves
    are declared, rather than of the web API that draws them — the API is a large import
    that this process, in session 0, has no reason to load.
    """
    from ..runtime import profile_control as profilectl

    return str(profilectl.SCREEN)

#: The defaults of the `keep` block — a machine that has never been configured.
DEFAULTS = {"enabled": True, "profiles": [], "session": -1, "module": "panel.headless"}


def settings(config: dict) -> dict:
    """The `keep` block with anything unset filled in."""
    said = dict(DEFAULTS)
    block = (config or {}).get("keep")
    if isinstance(block, dict):
        for key in DEFAULTS:
            if key in block and block[key] is not None:
                said[key] = block[key]
    said["enabled"] = bool(said["enabled"])
    said["profiles"] = [str(p).strip() for p in (said["profiles"] or []) if str(p).strip()]
    try:
        said["session"] = int(said["session"])
    except (TypeError, ValueError):
        said["session"] = -1
    return said


def machine_profiles() -> list:
    """What this machine WANTS farmed — the default when `service.json` names nothing.

    THE STANDING LIST, NOT THE LAST ONE (#2068). This used to read `open_profiles`, which
    is a record rather than a wish: every panel process rewrites it on every open, close
    and switch, so a panel somebody started for ten minutes to look at two test accounts
    made those accounts the machine's boot list — and this service then put them back
    five seconds after every attempt to quit them. Two different questions had one answer
    and the temporary one kept winning.

    `panel/profile.py::keep_profiles` is the other answer, and only a PERSON writes it:
    opening or closing a profile on purpose, in either front-end, or `python -m
    panel.keep` on the machine itself. A machine that has never decided falls back to
    `open_profiles` and behaves exactly as it did — reading the wish never invents one —
    and the FIRST deliberate press turns the record into a wish and ends the drift.
    """
    try:
        from .. import profile as profilemod

        manager = profilemod.ProfileManager()
        names = [n for n in profilemod.keep_or_last_open() if manager.exists(n)]
        if names:
            return names
        one = manager.active or profilemod.DEFAULT_PROFILE
        return [one] if one else []
    except Exception:                        # noqa: BLE001 — a reading, never the service
        return []


class Keeper:
    """Keeps the wanted profiles served, and puts down what it started."""

    def __init__(self, registry, config: dict, *, log=None, launcher=None,
                 clock=time.monotonic) -> None:
        self.registry = registry
        self.settings = settings(config)
        self._log = log or (lambda line: None)
        #: Swapped in the tests. Everything about crossing a Windows session lives in
        #: `panel/service/session.py`, and this class knows only «ask it to start this».
        self._launch = launcher or sessionmod.launch
        self._clock = clock
        self._stop = threading.Event()
        self._thread = None
        #: The pids THIS service started. What it may put down, and nothing else.
        self.own: set = set()
        self._last_seen: dict = {}           # profile -> when a panel last served it
        self._fails = 0
        self._next_try = 0.0
        self._said_no_session = False
        #: Profiles said to be held by a panel that is not talking to us — said once each.
        self._said_held: set = set()
        #: profile -> when the panel was last ASKED to open it, so a refusal is not
        #: repeated every five seconds (:data:`ASK_AGAIN_SEC`).
        self._asked: dict = {}

    # -- what is wanted, and what is there -----------------------------------
    def wanted(self) -> list:
        if not self.settings["enabled"]:
            return []
        return list(self.settings["profiles"]) or machine_profiles()

    def serving(self) -> set:
        """Every profile a connected panel says it has open."""
        return {name for panel in self.registry.all() if not panel.closed
                for name in panel.profiles}

    def held(self, name: str) -> bool:
        """Is a live panel PROCESS on ``name``, whether or not it has dialled in?

        The register answers a narrower question than the keeper was asking of it: it
        knows which panels are TALKING to this service, and the keeper read that as which
        panels exist. A panel that is up but not connected — its link dropped, it is still
        coming up, somebody started it by hand — therefore read as an empty account, and
        got another panel started on top of it every time the grace ran out. Eight of them
        ended up on one profile that way (#1994).

        The instance lock is the same question answered by the kernel: it is held for the
        life of the process and released by the OS whatever ends it, so it cannot go stale
        and there is nothing to time out (`panel/runtime/autostart.py`).
        """
        try:
            from .. import profile as profilemod
            from ..runtime import autostart as autostartmod

            return bool(autostartmod.locked(profilemod.ProfileManager(), name))
        except Exception:                    # noqa: BLE001 — a reading, never the service
            return False

    def missing(self, now: float) -> list:
        """Wanted profiles with no panel — and none of them inside their grace."""
        serving = self.serving()
        out = []
        for name in self.wanted():
            if name in serving:
                self._last_seen[name] = now
                self._said_held.discard(name)
                continue
            seen = self._last_seen.get(name)
            if seen is not None and (now - seen) < GRACE_SEC:
                continue                     # its own restart is in flight
            if self.held(name):
                # A panel IS on it and is simply not talking to this service. Starting a
                # second one would not fix that and would cost the account two schedules
                # on one client — said once, and looked at again on the next tick.
                if name not in self._said_held:
                    self._said_held.add(name)
                    self._log(f"keeper: a panel already holds «{name}» and has not "
                              f"dialled in — not starting a second one")
                continue
            self._said_held.discard(name)
            out.append(name)
        return out

    # -- the loop ------------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None or not self.settings["enabled"]:
            if not self.settings["enabled"]:
                self._log("keeper: off — this service supervises nothing")
            return
        self._thread = threading.Thread(target=self._run, name="service-keeper",
                                        daemon=True)
        self._thread.start()

    def _run(self) -> None:
        # The first look is immediate: the whole point is that the machine comes up and
        # the panels are there, not that they are there five seconds later.
        while True:
            try:
                self.tick()
            except Exception as exc:         # noqa: BLE001 — a supervisor must not die
                self._log(f"keeper: {type(exc).__name__}: {exc}")
            if self._stop.wait(CHECK_SEC):
                return

    def tick(self) -> None:
        """One look: put the machine back to ONE panel holding everything it wants.

        The order is the whole of it (#2068):

        1. **More than one panel is an accident**, so it is undone first. Until it is,
           everything below would be asking a question with two answers.
        2. **A panel that is up is ASKED** to open what is missing. It used to be
           bypassed: `launch(missing)` started a SECOND process for exactly the profiles
           the first one lacked — which is how a machine that wanted three accounts ended
           up with two panels, two web servers on one port and one account the person
           could not see.
        3. **Only a machine with NO panel gets one started.**
        """
        now = self._clock()
        self.consolidate()
        missing = self.missing(now)
        if not missing:
            if self._fails:
                self._fails = 0
                self._said_no_session = False
            return
        panel = self.the_panel()
        if panel is not None:
            self.adopt(panel, missing, now)
            return
        if now < self._next_try:
            return
        self.launch(missing)

    # -- one panel, and it holds everything ----------------------------------
    def the_panel(self):
        """THE panel of this machine, or ``None`` when none has dialled in.

        «Никаких других панелей у нас нет, есть одна, и она управляет всеми» — the
        person, 2026-08-31. The oldest connection wins when there is somehow more than
        one, which is the same one :meth:`consolidate` keeps, so the two never disagree
        about which process the machine is.
        """
        panels = [p for p in self.registry.all() if not p.closed]
        if not panels:
            return None
        return min(panels, key=lambda p: (float(getattr(p, "at", 0.0) or 0.0),
                                          int(getattr(p, "pid", 0) or 0)))

    def consolidate(self) -> list:
        """Put down every panel but THE one. Returns the pids it asked to go.

        A second panel is not a configuration this machine has — it is damage, and the
        damage is mostly invisible: on Windows two processes can hold one web port
        (`panel/web/server.py::_Server`), so the browser reaches whichever the kernel
        picks and an account being farmed by the other one reads as «закрыт». It is
        fixed rather than reported, because a person cannot act on «у вас две панели»
        and should not have to.

        The profiles the stray was holding are not lost: its lock goes with it, the next
        tick counts them missing, and :meth:`adopt` asks the survivor to open them.
        """
        panels = [p for p in self.registry.all() if not p.closed]
        if len(panels) <= 1:
            return []
        keep = self.the_panel()
        gone = []
        for panel in panels:
            if panel is keep:
                continue
            pid = int(getattr(panel, "pid", 0) or 0)
            self._log(f"keeper: TWO PANELS on one machine — asking {pid} "
                      f"({', '.join(panel.profiles) or 'no profiles'}) to quit and "
                      f"leaving {int(getattr(keep, 'pid', 0) or 0)} to hold everything")
            try:
                panel.ask("POST", "/api/panel", {}, {"action": "quit"}, timeout=5.0)
            except Exception as exc:         # noqa: BLE001 — a supervisor must not die
                self._log(f"keeper: panel {pid} did not take the press: {exc}")
            gone.append(pid)
        return gone

    def adopt(self, panel, profiles: list, now: float) -> None:
        """Ask the one panel to open the profiles it is missing.

        THE PRESS IS THE PERSON'S OWN. `/api/screen/press` on the profiles screen is what
        the button in the browser sends (`panel/web/api.py::_profiles_press`), so a
        profile the service adds is opened by exactly the code path a person's tap uses —
        the same lock, the same log lines, and the same refusals when a profile has no
        client of its own to drive.

        A REFUSAL IS NOT RETRIED EVERY FIVE SECONDS. Some are permanent until somebody
        changes something (a profile with no session and no port of its own), and a
        supervisor that asks anyway fills the log with the same line all night. So each
        name is asked, and then left alone for :data:`ASK_AGAIN_SEC` before it is asked
        again.
        """
        for name in profiles:
            when = self._asked.get(name)
            if when is not None and (now - when) < ASK_AGAIN_SEC:
                continue
            self._asked[name] = now
            self._log(f"keeper: asking panel {int(getattr(panel, 'pid', 0) or 0)} "
                      f"to open «{name}»")
            try:
                status, payload = panel.ask(
                    "POST", "/api/screen/press", {},
                    {"id": _profiles_screen(), "action": "open",
                     "args": {"name": name}})
            except Exception as exc:         # noqa: BLE001 — a supervisor must not die
                self._log(f"keeper: panel did not take «{name}»: {exc}")
                continue
            payload = payload if isinstance(payload, dict) else {}
            if int(status) == 200 and payload.get("ok"):
                # Opened, or opening — a staged page answers «принято, идёт» and dials
                # its new list in when it is drawn (`panel/runtime/service_link.py`).
                self._asked.pop(name, None)
                continue
            self._log(f"keeper: the panel would not open «{name}»: "
                      f"{payload.get('reason') or payload.get('error') or status} — "
                      f"asking again in {ASK_AGAIN_SEC:.0f}s")

    def launch(self, profiles: list) -> dict:
        """Start ONE panel holding ``profiles``. Said in the log, whatever happens.

        NOT FROM A TEST RUN (#2002), and the refusal is in the launcher rather than here
        (`panel/service/session.py::launch`): `tests/test_panel_service.py` started a real
        :class:`~panel.service.host.Service`, and a service starts its keeper — so a plain
        `tools/run_tests.py` spawned `-m panel.headless --profile default` on the LIVE
        account, detached. It outlived the run, took the machine lease off the real panel
        and played `launch_game` against the real client every five minutes. Guarding the
        LAUNCHER and not this method is what lets `tests/test_service_keeper.py` go on
        exercising every branch below with a launcher of its own.
        """
        cmd = sessionmod.panel_command(profiles, module=self.settings["module"])
        from ..runtime import paths

        said = self._launch(cmd, cwd=paths.REPO, session_id=self.settings["session"],
                            log=self._log)
        if said.get("ok"):
            self.own.add(int(said.get("pid") or 0))
            self._fails = 0
            self._said_no_session = False
            self._next_try = self._clock() + GRACE_SEC
            self._log(f"keeper: started a panel for {', '.join(profiles)} "
                      f"(pid {said.get('pid')}, session {said.get('session')}, "
                      f"{said.get('how')})")
            return said
        why = str(said.get("why") or "failed")
        self._next_try = self._clock() + BACKOFF_SEC[min(self._fails, len(BACKOFF_SEC) - 1)]
        self._fails += 1
        if why == "no_privilege":
            # Only SYSTEM may borrow a session's token. Said plainly, because the fix is
            # «run it as the service» and not anything inside this file.
            self._log("keeper: this process may not start a program in somebody's "
                      "session — only the Windows SERVICE can (LocalSystem holds "
                      "SeTcbPrivilege). Run it with service_install.bat.")
        elif why in ("no_session", "no_token"):
            # THE HONEST ONE, and it is said ONCE. Nobody is signed in, so there is no
            # desktop to start a panel on — and the game could not draw on one either.
            if not self._said_no_session:
                self._said_no_session = True
                self._log("keeper: nobody is signed in to this machine — a panel needs a "
                          "session with a desktop (sign in, or leave one logged on and "
                          "disconnected). Still looking.")
        else:
            self._log(f"keeper: could not start a panel: {said.get('detail') or why}")
        return said

    # -- going down ----------------------------------------------------------
    def stop(self, *, wait: float = STOP_WAIT_SEC) -> None:
        """Stop the loop and ask the panels THIS service started to quit.

        Orderly and never a kill: `panel/runtime/panel_control.py` is the same shutdown
        the window's ✕ runs — every profile written out, every tab's children stopped,
        the game and the daemon left alone.
        """
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
        mine = [p for p in self.registry.all()
                if not p.closed and int(getattr(p, "pid", 0) or 0) in self.own]
        if not mine:
            return
        for panel in mine:
            self._log(f"keeper: asking panel {panel.pid} to quit")
            try:
                panel.ask("POST", "/api/panel", {}, {"action": "quit"}, timeout=5.0)
            except Exception as exc:         # noqa: BLE001 — going down anyway
                self._log(f"keeper: panel {panel.pid} did not take the press: {exc}")
        # REAL time here, not `self._clock`: everything else in this class is a DECISION
        # about when to try again and is happily driven by a test's own clock, but this is
        # a wait on other processes actually going away.
        deadline = time.monotonic() + float(wait)
        while time.monotonic() < deadline:
            if not [p for p in mine if not p.closed]:
                self._log("keeper: every panel it started has gone down")
                return
            time.sleep(0.25)
        left = [p.pid for p in mine if not p.closed]
        # NOT KILLED HERE, on purpose. A panel still writing a profile out is a panel to
        # leave alone, and the next service adopts nothing. What used to be missing is the
        # FLOOR under that politeness: one that never went — with its captures, sniffers
        # and tools under it — outlived the service and went on farming for a machine
        # whose service is stopped. `panel/service/tree.py` is that floor: the service
        # holds a job that kills on close, so whatever is still here when this process
        # ends goes with it, whole tree and all (#2613).
        self._log(f"keeper: still up after {wait:.0f}s and left to the job: {left}")

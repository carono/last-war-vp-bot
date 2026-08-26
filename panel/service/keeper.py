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

* `profiles` empty means **the ones this machine's panel last had open**
  (`profiles/settings.json`), which is the machine's own answer and not a name in the
  code — the rule the whole repository is written to (`CLAUDE.md`).
* `session` `-1` means «wherever somebody is signed in, the machine's own screen first».
* `enabled` `false` is the old behaviour exactly: a door, supervising nothing.

One panel process holds every wanted profile, which is what a window does too — a profile
is an independent instance INSIDE it (`CLAUDE.md`), with its own log, schedule, budgets
and daemon.
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
    """What this machine's panel last had open — the default when nothing is configured.

    Asked of `panel/profile.py`, which is where the answer already lives: the same file
    the window writes on every open, close and switch. A service that named a profile of
    its own would be a second answer to a question that has one.
    """
    try:
        from .. import profile as profilemod

        manager = profilemod.ProfileManager()
        names = [n for n in (manager.open_profiles() or []) if manager.exists(n)]
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
        """One look: start what is missing, if it is time to try again."""
        now = self._clock()
        missing = self.missing(now)
        if not missing:
            if self._fails:
                self._fails = 0
                self._said_no_session = False
            return
        if now < self._next_try:
            return
        self.launch(missing)

    def launch(self, profiles: list) -> dict:
        """Start ONE panel holding ``profiles``. Said in the log, whatever happens."""
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
        # NOT KILLED, on purpose. A panel still writing a profile out is a panel to leave
        # alone; the service is going away either way, and the next one adopts nothing.
        self._log(f"keeper: still up after {wait:.0f}s and left alone: {left}")

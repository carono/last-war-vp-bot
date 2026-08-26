r"""The readings a profile's light is made of — taken by the PANEL, not by a window.

WHY THIS MODULE EXISTS (#1984). Everything below used to live in `panel/__main__.py`,
inside the Tk shell's status poll, and that was fine while a panel WAS a window. It is
not any more: the machine's service runs `panel.headless` (#1976, P3), a panel with no
window at all — and in that panel nothing ever took these readings. Live on 2026-08-26
the result was a profile that played happily while every front-end said «клиент игры не
запущен»: `ProfileHealth` was never written, so the phone drew the boot's `unread()`
verdict for hours, the gate fell back to its own reading, and the recovery — the
watchdog's restart, the kick's wait, the maintenance knock — never ran at all, because
all three are fed from here.

So the readings are the RUNTIME's. One `StatusPoll` per open profile, on the profile's
own ticker, taking:

* **is there a client** for this profile (its exe, its Windows session);
* **does a chunk land** in that client's Lua VM — our own plumbing;
* **does the game SERVER answer** — an active probe on its own throttle, the only
  reading that earns green;
* **is the client wedged** — asked of Windows, and only when nothing lands;
* **is the account taken** — the kick modal (`tools/lib/game_kick.py`);
* **is the server SHUT** — the maintenance message (`tools/lib/game_maintenance.py`);
* **is this client in a session at all** — the login screen, told from a playing account
  by the game's own clock.

…and then acting on them: the verdict onto `rt.health`, the decisions to `rt.recovery`,
the cure through `rt.play_async`, and one log line per EDGE rather than per poll.

WHAT IS NOT HERE. Pixels. Nothing in this file touches a widget or a Tk variable: the
window draws out of `rt.health` exactly as the phone does, which is what keeps the two
front-ends from wording one reading twice.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import profile_health

from . import game_process
from . import recovery as recoverymod

#: How often the readings are taken. Eight seconds: a process-list scan and a couple of
#: cheap questions, with the expensive ones behind their own throttles below.
POLL_SEC = 8.0

#: How often the client's own message dialog is read — the kick and the maintenance
#: notice, one round trip for both (~90 ms against a warm client).
DIALOG_POLL_SEC = 24.0

#: …and how often «is this client in a session at all» is asked (31–81 ms measured).
SESSION_POLL_SEC = 24.0

#: Consecutive readings before the log is told the server has stopped answering. A
#: client reconnecting looks briefly exactly like one that has given up.
WATCHDOG_STRIKES = 2

#: The scenario the server probe plays, and the one thing it needs: a warzone that is
#: NOT this account's, so the answer has to come over the conversation being doubted.
PROBE_ACTION = "read_server_info"


@dataclass(frozen=True)
class Reading:
    """One poll's answers, for a front-end that wants to draw them."""

    probe: object
    health: object
    kicked: bool = False
    session: str = ""
    maintenance: str = ""
    maintenance_secs: "float | None" = None


class StatusPoll:
    """One profile's readings, on its own clock. Front-end free."""

    def __init__(self, rt) -> None:
        self.rt = rt
        self._busy = False
        self._link_busy = threading.BoundedSemaphore(1)
        self._on = False
        #: Carried between reads, never re-read in the gaps: the recovery counts
        #: CONSECUTIVE readings, and a throttle answering «nothing on screen» in between
        #: would keep resetting the run it feeds.
        self._tip_at = 0.0
        self._kick_was = False
        self._maint_was = ""
        self._maint_secs: "float | None" = None
        self._maint_said = ""
        self._session_at = 0.0
        self._session_was = ""
        self._link_gone = 0

    # -- the clock -----------------------------------------------------------
    def start(self) -> None:
        """Take the readings from now on, every :data:`POLL_SEC`.

        For a panel with no window. The window keeps its own clock — it has to paint
        after every poll — and calls :meth:`read_and_act` from it, so both panels run
        this code and only one of them draws.
        """
        if self._on:
            return
        self._on = True
        self._tick()

    def stop(self) -> None:
        self._on = False
        try:
            self.rt.tick.disarm("status")
        except Exception:                     # noqa: BLE001 — going down, never a fault
            pass

    def _tick(self) -> None:
        if not self._on:
            return
        self.poll_now()
        try:
            self.rt.tick.arm("status", int(POLL_SEC * 1000), self._tick)
        except Exception:                     # noqa: BLE001 — the panel is going down
            self._on = False

    def poll_now(self) -> bool:
        """One cycle on a thread of its own. ``False`` when one is already in flight.

        ONE READING AT A TIME. Everything here is quick while things are well and can
        block for far longer than the poll's period when they are not; without this, an
        unhealthy client quietly grew a thread per poll for as long as it stayed unhealthy.
        """
        if self._busy:
            return False
        self._busy = True

        def work() -> None:
            try:
                self.read_and_act()
            except Exception:                 # noqa: BLE001 — a reading, never the panel
                self.rt.dbg("status").error("status poll failed", exc_info=True)
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True).start()
        return True

    # -- the readings --------------------------------------------------------
    def read_and_act(self) -> Reading:
        """Take every reading, write the verdict, and act on what it means. Blocks."""
        rt = self.rt
        now = time.time()
        try:
            found = game_process.profile_probe(rt.settings)
            lands = rt.game.plumbing()
            server = rt.recovery.server_state(now)
            # …the one reading that tells a WEDGED client from a bug of ours. Asked only
            # when nothing is landing: it enumerates windows.
            responding = True
            if lands == profile_health.NOT_LANDING:
                responding = rt.game.responding()
            # ONE READING OF THE DIALOG, TWO QUESTIONS (#1982): the kick and the
            # maintenance notice are text in the client's one generic message window.
            tip = self._read_dialog(found, lands)
            kicked = self._read_kicked(tip)
            maint, maint_secs = self._read_maintenance(tip)
            session = self._read_session(found, lands)
        except Exception as exc:              # noqa: BLE001 — a reading, never the panel
            # A reading that never came is «no client» with the fault in the tooltip:
            # three colours means three, and there is no colour for «could not look».
            health = rt.health.failed(exc)
            rt.dbg("status").error("status poll failed", exc_info=True)
            return Reading(probe=None, health=health)
        health = rt.health.update(found, plumbing=lands, server=server,
                                  responding=responding, error=rt.game.error(),
                                  maintenance=maint == "closed")
        # THE GATE reads the verdict written one line up, so this costs a dict lookup.
        rt.gate.alive()
        # THE LINK'S OWN SUPERVISOR (#1911): if a chunk is not landing — including the
        # first poll after a client appears, when nothing has ever landed — take hold of
        # the client. Not while the person has switched the profile off.
        if lands != profile_health.LANDING and getattr(found, "running", False) \
                and rt.power.on:
            self.take_link()
        self._announce_link(health)
        self._announce_maintenance(maint, maint_secs)
        self._recovery_check(found, health, kicked, session, now)
        return Reading(probe=found, health=health, kicked=kicked, session=session,
                       maintenance=maint, maintenance_secs=maint_secs)

    def _read_dialog(self, found, lands: str) -> "str | None":
        """The client's own message window, read ONCE for both questions asked of it.

        `''` is «no dialog is open», a string is what it says, and ``None`` is «not this
        time» — either the reading was not due, or it failed. Both callers treat ``None``
        the same way: keep the last verdict, so a reading that fails can only ever ADD a
        reason and never take one away.
        """
        if lands != profile_health.LANDING or not getattr(found, "running", False):
            self._tip_at = 0.0
            self._kick_was = False
            self._maint_was, self._maint_secs = "", None
            return None
        now = time.time()
        if not (self._kick_was or self._maint_was
                or (now - self._tip_at) >= DIALOG_POLL_SEC):
            return None
        self._tip_at = now
        try:
            import game_kick

            return game_kick.tip(self.rt.game.evaluator())
        except Exception:                     # noqa: BLE001 — a reading, never the fault
            return None

    def _read_kicked(self, tip: "str | None") -> bool:
        """Is the client showing the game's own «вход с другого устройства» modal?

        The TEXT decides, compared with the game's own wording in every language it
        ships (`tools/lib/game_kick.py`) — «a dialog is open» is not evidence, because
        the window is generic and the cure for a kick is a restart.
        """
        if tip is None:
            return self._kick_was
        if not tip.strip():
            self._kick_was = False
            return False
        try:
            import game_kick

            said = game_kick.judge(tip)
        except Exception:                     # noqa: BLE001 — a reading, never the fault
            said = None
        # `None` is «no language tables»: with nothing to compare it with, a generic
        # dialog is not evidence of a kick.
        self._kick_was = bool(said)
        return self._kick_was

    def _read_maintenance(self, tip: "str | None") -> tuple:
        """Is the client sitting on a closed server?  ``(state, seconds)`` (#1982)."""
        if tip is None:
            return self._maint_was, self._maint_secs
        try:
            import game_maintenance

            state, secs = (game_maintenance.judge(tip) if tip.strip() else ("", None))
        except Exception:                     # noqa: BLE001 — a reading, never the fault
            state, secs = None, None
        if state is not None:                 # `None` is «cannot judge» — keep the last
            self._maint_was, self._maint_secs = state, secs
        return self._maint_was, self._maint_secs

    def _read_session(self, found, lands: str) -> str:
        """Is this client in a session, or sitting at the login screen? (#1299)

        The one thing a client at the login screen cannot do is say what time it is.
        Asked only of a client we can actually drive, and throttled: everything else is
        already red or amber on readings that cost nothing.
        """
        import game_clock                     # lazy: tools/lib, and only on this path

        if lands != profile_health.LANDING or not getattr(found, "running", False):
            self._session_at, self._session_was = 0.0, ""
            return game_clock.CANNOT_TELL
        now = time.time()
        if (now - self._session_at) < SESSION_POLL_SEC:
            return self._session_was or game_clock.CANNOT_TELL
        try:
            said = game_clock.session_state(self.rt.game.evaluator())
        except Exception:                     # noqa: BLE001 — a reading, never the fault
            said = game_clock.CANNOT_TELL
        self._session_at = now
        if said != game_clock.CANNOT_TELL:    # «не смог спросить» keeps the last answer
            self._session_was = said
        return self._session_was or game_clock.CANNOT_TELL

    # -- what the readings mean ---------------------------------------------
    def _announce_link(self, health) -> None:
        """Say it in the log the moment the game stops answering, and when it returns."""
        rt = self.rt
        if health.colour == profile_health.OK:
            waited = rt.game.link_wait()
            if waited is not None:
                rt.say("game", "log.game.link_ready", secs=f"{waited:.0f}")
        if health.reason != profile_health.NO_TRAFFIC:
            if self._link_gone >= WATCHDOG_STRIKES and health.colour == profile_health.OK:
                rt.say("game", "log.game.link_back")
            self._link_gone = 0
            return
        self._link_gone += 1
        if self._link_gone == WATCHDOG_STRIKES:
            rt.say("game", "log.game.link_lost")

    def _announce_maintenance(self, state: str, secs) -> None:
        """Say the closed door in the log, on its EDGES and nowhere else (#1982)."""
        if state == self._maint_said:
            return
        self._maint_said = state
        if state == "closed":
            self.rt.say("game", "log.game.maintenance")
        elif state == "closing":
            self.rt.say("game", "log.game.maintenance_soon",
                        mins=max(1, -(-int(secs or 0) // 60)))
        elif state == "":
            self.rt.say("game", "log.game.maintenance_over")

    def _recovery_check(self, found, health, kicked: bool, session: str,
                        now: float) -> None:
        """Restart a client the server has stopped hearing — the other half of a crash.

        **THE OTHER AMBER IS NOT FED IN HERE, EVER.** `no_connection` means a chunk does
        not reach the client's VM while the client itself is answering Windows — that is
        OUR wiring, the cure is a fix, and restarting a client over it is six pointless
        relaunches committed on purpose (#1268). `client_hung` is fed in: a wedged
        process is exactly what a restart is for.
        """
        rt = self.rt
        import game_link                      # lazy: tools/lib, and only on this path

        rt.recovery.kick_hold_sec = 60.0 * rt.settings.opt_int("kick_hold_min",
                                                               low=0, high=1440)
        deaf = health.reason in (profile_health.NO_TRAFFIC, profile_health.CLIENT_HUNG)
        idle = game_link.idle_sec()
        self._act_on(rt.recovery.note(deaf, now, idle_sec=idle, kicked=kicked,
                                      running=getattr(found, "running", False),
                                      talking=health.colour == profile_health.OK))
        # …AND THE ACTIVE QUESTION THE WHOLE MODEL RESTS ON (#1911): green is earned,
        # never assumed. Throttled inside the recovery, so at most one round trip every
        # couple of minutes on a healthy profile.
        if getattr(found, "running", False) and health.plumbing == profile_health.LANDING \
                and (rt.recovery.probe_due(now) or rt.recovery.probe_idle_due(now)):
            self._probe_server(now)
        # …AND THE CLOSED DOOR (#1549). Last, because every branch above it is a fault
        # and this one is not: the client is fine and the server is shut.
        import game_clock

        playing = (True if session == game_clock.IN_SESSION
                   else False if session == game_clock.LOGIN_SCREEN else None)
        self._act_on(rt.recovery.note_session(
            playing, health.colour == profile_health.OK, now, idle_sec=idle))

    def _act_on(self, said) -> None:
        """Say what the recovery decided, and do it. One door for every decision.

        ASK THE SETS, never a constant: `ACT_KICK` was added beside `ACT` once and the
        panel went on testing `key == ACT`, so a kicked client was told it was being
        restarted and never was (#1259).
        """
        if said is None:
            return
        rt = self.rt
        key, fmt = said
        if key in recoverymod.SAYINGS:
            # A reading, not a cure — said whatever the watchdog switch is set to:
            # somebody who turned the automatic restart OFF is exactly the person who
            # has to be told their errands are pressing nothing.
            rt.say("game", key, **fmt)
            return
        if not rt.settings.opt_bool("watchdog"):
            return
        # A CURE THAT NEEDS THE PANEL RUNNING (#1393): putting the client back would
        # undo «Стоп всё» on its own, so it asks the same switch the schedule asks — and
        # says nothing, because the gate has already said it once.
        if key in recoverymod.RESTARTS and rt.gate.relaunch_held():
            rt.dbg("status").info("recovery %s held: this profile is switched off", key)
            return
        rt.say("game", key, **fmt)
        if key in recoverymod.RESTARTS:
            # A KICK RESTART STARTS THE STABILITY CLOCK (#1296): the escalating wait is
            # measured from the moment the client was put back, because the question it
            # answers is «did the session hold?».
            if key in recoverymod.KICK_ACTS:
                rt.recovery.note_kick_restart(time.time())
            rt.play_async("restart_game")

    # -- the server probe ----------------------------------------------------
    def _probe_target(self) -> int:
        """A warzone id to ask the server about — the machine's list, never an account's."""
        try:
            import server_list

            known = (server_list.load() or {}).get("servers") or {}
            ids = sorted(int(k) for k in known)
            return ids[0] if ids else 0
        except Exception:                     # noqa: BLE001 — a reading, never the poll
            return 0

    def _probe_server(self, now: float) -> None:
        """Ask the game SERVER something only it can answer, and report the answer."""
        rt = self.rt
        target = self._probe_target()
        if not target:
            rt.say("game", "log.game.probe_impossible")
            return
        rt.recovery.probe_started(now)
        started = rt.play_async(PROBE_ACTION, {"server": target}, tag="game",
                                on_result=self._probe_back)
        if not started:
            # Nothing was played, so nothing is in flight and no deadline is running.
            # Writing the not-asked question down as an answered one is the reading
            # green used to be made of.
            rt.recovery.probe_unstarted(time.time())
            rt.say("game", "log.game.probe_busy")

    def _probe_back(self, outcome) -> None:
        """The probe answered — or the scenario said why it could not."""
        ok = bool(outcome is not None and getattr(outcome, "ok", False))
        self.rt.dbg("status").info("link probe answered=%s", ok)
        self.rt.recovery.note_probe(ok, time.time())

    # -- the link's cure -----------------------------------------------------
    def take_link(self) -> bool:
        """Take hold of the client when nothing is landing — the poll's own cure (#1911).

        ONE AT A TIME: the attach blocks for seconds, and a poll firing mid-attach would
        start a second one. ``False`` means one was already in flight.
        """
        if not self._link_busy.acquire(blocking=False):
            return False

        def work() -> None:
            try:
                self.rt.game.ensure()
            except Exception:                 # noqa: BLE001 — a cure, never the panel
                self.rt.dbg("status").error("attach failed", exc_info=True)
            finally:
                self._link_busy.release()
                self.rt.gate.changed()

        threading.Thread(target=work, daemon=True).start()
        return True

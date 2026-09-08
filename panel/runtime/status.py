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

from . import bus
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

#: Least time between two watchdog relaunches. A client that dies on start-up would
#: otherwise be relaunched every eight seconds forever.
WATCHDOG_COOLDOWN_SEC = 300.0

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
        #: Has «клиент запущен, но в игру не вошёл» been said for the state it is in
        #: now (#2060). An edge, not a tick: the state lasts as long as a maintenance
        #: window does, and one line per poll would bury the log it is meant to explain.
        self._said_not_in_game = False
        #: The last verdict said out loud, so a light that has not moved is a heartbeat
        #: in `debug.log` and a light that HAS is news (:meth:`_note_verdict`).
        self._said_verdict = None
        #: WHETHER THE CLIENT WAS IN THE GAME at the previous poll, so that ENTERING it
        #: can be noticed (#2075). `None` while nothing has been read. The strip along the
        #: top of every screen reads the character once and holds it for ever; a fresh
        #: login is the one fact that can have changed it, and this is where that fact is
        #: seen. It is a transition and never a clock — the poll runs anyway.
        self._was_playing = None
        #: The crash watchdog's own bookkeeping: consecutive dead readings, when the
        #: last one was taken (a strike is a fresh LOOK, not the same cached walk seen
        #: twice — #1702), whether the client was ever up, when it was last put back and
        #: which hold was last said out loud.
        self._game_gone = 0
        self._game_gone_at = 0.0
        self._game_was_up = False
        self._watchdog_last = 0.0
        self._wd_held = ""

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
            # …AND WHEN IT LAST ANSWERED (#2061). Green is a statement about a moment
            # with a five-minute shelf life, and the person asked for the moment to be on
            # screen beside the colour rather than implied by it.
            server_at = rt.recovery.server_answered_at()
            # …the one reading that tells a WEDGED client from a bug of ours. Asked only
            # when nothing is landing: it enumerates windows.
            responding = True
            if lands == profile_health.NOT_LANDING:
                responding = rt.game.responding()
            # ONE READING, THREE QUESTIONS (#1982): the game's own maintenance window,
            # the kick modal's text and the message dialog's text all come out of a
            # single round trip (`tools/lib/game_maintenance.look`).
            seen = self._look(found, lands)
            kicked = self._read_kicked(seen)
            maint, maint_secs = self._read_maintenance(seen)
            session = self._read_session(found, lands)
        except Exception as exc:              # noqa: BLE001 — a reading, never the panel
            # A reading that never came is «no client» with the fault in the tooltip:
            # three colours means three, and there is no colour for «could not look».
            health = rt.health.failed(exc)
            rt.dbg("status").error("status poll failed", exc_info=True)
            # AND SAID ONCE, in the person's own log. «A reading that never came is no
            # client with the fault in the tooltip» (#1911) is the rule — but a tooltip
            # is only true while somebody is hovering over it, and this is the one way
            # the light can say «клиент игры не запущен» over a client that is running.
            if self._said_verdict != ("failed", str(exc)[:80]):
                self._said_verdict = ("failed", str(exc)[:80])
                rt.say("game", "log.game.read_failed", error=str(exc)[:200])
            return Reading(probe=None, health=health)
        # …AND WHETHER THE CLIENT IS IN THE GAME, in the light itself (#2060). A person
        # looking at «нет связи» cannot tell our own broken plumbing from a client that
        # is up, driveable and sitting at the login screen — opposite faults with
        # opposite acts. Three-valued on purpose: only the client's OWN evidence counts.
        import game_clock

        playing = (True if session == game_clock.IN_SESSION
                   else False if session == game_clock.LOGIN_SCREEN else None)
        # …AND THE MOMENT IT ENTERS THE GAME IS NEWS FOR THE HEADER (#2075). Somebody has
        # just logged in — possibly as somebody else — so the name, the level and the face
        # are worth asking for again. The strip takes no reading on a clock, so this
        # transition is the door: it fires on false/unknown -> true and on nothing else,
        # and the reading itself still waits for a free link.
        if playing and self._was_playing is not True:
            try:
                rt.header.mark_stale(place=True, who=True)
            except Exception:                 # noqa: BLE001 — a hint, never the poll
                pass
        # …and the same edge is what every push-driven board reads on, but it may not
        # be told here — the gate below is still holding the light this poll is about to
        # write, so a subscriber that plays a scenario is refused «нет связи с игрой»
        # and never asked again. It is published after the verdict instead (#2633).
        entered = bool(playing and self._was_playing is not True)
        self._was_playing = playing
        # …AND WHETHER THE ACCOUNT HAS BEEN TAKEN (#2061). The kick was read on every
        # poll already — the recovery acts on it — and the LIGHT was never told, so a
        # client whose last server probe answered before the kick showed green while
        # nothing was arriving at all. It outranks green rather than narrowing amber:
        # see `tools/lib/profile_health.verdict`.
        health = rt.health.update(found, plumbing=lands, server=server,
                                  responding=responding, error=rt.game.error(),
                                  maintenance=maint == "closed", in_game=playing,
                                  kicked=kicked, server_at=server_at)
        # THE GATE reads the verdict written one line up, so this costs a dict lookup.
        rt.gate.alive()
        # …AND *NOW* THE CLIENT IS «READY», which is the moment every push-driven board
        # takes its first reading (#2633). The person's rule: «все данные должны
        # подтягиваться при старте клиента, а их изменение проводиться по пушам» — so a
        # statistic is read once, here, and moved by the wire after that.
        #
        # AFTER the verdict and the gate, deliberately, and the first cut of this had it
        # BEFORE: the light was still the boot's red, so every subscriber's play was
        # refused with «нет связи с игрой — ничего автоматического не стартует» and the
        # edge does not come round again. The fact is «клиент в игре И панель это уже
        # знает», and nothing below this line may be reordered above it.
        #
        # Nothing is read ON this thread: a subscriber hangs its play on a worker like
        # any other press.
        if entered:
            try:
                rt.bus.publish(bus.GAME_READY)
            except Exception:                 # noqa: BLE001 — a fact, never the poll
                pass
        # …AND THE VERDICT IS WRITTEN DOWN (#1982 follow-up). The window has printed a
        # `systems:` line off every poll for a year, and a panel with no window printed
        # nothing at all — so «панель показывала, что клиента нет» could not be dated,
        # confirmed or denied afterwards, which is exactly the question that came back.
        # On CHANGE it is news, otherwise it is a debug heartbeat; both carry the pid,
        # the probe's own sentence and which Windows session this panel is looking in,
        # because «no client» has several different causes and they want opposite acts.
        self._note_verdict(health, found)
        # THE LINK'S OWN SUPERVISOR (#1911): if a chunk is not landing — including the
        # first poll after a client appears, when nothing has ever landed — take hold of
        # the client. Not while the person has switched the profile off.
        if lands != profile_health.LANDING and getattr(found, "running", False) \
                and rt.power.on:
            self.take_link()
        self._announce_link(health)
        self._announce_maintenance(maint, maint_secs, seen)
        self._recovery_check(found, health, kicked, playing, now)
        # …AND THE OTHER HALF OF A CRASH: the PROCESS going away, which the recovery
        # above deliberately never treats as a fault of the link (#1984 moved this out
        # of the window with everything else — a panel nobody is looking at has to put
        # its client back too).
        self._watchdog_check(bool(getattr(found, "running", False)))
        return Reading(probe=found, health=health, kicked=kicked, session=session,
                       maintenance=maint, maintenance_secs=maint_secs)

    def _note_verdict(self, health, found) -> None:
        """One line per verdict CHANGE, and a debug heartbeat the rest of the time.

        WHAT IT HAS TO ANSWER, because this is the line somebody reads a day later: what
        the light said, which reading decided it, whether a client process was found and
        WHERE this panel was looking. The last one matters since the service started
        launching the panel (#1976): a panel in the wrong Windows session sees no client
        at all and says exactly what a closed game says.
        """
        rt = self.rt
        try:
            import game_link

            here = game_link.own_session()
        except Exception:                     # noqa: BLE001 — a reading, never a line
            here = None
        said = ("systems: light=%s (%s) client=%s pid=%s lands=%s server=%s session=%s"
                % (health.colour, health.reason,
                   bool(getattr(found, "running", False)), getattr(found, "pid", None),
                   health.plumbing, health.server,
                   "?" if here is None else here))
        snap = (health.colour, health.reason, bool(getattr(found, "running", False)),
                health.plumbing, health.server)
        log = rt.dbg("status")
        if snap != self._said_verdict:
            self._said_verdict = snap
            log.info(said)
        else:
            log.debug(said)

    def _look(self, found, lands: str) -> "dict | None":
        """What the client says about its own windows, read ONCE for every question.

        A dict is an answer (`tools/lib/game_maintenance.look`): the game's own
        maintenance window by name, the message dialog's text, and where the client is
        sitting. ``None`` is «not this time» — either the reading was not due, or it
        failed — and every caller treats that the same way: keep the last verdict, so a
        reading that fails can only ever ADD a reason and never take one away.
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
            import game_maintenance

            return game_maintenance.look(self.rt.game.evaluator())
        except Exception:                     # noqa: BLE001 — a reading, never the fault
            return None

    def _read_kicked(self, seen: "dict | None") -> bool:
        """Is the client showing the game's own «вход с другого устройства» modal?

        The TEXT decides, compared with the game's own wording in every language it
        ships (`tools/lib/game_kick.py`) — «a dialog is open» is not evidence, because
        the window is generic and the cure for a kick is a restart.
        """
        if seen is None:
            return self._kick_was
        tip = seen.get("tip") or ""
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

    def _read_maintenance(self, seen: "dict | None") -> tuple:
        """Is the client sitting on a closed server?  ``(state, seconds)`` (#1982).

        TWO RUNGS, strongest first: the game's OWN window for the state, which is the
        same in every language and needs no tables at all, and below it the message
        dialog's text against the game's own wording.
        """
        if seen is None:
            return self._maint_was, self._maint_secs
        tip = seen.get("tip") or ""
        try:
            import game_maintenance

            if seen.get("window"):
                state, secs = game_maintenance.CLOSED, None
            else:
                state, secs = (game_maintenance.judge(tip) if tip.strip()
                               else ("", None))
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
        """Say it in the log the moment the game stops answering, and when it returns.

        …and NAME the one amber a person cannot read off «нет связи» (#2060): a client
        that is up and driveable and has not got into the game. Said on its edge, like
        the closed door below it, because it is a state and not an event.
        """
        rt = self.rt
        if health.reason == profile_health.NOT_IN_GAME:
            if self._said_not_in_game is not True:
                self._said_not_in_game = True
                rt.say("game", "log.game.not_in_game")
        else:
            self._said_not_in_game = False
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

    def _announce_maintenance(self, state: str, secs, seen=None) -> None:
        """Say the closed door in the log, on its EDGES and nowhere else (#1982).

        …and WRITE THE READING DOWN the first time it fires. The detector was built with
        no live sample — the one window that has been watched was watched from outside
        the client (#1549) and the next was missed by twenty minutes — so the first real
        maintenance has to leave something behind that settles it: which rung answered,
        what the dialog said, which windows were open. It goes to the profile's own
        directory, which is git-ignored, and never into the repository.
        """
        if state == self._maint_said:
            return
        self._maint_said = state
        if state == "closed":
            self.rt.say("game", "log.game.maintenance")
            # …AND THE ONE LENGTH THE GAME EVER NAMES: «(Estimated time: 10-30 minutes)»
            # on the season close. Said as the game says it — a range, and its own.
            try:
                import game_maintenance

                span = game_maintenance.estimate((seen or {}).get("tip") or "")
            except Exception:                 # noqa: BLE001 — a reading, never a line
                span = None
            if span:
                self.rt.say("game", "log.game.maintenance_estimate",
                            low=int(span[0] // 60), high=int(span[1] // 60))
        elif state == "closing":
            self.rt.say("game", "log.game.maintenance_soon",
                        mins=max(1, -(-int(secs or 0) // 60)))
        elif state == "":
            self.rt.say("game", "log.game.maintenance_over")
        if state in ("closed", "closing"):
            self._record(state, secs, seen)

    def _record(self, state: str, secs, seen) -> None:
        """Keep the raw reading of a real maintenance, for whoever reads it next.

        A GIT-IGNORED sample in this profile's own directory: everything the client
        answered, verbatim, plus what the light said at the time. It exists because
        every word of this detector was inferred from the game's own tables rather than
        from a recording — one real file ends the guessing.
        """
        rt = self.rt
        try:
            import json
            import os

            folder = os.path.join(rt.profiles.dir(), "maintenance")
            os.makedirs(folder, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            body = {"at": stamp, "state": state, "seconds": secs,
                    "reading": seen or {},
                    "light": {"colour": rt.health.colour,
                              "reason": rt.health.current.reason,
                              "plumbing": rt.health.current.plumbing,
                              "server": rt.health.current.server},
                    "session": self._session_was}
            path = os.path.join(folder, f"{stamp}-{state}.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(body, handle, ensure_ascii=False, indent=2)
            rt.dbg("status").info("maintenance sample written: %s", path)
        except Exception:                     # noqa: BLE001 — a record, never the panel
            rt.dbg("status").error("maintenance sample failed", exc_info=True)

    def _recovery_check(self, found, health, kicked: bool, playing: "bool | None",
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
        # …AND WHETHER THE CONFIRMATION CAN EVEN BE ASKED FOR (#2446). The probe below
        # is a scenario that runs INSIDE the client's Lua VM and is only sent while the
        # plumbing is `LANDING` — so on a client nothing reaches, no probe is ever sent,
        # none ever fails, and the recovery waits on «0 из 2» for ever. It happens in two
        # shapes and the live one was the second: `NOT_LANDING` (the main thread never
        # reaches its park) and `PLUMBING_UNASKED` (never attached, so nothing has ever
        # come back and there is no age to judge — which falls through `verdict` to
        # `NO_TRAFFIC` and reads as an ordinary deaf client). From 00:41 to past 06:43 on
        # 2026-09-05 that was six hours with the schedule held and no restart.
        unprobeable = health.plumbing != profile_health.LANDING
        idle = game_link.idle_sec()
        self._act_on(rt.recovery.note(deaf, now, idle_sec=idle, kicked=kicked,
                                      running=getattr(found, "running", False),
                                      unprobeable=unprobeable,
                                      talking=health.colour == profile_health.OK))
        # …AND THE ACTIVE QUESTION THE WHOLE MODEL RESTS ON (#1911): green is earned,
        # never assumed. Throttled inside the recovery, so at most one round trip every
        # couple of minutes on a healthy profile.
        if getattr(found, "running", False) and health.plumbing == profile_health.LANDING \
                and (rt.recovery.probe_due(now) or rt.recovery.probe_idle_due(now)):
            self._probe_server(now)
        # …AND THE CLOSED DOOR (#1549). Last, because every branch above it is a fault
        # and this one is not: the client is fine and the server is shut.
        #
        # It is told WHO ELSE OWNS THE FAULT (#2060): the watchdog when there is no
        # process, and US when nothing lands in the VM — `CLIENT_HUNG` / `NO_CONNECTION`,
        # the states #1268 forbids restarting a client over. Passing «is the server
        # answering» instead left the one state neither branch owned — a client up,
        # driveable and outside the game — cured by nobody for 6.9 hours.
        self._act_on(rt.recovery.note_session(
            playing, health.colour == profile_health.OK, now, idle_sec=idle,
            running=getattr(found, "running", False),
            wiring_bad=health.plumbing == profile_health.NOT_LANDING))

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

    def _watchdog_check(self, running: bool) -> None:
        """Notice the client dying, and put it back if asked to.

        Runs off every status poll, in whichever panel is taking the readings — the
        window used to own this, and a panel with no window then watched nothing at all
        (#1984). Two things make it safe to leave on overnight:

          * WATCHDOG_STRIKES consecutive dead readings, not one. A single scan can
            race the process table, and the client legitimately restarts itself once
            after the first login — relaunching *that* would fight the game.
          * a cooldown between relaunches. A client that dies during start-up would
            otherwise be relaunched every eight seconds until morning.

        A crash is announced whether or not the watchdog is on: knowing the client
        went away is worth a log line even when putting it back is the person's job.
        """
        rt = self.rt
        if running:
            if self._game_gone >= WATCHDOG_STRIKES:
                rt.say("game", "log.game.back")
            self._game_gone = 0
            self._game_gone_at = 0.0
            self._game_was_up = True
            self._wd_held = ""
            return
        # A STRIKE IS A FRESH LOOK, NOT THE SAME WALK SEEN TWICE (#1702).
        #
        # `WATCHDOG_STRIKES` exists because «a single scan can race the process table».
        # It did not deliver that: the process walk is shared and cached for two seconds
        # (`game_link.MACHINE_TTL_SEC`), and the status poll can fire twice inside one
        # window — live on 2026-08-21, two snapshots 109 ms apart, both `game=down`,
        # with the daemon answering `warm` in the same breath. Both strikes came from
        # ONE scan, and the panel relaunched a client that had never stopped running.
        #
        # So strikes are spaced: a second dead reading counts only once the poll has
        # genuinely come round again. Three quarters of the interval, because the poll
        # jitters and an exact comparison would drop the strike that is due.
        now = time.monotonic()
        if self._game_gone and (now - self._game_gone_at) < POLL_SEC * 0.75:
            rt.dbg("status").debug("watchdog: dead reading %.2fs after the last — not a strike",
                            now - self._game_gone_at)
            return
        self._game_gone_at = now
        self._game_gone += 1
        if self._game_gone < WATCHDOG_STRIKES:
            return                        # still counting
        if self._game_gone == WATCHDOG_STRIKES and self._game_was_up:
            rt.say("game", "log.game.gone")
        if not rt.settings.opt_bool("watchdog"):
            return
        # …AND NOT WHILE THE PANEL IS STOPPED (#1393). The client going away is exactly
        # what «Стоп всё» has just arranged, and a watchdog that has never heard of the
        # press is how the client used to be back eight seconds after it. The crash is
        # still ANNOUNCED above — knowing the client went is worth a line whatever is
        # allowed to act on it — and only the relaunch is held.
        # THE SWITCH, NOT THE DAEMON (#1910) — see the same change beside the recovery's
        # verdict. «Профиль выключен» still stops the watchdog dead, which is what #1393
        # needed; «демон не отвечает» must not, because the client this is about to put
        # back is what the daemon has been failing to attach to.
        if rt.gate.relaunch_held():
            rt.dbg("status").info("watchdog held: this profile is switched off")
            return
        # SAID ONCE, ASKED EVERY POLL — and the two used to be the same `return`. This
        # method acted on the EXACT strike (`!= WATCHDOG_STRIKES`), so a client that
        # was still gone on the next poll was never looked at again: the watchdog had
        # one attempt per death, and any hold below spent it. The cooldown branch could
        # therefore never fire inside an episode, which is why «перезапуск был N мин
        # назад — жду» promised a retry that did not exist.
        #
        # Live on 2026-08-08 that cost half an hour: the kick's wait was armed at
        # 07:55:06, the process went away at 08:07:42 (the wait said «жду 3 мин» and
        # returned, spending the attempt), the wait ran out at 08:10:06 — and nothing
        # put the client back until a person pressed «Запустить» at 08:38:25. A hold
        # must suppress the act while it lasts and NOTHING after it (#1291), exactly as
        # `Recovery.note` was taught for the restart cooldown.
        #
        # A CLIENT THAT WAS KICKED IS NOT A CLIENT THAT CRASHED (#1291). The account is
        # on another device; the process going away here is what happens when the person
        # holding it closes this one, or when the kicked client finally gives up. Putting
        # it back inside the wait undoes the wait completely — the whole point of which
        # is that this machine stops taking the account off whoever is playing it.
        left = rt.recovery.kick_hold_left(time.time())
        if left > 0:
            if self._wd_held != "kick":
                self._wd_held = "kick"
                rt.say("game", "log.game.kick_hold", mins=-(-left // 60))
            return
        # A client of another session is put back too, and by the same recipe: it
        # starts the launcher inside the session the profile names (#1218). It used to
        # be refused here, because what the recipe did then was spawn a process on THIS
        # desktop — a third client nobody asked for, while the account that had died
        # stayed dead all night, which is the one case an overnight watchdog exists for.
        since = time.time() - self._watchdog_last
        if self._watchdog_last and since < WATCHDOG_COOLDOWN_SEC:
            if self._wd_held != "cooldown":
                self._wd_held = "cooldown"
                rt.say("game", "log.game.watchdog_hold", mins=int(since // 60))
            return
        # …and the latch is NOT cleared here. An attempt that fails puts the cooldown
        # straight back, and re-announcing it after every retry says «жду» twice per
        # five minutes for as long as the client stays down — a night of it for a
        # profile whose Windows session is simply not up. The client coming back is
        # what clears it, which is the only event that makes the sentence new again.
        self._watchdog_last = time.time()
        rt.say("game", "log.game.watchdog_relaunch")
        rt.play_async("launch_game")

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

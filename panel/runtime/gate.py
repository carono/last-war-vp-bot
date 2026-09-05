"""Is this profile's daemon alive? — THE one gate on every timer and every trigger.

**Nothing automatic happens while this profile's daemon is down.** Not a scenario, not a
read into the game, not a relaunch of the client, not a retry, and not a line in the log
every few seconds saying that none of it worked. The schedule waits, quietly, until the
daemon is back — and then goes on exactly as it was.

WHY IT IS ONE OBJECT AND NOT A CHECK PER CALLER. Because the check drifts. «Стоп всё»
now ends two things and only two — the client and this profile's daemon (#1393) — and
everything that would otherwise notice a client missing was, until now, free to put it
back: the schedule's `restart_game`, the process watchdog, the recovery's verdict. Three
detectors, three ideas of «may I», and the emergency button undone within eight seconds
of being pressed. So they all ask ONE object, per profile, and a fourth detector added
tomorrow asks the same one.

WHAT IT COSTS, AND WHY IT IS HONEST. Nothing, on almost every call. The window's status
poll already probes this profile's daemon every eight seconds and leaves the verdict on
`rt.health` (`panel/runtime/health.py`) — a socket probe plus, when it matters, the pid
comparison. This reads THAT, so a timer tick and a trigger poll pay a dict lookup rather
than a round trip. Two things keep it from being a stale belief instead of a fact:

* a reading older than :data:`FRESH_SEC` is not used at all — a runtime with no window
  behind it (a tab launched on its own) has nobody polling, and «nobody has looked» may
  never read as «alive»;
* :meth:`LinkGate.changed` throws away everything known so far. Whoever starts or
  stops a daemon says so, and the next question is answered by asking the port rather
  than by quoting a reading taken before the thing happened. Without it «Стоп всё» would
  leave up to eight seconds in which an errand still believed the daemon was warm — and
  an errand that believes that calls `ensure()`, which would start the daemon the press
  had just stopped.

WHAT IT DOES NOT GATE. A person's own press, and putting the CLIENT back. A button in the window or on the phone that
starts the client, brings the daemon up or plays a scenario is somebody standing there
asking for it, and this is not the object that says no to a human being. It gates what
runs BY ITSELF.

And it does not gate the CURE on the illness (#1910). Restarting the daemon was already
below this gate — a stale daemon holds the gate that holds its own cure — and putting the
CLIENT back turned out to be the same shape: a daemon with no client to attach to is not
alive, so gating `launch_game` / `restart_game` on «is the daemon alive» is a closed loop.
Live on 2026-08-24 a profile sat in it all afternoon: no client, seventeen daemon
restarts, ZERO client restarts. The SWITCH still holds them — see
:meth:`LinkGate.relaunch_held` and :data:`RELAUNCH_ACTIONS` — which is the half of
#1393 that was doing the work, and the half «Стоп всё» needs.

PER PROFILE, LIKE EVERYTHING ELSE THAT IS AN ACCOUNT'S (`CLAUDE.md`). One of these lives
on each :class:`~panel.runtime.host.PanelRuntime`; there is no module-level state here at
all, because two open profiles have two daemons on two ports and one of them being down
says nothing whatever about the other.
"""
from __future__ import annotations

import threading
import time

import profile_health


#: How old the status poll's verdict may be before this stops believing it. The poll runs
#: every eight seconds (`panel/__main__.py::STATUS_POLL_MS`), so this is three of its
#: turns: long enough that an unlucky poll does not send every gate question to the
#: socket, short enough that a poll which has died is noticed rather than quoted for ever.
FRESH_SEC = 30.0

#: The scenarios that PUT THE CLIENT BACK, and the one family the daemon half of this
#: gate may not hold (#1910). A daemon with no client to attach to is not alive, and the
#: thing that gives it one is exactly these — so gating them on «is the daemon alive» is
#: a cure locked behind the illness. Live on 2026-08-24 that is precisely where `default`
#: sat: no client, seventeen daemon restarts, ZERO client restarts, and a watchdog held
#: at every poll by the gate the missing client had shut. The SWITCH still holds them —
#: «профиль выключен» has to mean the account is not playing — which is the half #1393
#: actually needed and the half that keeps «Стоп всё» honest.
#:
#: `panel/runtime/host.py` imports this as `RELAUNCHES`: it is one list, in one place,
#: because the relaunch lock and this gate must never disagree about what a relaunch is.
RELAUNCH_ACTIONS = frozenset({"launch_game", "restart_game", "recover_from_kick"})

#: EVERYTHING THAT MAY RUN WHILE THE LIGHT IS NOT GREEN, and nothing else (#2446).
#:
#: The person's rule, in their own words: «никакие сценарии, таймеры, триггеры, ничего не
#: должно работать, если статус не зелёный, исключение сценарии перезапуска». So this is
#: the whole of the exception list, in one frozenset, because an exception that lives in
#: three `if`s is an exception nobody can audit.
#:
#: It is :data:`RELAUNCH_ACTIONS` plus the SERVER PROBE, and the probe is not a courtesy:
#: green is «the server answered», the answer comes from `read_server_info`, and that
#: scenario goes through the same door as every other one. Leave it out and the gate is a
#: trap with no handle on the inside — the light can never go green again because the one
#: question that could turn it green is refused for the light not being green.
RECOVERY_ACTIONS = RELAUNCH_ACTIONS | {"read_server_info"}

#: …AND THE ONE THING THAT PASSES EVEN A SWITCHED-OFF PROFILE: closing the client.
#:
#: It is not a recovery, it is the opposite — but «Стоп всё» IS the switch being flipped
#: off (`panel/runtime/panic.py`), and a gate that held the press would leave the client
#: running for ever in a profile somebody had just switched off: the gate holding its own
#: cure. Separate from :data:`RECOVERY_ACTIONS` because the two are checked on opposite
#: sides of the switch — putting a client BACK must stay held by «профиль выключен»
#: (#1393), and taking it away must not.
LIFECYCLE_ACTIONS = frozenset({"quit_game"})


class LinkGate:
    """One profile's «may anything run right now», and the two lines that say it changed."""

    __slots__ = ("rt", "_lock", "_open", "_since", "_changed_at")

    def __init__(self, rt) -> None:
        self.rt = rt
        # Written from the timer thread, the trigger poll thread and the status poll;
        # read from both front-ends' paint. Cheap enough to hold for the whole of a read.
        self._lock = threading.Lock()
        #: The last answer given, or ``None`` while nothing has asked yet.
        self._open: "bool | None" = None
        #: …and since when it has been that answer — what the mark on screen counts.
        self._since = 0.0
        #: When somebody last told us the daemon's existence changed (:meth:`changed`).
        #: Readings taken before this moment are not evidence about the world after it.
        self._changed_at = 0.0

    # -- the question --------------------------------------------------------
    def alive(self) -> bool:
        """Does a chunk reach this profile's client right now? (#1911)

        The one question. ``True`` lets the automatic side of the panel do what it was
        going to do; ``False`` means it does nothing at all and says nothing about it —
        the edge is announced here, once, rather than by every caller in its own words.
        """
        answer = self._read()
        self._note(answer)
        return answer

    def held(self) -> bool:
        """The same reading, the other way round — for a drawer that asks «is it stuck»."""
        return not self.alive()

    def reason(self) -> "str | None":
        """The locale key naming why nothing may run, or ``None`` while it may.

        What a skip line puts inside its sentence (`panel/timers.py::note_skip`).
        """
        if self.alive():
            return None
        if self._switched_off():
            return "timers.log.skip_off"
        if self._maintenance():
            return "timers.log.skip_maintenance"
        # …AND «ПОДЦЕПЛЕНЫ, НО СЕРВЕР МОЛЧИТ» IS ITS OWN SENTENCE (#2446). «Нет связи с
        # игрой» would send somebody looking at the client, which is running perfectly.
        return ("timers.log.skip_silent" if self._landing()
                else "timers.log.skip_link")

    def _landing(self) -> bool:
        """Do chunks reach the client? Read off the light, never taken here."""
        health = getattr(self.rt, "health", None)
        try:
            return getattr(health.current, "plumbing", "") == profile_health.LANDING
        except Exception:                     # noqa: BLE001 — a reading, never the gate
            return False

    def blocks(self, name: str = "", *, human: bool = False) -> str:
        """May this SCENARIO be played right now? ``""`` when it may.

        The other face of :meth:`alive`, and the one every RUN asks — because a gate that
        only the schedule and the watchdog consulted was a gate with three doors round the
        side (#1910). A tab polling its board, a wire handler joining a rally straight off
        the capture's reader, an auto-order re-armed on the panel's own clock: none of
        them is a timer, none of them is a trigger, and every one of them was pressing
        into a client that was not there — «пытаются выполниться сценарии, а демона нет»,
        with nothing in the log naming a hold because no hold was being asked for.

        So the question is asked at the ONE door every scenario goes through
        (`panel/runtime/actions.py::ActionRunner.run`), and the answer is a LOCALE KEY
        rather than a bool: a run that does not happen has to say so in the person's own
        words, and silent suppression is its own class of bug in this codebase (#1884).

        ``human`` USED TO BE A BLANKET EXEMPTION and is not one any more (#2446). The
        person's rule names manual runs explicitly — «ни таймеры, ни триггеры, ни ручные
        прогоны» — and the reason is the same for a button as for a clock: a press into a
        client the server is not hearing does nothing, takes the game claim while it does
        it, and delays the restart that would fix the thing the person was pressing about.
        What a press still gets is the RECOVERY family below, which is everything anybody
        could usefully press in that state, plus the profile's own switch, which is not a
        scenario at all.
        """
        if name in LIFECYCLE_ACTIONS:
            # Ahead of the switch on purpose — see :data:`LIFECYCLE_ACTIONS`.
            return ""
        if self.alive():
            return ""
        if self._switched_off():
            return "action.held.off"
        if name in RECOVERY_ACTIONS:
            # THE CURE IS NOT HELD BY THE ILLNESS (:data:`RECOVERY_ACTIONS`). Putting the
            # client back is what makes the link live again, and asking the server whether
            # it is there is what turns the light green — neither can wait for the state
            # it is there to end.
            return ""
        if human:
            # A PERSON IS OWED A DIFFERENT SENTENCE. They are standing at the button and
            # deserve to be told the press was refused and why, rather than reading a line
            # written for a timer that nobody is watching.
            return "action.held.human"
        return "action.held.link"

    def relaunch_held(self) -> bool:
        """Is putting the CLIENT back held right now? Only the switch may hold it (#1910).

        Asked by the detectors that would relaunch — the process watchdog and the
        recovery's verdict — instead of :meth:`alive`, which they used to ask and which
        answers «no» for the very reason they are about to cure. The switch still stops
        them dead: that is what «Стоп всё» и «профиль выключен» have to mean, and it is
        the half of #1393 that was doing the work all along.
        """
        return self._switched_off()

    def _read(self) -> bool:
        """The reading itself: the switch first, then the poll's verdict, then the link.

        **GREEN, AND ONLY GREEN (#2446).** One definition, in one place, so that it
        cannot drift: green is `profile_health.OK` — the panel drives the client AND the
        game server answered. Amber in every one of its shapes (a kick, a deaf client,
        a silent server, a wedged VM, maintenance) and red both hold this shut.

        THIS REVERSES WHAT WAS WRITTEN HERE, and the reversal is the person's, in their
        words: «никакие сценарии, таймеры, триггеры, ничего не должно работать, если
        статус не зелёный, исключение сценарии перезапуска». What stood here said the
        opposite — that a silent server must NOT hold the gate, because #1910 lost hours
        of banners to a socket reading that was simply wrong, and that «what runs against
        a deaf client fails visibly, which is the honest outcome».

        It is not honest, and the night of 2026-09-05 is the measurement. For 375 minutes
        the server answered nothing and the panel went on starting errands into it: the
        log filled with runs that looked like work, every one of them took the game claim
        for its duration, and the recovery — which needs that same claim to put the
        client back — queued behind them. A run that cannot possibly succeed is not
        evidence, it is noise plus an obstacle.

        #1910's reason expired with the reading it was about: the gate then rested on the
        SOCKET TABLE, which could say `lost` for hours while the server answered every
        probe. It rests on the probe's own answer now, so the failure mode it was written
        against cannot happen — a server that answers IS green.
        """
        # THE SWITCH BEFORE ANYTHING ELSE (#1882). «Профиль работает» is what a person
        # decided; a link that happens to be warm is only what a machine is doing.
        if self._switched_off():
            return False
        health = getattr(self.rt, "health", None)
        read_at = float(getattr(health, "read_at", 0.0) or 0.0) if health is not None else 0.0
        # STRICTLY newer than the change, because the wall clock is not fine-grained:
        # Windows ticks it every ~16 ms, so a poll and a `changed()` in the same instant
        # carry the same stamp — and «the same instant» has to fall on the side of
        # distrusting the reading.
        if read_at > self._changed_at and (time.time() - read_at) <= FRESH_SEC:
            # THE CLOSED DOOR HOLDS IT, AND IT IS THE ONE AMBER THAT DOES (#1982). The
            # server being SHUT is not the client being deaf: chunks land, the panel
            # drives the client perfectly, and every errand it starts is refused by a
            # server that is not there — twenty identical failures, retry holds spent,
            # and a daily quota's attempts written off against a door. So while the
            # client is showing the game's OWN maintenance message
            # (`tools/lib/game_maintenance.py`) nothing automatic starts, the reason is
            # said once, and it lifts by itself when the message goes. The operator's
            # decision, asked for and given in those words: «держать очередь и сказать
            # один раз».
            if getattr(health.current, "reason", "") == profile_health.MAINTENANCE:
                return False
            # THE ONE PLACE «GREEN» IS DEFINED for everything that runs by itself. It is
            # `verdict`'s own colour, never a re-derivation of it here: a second opinion
            # about the light is a second light.
            return bool(getattr(health.current, "ok", False))
        # Nobody is polling this runtime (a tab launched on its own), the poll has died,
        # or something has just re-attached and the last verdict predates it. Ask the
        # link — an object in this process, so the answer costs nothing.
        #
        # IT IS HALF AN ANSWER AND IT IS THE SAFE HALF (#2446). `ready()` is «does a chunk
        # land», which is a necessary condition for green and not a sufficient one: it
        # cannot tell whether the SERVER is answering, because that costs a round trip and
        # a gate asked in front of every errand may never be the thing that spends one. So
        # a stale-verdict runtime is held unless the link itself is landing AND the
        # recovery has an answer from the server inside its shelf life — the same fact the
        # light is made of, read rather than re-taken.
        try:
            if not bool(self.rt.game.ready()):
                return False
            rec = getattr(self.rt, "recovery", None)
            if rec is None:
                return True                  # a runtime with no recovery has no light
            return bool(rec.link_confirmed(time.time()))
        except Exception:                     # noqa: BLE001 — a reading, never the panel
            return False

    def _maintenance(self) -> bool:
        """Is the last verdict «the server is under maintenance»? (#1982)

        Read off the light rather than taken here: the reading is one round trip into
        the client, made by the status poll that was making it anyway
        (`panel/runtime/status.py`), and a gate asked in front of every errand may never
        be the thing that spends one.
        """
        health = getattr(self.rt, "health", None)
        try:
            return getattr(health.current, "reason", "") == profile_health.MAINTENANCE
        except Exception:                     # noqa: BLE001 — a reading, never the gate
            return False

    def _switched_off(self) -> bool:
        """Is this profile's own switch off? A runtime built without one is never off."""
        power = getattr(self.rt, "power", None)
        if power is None:
            return False
        try:
            return bool(power.off)
        except Exception:                     # noqa: BLE001 — a reading, never the gate
            return False

    def changed(self) -> None:
        """This profile's link was just re-made or let go — distrust what is known.

        Called by whoever did it. Two effects, and both matter: the port's cached answer
        is dropped, and every verdict the status poll has already made is ruled out of
        date — so the next question is decided by asking rather than by quoting a reading
        from before the act. See the module docstring.
        """
        with self._lock:
            self._changed_at = time.time()
        try:
            self.rt.game.forget_up()
        except Exception:                     # noqa: BLE001 — housekeeping, never the act
            pass

    # -- saying it, once ------------------------------------------------------
    def _note(self, answer: bool) -> None:
        """Say the EDGE, in the person's log, and never the state.

        «Ничего не запускается, потому что демон остановлен» is a thing somebody has to
        be told — the whole of #1262 is that a panel holding still looks exactly like a
        panel with nothing to do. Saying it per tick is the other failure, and the one
        this task exists to remove, so it is said when it becomes true and again when it
        stops being true. The mark on screen (:meth:`state`) is what carries it in
        between, because a line scrolls away and a mark does not.
        """
        with self._lock:
            was, self._open = self._open, answer
            if was is answer:
                return
            self._since = time.time()
            first = was is None
        if answer:
            if not first:                     # an ordinary start-up is not news
                self._say("gate.log.free")
            return
        # TWO WAYS TO ARRIVE HERE, and they are not the same sentence: somebody switched
        # this profile off, or its daemon went away on its own. A person reading «демон
        # не работает» after ticking a box would go looking for a fault that is not
        # there (#1882).
        if self._switched_off():
            self._say("gate.log.off")
        else:
            # …AND THE THIRD WAY (#1982): the server is shut. «Нет связи с игрой» would
            # send somebody looking for a fault in a panel that is working perfectly.
            if self._maintenance():
                self._say("gate.log.maintenance")
            else:
                self._say("gate.log.silent" if self._landing() else "gate.log.held")

    def _say(self, key: str) -> None:
        try:
            self.rt.say("panel", key)
        except Exception:                     # noqa: BLE001 — a line, never the gate
            pass

    # -- what both front-ends draw -------------------------------------------
    def state(self, now: "float | None" = None) -> dict:
        """The mark: whether everything is held, and for how long. Numbers, never words.

        Read from the window's paint and from the phone's `/api/state`, out of ONE object
        — the same arrangement as the panic mark and the profile's light beside it. It
        reports what was last ANSWERED rather than taking a reading of its own: a drawer
        must never be the thing that probes a socket (`panel/runtime/health.py` says the
        same about the same kind of state).
        """
        now = time.time() if now is None else now
        with self._lock:
            held = self._open is False
            since = self._since
        # …AND WHY, AS AN ID (#1982). The mark used to say one sentence — «нет связи с
        # игрой» — for every way of being held, and during maintenance that sentence is
        # simply false: the link is perfect and the SERVER is shut. Both front-ends word
        # this for themselves, so the reason travels as an id and never as words.
        why = ("off" if self._switched_off()
               else "maintenance" if self._maintenance() else "link")
        return {"held": held, "for_sec": int(now - since) if held and since else 0,
                "reason": why if held else ""}

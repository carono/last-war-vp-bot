"""The chat's own thread, and the one promise it makes: a typed message is not lost (#2594).

The person's rule, in their own words: «Чат должен всегда работать в отдельном потоке и
его действия ничего не должны блокировать и сам он не зависит от работы сценариев
панели» — and, when the measurements came back, the half that mattered most: **отправка
человека не должна теряться.**

WHAT WAS MEASURED, and it is the whole reason this file exists. Live on `default`'s own
`panel.log` over 2026-09-04..06 (55 h), a send was `play_async(..., human=True)` straight
off the widget's command: the box was cleared, the run was refused because something else
was driving the client, and the log said «занят — дождись завершения текущего действия».
**Eight times in that window the message simply ceased to exist** — no draft, no queue, no
way to press again except by typing it out from memory. Everything else in the panel that
is refused comes back on the next tick of a schedule; a sentence somebody typed has no
next tick.

SO A SEND IS QUEUED, NEVER ATTEMPTED-AND-DROPPED. The press hands the message to this
lane and is answered at once; the lane's own thread takes them one at a time, plays
`send_chat_message` under a proper claim, and — when the client is busy or the link is
momentarily not there — WAITS AND ASKS AGAIN, for up to :data:`HOLD_SEC`. Only two things
end a message's life: it went, or it kept being refused for longer than a person would
have stood there re-pressing.

WHY A THREAD OF ITS OWN AND NOT THE PRESS'S. Three reasons, and the first is the rule:
* the press comes off the **Tk thread** (a button) or an **HTTP worker** (the phone), and
  neither may block for the twelve seconds `claim_soon` is allowed to wait, let alone for
  the retries after it;
* two messages typed in a row must arrive **in the order they were typed**, which one
  queue and one consumer give for nothing and two racing workers cannot give at all;
* the chat must never be the thing a farming run is waiting behind, so the lane holds
  nothing at all between sends — it owns a queue, not a claim.

PER PROFILE, LIKE EVERYTHING THAT IS AN ACCOUNT'S (`CLAUDE.md`). One runtime switches
between accounts, so every message is stamped with the profile it was typed under and a
message whose profile is no longer the open one is dropped rather than posted into
somebody else's alliance. That is the same mistake #1306 catalogued, and it is the one
this queue would make by simply outliving a switch.
"""
from __future__ import annotations

import collections
import threading
import time

from . import claims

#: How long a refused message keeps trying before the lane gives up on it. Five minutes:
#: long enough to outlast anything the schedule does — the longest ordinary errand
#: measured on this account holds the client for ~300 s (`restart_game`) — and short
#: enough that a message which cannot go is SAID so while the person still remembers
#: typing it.
HOLD_SEC = 300.0

#: How long the lane waits before asking again. Three seconds rather than a tight loop:
#: `play_now` has already spent up to `link.YIELD_WAIT_SEC` (12 s) hanging a demand on
#: the door and polling it, so this is the pause BETWEEN those waits, not instead of one.
RETRY_SEC = 3.0

#: The refusals that mean «not now» rather than «not at all». Compared against the
#: locale KEY the gate answered with, plus the busy sentence the claim answers with —
#: see :meth:`ChatOutbox._transient`.
TRANSIENT_KEYS = ("busy", "action.held.link", "action.held.human", "action.held.off",
                  "timers.log.skip_link", "timers.log.skip_silent")


class ChatOutbox:
    """One profile's queue of messages waiting to leave, and the thread that empties it."""

    __slots__ = ("rt", "_q", "_lock", "_thread", "_seq")

    def __init__(self, rt) -> None:
        self.rt = rt
        self._q: collections.deque = collections.deque()
        self._lock = threading.Condition()
        self._thread: "threading.Thread | None" = None
        self._seq = 0

    # -- the door ------------------------------------------------------------
    def send(self, args: dict, what: str, room: str) -> bool:
        """Queue one message. Answers at once, and answers ``True`` for «accepted».

        It is deliberately not «sent»: the press has no way of knowing whether the client
        is free this second, and pretending it does is what made the old path throw the
        message away. What the caller may rely on is that the message is now the lane's
        problem and that the lane will say, in the log, which of the two ends it reached.
        """
        room = str(room or "").strip()
        if not room:
            return False
        with self._lock:
            self._seq += 1
            self._q.append({"args": dict(args), "what": str(what), "room": room,
                            "profile": self._profile(), "at": time.monotonic(),
                            "seq": self._seq})
            waiting = len(self._q)
            self._lock.notify()
        self._start()
        if waiting > 1:
            # ONLY WHEN THERE IS A QUEUE. One message going straight out needs no line
            # about queueing — `chat.sending` has already been said by the tab — and a
            # panel that narrates its own plumbing on every press is the noise this
            # codebase keeps relearning (#1911).
            self.rt.log.say("chat", "chat.send.queued", waiting=waiting)
        return True

    def waiting(self) -> int:
        """How many messages are still to go — for a screen that wants to say so."""
        with self._lock:
            return len(self._q)

    # -- the thread ----------------------------------------------------------
    def _start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._loop, daemon=True,
                name=f"lw:{self._profile()}:chat:outbox"[:60])
            self._thread.start()

    def _profile(self) -> str:
        try:
            return str(self.rt.profiles.active or "")
        except Exception:                       # noqa: BLE001 — a name, never the send
            return ""

    def _loop(self) -> None:
        """Take one message at a time and keep at it until it goes or the hold runs out."""
        while True:
            with self._lock:
                if not self._q:
                    # Nothing left: the thread ends rather than idling for the life of the
                    # panel. `_start` makes a new one the next time somebody types, which
                    # costs microseconds and leaves no thread per profile per session
                    # sitting on a condition variable for ever.
                    self._thread = None
                    return
                item = self._q[0]
            if not self._carry(item):
                # It went, it was given up on, or it belonged to another account — every
                # one of those is «off the queue». A retry leaves the item where it is.
                with self._lock:
                    if self._q and self._q[0] is item:
                        self._q.popleft()
                continue
            time.sleep(RETRY_SEC)

    def _carry(self, item: dict) -> bool:
        """Try once. ``True`` means «leave it queued and come back», ``False`` «done with it»."""
        if item["profile"] != self._profile():
            # A SWITCH HAPPENED WHILE IT WAITED. Posting it now would put one account's
            # sentence into another account's chat, which is the whole of #1306 in one
            # press. Said, because a message quietly not sent is the thing this lane
            # exists to abolish.
            self.rt.log.say("chat", "chat.send.dropped_profile",
                            what=item["what"], profile=item["profile"])
            return False
        outcome = self.rt.play_now("send_chat_message",
                                   dict(item["args"], room=item["room"]),
                                   tag="chat", priority=claims.HUMAN, human=True)
        if outcome:
            self.rt.log.say("chat", "chat.send.sent",
                            room=item["room"], what=item["what"])
            return False
        reason = str(getattr(outcome, "reason", "") or "")
        waited = time.monotonic() - float(item["at"])
        if not self._transient(reason):
            # The RECIPE said no — an empty room, a message the game refused. Asking
            # again would refuse again, and saying so once is the honest answer.
            self.rt.log.say("chat", "chat.send.failed",
                            what=item["what"], reason=reason)
            return False
        if waited >= HOLD_SEC:
            self.rt.log.say("chat", "chat.send.gave_up",
                            what=item["what"], secs=int(waited), reason=reason)
            return False
        self.rt.log.say("chat", "chat.send.waiting",
                        what=item["what"], secs=int(waited))
        return True

    def _transient(self, reason: str) -> bool:
        """Is this a «not now» rather than a «not at all»?

        The reason arrives already TRANSLATED — `play_async` puts `self.t(key)` on the
        Outcome, because that string is also what a person reads — so the keys are
        translated here too and compared as text. It is a comparison against this
        panel's own words in this panel's own language, never a parse of the game's.
        """
        text = reason.strip()
        if not text:
            # A run that failed with nothing to say lost the client somewhere it could
            # not name — the ordinary shape of «the link went away mid-send». Worth
            # another try, which is the whole point of the hold.
            return True
        for key in TRANSIENT_KEYS:
            try:
                said = str(self.rt.t(key, name="send_chat_message") or "")
            except Exception:                   # noqa: BLE001 — a comparison, never the send
                continue
            if said and said == text:
                return True
        return False

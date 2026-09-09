"""A very small publish/subscribe, for the facts one tab has and another wants.

Five places in the panel reach across tabs today — a capture line nudging the
secret-task list, a collect refreshing the inventory, the resource tracker feeding the
stats table (docs/research/panel-tabs-refactor.md §7). Once a tab can be switched off in
the profile, "reach into the other tab" stops being safe: the other tab may not be there.

So: publish a fact, and whoever is listening hears it. Deliberately tiny — no wildcards,
no ordering guarantees, no persistence, no replay. Anything that needs more than this is
a runtime service, not an event.

Delivery is on the Tk thread when a widget is given, because a subscriber is almost
always about to repaint something. `subscribe` returns the unsubscribe callable, which
is what a tab's `shutdown()` calls — a listener that outlives its tab would repaint a
destroyed widget.
"""
from __future__ import annotations

#: «The client is up, logged in and answering» — published once per appearance by
#: :class:`~panel.runtime.status.StatusPoll`, on the edge and never on the clock.
#:
#: It exists because a reading has to start somewhere. The panel does not poll for what
#: the game already knows (`CLAUDE.md`, «Read once, then LISTEN»), so every board that
#: is kept current by pushes needs ONE moment to take its first reading — and that
#: moment is the client becoming usable, not somebody opening a page and not a button
#: called «Обновить». A subscriber hears it again after a link is lost and comes back,
#: which is the other time everything it holds may have moved unheard.
GAME_READY = "game.ready"

#: How far apart the listeners of a SPREAD topic are told, in seconds (#2678).
#:
#: `GAME_READY` is the one moment every push-driven board takes its first reading, so
#: every one of them read at once: ten chunks inside thirty seconds of a client that had
#: just got into the game, each one an attach — a suspend of the game's main thread, a
#: redirect of its RIP and a restore. That minute is when the client dies; six of nine
#: measured restarts killed it 59-95 s in (`docs/research/client-crashes.md`).
#:
#: It is the same cure the errands got in #2667 and the same decision behind it, in the
#: person's words: «Да, разноси, сделай правило, пусть лаг будет, нет веской причины все
#: разом делать». Nothing is dropped and nothing is re-decided — every listener is told,
#: in the order it subscribed, a few seconds apart. A board is at worst a minute older
#: than it could be, on a reading that is then kept current by the wire.
SPREAD_SEC = 6.0

#: The topics delivered that way. Only the boot's own stampede is on the list: a push, a
#: capture line or a collect finishing is an EVENT and is answered at once, exactly as
#: `CLAUDE.md` («Nothing starts in a burst») requires.
SPREAD_TOPICS = frozenset({GAME_READY})


class EventBus:
    def __init__(self, widget=None, post=None, arm=None) -> None:
        self._subs: dict = {}
        self._w = widget
        #: The clock's one-shot booker (`panel/runtime/tick.py::Ticker.arm`), used to
        #: hand a SPREAD topic's listeners their turn one at a time. Without one the
        #: spread cannot happen and the topic is delivered whole — which is what a bare
        #: harness and a test get, and what the panel did before #2678.
        self._arm = arm
        self._spread_n = 0
        #: How a fact gets onto the ONE thread when there is no widget to hand it to —
        #: the windowless clock's own queue (#1976, P3). Without either, a fact is
        #: delivered where it was published, which is what a bare harness and a test get.
        self._post = post

    def subscribe(self, topic: str, func):
        """Listen to ``topic``. Returns the callable that stops listening."""
        self._subs.setdefault(topic, []).append(func)

        def _off() -> None:
            try:
                self._subs.get(topic, []).remove(func)
            except ValueError:
                pass
        return _off

    def publish(self, topic: str, payload=None) -> None:
        """Tell every listener of ``topic``. A listener that raises does not stop the rest."""
        listeners = list(self._subs.get(topic, ()))
        if not listeners:
            return
        if topic in SPREAD_TOPICS and self._arm is not None and len(listeners) > 1:
            self._spread(topic, listeners, payload)
            return
        if self._w is None:
            if self._post is not None:
                self._post(lambda: self._deliver(listeners, payload))
                return
            self._deliver(listeners, payload)
            return
        # Through the window's hand-over queue (panel/runtime/tick.py), because a fact
        # is nearly always published by a WORKER — a capture line, a collect finishing,
        # a wire event — and `after` from a worker blocks it on the event loop that
        # draws every open profile (#1226).
        from .tick import poster

        post = poster(self._w)
        if post is None:
            self._deliver(listeners, payload)
            return
        post.post(lambda: self._deliver(listeners, payload))

    def _spread(self, topic: str, listeners, payload) -> None:
        """Tell the listeners of ``topic`` one at a time, :data:`SPREAD_SEC` apart.

        The first is told at once — a spread that made even the first reading wait would
        be a delay with nothing to show for it — and the rest are booked on the clock,
        each on a name of its own so no two of them cancel each other. The booking runs
        on the one thread the chains run on, which is where a listener has always run.

        A listener that has unsubscribed by the time its turn comes is skipped: the tab
        it belonged to may have been switched off, and repainting a destroyed widget is
        the thing `subscribe`'s unsubscribe callable exists to prevent.
        """
        live = self._subs.setdefault(topic, [])
        for i, func in enumerate(listeners):
            if i == 0:
                self._hand_over([func], payload)
                continue
            self._spread_n += 1
            name = f"bus.spread.{self._spread_n}"

            def _turn(f=func, p=payload) -> None:
                if f in live:
                    self._deliver([f], p)
            try:
                self._arm(name, int(i * SPREAD_SEC * 1000), _turn)
            except Exception:                    # noqa: BLE001 — a clock that will not
                self._deliver([func], payload)   # book still owes the listener its fact

    def _hand_over(self, listeners, payload) -> None:
        """Deliver on the ONE thread, whichever of the three ways this bus has."""
        if self._w is None:
            if self._post is not None:
                self._post(lambda: self._deliver(listeners, payload))
                return
            self._deliver(listeners, payload)
            return
        from .tick import poster

        post = poster(self._w)
        if post is None:
            self._deliver(listeners, payload)
            return
        post.post(lambda: self._deliver(listeners, payload))

    @staticmethod
    def _deliver(listeners, payload) -> None:
        for func in listeners:
            try:
                func(payload)
            except Exception:                    # noqa: BLE001 — one deaf listener is
                pass                             # not the other listeners' problem

    def topics(self) -> dict:
        """Live subscriber counts per topic (diagnostics; also proves shutdown unhooked)."""
        return {k: len(v) for k, v in self._subs.items() if v}

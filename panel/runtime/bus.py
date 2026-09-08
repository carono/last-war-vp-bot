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


class EventBus:
    def __init__(self, widget=None, post=None) -> None:
        self._subs: dict = {}
        self._w = widget
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

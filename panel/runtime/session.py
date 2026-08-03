"""One open profile — the thing a window may hold several of (#1206).

A *session* is one profile, open: its :class:`~panel.runtime.host.PanelRuntime`, its
daemon, its schedule, its tabs, and the shell's per-profile state. Where the panel used
to say "the profile" and mean the process, it says "this session" and means one of
several — and the difference between one open profile and four is how many of these
exist, not what any of them does.

WHAT IS HERE AND WHAT IS NOT. This object owns the runtime and the lifecycle. It owns
no widgets: the page a session is drawn on is the shell's, because only the shell knows
what a page looks like. What the shell keeps *per profile* — the log widget, the status
strip, the poller's stop flag, the sweep's place — lives in :attr:`state`, a plain dict
the shell reads and writes through the attribute routing described in
docs/research/multi-profile-panel.md §3. That is a dict rather than attributes on this
class on purpose: the shell's per-profile state is the shell's business and changes with
it, and a session that had to declare each of them would be edited by every task that
touches the window.

THE SCOPE. The first session opened has none: it writes the shared debug log exactly as
every panel always has, so a window with one profile is unchanged down to the file it
logs into. Every session after it names one, and then each profile's `debug.log` fills
independently (panel/debug_log.py).
"""
from __future__ import annotations

import contextlib
import functools
import threading

from .. import profile as profilemod
from .host import PanelRuntime


class ProfileSession:
    """One profile, open. The runtime plus the shell's per-profile state."""

    def __init__(self, name: str, *, root, defaults: dict | None = None,
                 scope: str | None = None, daemon_state=None) -> None:
        #: The profile this session IS. A session does not switch profiles — closing
        #: one and opening another is the same thing and says what it means.
        self.name = profilemod.sanitize(name) or profilemod.DEFAULT_PROFILE
        self.scope = scope
        self.rt = PanelRuntime(
            root,
            profiles=profilemod.ProfileManager(pin=self.name),
            defaults=defaults, scope=scope, daemon_state=daemon_state)
        #: The shell's per-profile attributes (see the module docstring).
        self.state: dict = {}
        #: The page this session is drawn on, once the shell has made one. Held here
        #: so the notebook can be asked "which session is this tab?" without a second
        #: map to keep in step.
        self.page = None
        self._started = False

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        """Begin what this profile does while nobody is looking. Idempotent.

        The schedule and its listeners, and nothing that draws: a session whose page
        has never been on screen still runs its errands, which is the entire point of
        holding more than one open.
        """
        if self._started:
            return
        self._started = True
        self.rt.schedule.start()

    def stop(self) -> None:
        """Stop the errands but keep the runtime — a session being closed, not the app."""
        if not self._started:
            return
        self._started = False
        try:
            self.rt.schedule.stop()
        except Exception:                    # noqa: BLE001 — closing, never the panel
            pass

    @property
    def started(self) -> bool:
        return self._started

    def shutdown(self) -> None:
        """Everything this session holds, let go of: tabs, errands, daemon claim, files."""
        for tab in self.rt.tabs.live:
            try:
                tab.shutdown()
            except Exception:                # noqa: BLE001 — one tab, not the window
                pass
        self.stop()
        try:
            self.rt.shutdown()
        finally:
            # Including the UNSCOPED one, which is the first session's. Leaving it open
            # would keep a closed profile's `debug.log` locked for the rest of the run —
            # on Windows that is a file nothing can move, rotate or delete. Every other
            # session has a scope of its own and is untouched by this.
            from .. import debug_log as dbgmod
            dbgmod.shutdown(self.scope)

    # -- what the window shows about it -------------------------------------
    def label(self) -> str:
        """What the outer notebook writes on this session's tab.

        The profile's name, which is what the operator called it — never translated,
        and never decorated here: a session that is behind on something says so through
        the page it draws, not through its own name.
        """
        return self.name

    def __repr__(self) -> str:
        return f"<ProfileSession {self.name!r} scope={self.scope!r}>"


class SessionScoped:
    """Attributes that belong to the open profile rather than to the window.

    The shell is two thousand lines of methods written against `self._log`, `self._rt`,
    `self._dash_values` — every one of them correct, and every one of them about ONE
    profile. Rewriting them all to take a session would be a diff nobody can review
    against a file three other tasks are editing, and it would say nothing the names do
    not already say.

    So the names are declared instead. A class lists in :attr:`SESSION_ATTRS` exactly
    which of its attributes are per-profile, and reads and writes of those go to the
    session whose page is showing. Everything else is the window's and is stored the
    ordinary way. `self._log` in a method means "this profile's log widget", which is
    what it always meant — there is simply more than one profile for it to mean it
    about now (docs/research/multi-profile-panel.md §3).

    THREE THINGS KEEP THIS HONEST rather than magic:

    * the list is explicit and finite, and a contract test walks it;
    * a name that is a property or a method on the class is NEVER routed, so declaring
      one by mistake is inert rather than a silently broken descriptor;
    * before there is a session — during the window's own construction — nothing is
      routed and every attribute is the window's, exactly as it was.
    """

    #: The attribute names that belong to the open profile. Declared by the subclass.
    SESSION_ATTRS: frozenset = frozenset()

    #: The session whose page is on screen. The default answer, and the right one for
    #: the Tk thread — which is where a button, a menu and a repaint all happen.
    _current_session = None

    # WHY A THREAD-LOCAL, AND NOT JUST THE ATTRIBUTE ABOVE. The first version of this
    # swapped `_current_session` around a call and put it back. That is correct on the
    # Tk thread, where there is one caller at a time; it is a DATA RACE the moment two
    # workers are bound to two different sessions at once. It cost a whole live boot:
    # two profiles opening in parallel, both boot threads swapping the one attribute,
    # and both ran the FIRST profile's start-up — one client got its schedule started
    # twice and the other got nothing at all, in silence.
    #
    # So a bound call marks the session on ITS OWN thread and the attribute stays the
    # default for everybody else.
    def _bindings(self):
        local = self.__dict__.get("_session_local")
        if local is None:
            local = threading.local()
            object.__setattr__(self, "_session_local", local)
        return local

    def _session(self):
        """The session THIS thread is acting for: its binding, else the showing one."""
        bound = getattr(self._bindings(), "session", None)
        return bound if bound is not None else self.__dict__.get("_current_session")

    @contextlib.contextmanager
    def session_scope(self, session):
        """Act for ``session`` on this thread until the block ends. Nestable."""
        local = self._bindings()
        previous = getattr(local, "session", None)
        local.session = session
        try:
            yield session
        finally:
            local.session = previous

    def bind_session(self, func, session=None):
        """``func``, re-entering the session it was made in whenever it is called.

        «Made in» is :meth:`_session` — the session THIS THREAD is acting for — and not
        the showing one. The difference is invisible on the Tk thread and load-bearing
        everywhere else: the shell's start-up runs on a thread per profile, so
        everything it arms or spawns there would otherwise be bound to whichever page
        happened to be on screen. It cost the second profile's account strip: it polled
        the FIRST profile's client and wrote the readings into the first profile's log.
        Real numbers, wrong account.

        Bind at the SCHEDULING site — an `after`, a thread, a repeating callback — never
        at the site that reads an attribute.

        NOT called `bind`: the shell mixes this into `tk.Tk`, and `Misc.bind` is how
        every widget in the panel attaches an event handler. Shadowing it took the
        window down on the line after the one that built it.
        """
        owner = session if session is not None else self._session()
        if owner is None:
            return func

        @functools.wraps(func)
        def run(*args, **kw):
            with self.session_scope(owner):
                return func(*args, **kw)
        return run

    def _routed(self, name: str) -> bool:
        """Does ``name`` belong to a session? (A descriptor never does.)"""
        cls = type(self)
        if name not in cls.SESSION_ATTRS or hasattr(cls, name):
            return False
        return self._session() is not None

    def __getattr__(self, name):
        # Reached only when ordinary lookup failed — which for a routed name it always
        # does, because `__setattr__` never puts one in the instance dictionary.
        if name in type(self).SESSION_ATTRS:
            session = self._session()
            if session is not None:
                try:
                    return session.state[name]
                except KeyError:
                    pass
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r}")

    def __setattr__(self, name, value) -> None:
        if self._routed(name):
            self._session().state[name] = value
            return
        super().__setattr__(name, value)

    def __delattr__(self, name) -> None:
        session = self._session() if self._routed(name) else None
        if session is not None and name in session.state:
            del session.state[name]
            return
        super().__delattr__(name)

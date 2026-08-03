"""The set of profiles one window has open, and which of them is on screen (#1206).

One :class:`~panel.runtime.session.ProfileSession` per open profile; this is the thing
that holds them. It answers three questions the shell used to answer with "the profile",
because there was only ever one:

* **Which sessions are there?** :attr:`sessions`, in the order their pages sit in.
* **Which one is the operator looking at?** :attr:`current` — and it is the ONLY thing
  a switch changes. Nothing stops running because its page went out of sight.
* **Which ones should be open at all?** :meth:`restore` reads that off the panel-wide
  `panel/settings.json`, and every open/close writes it back, so a window comes up the
  way it was left.

WHAT IS NOT HERE. Widgets. The shell draws a page per session and tells this object
which one is showing; this object never reaches into a page. Keeping it that way is
what lets the whole thing be tested without a display, which
tests/test_panel_workspace.py does.

ONE RULE WORTH SPELLING OUT: the FIRST session opened gets no debug-log scope, so a
window with one profile open logs exactly where it always did. See
`panel/runtime/session.py`.
"""
from __future__ import annotations

from .. import profile as profilemod
from .session import ProfileSession


class Workspace:
    """Every profile this window has open."""

    def __init__(self, root, *, defaults: dict | None = None, profiles=None,
                 daemon_state=None, log=None, can_open=None, refused=None) -> None:
        self._root = root
        self._defaults = defaults
        #: The panel's OWN profile manager — unpinned, and the only one allowed to
        #: write the panel-wide file. Each session holds a pinned one of its own.
        self.profiles = profiles if profiles is not None else profilemod.ProfileManager()
        self._daemon_state = daemon_state
        self._log = log                      # callable(session, tag, key, **fmt)
        #: ``can_open(name) -> bool`` — is this profile free to open HERE? The rule the
        #: operator set is ONE PANEL PER PROFILE, not one per machine: a profile another
        #: panel already holds must not be opened a second time, because the two would
        #: write one `config.json` over each other and drive one daemon. Without this,
        #: a second panel started for its own profile would silently adopt the FIRST
        #: one's remembered list and take over every profile in it — which is exactly
        #: what happened the first time this was run live.
        self._can_open = can_open
        self._refused = refused              # callable(name) — say a profile was skipped
        #: Profiles this window WANTED open and could not have (another panel holds
        #: them). Remembered beside the open ones so a refusal — which may be nothing
        #: worse than the previous panel's lock outliving it by a moment — cannot erase
        #: a profile from the list for good.
        self._held_elsewhere: list = []
        self._sessions: list = []
        self._current: "ProfileSession | None" = None

    def free(self, name: str) -> bool:
        """Is ``name`` open in no other panel? ``True`` when nothing was asked."""
        if self._can_open is None:
            return True
        try:
            return bool(self._can_open(name))
        except Exception:                    # noqa: BLE001 — a refusal must not be one
            return True

    # -- what is open -------------------------------------------------------
    @property
    def sessions(self) -> list:
        return list(self._sessions)

    @property
    def names(self) -> list:
        return [s.name for s in self._sessions]

    @property
    def current(self):
        return self._current

    def get(self, name: str):
        """The open session for ``name``, or ``None``."""
        name = profilemod.sanitize(name)
        return next((s for s in self._sessions if s.name == name), None)

    def __len__(self) -> int:
        return len(self._sessions)

    def __contains__(self, name) -> bool:
        return self.get(str(name)) is not None

    # -- opening and closing -------------------------------------------------
    def open(self, name: str, *, make_current: bool = True) -> ProfileSession:
        """Open ``name`` beside whatever is already open, or return it if it is.

        Creates the profile if there is no such directory — the same thing
        `--profile` on the command line has always done, and the only sensible answer
        to "open the profile I just typed".
        """
        existing = self.get(name)
        if existing is not None:
            if make_current:
                self.switch_to(existing.name)
            return existing
        name = self.profiles._ensure_dir(name)
        session = ProfileSession(
            name, root=self._root, defaults=self._defaults,
            scope=self._next_scope(name), daemon_state=self._daemon_state)
        self._sessions.append(session)
        if make_current or self._current is None:
            self._current = session
        self._remember()
        return session

    def close(self, name: str) -> "ProfileSession | None":
        """Shut one session down and take its page out. The last one cannot be closed.

        Returns the session that was closed, or ``None`` when there was nothing to
        close or it was the only one left — a window with no profile open is a window
        with nothing in it, and «Закрыть» must not be the way to get there.
        """
        session = self.get(name)
        # Closing on purpose is the one thing that forgets a profile — see `_remember`.
        self._held_elsewhere = [n for n in self._held_elsewhere
                                if n != profilemod.sanitize(name)]
        if session is None or len(self._sessions) <= 1:
            return None
        index = self._sessions.index(session)
        self._sessions.remove(session)
        try:
            session.shutdown()
        finally:
            if self._current is session:
                self._current = self._sessions[min(index, len(self._sessions) - 1)]
            self._remember()
        return session

    def switch_to(self, name: str):
        """Bring one open session's page to the front. Everything keeps running."""
        session = self.get(name)
        if session is None or session is self._current:
            return self._current
        self._current = session
        self._remember()
        return session

    # -- everything at once --------------------------------------------------
    def each(self, func) -> list:
        """Call ``func(session)`` for every open session; one raising does not stop it.

        This is what the shell's boot, its status poll, its «Стоп всё» and its close
        all became: the thing that used to happen once now happens per session, and a
        session that throws on the way out must not take the others with it.
        """
        out = []
        for session in list(self._sessions):
            try:
                out.append(func(session))
            except Exception as exc:         # noqa: BLE001 — one profile, not the window
                out.append(exc)
                self._complain(session, exc)
        return out

    def start_all(self) -> None:
        self.each(lambda s: s.start())

    def shutdown(self) -> None:
        """The window is closing. Every session, then the record of what was open."""
        self._remember()
        self.each(lambda s: s.shutdown())
        self._sessions, self._current = [], None

    # -- coming back the way it was left -------------------------------------
    def restore(self, first: str | None = None) -> list:
        """Open what was open last time. Returns the sessions, the on-screen one first.

        ``first`` overrides which profile is on screen (a `--profile` on the command
        line). A panel that has never had more than one profile open has no record, and
        then this opens exactly the one the active-profile pointer names — which is the
        behaviour of every panel before this existed.
        """
        wanted = self.profiles.open_profiles()
        head = profilemod.sanitize(first or "") or self.profiles.active
        if head not in wanted:
            wanted.insert(0, head)
        # The head is opened whatever the answer: a window a person asked for opens,
        # and whether THAT profile is already somewhere else was decided before this
        # window was built at all (`panel/__main__.py::_already_open`). The rest of the
        # remembered list is only remembered, so a profile another panel is holding is
        # skipped and said out loud rather than taken over.
        self._held_elsewhere = []
        for name in wanted:
            if name != head and not self.free(name):
                self._held_elsewhere.append(name)
                if self._refused is not None:
                    self._refused(name)
                continue
            self.open(name, make_current=False)
        self.switch_to(head)
        # The pointer follows the page that is on screen, so the next plain launch
        # comes up looking at the same profile even if the list is later lost.
        if self._current is not None:
            self.profiles.set_active(self._current.name)
        self._remember()
        return self.sessions

    # -- helpers -------------------------------------------------------------
    def _next_scope(self, name: str) -> "str | None":
        """The debug-log scope for a session about to be opened.

        ``None`` for the first — see the module docstring. The profile's name for every
        one after it, which is unique among open sessions by construction.
        """
        return None if not self._sessions else name

    def _remember(self) -> None:
        """Write down what this window would have open, and what is showing.

        WOULD have, not does: a profile another panel is holding stays in the list. It
        may be held for the length of a lock that outlived a killed panel by a moment,
        and dropping it would quietly forget the profile for ever — the next launch has
        no way to know it was ever wanted. The only thing that takes a name out of this
        list is closing it on purpose.
        """
        names = self.names
        if self._current is not None:
            names = [self._current.name] + [n for n in names if n != self._current.name]
            self.profiles.set_active(self._current.name)
        names += [n for n in self._held_elsewhere if n not in names]
        self.profiles.set_open_profiles(names)

    def _complain(self, session, exc: Exception) -> None:
        if self._log is None:
            return
        try:
            self._log(session, f"{type(exc).__name__}: {exc}")
        except Exception:                    # noqa: BLE001 — a complaint, not the panel
            pass

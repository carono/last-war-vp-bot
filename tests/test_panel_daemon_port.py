r"""The port a profile names reaches its daemon — from the FIRST instant, and afterwards.

Two answers to "which daemon does this profile drive" have to agree, and for two days
they did not (#1224). A profile whose client lives in another Windows session names a
port of its own (47655); the panel claimed the game lease on 47654 and pressed the
scenario into 47655, so every action of that account came back «lease lost», the restart
errand never saw `scene == city`, and it relaunched a healthy client every six minutes
all night. Nothing looked broken from outside: the daemon answered, the strip said warm.

Two independent causes, one per half of this file:

* **A widget beats the file** (`panel/runtime/settings.py`), so a variable created with
  the CODE's default is the answer to every read of that knob until somebody applies the
  profile to the widgets — which the shell does long after the runtime, and its game
  link, were built. A knob must therefore START at the profile's saved value.
* **The client froze its port.** Everything on the link re-reads `port()` on every use;
  the `DaemonClient` was built once, in the constructor. So even a port that arrives
  late — an applied profile, an edited setting — has to move it.

No widget, no game, no socket: a stand-in variable, a stand-in daemon, and a port that
moves under the link the way an applied profile moves it.

    C:\Python312\python.exe tests\test_panel_daemon_port.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import contextlib                                           # noqa: E402
import panel.runtime.daemon as daemonmod                     # noqa: E402
from panel.runtime.daemon import GameLink                   # noqa: E402
from panel.runtime.settings import SettingsBinder           # noqa: E402


# ---------------------------------------------------------------------------
# doubles
# ---------------------------------------------------------------------------

class _Var:
    """A Tk variable, minus Tk: a value, a trace, and the same `get`/`set`."""

    def __init__(self, value):
        self.value = value
        self._watchers: list = []

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value
        for call in self._watchers:
            call()

    def trace_add(self, _mode, call) -> None:
        self._watchers.append(call)


def _var(_master, default):
    """The factory `create_vars` is handed — it picks the KIND of variable from the
    value it is given, which is why the type of that value is part of the contract."""
    return _Var(bool(default) if isinstance(default, bool) else str(default))


class _Log:
    def __init__(self) -> None:
        self.lines: list = []

    def put(self, line) -> None:
        self.lines.append(str(line))

    def say(self, tag, key, **fmt) -> None:
        self.lines.append(f"{tag}:{key}")


class _Daemon:
    """One daemon's lease, so a claim can be asked WHICH daemon received it."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.held: str = ""
        self.owner: str = ""
        self.issued = 0

    def client(self, token=None):
        return _Client(self, token)


class _Client:
    def __init__(self, daemon: _Daemon, token=None) -> None:
        self._d = daemon
        self.port = daemon.port
        self.token = "" if token is None else token

    def acquire(self, owner: str, ttl: float = 120.0):
        if self._d.held and self._d.held != self.token:
            return None
        if not self._d.held:
            self._d.issued += 1
            self._d.held = f"tok{self._d.port}-{self._d.issued}"
            self._d.owner = owner
        self.token = self._d.held
        return self.token

    def release(self) -> bool:
        if not self.token:
            return True
        try:
            if self._d.held == self.token:
                self._d.held, self._d.owner = "", ""
            return True
        finally:
            self.token = ""

    def lease_state(self) -> dict:
        return {"owner": self._d.owner, "held_sec": 1}


@contextlib.contextmanager
def _daemons(*daemons: _Daemon):
    """While this is open, the link builds its clients against THESE daemons.

    A re-point makes a client of its own, and a test that let it make a real one would
    reach for a socket on this machine — which on the box this bug was found on is a
    live daemon driving a live account.
    """
    by_port = {d.port: d for d in daemons}
    was = daemonmod.lua_client.DaemonClient
    daemonmod.lua_client.DaemonClient = (
        lambda port=None, token=None, **kw: by_port[int(port)].client(token))
    try:
        yield
    finally:
        daemonmod.lua_client.DaemonClient = was


def _binder(saved: dict, defaults: dict) -> SettingsBinder:
    binder = SettingsBinder(profiles=None, defaults=defaults)
    binder.values = dict(saved)
    return binder


# ---------------------------------------------------------------------------
# a knob starts where the profile left it
# ---------------------------------------------------------------------------

def test_a_knob_answers_the_profiles_value_before_the_page_is_drawn() -> None:
    """The bug itself: 47655 in the file, 47654 out of a brand-new runtime."""
    binder = _binder({"daemon_port": 47655}, {"daemon_port": 47654})
    binder.create_vars(master=None, factory=_var)
    assert binder.opt_int("daemon_port") == 47655, binder.opt("daemon_port")


def test_a_knob_the_profile_never_saved_starts_at_the_default() -> None:
    binder = _binder({}, {"daemon_port": 47654, "win_python": "py"})
    binder.create_vars(master=None, factory=_var)
    assert binder.opt_int("daemon_port") == 47654
    assert binder.opt_str("win_python") == "py"


def test_a_boolean_knob_keeps_its_kind_however_it_was_saved() -> None:
    """The factory chooses a checkbox or a text box from what it is handed, so a
    `"true"` in somebody's hand-edited config must not turn one into the other."""
    binder = _binder({"watchdog": "true", "autoloot": False},
                     {"watchdog": False, "autoloot": True})
    binder.create_vars(master=None, factory=_var)
    assert isinstance(binder.vars["watchdog"].get(), bool)
    assert binder.opt_bool("watchdog") is True
    assert binder.opt_bool("autoloot") is False


def test_a_null_in_the_file_is_not_a_value() -> None:
    binder = _binder({"daemon_port": None}, {"daemon_port": 47654})
    binder.create_vars(master=None, factory=_var)
    assert binder.opt_int("daemon_port") == 47654


# ---------------------------------------------------------------------------
# …and the link follows it
# ---------------------------------------------------------------------------

def _link(port, log=None) -> GameLink:
    link = GameLink(port=port, python=lambda: "python", log=log or _Log(),
                    env=dict, cwd=str(_REPO), daemon_script="x")
    # THE FAKE DAEMONS ABOVE ARE REACHABLE, and `up()` has to agree with them rather
    # than with this machine's socket table. `_claim_lease` short-circuits on `up()` —
    # a daemon that cannot be reached cannot be holding a lease, and asking costs a
    # connect on the Tk thread (#1226) — so «the claim lands on the daemon the profile
    # names» was decided by which of 47654 / 47655 happened to have a live daemon on the
    # box running the test: on the machine this was written on it read the claim as
    # granted with no token at all, and green everywhere a daemon runs on neither port.
    link.up = lambda fresh=False: True
    return link


def test_the_client_follows_a_port_that_arrives_late() -> None:
    """What a boot does: the profile's port reaches the panel after the link was built."""
    here, there = _Daemon(47654), _Daemon(47655)
    named = {"port": here.port}
    with _daemons(here, there):
        link = _link(lambda: named["port"])
        named["port"] = there.port
        assert link.client.port == there.port, link.client.port


def test_the_claim_lands_on_the_daemon_the_profile_names() -> None:
    """The whole point: claim and run must be the same daemon, or every run is refused."""
    here, there = _Daemon(47654), _Daemon(47655)
    named = {"port": here.port}
    with _daemons(here, there):
        link = _link(lambda: named["port"])
        named["port"] = there.port                # the profile's own port, applied late
        assert link.claim("timer") is True
        assert there.held and there.owner == "timer", (there.held, there.owner)
        assert not here.held, "the other account's client must be left alone"
        link.release()


def test_repointing_hands_the_old_daemons_lease_back() -> None:
    """A lease left behind holds that client for its whole ttl, and nobody knows why."""
    here, there = _Daemon(47654), _Daemon(47655)
    named = {"port": here.port}
    with _daemons(here, there):
        link = _link(lambda: named["port"])
        assert link.claim("timer") is True and here.held
        named["port"] = there.port
        assert link.client.port == there.port
        assert not here.held, "the daemon being left must not keep holding the claim"
        assert link.token == "", "…and the token it granted is not waved at the new one"


def test_rebind_still_reports_whether_it_moved() -> None:
    """The shell says «порт демона …» off this, and must not say it every poll."""
    here, there = _Daemon(47654), _Daemon(47655)
    named = {"port": here.port}
    with _daemons(here, there):
        link = _link(lambda: named["port"])
        assert link.rebind() is False
        named["port"] = there.port
        assert link.rebind() is True
        assert link.rebind() is False


def test_ensure_asks_the_socket_rather_than_its_own_cache():
    """«already warm» must never be said off a cached yes (#1281).

    `up()` reuses its answer for a second or so — right for the status poll and the
    schedule's gate, which ask constantly; wrong for the one caller whose whole job is
    to notice a daemon that has GONE. A client restarted by anything takes its daemon
    with it, and `ensure` was answering «already warm on port 47654» off a cache, doing
    nothing, and leaving the port dead — the rally auto-join went deaf for stretches at
    a time with the panel reporting a warm daemon. Seen live three times in twenty
    minutes.

    Checked by asking whether the reading was FRESH, not by counting sockets: the cache
    is what the class is allowed to keep, and the guarantee is only about this caller.
    """
    asked: list = []

    class _Link(GameLink):
        def __init__(self):
            pass                                     # nothing here is needed to ask

        def port(self):
            return 47654

        def up(self, fresh: bool = False) -> bool:
            asked.append(fresh)
            return True

        def _note(self, *a, **k):
            pass

        def on_state(self, *a, **k):
            pass

    assert _Link().ensure() is True
    assert asked == [True], (
        "ensure() read the cached answer; a daemon that died inside the cache window "
        "is then reported warm and never restarted")


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())

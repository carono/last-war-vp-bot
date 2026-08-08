r"""Зелёный — это гарантия, а не догадка: один огонёк на профиль (#1299).

A person with four accounts open reads four tab labels and nothing else, so each tab
carries its profile's whole health in one colour. The danger is entirely on one side:
an amber light that should have been green costs a second glance, and a green one that
should have been amber is never looked at again — which is how an account farms nothing
all night while every indicator says it is fine
(`docs/research/server-link-status.md` §5).

So this file is mostly a list of things that must NOT be green. Every one of them is a
state where the cheap readings all look healthy:

* a client at the login screen — sockets established, daemon warm, and every question
  answered with a plausible lie (#1227);
* a kicked account — one conversation still up, chunks still landing, and the clock
  still answering out of an offset set before the session ended (§5.3);
* a daemon that answers its port while nothing it sends reaches the game (#1286);
* a link with no verdict — a client 45 seconds old, or a machine that will not
  attribute its sockets. Amber, and never red: «не знаю» is not a fault;
* a reading that never happened, or that raised. Amber with its own reason, because
  «пусто» and «не смог прочитать» must not be one answer (#1296).

The rule is `tools/lib/profile_health.py` and takes ids, so none of this needs a game, a
socket or a clock. The wording half needs `panel.runtime`, which drags Tk in.

    C:\Python312\python.exe tests\test_profile_health.py
"""
from __future__ import annotations

TIER = "ui"        # panel.runtime drags tkinter in — see tools/run_tests.py

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import game_clock                                        # noqa: E402
import game_link                                         # noqa: E402
import profile_health as ph                              # noqa: E402

from panel.runtime.health import ProfileHealth           # noqa: E402


# -- stand-ins ---------------------------------------------------------------

class _Probe:
    """`panel.runtime.game_process.Probe` as far as the light is concerned."""

    def __init__(self, link: str, running: bool = True, text: str = "") -> None:
        self.link = link
        self.running = running
        self.message = text or f"client is {link}"


class _Eval:
    """A Lua evaluator that answers one canned reply — or refuses to answer at all."""

    def __init__(self, lines=None, raises: bool = False) -> None:
        self.lines = lines if lines is not None else []
        self.raises = raises
        self.calls = 0

    def run(self, chunk, marker=None, settle=1.2, early=False):
        self.calls += 1
        if self.raises:
            raise RuntimeError("no daemon")
        return list(self.lines)


def _healthy(**over):
    """The one combination that is allowed to be green — overridden a field at a time."""
    args = dict(link=game_link.ONLINE, running=True, daemon=ph.DAEMON_LIVE,
                session=ph.IN_SESSION, kicked=False)
    args.update(over)
    return ph.verdict(**args)


# -- the one green state -----------------------------------------------------

def test_green_needs_every_reading_to_agree():
    said = _healthy()
    assert (said.colour, said.reason) == (ph.OK, ph.HEALTHY), said


def test_every_single_reading_can_take_green_away():
    """One field at a time, and none of them may leave the light green."""
    for over in ({"link": game_link.LOST}, {"link": game_link.UNKNOWN},
                 {"link": game_link.OFFLINE}, {"running": False},
                 {"daemon": ph.DAEMON_IS_NONE}, {"daemon": ph.DAEMON_IS_STALE},
                 {"daemon": ph.DAEMON_UNASKED},
                 {"session": ph.LOGIN_SCREEN}, {"session": ph.SESSION_CANNOT_TELL},
                 {"kicked": True}):
        assert _healthy(**over).colour != ph.OK, over


# -- the states that look healthy and are not --------------------------------

def test_a_client_at_the_login_screen_is_red():
    """Sockets, pid and a warm daemon — and nobody is playing (#1227)."""
    said = _healthy(session=ph.LOGIN_SCREEN)
    assert (said.colour, said.reason) == (ph.BAD, ph.NOT_LOGGED_IN), said


def test_a_kicked_account_is_red_whatever_else_reads_fine():
    """The kick outranks everything: every other reading stays healthy under it (§5.3)."""
    said = _healthy(kicked=True)
    assert (said.colour, said.reason) == (ph.BAD, ph.KICKED), said


def test_a_daemon_that_answers_and_lands_nothing_is_amber_not_green():
    said = _healthy(daemon=ph.DAEMON_IS_STALE)
    assert (said.colour, said.reason) == (ph.WARN, ph.DAEMON_STALE), said


def test_no_daemon_is_amber_because_the_account_is_still_playing():
    """The game plays on with no daemon; only the pressing stops. Partly working."""
    said = _healthy(daemon=ph.DAEMON_IS_NONE)
    assert (said.colour, said.reason) == (ph.WARN, ph.DAEMON_NONE), said


def test_a_link_with_no_verdict_is_amber_and_never_red():
    """A client 45 seconds old is not a fault, and painting it red teaches nobody."""
    said = _healthy(link=game_link.UNKNOWN)
    assert (said.colour, said.reason) == (ph.WARN, ph.LINK_UNKNOWN), said


def test_a_dead_link_and_a_missing_client_are_red():
    assert _healthy(link=game_link.LOST).reason == ph.LINK_LOST
    assert _healthy(running=False, link=game_link.OFFLINE).reason == ph.CLIENT_OFF


def test_a_reading_that_never_happened_is_amber_with_its_own_reason():
    """«Пусто» and «не смог прочитать» are different answers (#1296)."""
    said = ph.verdict(link=game_link.ONLINE, running=True, daemon=ph.DAEMON_LIVE,
                      session=ph.IN_SESSION, read=False)
    assert (said.colour, said.reason) == (ph.WARN, ph.UNREAD), said
    blew_up = ph.verdict(link=game_link.ONLINE, running=True, daemon=ph.DAEMON_LIVE,
                         session=ph.IN_SESSION, error="socket table refused")
    assert (blew_up.colour, blew_up.reason) == (ph.WARN, ph.UNREAD), blew_up
    assert blew_up.error == "socket table refused"


def test_a_daemon_that_is_down_is_blamed_before_the_session_it_made_unaskable():
    """With no daemon the session cannot be asked, so the mystery is the daemon's."""
    said = _healthy(daemon=ph.DAEMON_IS_NONE, session=ph.SESSION_CANNOT_TELL)
    assert said.reason == ph.DAEMON_NONE, said


# -- the reading behind the login test ---------------------------------------

def test_the_clock_tells_a_login_screen_from_a_read_that_failed():
    """The distinction the whole red/amber split rests on (`game_clock.session_state`).

    A client at the login screen ANSWERS, with its own uptime; one that cannot be
    reached does not answer at all. Folding the two together is what `session_ready`
    does — fine for its own callers, and a fail-closed light here.
    """
    game_clock.reset()
    now_ms = int(__import__("time").time() * 1000)
    assert game_clock.session_state(_Eval([f"ACT NOWMS={now_ms}"])) == game_clock.IN_SESSION
    # An hour and three quarters of uptime, which is what a login screen answered live.
    assert game_clock.session_state(_Eval(["ACT NOWMS=6280648"])) == game_clock.LOGIN_SCREEN
    assert game_clock.session_state(_Eval([])) == game_clock.CANNOT_TELL
    assert game_clock.session_state(_Eval(raises=True)) == game_clock.CANNOT_TELL
    game_clock.reset()


def test_the_clock_is_still_kept_by_the_same_round_trip():
    """`read` and `session_state` are one reading in two shapes, not two readings."""
    game_clock.reset()
    ev = _Eval([f"ACT NOWMS={int(__import__('time').time() * 1000) + 11000}"])
    offset = game_clock.read(ev)
    assert ev.calls == 1
    assert offset is not None and 9000 < offset < 13000, offset
    game_clock.reset()


# -- what the panel says about it --------------------------------------------

def _words(key, **fmt):
    """A translator that hands back the key, so a test reads what was ASKED for."""
    return key


def test_a_fresh_profile_is_amber_before_anything_has_read_it():
    health = ProfileHealth()
    assert health.colour == ph.WARN
    assert health.message().key == "health.unread"
    assert health.read_at == 0.0


def test_the_tooltip_names_every_reading_that_decided_the_colour():
    """A dot with no explanation cannot say whether to fix the client or the daemon."""
    health = ProfileHealth()
    health.update(_Probe(game_link.ONLINE), warm=True, stale=True,
                  session=game_clock.CANNOT_TELL, kicked=False)
    said = health.lines(_words)
    assert said[0] == "health.daemon_stale"
    assert any(line.startswith("health.tip.game:") for line in said), said
    assert any("daemon.stale" in line for line in said), said
    assert any("health.unasked" in line for line in said), said


def test_the_wording_follows_the_rule_and_not_the_other_way_round():
    health = ProfileHealth()
    health.update(_Probe(game_link.ONLINE), warm=True, stale=False,
                  session=game_clock.IN_SESSION)
    assert health.colour == ph.OK
    assert health.message().key == "health.ok"
    state = health.state(_words)
    assert state["colour"] == ph.OK and state["reason"] == ph.HEALTHY
    assert isinstance(state["tip"], list) and state["tip"]


def test_a_poll_that_raised_leaves_amber_and_keeps_what_it_knew():
    health = ProfileHealth()
    health.update(_Probe(game_link.ONLINE, text="online (pid 1)"), warm=True,
                  stale=False, session=game_clock.IN_SESSION)
    health.failed(RuntimeError("psutil refused"))
    assert health.colour == ph.WARN
    assert health.message().key == "health.unread"
    # The client's last sentence is still the newest thing anybody knows.
    assert any("online (pid 1)" in line for line in health.lines(_words))


def _run() -> int:
    failed = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        try:
            func()
            print(f"  ok   {name}")
        except Exception as exc:                          # noqa: BLE001
            failed += 1
            print(f"  FAIL {name}: {exc}")
    total = sum(1 for n, f in globals().items()
                if n.startswith("test_") and callable(f))
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run())

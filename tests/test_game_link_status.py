r"""Is the account online, or merely running? (task #1223)

A client that has been up since yesterday can lose its server session and go on looking
perfectly healthy: the window draws, the process is there, every Lua getter answers —
with yesterday's numbers — and the panel said «работает (pid …)» in green over an account
that had not spoken to the server since the small hours. An hour once went into "the
event has no attempts today" before anybody looked at the sockets.

That is the state pinned here. `panel/runtime/game_process.probe` answers two questions
instead of one — the process exists, and the server is still on the other end — and the
second one has four answers, not two:

  * ONLINE — an ESTABLISHED connection to the game server. The only green one.
  * LOST — the process is alive and its sockets are half-closed: the server hung up.
  * UNKNOWN — the process is alive and its sockets say nothing: one still starting up,
    or a machine that will not attribute them. Never to be read as a fault.
  * OFFLINE — no client at all.

And one thing that must not change: `running` stays true through a LOST link. The
watchdog acts on it, and a client that lost the server is not a client to kill and
relaunch behind the person's back.

No Tk, no game, no Windows: the process list and the socket table are the seams
(`game_link._pids_by_name` / a stand-in `psutil`), stubbed here.

**The stubs go on `tools/lib/game_link.py`, and the assertions on the panel** — which is
the shape of #1260 and worth keeping that way round. The reading lives in the shared
module now (so that everything which SENDS can ask it, not only the layer which draws
it), and `panel/runtime/game_process.py` is the wording on top. Stubbing the machine in
one place and reading the answer through the other is what proves there is still only
one implementation: put the stubs on the panel instead and this file would pass over a
second copy of the rule.

    C:\Python312\python.exe tests\test_game_link_status.py
    python3 tests/test_game_link_status.py      # SKIP: the runtime package needs tkinter
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import game_link                                 # noqa: E402 — the reading

try:                                             # the WSL python3 has no tkinter, and
    from panel.runtime import game_process as gp   # the runtime package imports it
except Exception as _exc:                        # noqa: BLE001
    gp, _WHY = None, _exc


class _Conn:
    """One row of the socket table, as psutil hands it over."""

    def __init__(self, pid, status, port=10012, ip="203.0.113.7") -> None:
        self.pid = pid
        self.status = status
        self.raddr = None if port is None else _Addr(port, ip)


class _Addr:
    def __init__(self, port, ip="203.0.113.7") -> None:
        self.ip, self.port = ip, port


class _Machine:
    """One client and one socket table: what runs, and what its sockets are doing.

    ``conns`` is the WHOLE table, as `psutil.net_connections` returns it — including the
    rows belonging to nobody this test cares about, because that is the shape the real
    one comes back in and the pid filter is half of what is being tested.
    """

    def __init__(self, pids, conns=()) -> None:
        self.pids, self.conns = list(pids), list(conns)

    def __enter__(self):
        self._saved = (game_link._pids_by_name, game_link._pids_in_session,
                       game_link.sessions, game_link.own_session,
                       sys.modules.get("psutil"))
        game_link._pids_by_name = lambda exe: list(self.pids)
        game_link.own_session = lambda: None  # a machine with no sessions: the name is all
        # …and the same client, seen as the second account's — so the six sentences
        # below («в сессии {user}» and not) come off one machine rather than two.
        game_link.sessions = lambda: [{"id": 4, "user": "player2",
                                       "state": game_link.WTS_DISCONNECTED}]
        game_link._pids_in_session = lambda exe, session: list(self.pids)
        sys.modules["psutil"] = self._psutil()
        # The socket table is shared between open profiles and cached for a couple of
        # seconds (#1226), so a case that did not drop it would be reading the machine
        # the PREVIOUS case set up. Both ends, so nothing leaks either way.
        game_link.forget_machine_state()
        return self

    def _psutil(self):
        table = self.conns

        class _Fake:
            @staticmethod
            def net_connections(kind="tcp"):
                return list(table)

        return _Fake

    def __exit__(self, *exc):
        (game_link._pids_by_name, game_link._pids_in_session, game_link.sessions,
         game_link.own_session, held) = self._saved
        if held is None:
            sys.modules.pop("psutil", None)
        else:
            sys.modules["psutil"] = held
        game_link.forget_machine_state()
        return False


# -- the four answers --------------------------------------------------------

def test_an_established_connection_is_the_only_green_one():
    with _Machine([111], [_Conn(111, "ESTABLISHED")]):
        found = gp.probe("LastWar.exe")
    assert found.running is True and found.link == gp.ONLINE, found
    assert found.online and found.conn == "203.0.113.7:10012", found.conn
    assert found.message.key == "game.st.running_at", found.message.key


def test_a_half_closed_socket_is_the_state_that_used_to_read_as_running():
    """CLOSE_WAIT: the server said goodbye and the client never noticed."""
    with _Machine([111], [_Conn(111, "CLOSE_WAIT"), _Conn(111, "CLOSE_WAIT")]):
        found = gp.probe("LastWar.exe")
    assert found.link == gp.LOST, found.link
    assert found.dead == 2 and found.conn is None, found
    assert found.message.key == "game.st.lost", found.message.key
    # …and the process IS still running. The watchdog reads this half and must not be
    # told the client is gone: killing and relaunching it is the person's call.
    assert found.running is True, "a lost link is not a dead client"


def test_sockets_that_cannot_be_seen_are_not_a_fault():
    """A machine that will not attribute this client's sockets: the table comes back
    with no pid of ours in it. (This one DOES attribute a second account's — read live
    — but that is its answer, not a guarantee, and a permanent red would be wrong.)"""
    with _Machine([111], [_Conn(None, "ESTABLISHED"), _Conn(999, "CLOSE_WAIT")]):
        found = gp.probe("LastWar.exe")
    assert found.link == gp.UNKNOWN, found.link
    assert found.running is True and found.dead == 0, found
    assert found.message.key == "game.st.running", found.message.key


def test_a_client_that_is_still_starting_is_not_a_lost_one():
    """Web sockets and its own loopback pair, no game socket yet — a launch takes about
    45 seconds, and calling that «связь потеряна» would put a red strip and a log line
    after every scheduled restart."""
    with _Machine([111], [_Conn(111, "ESTABLISHED", port=443),
                          _Conn(111, "ESTABLISHED", port=63204, ip="127.0.0.1")]):
        found = gp.probe("LastWar.exe")
    assert found.link == gp.UNKNOWN and found.dead == 0, found


def test_no_client_at_all_is_offline_however_the_sockets_look():
    with _Machine([], [_Conn(111, "ESTABLISHED")]):
        found = gp.probe("LastWar.exe")
    assert found.running is False and found.link == gp.OFFLINE, found
    assert found.message.key == "game.st.not_found", found.message.key


# -- what counts as a socket of the game -------------------------------------

def test_the_web_ports_are_not_the_game():
    """The client talks to a CDN over 443 all day; neither state says anything."""
    with _Machine([111], [_Conn(111, "ESTABLISHED", port=443),
                          _Conn(111, "CLOSE_WAIT", port=80)]):
        found = gp.probe("LastWar.exe")
    assert found.link == gp.UNKNOWN, found.link


def test_a_cleanly_closed_connection_is_not_a_lost_one():
    """TIME_WAIT is what an ordinary reconnect leaves behind, and it is not a fault."""
    with _Machine([111], [_Conn(111, "TIME_WAIT"), _Conn(111, "ESTABLISHED")]):
        assert gp.probe("LastWar.exe").link == gp.ONLINE
    with _Machine([111], [_Conn(111, "TIME_WAIT")]):
        # No proof either way — «не знаю», not «связь потеряна». A client that
        # reconnects every few hours would otherwise look broken after every one.
        assert gp.probe("LastWar.exe").link == gp.UNKNOWN


def test_the_established_one_wins_over_the_stale_ones_beside_it():
    """A healthy client KEEPS half-closed sockets — six of them, in the first live
    reading: it greets several gateways while logging in and leaves the losers hanging.
    So a live connection is asked for first, and a pile of dead ones beside it is an
    ordinary afternoon rather than a fault."""
    table = [_Conn(111, "CLOSE_WAIT", ip=f"203.0.113.{n}") for n in range(1, 7)]
    with _Machine([111], table + [_Conn(111, "ESTABLISHED")]):
        found = gp.probe("LastWar.exe")
    assert found.link == gp.ONLINE and found.dead == 0, found


def test_a_live_socket_of_ANOTHER_service_does_not_vouch_for_a_dead_game():
    """The night this cost, in one table (#1266, docs/…/server-link-status.md §2.2).

    The client keeps a chat / control channel on a port of its own. It survived while
    every game socket went half-closed, and «an established socket outranks a pile of
    dead ones» — true when they are ONE conversation — handed back `online, dead=0`
    without ever reaching the count. The panel wrote `link=online` all night, the
    recovery never counted a strike, the gate let every scenario through, and every
    timer pressed into a socket the far end had closed.
    """
    dead_game = [_Conn(111, "CLOSE_WAIT", port=10012, ip=f"203.0.113.{n}")
                 for n in range(1, 7)]
    chat = _Conn(111, "ESTABLISHED", port=17935, ip="198.51.100.4")
    with _Machine([111], dead_game + [chat]):
        found = gp.probe("LastWar.exe")
    assert found.link == gp.LOST, f"the control channel vouched for the game: {found}"
    assert found.dead == 6, found.dead
    assert found.conn is None, found.conn


def test_the_same_two_services_on_a_HEALTHY_client_are_still_green():
    """…and the other half, which is what stops the cure being worse than the disease.

    The live reading of a healthy client, exactly: five half-closed game sockets (the
    losers of the gateway race), one established game socket, and the control channel
    beside them. A rule that called this «lost» would restart a perfectly good client
    every ten minutes, which is the one failure worse than the one above.

    The endpoint is the GAME's, not whichever row psutil happened to hand over first —
    the strip spent that night naming the chat host as the server.
    """
    table = [_Conn(111, "CLOSE_WAIT", port=10012, ip=f"203.0.113.{n}")
             for n in range(1, 6)]
    table += [_Conn(111, "ESTABLISHED", port=10012, ip="203.0.113.9"),
              _Conn(111, "ESTABLISHED", port=17935, ip="198.51.100.4")]
    with _Machine([111], table):
        found = gp.probe("LastWar.exe")
    assert found.link == gp.ONLINE, found
    assert found.conn == "203.0.113.9:10012", f"the endpoint is not the game's: {found.conn}"


def test_the_verdict_is_taken_per_conversation_and_not_per_process():
    """The rule under both cases above, asked of the classifier directly.

    A conversation is a remote PORT: the client greets several gateways on one, so
    grouping by address would put each loser in a box of its own and call five of them
    dead. And a dead conversation is never outvoted by a live one — the two errors are
    not symmetric, a wrong `online` being silent and a wrong `lost` being one restart.
    """
    def conn(port, status, ip="203.0.113.7"):
        return _Conn(111, status, port=port, ip=ip)

    talks = game_link.conversations([conn(10012, "CLOSE_WAIT", "203.0.113.1"),
                                     conn(10012, "CLOSE_WAIT", "203.0.113.2"),
                                     conn(17935, "ESTABLISHED", "198.51.100.4")])
    assert talks == {10012: (None, 2), 17935: ("198.51.100.4:17935", 0)}, talks
    assert game_link.classify([conn(10012, "CLOSE_WAIT"),
                               conn(17935, "ESTABLISHED")])[0] == game_link.LOST
    # …and one conversation answering for itself is still the ordinary afternoon.
    assert game_link.classify([conn(10012, "CLOSE_WAIT", "203.0.113.1"),
                               conn(10012, "ESTABLISHED", "203.0.113.2")])[0] \
        == game_link.ONLINE


def test_the_client_talking_to_ITSELF_is_not_a_live_account():
    """The trap the first live reading walked into.

    A running client holds a pair of ESTABLISHED sockets to 127.0.0.1, both ends its
    own, and they survive the server hanging up — nothing about them involves the
    server. Taken as proof of a live account they would keep the strip green over
    exactly the client this whole reading exists to catch.
    """
    loop = [_Conn(111, "ESTABLISHED", port=63204, ip="127.0.0.1"),
            _Conn(111, "ESTABLISHED", port=63203, ip="127.0.0.1")]
    with _Machine([111], loop + [_Conn(111, "CLOSE_WAIT")]):
        found = gp.probe("LastWar.exe")
    assert found.link == gp.LOST, found.link
    assert found.conn is None, found.conn


# -- the old pair still answers ----------------------------------------------

def test_status_is_the_pair_it_always_was():
    """Everything that only presses buttons still asks `(running, label)`."""
    with _Machine([111], [_Conn(111, "CLOSE_WAIT")]):
        running, label = gp.status("LastWar.exe")
    assert running is True and label.key == "game.st.lost", label.key


# -- every word of it is a key the panel can say -----------------------------

def test_every_link_state_has_a_sentence_in_every_locale():
    seen = []
    for conns in ([_Conn(111, "ESTABLISHED")], [_Conn(111, "CLOSE_WAIT")], []):
        with _Machine([111], conns):
            seen.append(gp.probe("LastWar.exe").message)
            seen.append(gp.probe("LastWar.exe", user="player2").message)
    keys = [m.key for m in seen]
    assert len(set(keys)) == 6, keys        # three states, with and without a session
    root = Path(__file__).resolve().parents[1] / "panel" / "locales"
    for path in sorted(root.glob("*.json")):
        locale = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in keys if k not in locale]
        assert not missing, f"{path.name}: {missing}"
        for msg in seen:                    # …and it takes the values it is given
            locale[msg.key].format(**msg.fmt)


def test_the_phone_has_a_word_for_every_state_the_panel_can_report():
    """The pill on the phone is drawn from the same four ids (panel/web/static/app.js)."""
    root = Path(__file__).resolve().parents[1] / "panel"
    app = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")
    for state in (gp.ONLINE, gp.LOST, gp.UNKNOWN, gp.OFFLINE):
        assert f"{state}:" in app, f"the phone paints no pill for {state}"
    words = ["web.ui.link.online", "web.ui.link.lost", "web.ui.link.unknown"]
    for path in sorted((root / "locales").glob("*.json")):
        locale = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in words if k not in locale]
        assert not missing, f"{path.name}: {missing}"


# -- and the whole reading is askable WITHOUT the panel (#1260) --------------
#
# The four cases above go through `gp`, which is the panel wording what the shared
# module read. These go straight at the shared module, and they are named
# `test_the_reading_*` so that `_main` can still run them on a machine where the panel
# will not import at all — which is not a trick, it is the property being pinned. While
# the reading lived behind `panel.i18n.Message`, «ask before you send» was a rule that
# only held for whoever happened to be running the panel.

def test_the_reading_answers_with_no_front_end_at_all():
    with _Machine([111], [_Conn(111, "CLOSE_WAIT"), _Conn(111, "CLOSE_WAIT")]):
        found = game_link.probe("LastWar.exe")
    assert found.running is True and found.link == game_link.LOST, found
    assert found.pid == 111 and found.dead == 2 and found.conn is None, found
    assert found.online is False


def test_the_reading_imports_nothing_of_the_panel():
    """The one line that would quietly undo the move.

    A `from panel...` here and the shared module is panel-only again — importable by the
    layer that DRAWS and by nothing that SENDS, which is the state #1259 lost a day to.
    Prose may name the panel (and does); an import may not.
    """
    src = (ROOT / "tools" / "lib" / "game_link.py").read_text(encoding="utf-8")
    bad = [line for line in src.splitlines()
           if line.startswith(("import ", "from ")) and "panel" in line]
    assert not bad, bad


def test_the_reading_says_WHY_there_is_no_client_rather_than_just_that():
    """Three different «no client», and they want three different things done.

    `no_session` is «there is nowhere to look» — the watchdog must not answer it by
    starting a client on THIS desktop — and it is a different fact from «that session
    is up and empty», which is a client to start, and from «nothing here», which is
    the ordinary single-account case.
    """
    with _Machine([], []):
        assert game_link.probe("LastWar.exe").reason == game_link.NOT_FOUND
        assert game_link.probe("LastWar.exe", user="player2").reason \
            == game_link.SESSION_NOT_FOUND
        assert game_link.probe("LastWar.exe", user="nobody").reason \
            == game_link.NO_SESSION


def test_the_panel_has_a_sentence_for_every_one_of_those_reasons():
    """…and the words stay the panel's, in all eleven locales."""
    with _Machine([], []):
        keys = [gp.probe("LastWar.exe").message.key,
                gp.probe("LastWar.exe", user="player2").message.key,
                gp.probe("LastWar.exe", user="nobody").message.key]
    assert keys == ["game.st.not_found", "game.st.session_not_found",
                    "game.st.no_session"], keys
    root = Path(__file__).resolve().parents[1] / "panel" / "locales"
    for path in sorted(root.glob("*.json")):
        locale = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in keys + ["game.st.no_psutil", "game.st.probe_error"]
                   if k not in locale]
        assert not missing, f"{path.name}: {missing}"


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    if gp is None:
        # Not a skip of the whole file any more. The panel needs tkinter; the reading
        # needs nothing, and a machine that cannot import the panel is exactly where
        # that has to be true.
        print(f"  the runtime package will not import here: {_WHY}")
        print("  …running the panel-free half, which is the point of #1260")
        tests = [t for t in tests if t.__name__.startswith("test_the_reading_")]
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

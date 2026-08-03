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
  * UNKNOWN — the process is alive and its sockets say nothing, which is the ORDINARY
    state of a client in another Windows session and must never read as a fault.
  * OFFLINE — no client at all.

And one thing that must not change: `running` stays true through a LOST link. The
watchdog acts on it, and a client that lost the server is not a client to kill and
relaunch behind the person's back.

No Tk, no game, no Windows: the process list and the socket table are the seams
(`gp._pids_by_name` / a stand-in `psutil`), stubbed here.

    C:\Python312\python.exe tests\test_game_link_status.py
    python3 tests/test_game_link_status.py      # SKIP: the runtime package needs tkinter
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
        self._saved = (gp._pids_by_name, gp._pids_in_session, gp.sessions,
                       gp.own_session, sys.modules.get("psutil"))
        gp._pids_by_name = lambda exe: list(self.pids)
        gp.own_session = lambda: None       # a machine with no sessions: the name is all
        # …and the same client, seen as the second account's — so the six sentences
        # below («в сессии {user}» and not) come off one machine rather than two.
        gp.sessions = lambda: [{"id": 4, "user": "player2",
                                "state": gp.WTS_DISCONNECTED}]
        gp._pids_in_session = lambda exe, session: list(self.pids)
        sys.modules["psutil"] = self._psutil()
        return self

    def _psutil(self):
        table = self.conns

        class _Fake:
            @staticmethod
            def net_connections(kind="tcp"):
                return list(table)

        return _Fake

    def __exit__(self, *exc):
        (gp._pids_by_name, gp._pids_in_session, gp.sessions,
         gp.own_session, held) = self._saved
        if held is None:
            sys.modules.pop("psutil", None)
        else:
            sys.modules["psutil"] = held
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
    """A client in another user's session: the table comes back with no pid of ours."""
    with _Machine([111], [_Conn(None, "ESTABLISHED"), _Conn(999, "CLOSE_WAIT")]):
        found = gp.probe("LastWar.exe")
    assert found.link == gp.UNKNOWN, found.link
    assert found.running is True and found.dead == 0, found
    assert found.message.key == "game.st.running", found.message.key


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


def _main() -> int:
    if gp is None:
        print(f"  SKIP the runtime package will not import here: {_WHY}")
        return 0
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

r"""The server port is READ off the running client, never assumed (#1053).

The game's gateway port is not stable across builds — `:17935` historically, `:10012`
on the current client, and it will move again — and every failure that follows from a
stale number is SILENT. A capture pinned to the wrong port hears nothing and looks
exactly like «nobody is playing»; a socket matcher pinned to it finds no socket and
says «is the client on the world map?» about a client that is sitting on it.

**And the client is having more than one conversation.** The game rides its own port,
the chat / control channel another, and they live and die separately — which is the
whole of #1266, and the trap this file exists to keep shut. Two readings that look
convincing and are both wrong were tried against a LIVE client on 2026-08-07:

  * «most sockets wins» — the client showed six sockets on `:10012` and one on
    `:17935`, and a 25 s capture on each found `:10012` silent and `:17935` carrying
    alliance pushes. It was measured on a client whose game link was **dead**: the six
    were half-closed and the survivor was the control channel;
  * «the only established socket must be the game» — the same mistake from the other
    side, and exactly the night #1266 was bought with.

So the rule is `game_link`'s and there is no second copy of it here: a conversation is
a port, the game's is the one carrying the **half-closed losers of its own gateway
race**, and «cannot say» survives as far as the operator.

Runs anywhere: psutil is stubbed, so there is no game and no sockets.

    C:\Python312\python.exe tests\test_game_port_detection.py
    python3 tests/test_game_port_detection.py
"""
from __future__ import annotations

# OFFLINE, and the docstring above has always said so: psutil is stubbed, so there is no
# game and no sockets. It was declared `live` because the stub had a hole — `_uninstall`
# only forgot the fake, and the code under test then imported the REAL psutil and read
# this desktop's client — which made one case fail on any machine that has both. The hole
# is closed below; the tier follows the file back to what it actually needs, which is
# nothing. See tools/run_tests.py.
TIER = "offline"

import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import game_paths                                          # noqa: E402
import map_capture                                         # noqa: E402
import steal_via_socket                                    # noqa: E402


class _Addr:
    def __init__(self, port, ip="10.0.0.1"):
        self.port, self.ip = port, ip


class _Conn:
    def __init__(self, pid, rport, lport=55000, status="ESTABLISHED",
                 rip="198.51.100.7"):
        self.pid, self.status = pid, status
        self.laddr, self.raddr = _Addr(lport), _Addr(rport, rip)


class _Proc:
    def __init__(self, pid, name):
        self.pid, self.info = pid, {"pid": pid, "name": name}


def _install(procs, conns):
    mod = types.ModuleType("psutil")
    mod.process_iter = lambda attrs=None: list(procs)
    mod.net_connections = lambda kind="tcp": list(conns)
    sys.modules["psutil"] = mod
    return mod


def _uninstall():
    # `None` in `sys.modules`, not a pop: popping it only forgets the FAKE, and the next
    # `import psutil` inside the code under test finds the real one — which on a machine
    # that has psutil installed and a client running reads that client's live sockets.
    # «No client, no psutil» then answered with this desktop's ports, and the one test
    # that says what «unread» means failed on the very machine the tool runs on. `None`
    # is the documented way to make an import raise ImportError.
    sys.modules["psutil"] = None
    steal_via_socket.set_game_port(None)            # re-open the probe for the next test


def _healthy(pid=7, game=10012, control=17935):
    """What a live client's table looks like: the game, its race losers, the control
    channel, the loopback pair it keeps to itself, and the web sockets."""
    return [_Conn(pid, game, lport=60385),
            _Conn(pid, game, lport=60299, status="CLOSE_WAIT"),
            _Conn(pid, game, lport=60302, status="CLOSE_WAIT"),
            _Conn(pid, control, lport=60388),
            _Conn(pid, 60294, lport=60295, rip="127.0.0.1"),
            _Conn(pid, 60295, lport=60294, rip="127.0.0.1"),
            _Conn(pid, 443, lport=60411), _Conn(pid, 80, lport=60307)]


# ---------------------------------------------------------------------------
def test_the_live_port_is_read_not_assumed():
    """A live client on :10012 — nothing may answer with the written-down fallback."""
    _install([_Proc(7, "lastwar.exe")], _healthy())
    try:
        assert map_capture.primary_game_port() == 10012
        assert steal_via_socket.game_port() == 10012
        assert steal_via_socket.game_port() != game_paths.game_port(), \
            "the fallback answered while the client was there to be asked"
    finally:
        _uninstall()


def test_the_game_is_told_by_its_gateway_race_not_by_counting():
    """The control channel has one live socket too; only the game leaves losers."""
    _install([_Proc(7, "lastwar.exe")], _healthy())
    try:
        assert map_capture.detect_game_ports() == {10012, 17935}, \
            "a capture must hear both conversations"
        assert map_capture.primary_game_port() == 10012, \
            "the matcher picked a conversation that is not the game's"
    finally:
        _uninstall()


def test_the_count_of_sockets_is_not_evidence():
    """Measured, not reasoned: the busier port was the one carrying nothing.

    Six sockets on :10012 and one on :17935, and 25 s of capture on each found the
    six-socket side silent. «Most sockets wins» is not a tie-break — those six were
    half-closed, which makes them evidence of the opposite thing.
    """
    conns = ([_Conn(7, 10012, lport=60299 + i, status="CLOSE_WAIT") for i in range(6)]
             + [_Conn(7, 17935, lport=60385)])
    _install([_Proc(7, "lastwar.exe")], conns)
    try:
        assert map_capture.primary_game_port() != 17935, \
            "the control channel was handed over as the game — the #1266 night again"
        assert map_capture.primary_game_port() is None, \
            "a stranded client has no game socket to point at, and must say so"
    finally:
        _uninstall()


def test_a_stranded_client_is_not_a_reading_of_a_healthy_one():
    """The live table on 2026-08-07 00:45, in full: this is what «lost» looks like.

    `game_link.probe()` said `link='lost', dead=6` at the same moment, and a matcher
    that answered :17935 here would write into the chat channel.
    """
    conns = ([_Conn(7, 10012, lport=60299 + i, status="CLOSE_WAIT") for i in range(6)]
             + [_Conn(7, 17935, lport=60385),
                _Conn(7, 60294, lport=60295, rip="127.0.0.1"),
                _Conn(7, 60295, lport=60294, rip="127.0.0.1"),
                _Conn(7, 443, lport=60411)])
    _install([_Proc(7, "lastwar.exe")], conns)
    try:
        assert map_capture.detect_game_ports() == {10012, 17935}, \
            "the dead conversation must stay in the filter — it is where the client returns"
        assert map_capture.primary_game_port() is None
        assert steal_via_socket.game_port() == game_paths.game_port(), \
            "an unreadable link must fall back loudly, not offer the control channel"
    finally:
        _uninstall()


def test_a_pid_asks_about_its_own_client():
    """Two accounts — a duplicated handle must not cross from one client to the other."""
    procs = [_Proc(7, "lastwar.exe"), _Proc(8, "lastwar.exe")]
    _install(procs, _healthy(7, game=10012) + _healthy(8, game=17935, control=10012))
    try:
        assert map_capture.primary_game_port(7) == 10012
        assert map_capture.primary_game_port(8) == 17935
        assert map_capture.detect_game_ports() == {10012, 17935}, \
            "machine-wide is still machine-wide"
    finally:
        _uninstall()


def test_web_sockets_are_never_the_game():
    """The client keeps HTTP/TLS open for assets and translation all day."""
    _install([_Proc(7, "lastwar.exe")],
             [_Conn(7, 443), _Conn(7, 443, lport=55001), _Conn(7, 80, lport=55002)])
    try:
        assert map_capture.detect_game_ports() == set()
        assert map_capture.primary_game_port() is None
    finally:
        _uninstall()


def test_the_client_talking_to_itself_is_not_a_gateway():
    """The loopback pair survives the server hanging up — counting it is the lie."""
    _install([_Proc(7, "lastwar.exe")],
             [_Conn(7, 58950, lport=58949, rip="127.0.0.1"),
              _Conn(7, 58949, lport=58950, rip="127.0.0.1")])
    try:
        assert map_capture.detect_game_ports() == set()
        assert map_capture.primary_game_port() is None
    finally:
        _uninstall()


def test_the_dead_conversation_stays_in_the_capture_filter():
    """A capture started against a stranded client must survive its reconnect."""
    _install([_Proc(7, "lastwar.exe")],
             [_Conn(7, 10012, status="CLOSE_WAIT")])
    try:
        assert map_capture.detect_game_ports() == {10012}
        assert map_capture.primary_game_port() is None, \
            "half-closed is not something to point a send at"
    finally:
        _uninstall()


def test_nothing_to_read_falls_back_and_says_so():
    """No client, no psutil — the fallback answers, and None is what «unread» means."""
    _uninstall()                                    # no psutil at all
    assert map_capture.detect_game_ports() == set()
    assert map_capture.primary_game_port() is None
    assert steal_via_socket.game_port() == game_paths.game_port()


def test_a_fallback_is_never_cached():
    """The client may not be up YET; a probe that failed once must not pin the run."""
    _uninstall()
    assert steal_via_socket.game_port() == game_paths.game_port()
    _install([_Proc(7, "lastwar.exe")], _healthy())
    try:
        assert steal_via_socket.game_port() == 10012, \
            "the failed probe stuck and the tool went on matching the wrong port"
    finally:
        _uninstall()


def test_a_reading_is_cached_so_one_run_agrees_with_itself():
    """The BPF filter and the peer match must be the same number all run long."""
    _install([_Proc(7, "lastwar.exe")], _healthy())
    try:
        assert steal_via_socket.game_port() == 10012
        sys.modules.pop("psutil", None)             # the client goes away mid-run
        assert steal_via_socket.game_port() == 10012, \
            "the port changed under a run that had already started matching on it"
    finally:
        _uninstall()


def test_the_port_can_be_pinned_by_hand():
    """`--port` is the escape hatch for a machine whose socket table cannot be read."""
    _install([_Proc(7, "lastwar.exe")], _healthy())
    try:
        steal_via_socket.set_game_port(17935)
        assert steal_via_socket.game_port() == 17935, "an explicit --port lost to a probe"
    finally:
        _uninstall()


def test_a_capture_hears_something_even_with_nothing_to_read():
    """The default filter must degrade to «everything», never to a stale number.

    `watch_rally` is the tool the rule was written for: its BPF used to default to
    a port literal, so against a client that had moved it captured nothing at all —
    indistinguishable from an alliance that called no rallies.
    """
    src = (_REPO / "tools" / "dev" / "watch_rally.py").read_text(encoding="utf-8")
    assert 'default="port' not in src, "the BPF default is a written-down port again"
    assert "detect_game_ports()" in src, "the BPF default no longer asks the client"


def test_one_owner_for_the_socket_rule():
    """`map_capture` must not grow its own copy of «which socket is the game»."""
    src = (_REPO / "tools" / "lib" / "map_capture.py").read_text(encoding="utf-8")
    assert "game_link.conversations(" in src, "the conversation rule was re-implemented"
    assert "_is_loopback" not in src, "a second loopback rule is back in map_capture"


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

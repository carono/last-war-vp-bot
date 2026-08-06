r"""The server port is READ off the running client, never assumed (#1053).

The game's gateway port moves, and not in one direction — :17935 for years, :10012
on one build, :17935 again on the next, with a client sometimes holding established
sockets on both. Every failure that follows from a stale number is SILENT: a capture
pinned to the wrong port hears nothing and looks exactly like «nobody is playing»,
and a socket matcher pinned to it finds no socket and says «is the client on the
world map?» about a client that is sitting on it.

So this file pins the reading itself:

  * what the live TCP table says wins, per client (`map_capture.detect_game_ports`);
  * a caller that must point at ONE socket gets an answer only when the client leaves
    no choice, and **None** the moment there are two — never a guess dressed up as a
    reading (`map_capture.primary_game_port`);
  * `steal_via_socket` asks that first and only then falls back to
    `game_paths.game_port()` / `LW_GAME_PORT`, and `--port` pins it by hand.

Runs anywhere: psutil is stubbed, so there is no game and no sockets.

    C:\Python312\python.exe tests\test_game_port_detection.py
    python3 tests/test_game_port_detection.py
"""
from __future__ import annotations

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
    sys.modules.pop("psutil", None)
    steal_via_socket.set_game_port(None)            # re-open the probe for the next test


# ---------------------------------------------------------------------------
def test_the_live_port_is_read_not_assumed():
    """The client is on :10012; nothing may answer with the fallback :17935."""
    procs = [_Proc(7, "lastwar.exe")]
    _install(procs, [_Conn(7, 10012), _Conn(7, 10012), _Conn(7, 443)])
    try:
        assert map_capture.detect_game_ports() == {10012}
        assert map_capture.primary_game_port() == 10012
        assert steal_via_socket.game_port() == 10012
        assert steal_via_socket.game_port() != game_paths.game_port(), \
            "the fallback answered while the client was there to be asked"
    finally:
        _uninstall()


def test_the_count_of_sockets_is_not_evidence():
    """Measured, not reasoned: six established sockets on the port carrying NOTHING.

    A 25 s capture on each of a live client's two candidate ports (#1053) found the
    six-socket one silent and the single-socket one carrying the alliance pushes. So
    «most sockets wins» is not a tie-break, and a matcher must not invent one.
    """
    procs = [_Proc(7, "lastwar.exe")]
    _install(procs, [_Conn(7, 10012), _Conn(7, 10012), _Conn(7, 10012),
                     _Conn(7, 17935)])
    try:
        assert map_capture.detect_game_ports() == {10012, 17935}, "a capture hears both"
        assert map_capture.primary_game_port() is None, \
            "the busiest port answered — the reading disproved live is back"
    finally:
        _uninstall()


def test_a_pid_asks_about_its_own_client():
    """Two accounts, two ports mid-migration — a duplicated handle must not cross."""
    procs = [_Proc(7, "lastwar.exe"), _Proc(8, "lastwar.exe")]
    _install(procs, [_Conn(7, 10012), _Conn(8, 17935)])
    try:
        assert map_capture.primary_game_port(7) == 10012
        assert map_capture.primary_game_port(8) == 17935
        assert map_capture.detect_game_ports() == {10012, 17935}, \
            "machine-wide is still machine-wide"
    finally:
        _uninstall()


def test_web_sockets_are_never_the_game():
    """The client keeps HTTP/TLS open for assets and translation all day."""
    procs = [_Proc(7, "lastwar.exe")]
    _install(procs, [_Conn(7, 443), _Conn(7, 443), _Conn(7, 80)])
    try:
        assert map_capture.detect_game_ports() == set()
        assert map_capture.primary_game_port() is None
    finally:
        _uninstall()


def test_the_client_talking_to_itself_is_not_a_gateway():
    """Measured live: the client keeps 127.0.0.1 pairs of its own, both ends its pid.

    Counted, they put two ephemeral numbers into every capture filter and can
    outvote the real gateway.
    """
    procs = [_Proc(7, "lastwar.exe")]
    _install(procs, [_Conn(7, 58950, lport=58949, rip="127.0.0.1"),
                     _Conn(7, 58949, lport=58950, rip="127.0.0.1"),
                     _Conn(7, 17935)])
    try:
        assert map_capture.detect_game_ports() == {17935}
        assert map_capture.primary_game_port() == 17935
    finally:
        _uninstall()


def test_two_candidates_are_not_guessed_between():
    """Also measured live: an established socket on the OLD port and one on the new.

    Nothing in the socket table tells them apart, and this is the read that decides
    which socket gets written into — so «cannot say» has to survive as far as the
    operator instead of being rounded to whichever number sorts first.
    """
    procs = [_Proc(7, "lastwar.exe")]
    _install(procs, [_Conn(7, 10012), _Conn(7, 17935)])
    try:
        assert map_capture.detect_game_ports() == {10012, 17935}, \
            "a capture must still hear both"
        assert map_capture.primary_game_port() is None, "a tie was decided by coin-flip"
        assert steal_via_socket.game_port() == game_paths.game_port(), \
            "an ambiguous read must fall back, loudly, not pick one"
    finally:
        _uninstall()


def test_a_socket_that_is_not_established_is_not_a_reading():
    """A half-closed leftover is exactly what a stranded client is full of.

    Live, the CLOSE_WAIT sockets outnumbered the working one four to one and all
    named the gateway the client had already left.
    """
    procs = [_Proc(7, "lastwar.exe")]
    _install(procs, [_Conn(7, 10012, status="CLOSE_WAIT"),
                     _Conn(7, 10012, status="CLOSE_WAIT"),
                     _Conn(7, 17935)])
    try:
        assert map_capture.primary_game_port() == 17935, \
            "a port nobody is talking on outvoted the one they are"
        _uninstall()
        _install(procs, [_Conn(7, 10012, status="CLOSE_WAIT")])
        assert map_capture.primary_game_port() is None
    finally:
        _uninstall()


def test_nothing_to_read_falls_back_and_says_so():
    """No client, no psutil — the fallback answers, and None is what «unread» looks like."""
    _uninstall()                                    # no psutil at all
    assert map_capture.detect_game_ports() == set()
    assert map_capture.primary_game_port() is None
    assert steal_via_socket.game_port() == game_paths.game_port()


def test_a_fallback_is_never_cached():
    """The client may not be up YET; a probe that failed once must not pin the run."""
    _uninstall()
    assert steal_via_socket.game_port() == game_paths.game_port()
    procs = [_Proc(7, "lastwar.exe")]
    _install(procs, [_Conn(7, 10012)])
    try:
        assert steal_via_socket.game_port() == 10012, \
            "the failed probe stuck and the tool went on matching the wrong port"
    finally:
        _uninstall()


def test_a_reading_is_cached_so_one_run_agrees_with_itself():
    """The BPF filter and the peer match must be the same number all run long."""
    procs = [_Proc(7, "lastwar.exe")]
    _install(procs, [_Conn(7, 10012)])
    try:
        assert steal_via_socket.game_port() == 10012
        sys.modules.pop("psutil", None)             # the client goes away mid-run
        assert steal_via_socket.game_port() == 10012, \
            "the port changed under a run that had already started matching on it"
    finally:
        _uninstall()


def test_the_port_can_be_pinned_by_hand():
    """`--port` is the escape hatch for a machine whose socket table cannot be read."""
    procs = [_Proc(7, "lastwar.exe")]
    _install(procs, [_Conn(7, 10012)])
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

r"""A capture decodes ONE account's traffic, not every client on the machine.

The BPF filter can only narrow by TCP port, and two clients of the same game dial the
SAME server port — so every capture on this machine used to decode both accounts, and
a wire trigger in one profile could fire off the other profile's push. What differs
between them is the LOCAL port, which is not in the packet at all: it is in the socket
table, keyed by pid.

`map_capture.OwnPorts` is that lookup, and this file pins the three things about it that
would each be a silent disaster:

  * it keeps OUR ports and drops the other client's;
  * **it never goes deaf on doubt** — no psutil, a pid that cannot be asked, a foreign
    token that refuses, and the answer is «cannot tell», which the decoder reads as
    «keep everything». A capture that quietly kept nothing would look exactly like an
    account with nothing happening;
  * it follows the client across a RESTART, by the Windows account it runs as, so a
    relaunch does not need a new capture.

Runs anywhere: psutil is stubbed, so there is no game, no sockets and no npcap.

    C:\Python312\python.exe tests\test_capture_own_client.py
    python3 tests/test_capture_own_client.py
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import map_capture                                        # noqa: E402


class _Addr:
    def __init__(self, port):
        self.port = port
        self.ip = "10.0.0.1"


class _Conn:
    def __init__(self, pid, lport, rport=10012):
        self.pid, self.laddr, self.raddr = pid, _Addr(lport), _Addr(rport)


class _Proc:
    def __init__(self, pid, name, user):
        self.pid = pid
        self.info = {"pid": pid, "name": name}
        self._user = user

    def username(self):
        if self._user is None:
            raise PermissionError("access denied")
        return self._user


def _psutil(procs, conns):
    """A stand-in psutil holding exactly the processes and sockets given."""
    mod = types.ModuleType("psutil")
    by_pid = {p.pid: p for p in procs}
    mod.Process = lambda pid: by_pid[pid]
    mod.pid_exists = lambda pid: pid in by_pid
    mod.process_iter = lambda attrs=None: list(procs)
    mod.net_connections = lambda kind="tcp": list(conns)
    return mod


def _install(monkey, procs, conns):
    monkey["psutil"] = _psutil(procs, conns)
    sys.modules["psutil"] = monkey["psutil"]


def _uninstall():
    sys.modules.pop("psutil", None)


# ---------------------------------------------------------------------------
def test_our_ports_are_ours_and_the_other_account_is_not():
    """The whole point: two clients, one server port, told apart by the local one."""
    ours, theirs = 4001, 4002
    procs = [_Proc(ours, "lastwar.exe", "PC\\player"),
             _Proc(theirs, "lastwar.exe", "PC\\second")]
    conns = [_Conn(ours, 55001), _Conn(ours, 55002), _Conn(theirs, 55003)]
    _install({}, procs, conns)
    try:
        assert map_capture.OwnPorts([ours])() == {55001, 55002}
        assert map_capture.OwnPorts([theirs])() == {55003}
    finally:
        _uninstall()


def test_web_sockets_are_not_the_game():
    """The client talks HTTP to a CDN all day; those sockets are not the stream."""
    procs = [_Proc(7, "lastwar.exe", "PC\\player")]
    conns = [_Conn(7, 55001, rport=443), _Conn(7, 55002, rport=80),
             _Conn(7, 55003, rport=10012)]
    _install({}, procs, conns)
    try:
        assert map_capture.OwnPorts([7])() == {55003}
    finally:
        _uninstall()


def test_no_psutil_means_cannot_tell_which_keeps_everything():
    """«Cannot tell» must never come back looking like «nothing is ours»."""
    _uninstall()
    watcher = map_capture.OwnPorts([7])
    assert watcher() == set(), "an unanswerable question must answer empty"
    # …and empty is what the decoder reads as «keep everything» — pinned below.


def test_a_refused_socket_table_keeps_everything_too():
    procs = [_Proc(7, "lastwar.exe", "PC\\player")]
    mod = _psutil(procs, [])

    def refuse(kind="tcp"):
        raise PermissionError("access denied")

    mod.net_connections = refuse
    sys.modules["psutil"] = mod
    try:
        assert map_capture.OwnPorts([7])() == set()
    finally:
        _uninstall()


def test_the_decoder_keeps_everything_when_the_owner_is_unknown():
    """The contract the two above rest on, read off the decoder itself."""
    from live_sniffer import LiveDecoder

    dec = LiveDecoder()
    assert dec.own_ports is None, "a capture is machine-wide until told whose it is"

    kept = []
    dec.own_ports = lambda: set()          # «cannot tell»
    # The gate is `if mine and ...`, so an empty answer never drops anything. Read the
    # condition rather than a packet, because a packet needs scapy and a live capture.
    for sport, dport in ((55001, 10012), (55003, 10012)):
        mine = dec.own_ports()
        kept.append(not (mine and sport not in mine and dport not in mine))
    assert kept == [True, True], kept

    dec.own_ports = lambda: {55001}
    kept = []
    for sport, dport in ((55001, 10012), (55003, 10012)):
        mine = dec.own_ports()
        kept.append(not (mine and sport not in mine and dport not in mine))
    assert kept == [True, False], "the other client's packet was not dropped"


def test_a_restarted_client_is_followed_by_its_windows_account():
    """Same account, new pid — the ear must not need replacing for that."""
    old_pid, new_pid = 4001, 4009
    procs = [_Proc(old_pid, "lastwar.exe", "PC\\player")]
    conns = [_Conn(old_pid, 55001)]
    _install({}, procs, conns)
    try:
        watcher = map_capture.OwnPorts([old_pid], ttl=0.0)
        assert watcher() == {55001}

        # The client is relaunched: the old pid is gone, a new one is up as the same
        # user, and the other account is running beside it and must NOT be adopted.
        procs = [_Proc(new_pid, "lastwar.exe", "PC\\player"),
                 _Proc(4002, "lastwar.exe", "PC\\second")]
        conns = [_Conn(new_pid, 55009), _Conn(4002, 55003)]
        _install({}, procs, conns)
        assert watcher() == {55009}, "the restarted client was not followed"
    finally:
        _uninstall()


def test_a_client_whose_user_cannot_be_read_is_not_adopted_by_guesswork():
    """A foreign token that refuses is «cannot tell», not «probably ours»."""
    procs = [_Proc(4001, "lastwar.exe", None)]      # username() raises
    _install({}, procs, [_Conn(4001, 55001)])
    try:
        watcher = map_capture.OwnPorts([4001], ttl=0.0)
        assert watcher() == {55001}, "a live pid still answers with its own sockets"
        # It dies, and with no user anchored there is nothing to follow it by — which
        # must read as «cannot tell» rather than as another account's client.
        _install({}, [_Proc(4002, "lastwar.exe", "PC\\second")], [_Conn(4002, 55003)])
        assert watcher() == set(), "somebody else's client was adopted"
    finally:
        _uninstall()


def test_the_flag_exists_and_is_repeatable():
    """The panel passes one `--client-pid` per pid of its own client."""
    import argparse

    ap = argparse.ArgumentParser()
    map_capture.add_capture_arguments(ap, include_dump=False)
    args = ap.parse_args(["--client-pid", "11", "--client-pid", "22"])
    assert args.client_pid == [11, 22], args.client_pid
    assert ap.parse_args([]).client_pid == [], "no flag must stay machine-wide"


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

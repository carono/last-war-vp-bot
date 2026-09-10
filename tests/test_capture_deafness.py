r"""A capture that stops hearing the wire says so and is replaced (#2740).

«Сборщик секреток не собирает: стоя прямо на секретке, в грид ничего не попадает.»

Measured live on 2026-09-10: the panel's own sniffer reported ``0 map response(s)`` for
twenty-two minutes while a second process started by hand on the same machine, in the
same seconds, with the SAME narrowing flags, decoded 228 map responses, 26 248 tiles and
570 tasks off the same interface. The panel's child was alive the whole time: its ticker
printed, its checkpoint was rewritten (empty), its switch said «on». Its pcap handle had
simply stopped delivering — the client had re-dialled through another gateway — and
nothing anywhere could say so, because:

  * ``sniff_forever`` ended the thread when `sniff()` RETURNED, silently;
  * the progress line named map responses but never the packets underneath them, so
    «the map is not moving» and «this capture is deaf» printed the same sentence;
  * and `diagnose`, which knows the difference, only ever runs when the process EXITS,
    which a panel child does not do.

Three things are pinned here, one per hole:

  1. the sniffer loops — a capture that ends without being asked is re-opened;
  2. the deafness watch ends the process, so whoever started it starts a fresh one —
     but only while this account HAS a client, because a capture whose client is down is
     right to hear nothing;
  3. the progress line names what arrived from the wire, and does it without turning
     back into the per-second repeat #1332 removed.

No wire, no game, no npcap::

    python3 tests/test_capture_deafness.py
    C:\Python312\python.exe tests\test_capture_deafness.py
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import map_capture                                        # noqa: E402


class _Index:
    """Just enough of a MapIndex for the transport to talk to."""

    def __init__(self, ports=None) -> None:
        self.delivered = 0
        self.packets = 0
        self.own_ports = (lambda: ports) if ports is not None else None
        self.fed = 0

    def feed_packet(self, pkt, iface) -> None:
        self.fed += 1


def test_a_capture_that_ends_by_itself_is_opened_again():
    """The live fault: `sniff()` returned, the thread ended, nobody said anything."""
    index, stop = _Index(), threading.Event()
    rounds = []

    def fake_sniff(**kw):
        rounds.append(kw["filter"])
        if len(rounds) >= 3:
            stop.set()                    # the third round is asked to go

    sent = sys.modules.get("scapy.sendrecv")
    map_capture.REOPEN_SEC, keep = 0.0, map_capture.REOPEN_SEC
    try:
        sys.modules["scapy.sendrecv"] = type(sys)("scapy.sendrecv")
        sys.modules["scapy.sendrecv"].sniff = fake_sniff
        map_capture.sniff_forever(index, None, "tcp port 1", stop)
    finally:
        map_capture.REOPEN_SEC = keep
        if sent is None:
            sys.modules.pop("scapy.sendrecv", None)
        else:
            sys.modules["scapy.sendrecv"] = sent
    assert len(rounds) == 3, f"the capture was opened {len(rounds)} time(s), not 3"


def test_being_asked_to_stop_does_not_re_open():
    """`stop` is the ONE thing that ends the thread — and it must end it at once."""
    index, stop = _Index(), threading.Event()
    stop.set()
    rounds = []

    sent = sys.modules.get("scapy.sendrecv")
    try:
        sys.modules["scapy.sendrecv"] = type(sys)("scapy.sendrecv")
        sys.modules["scapy.sendrecv"].sniff = lambda **kw: rounds.append(1)
        map_capture.sniff_forever(index, None, "tcp port 1", stop)
    finally:
        if sent is None:
            sys.modules.pop("scapy.sendrecv", None)
        else:
            sys.modules["scapy.sendrecv"] = sent
    assert not rounds, "a capture already asked to stop was opened anyway"


def _watch(index, *, seconds, poll=0.01, bump=None):
    """Run the deafness watch until it exits or gives up. Returns the exit code, or None."""
    stop, out = threading.Event(), {}
    real_exit = map_capture.os._exit

    def fake_exit(code):
        out["code"] = code
        stop.set()
        raise SystemExit(code)            # unwinds the watch thread, never the test

    map_capture.os._exit = fake_exit
    try:
        def run():
            try:
                map_capture.deaf_watch(index, stop, seconds=seconds, poll=poll)
            except SystemExit:
                pass
        t = threading.Thread(target=run, daemon=True)
        t.start()
        if bump is not None:
            bump(index, stop)
        t.join(timeout=3.0)
    finally:
        map_capture.os._exit = real_exit
        stop.set()
    return out.get("code")


def test_a_deaf_capture_ends_so_a_fresh_one_is_started():
    code = _watch(_Index(ports={4242}), seconds=0.05)
    assert code == 3, f"a deaf capture exited with {code!r}, not 3"


def test_a_capture_that_is_hearing_the_wire_is_left_alone():
    index = _Index(ports={4242})

    def keep_talking(idx, stop):
        for _ in range(40):
            if stop.is_set():
                return
            idx.delivered += 1
            stop.wait(0.01)
        stop.set()                        # the run is over; the watch may go

    code = _watch(index, seconds=0.2, bump=keep_talking)
    assert code is None, "a capture hearing keepalives was ended anyway"


def test_a_capture_whose_client_is_down_is_left_alone():
    """The empty set is «asked, and this account has no client» — silence is the truth."""
    code = _watch(_Index(ports=set()), seconds=0.05)
    assert code is None, "a capture was ended for hearing nothing while its client was down"


def test_either_counter_moving_counts_as_hearing():
    """`delivered` and `packets` are watched as a PAIR.

    They fail apart: `delivered` is what npcap handed over, `packets` what survived
    parsing. A handle delivering frames this decoder throws away is a different fault
    with a different cure (`diagnose` names it), and ending the process would not fix
    it — so movement in either one means the wire is being heard.
    """
    index = _Index(ports={4242})

    def payload_only(idx, stop):
        for _ in range(40):
            if stop.is_set():
                return
            idx.packets += 1
            stop.wait(0.01)
        stop.set()

    code = _watch(index, seconds=0.2, bump=payload_only)
    assert code is None, "a capture whose payload counter was moving was ended anyway"


def test_the_progress_line_names_what_arrived_from_the_wire():
    for name in ("tools/secret_task_capture.py", "tools/dev/secret_mission_capture.py"):
        source = (_REPO / name).read_text(encoding="utf-8")
        assert "packet(s) from the wire" in source, \
            f"{name}: the progress line still cannot tell a still map from a deaf capture"
        assert "ticker.due((bool(index.delivered)" in source, \
            f"{name}: the wire must enter the signature as a state, never as a count"


def test_the_watch_survives_an_index_that_counts_neither():
    """A `LiveDecoder` scanner has no `delivered` — the watch must not die on it (#2741).

    `start_capture` arms this thread for whatever index it was handed, and only
    `MapIndex` counts what npcap delivered. Live in the panel's own log on 2026-09-10,
    every five minutes: `AttributeError: 'EventMonitor' object has no attribute
    'delivered'` — so the deafness watch that #2740 added was, for those scanners, not
    running at all.
    """
    import threading
    import time
    import types

    mc = map_capture
    plain = types.SimpleNamespace()            # neither counter, no `own_ports`
    stop = threading.Event()
    done = threading.Event()

    def run():
        try:
            mc.deaf_watch(plain, stop, seconds=9999, poll=0.01, exit_code=0)
        finally:
            done.set()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    time.sleep(0.1)
    assert worker.is_alive(), "the watch died on an index that counts neither"
    stop.set()
    done.wait(2)



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

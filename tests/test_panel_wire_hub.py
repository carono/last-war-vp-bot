r"""One wire ear per profile, and everything that wants a push subscribes to it.

Every enabled wire trigger used to be its own capture process: its own npcap handle on
the same interface, its own full decode of every packet the game sent, to read one
command name out of it. The panel holds a runtime per open profile, so the bill was
listeners × profiles and every term of it was the same work repeated.

What this pins is the arithmetic and the two things that can go quietly wrong when many
ears become one:

  * **one child, whatever the number of subscribers**, and none at all before the first
    or after the last;
  * **a marker reaches every subscriber whose pattern matches, and nobody else** — a
    shared ear that delivered to the wrong listener would press in one profile's game
    for another's push;
  * **the ear closing is told to everyone**, because with a child each, a listener that
    died was one listener, and now it is all of them.

Runs anywhere: the child is a stand-in, so there is no capture, no npcap and no game.

    C:\Python312\python.exe tests\test_panel_wire_hub.py
    python3 tests/test_panel_wire_hub.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.runtime.wire import WireHub                    # noqa: E402
from panel.triggers import FIRE_MARKER                    # noqa: E402


class _Child:
    """A stand-in for the capture: remembers its command line, never runs anything."""

    def __init__(self, cmd, on_line, on_exit):
        self.cmd, self.on_line, self.on_exit = cmd, on_line, on_exit
        self.stopped = False
        self.started = False

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.stopped = True

    def patterns(self):
        return [self.cmd[i + 1] for i, a in enumerate(self.cmd) if a == "--match"]


class _Children:
    def __init__(self):
        self.spawned: list = []

    def python(self):
        return "python"

    def spawn(self, tag, cmd, *, on_line=None, on_exit=None, **kw):
        child = _Child(cmd, on_line, on_exit)
        self.spawned.append(child)
        return child


class _Dbg:
    def error(self, *a, **kw): ...
    def info(self, *a, **kw): ...
    def debug(self, *a, **kw): ...


class _Settings:
    """Enough of the binder for `game_process.profile_pids` to answer «cannot tell»."""

    def opt_str(self, key, default=""):
        return ""

    def opt_bool(self, key, default=False):
        return False


class _Rt:
    def __init__(self):
        self.children = _Children()
        self.settings = _Settings()
        self.said: list = []

    def say(self, tag, key, **fmt):
        self.said.append((tag, key, fmt))

    def dbg(self, component="panel"):
        return _Dbg()


def _hub():
    rt = _Rt()
    return rt, WireHub(rt)


def _fire(hub, command):
    """Feed the hub the marker line its child would have printed."""
    return hub._on_line(f"{FIRE_MARKER}\t{command}")


# ---------------------------------------------------------------------------
def test_the_ear_is_told_whose_client_it_is():
    """A shared ear must still be ONE account's — see tests/test_capture_own_client.py.

    Two clients of the same game dial the same server port, so the capture cannot tell
    them apart by filter and every profile's ear heard both. The hub names its profile's
    pids on the command line; what it must NOT do is invent one when the answer is «could
    not tell», because the capture reads no flag as «keep everything» rather than as
    «keep nothing» — and an ear that went deaf would look exactly like a quiet account.

    `profile_pids` is stubbed on purpose: what it answers depends on whether a game
    happens to be running on the machine the tests are on, and that must not decide
    whether this passes.
    """
    from panel.runtime import game_process, wire as wiremod

    real = game_process.profile_pids
    try:
        wiremod.game_process.profile_pids = lambda settings: [4001, 4002]
        rt, hub = _hub()
        hub.subscribe("al.help.new", lambda c: None)
        cmd = rt.children.spawned[-1].cmd
        pids = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--client-pid"]
        assert pids == ["4001", "4002"], cmd

        wiremod.game_process.profile_pids = lambda settings: []
        rt, hub = _hub()
        hub.subscribe("al.help.new", lambda c: None)
        cmd = rt.children.spawned[-1].cmd
        assert "--match" in cmd, cmd
        assert "--client-pid" not in cmd, "a pid was invented out of «cannot tell»"
    finally:
        wiremod.game_process.profile_pids = real


def test_no_subscriber_no_capture():
    """A profile with every trigger switched off must not spawn an ear at all."""
    rt, hub = _hub()
    assert rt.children.spawned == [], "an ear was opened with nobody listening"
    assert hub.listeners() == 0


def test_many_listeners_one_child():
    """THE WHOLE POINT: the process count stops following the listener count."""
    rt, hub = _hub()
    offs = [hub.subscribe(p, lambda c: None)
            for p in ("al.help.new", "push.alliance.march", "push.world.point")]
    assert hub.listeners() == 3
    live = [c for c in rt.children.spawned if not c.stopped]
    assert len(live) == 1, f"{len(live)} captures for 3 listeners"
    assert sorted(live[0].patterns()) == ["al.help.new", "push.alliance.march",
                                          "push.world.point"], live[0].patterns()

    # …and a hundred of them are still one, which is the case the person was worried
    # about: hundreds of listeners across several profiles.
    offs += [hub.subscribe("cmd.%03d" % i, lambda c: None) for i in range(100)]
    live = [c for c in rt.children.spawned if not c.stopped]
    assert len(live) == 1, f"{len(live)} captures for {hub.listeners()} listeners"
    assert hub.listeners() == 103

    for off in offs:
        off()
    assert hub.listeners() == 0
    assert all(c.stopped for c in rt.children.spawned), "the ear outlived its listeners"


def test_two_subscribers_on_the_same_pattern_share_one_ear_and_both_hear():
    """Two triggers on one push is one pattern, one child, and two callbacks."""
    rt, hub = _hub()
    heard = []
    hub.subscribe("al.help.new", lambda c: heard.append(("a", c)))
    hub.subscribe("al.help.new", lambda c: heard.append(("b", c)))
    live = [c for c in rt.children.spawned if not c.stopped]
    assert len(live) == 1 and live[0].patterns() == ["al.help.new"], live[0].patterns()
    _fire(hub, "al.help.new")
    assert heard == [("a", "al.help.new"), ("b", "al.help.new")], heard


def test_a_marker_reaches_only_the_patterns_that_match():
    """A shared ear must not press one listener's errand on another's push."""
    rt, hub = _hub()
    heard = {"help": [], "march": []}
    hub.subscribe("al.help.new", lambda c: heard["help"].append(c))
    hub.subscribe("push.alliance.march", lambda c: heard["march"].append(c))

    assert _fire(hub, "push.alliance.march.refresh") is False, "the marker must be eaten"
    assert heard == {"help": [], "march": ["push.alliance.march.refresh"]}, heard

    _fire(hub, "al.help.new")
    assert heard["help"] == ["al.help.new"], heard
    assert heard["march"] == ["push.alliance.march.refresh"], "…and nothing extra"

    # A command nobody asked for reaches nobody — the child matched it for some other
    # subscriber's pattern, or the ear is wider than this profile's interest.
    _fire(hub, "push.something.else")
    assert heard == {"help": ["al.help.new"],
                     "march": ["push.alliance.march.refresh"]}, heard


def test_a_human_line_is_left_for_the_log():
    """Only the marker is machinery; the readable line still reaches the log."""
    _rt, hub = _hub()
    hub.subscribe("al.help.new", lambda c: None)
    assert hub._on_line("12:00:00 <-- al.help.new  something") is None
    assert hub._on_line(f"{FIRE_MARKER}\tal.help.new") is False


def test_the_child_is_asked_for_markers_only():
    """No human line from the child, because that line carries the push's PAYLOAD.

    `uid`, `senderName`, `allianceId` — a live panel.log had 6 307 of them for one push
    (#1293), and a log is a file people send each other when something goes wrong.
    """
    rt, hub = _hub()
    hub.subscribe("al.help.new", lambda c: None)
    assert "--quiet" in rt.children.spawned[-1].cmd, rt.children.spawned[-1].cmd


def test_what_the_ear_heard_is_rolled_up_and_names_nobody():
    """The first is said at once; the rest are counted and said once a window."""
    import panel.runtime.wire as wiremod

    rt, hub = _hub()
    hub.subscribe("push.alliance.march", lambda c: None)
    rt.said.clear()
    for _ in range(500):
        _fire(hub, "push.alliance.march.refresh")
    assert len(rt.said) == 1, [s[1] for s in rt.said]
    tag, key, fmt = rt.said[0]
    assert key == "triggers.log.heard", key
    assert fmt["count"] == 1, fmt          # the first one, said on its own

    # …and the window's worth, in one line carrying the count and the command name.
    hub._heard_said -= wiremod.HEARD_NOTE_SEC + 1
    _fire(hub, "push.alliance.march.refresh")
    assert len(rt.said) == 2, [s[1] for s in rt.said]
    fmt = rt.said[1][2]
    assert fmt["count"] == 500, fmt        # the 499 counted plus this one
    assert "push.alliance.march.refresh×500" == fmt["detail"], fmt


def test_widening_the_patterns_relaunches_the_ear_and_narrowing_it_back_too():
    """The child carries the union, so a new pattern is a new command line."""
    rt, hub = _hub()
    off_a = hub.subscribe("al.help.new", lambda c: None)
    first = rt.children.spawned[-1]
    off_b = hub.subscribe("push.alliance.march", lambda c: None)
    assert first.stopped, "the narrower ear was left running beside the wider one"
    second = rt.children.spawned[-1]
    assert sorted(second.patterns()) == ["al.help.new", "push.alliance.march"]

    off_b()
    third = rt.children.spawned[-1]
    assert second.stopped and third.patterns() == ["al.help.new"], third.patterns()
    off_a()
    assert third.stopped and hub.listeners() == 0

    # Subscribing to a pattern already carried does NOT churn the child: two triggers
    # on one push must not restart the capture every time one of them is toggled.
    hub.subscribe("al.help.new", lambda c: None)
    fourth = rt.children.spawned[-1]
    hub.subscribe("al.help.new", lambda c: None)
    assert rt.children.spawned[-1] is fourth, "the ear was relaunched for nothing"


def test_the_ear_closing_is_told_to_every_subscriber():
    """With a child each, a dead listener was one listener. Now it is all of them."""
    _rt, hub = _hub()
    closed = []
    hub.subscribe("al.help.new", lambda c: closed.append(("a", c)))
    hub.subscribe("push.alliance.march", lambda c: closed.append(("b", c)))
    hub._on_exit()
    assert closed == [("a", None), ("b", None)], closed
    assert hub._proc is None


def test_one_subscriber_raising_does_not_deafen_the_others():
    """A callback that throws is one trigger's problem, never the ear's."""
    _rt, hub = _hub()
    heard = []

    def bad(_command):
        raise RuntimeError("boom")

    hub.subscribe("al.help", bad)
    hub.subscribe("al.help", lambda c: heard.append(c))
    _fire(hub, "al.help.new")
    assert heard == ["al.help.new"], heard


def test_an_empty_pattern_is_refused_rather_than_matching_everything():
    """`"" in command` is true for every command — a typo would subscribe to all of it."""
    _rt, hub = _hub()
    for bad in ("", "   ", None):
        try:
            hub.subscribe(bad, lambda c: None)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} was accepted as a pattern")


def test_two_subscribers_arriving_together_leave_one_ear():
    """The boot case: the trigger watcher subscribes once per enabled trigger, at once.

    `_sync` decides and acts in two steps — read the wanted patterns, stop what runs,
    start the replacement — and `_proc` is only set once the child HAS started. Without
    a lock around the whole of that, two subscribers both saw nothing to stop and both
    spawned, and the narrower ear went on decoding the stream for nobody. Seen live as
    two `wire_event_monitor` processes in the same second, one carrying a subset of the
    other's patterns (#1237).
    """
    import threading

    rt, hub = _hub()
    start = threading.Barrier(4)

    def join(pattern):
        start.wait()
        hub.subscribe(pattern, lambda c: None)

    threads = [threading.Thread(target=join, args=(p,))
               for p in ("al.help.new", "push.alliance.march", "push.world.point")]
    for th in threads:
        th.start()
    start.wait()
    for th in threads:
        th.join()

    live = [c for c in rt.children.spawned if not c.stopped]
    assert len(live) == 1, [c.patterns() for c in live]
    assert sorted(live[0].patterns()) == ["al.help.new", "push.alliance.march",
                                          "push.world.point"], live[0].patterns()


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

r"""The panel's auto-loot watcher — what it decides to fire at, and when it does not.

The «Автолут ★» checkbox is a standing order: while it is ticked a watcher thread
re-reads its sources and robs a starred task of the best level the moment one is
raidable (task #1109). Since #1124 the primary source is the live game VM (the
client's own alliance tasks), with the capture checkpoint kept as a second source —
so a raidable star is caught in a second or two rather than whenever the sweep next
pans over it. *Which* task the rule picks is covered by ``test_secret_missions.py``
(``targets_from_scan`` / ``targets_from_vm``); what is tested here is the layer above
it — the part that can quietly burn the day's five robberies:

  * nothing to look at yet — one complaint, not one per poll;
  * no star in the scan — no robbery at all;
  * a target is sent **once**: the checkpoint keeps showing a tile the server refused,
    or one we robbed before a fresh scan brings its loot count back;
  * no second robbery while one is still running, and none while the budget is spent;
  * a stale checkpoint (nothing re-seen in this scan window) is not a target.

``Panel._autoloot_tick`` is called unbound against a stub object, so no Tk window is
opened and no game is needed. That does mean **tkinter must be importable**: under the
WSL python3 it is not, so there the test says SKIP and passes. Run it under the
Windows Python to actually exercise it::

    C:\Python312\python.exe tests\test_panel_autoloot.py
    python3 tests/test_panel_autoloot.py        # SKIP without tkinter
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_runtime  # noqa: E402

try:
    import tkinter  # noqa: F401
    _HAS_TK = True
except Exception:       # noqa: BLE001 — no display is fine, no module is not
    _HAS_TK = False

import lastwar_proto as proto  # noqa: E402


def _task(uuid: int, cfg_id: int, family: str, level: int, looted=(), server: int = 534):
    """A raidable tile: dispatch finished a minute ago, expires in an hour."""
    now_ms = int(time.time() * 1000)
    return proto.SecretTask(
        uuid=uuid, server_id=server, x=100 + uuid, y=200, level=level,
        cfg_id=cfg_id, family=family, looted_by=tuple(looted), owner_uid="u%d" % uuid,
        alliance_id="a", expires_at=now_ms + 3_600_000, completed_at=now_ms - 60_000)


def _checkpoint(path: Path, tasks, age: int = 0) -> None:
    """Write `tasks` as a capture checkpoint seen `age` seconds ago."""
    seen = int(time.time()) - age
    records = []
    for task in tasks:
        record = task.as_dict()
        record["seen_at"] = seen
        records.append(record)
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def _Watcher(checkpoint: Path, level_from: str = "", level_to: str = "",
             skip_own: bool = False, own_server: int = 0, vm_up: bool = False):
    """The «Автолут ★» standing order, wired to nothing but a checkpoint path.

    It is `panel/tabs/secret_tasks/autoloot.py` now — the watcher moved out of the
    panel with the tab that owns the range aiming it — so the stand-in is a runtime and
    a tab rather than a Panel. Everything it touches is here and nothing else is: no Tk
    root, no daemon by default (these cases exercise the checkpoint source, the way the
    watcher always did; the VM source has its own test below), and no child ever
    spawned — `run` records the checkpoint the tick would have robbed from.
    """
    from panel import runtime as rtmod
    from panel.tabs.secret_tasks.autoloot import AutoLoot

    logs: list = []
    i18n = rtmod.Translator("ru")
    bus = fake_runtime.RecordingBus(translate=i18n.t, lines=logs)
    game = types.SimpleNamespace(up=lambda: vm_up, client=None, busy=False)
    # The knobs live in the binder; with no widgets attached the saved dict is the
    # answer, so an empty one means SETTINGS_DEFAULTS — the constants these numbers
    # used to be (the auto-loot budget, the poll period, the spent-pause).
    import panel.__main__ as pm
    settings = rtmod.SettingsBinder(profiles=None, defaults=pm.SETTINGS_DEFAULTS)
    rt = types.SimpleNamespace(
        profiles=types.SimpleNamespace(tasks_json=lambda: str(checkpoint)),
        game=game, settings=settings, log=bus, put=bus.put,
        children=types.SimpleNamespace(python=lambda: "python", spawn_raw=None),
        tick=types.SimpleNamespace(arm=lambda *a, **k: None))
    # The «уровень от / до» entries — auto-loot's OWN pair, not the display filter's —
    # duck-typed: `levels()` only reads `.get()`, so the rule can be exercised with no
    # Tk root window.
    # «Не грабить на своём сервере» rides along the same way: a box the rule reads live,
    # plus the tab's cached answer to "which server am I". Both duck-typed — the standing
    # order only ever calls `.get()` on the one and `own_server()` on the other.
    tab = types.SimpleNamespace(
        level_from_var=types.SimpleNamespace(get=lambda: level_from),
        level_to_var=types.SimpleNamespace(get=lambda: level_to),
        skip_own_var=types.SimpleNamespace(get=lambda: skip_own),
        own_server=lambda: own_server,
        capture=types.SimpleNamespace(running=False),
        t=i18n.t, say=bus.say)
    w = AutoLoot(rt, tab)
    w.rt, w.tab = rt, tab
    w.logs, w.runs = logs, []
    # Everything the panel says goes through the locale files, so the watcher's own
    # lines come out of `say` — with a real translator behind it, so the assertions are
    # on the words the operator actually reads.
    w.run = lambda checkpoint, vm_ready: w.runs.append(checkpoint)
    return w


def test_autoloot_watcher_fires_once_per_target():
    """The whole watcher decision, walked as one session on a moving checkpoint."""
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    tmp = Path(tempfile.mkdtemp())
    cp = tmp / "secret_tasks.json"
    w = _Watcher(cp)

    # No checkpoint yet and no live daemon: say so once, not on every poll, and rob
    # nothing.
    w.tick()
    w.tick()
    assert w.runs == [], w.runs
    assert sum("источника пока нет" in m for m in w.logs) == 1, w.logs

    # Plain (unstarred) tasks are not a target, however raidable.
    _checkpoint(cp, [_task(1, 50000704, "5000", 7)])
    w.tick()
    assert w.runs == [], w.runs

    # A star of the best level appears -> one robbery, and the same scan does not
    # fire a second one. The starred level-6 loses to the starred level-7.
    _checkpoint(cp, [_task(1, 50000704, "5000", 7), _task(2, 60000601, "6000", 6),
                     _task(3, 60000701, "6000", 7)])
    w.tick()
    assert w.runs == [str(cp)], w.runs
    assert w._seen == {3}, w._seen
    assert any("цель:" in m for m in w.logs), w.logs
    w.tick()
    w.tick()
    assert w.runs == [str(cp)], "re-fired at an already-sent target: %r" % (w.runs,)

    # A star that was not in the scan before is a fresh target.
    _checkpoint(cp, [_task(3, 60000701, "6000", 7), _task(9, 60000702, "6000", 7)])
    w.tick()
    assert w.runs == [str(cp)] * 2, w.runs
    assert w._seen == {3, 9}, w._seen

    # A robbery still running blocks a new one; so does the spent-budget pause.
    _checkpoint(cp, [_task(11, 60000701, "6000", 7)])
    w._proc = object()
    w.tick()
    assert w.runs == [str(cp)] * 2, "fired while a robbery was still running"
    w._proc = None
    w._pause_until = time.time() + 60
    w.tick()
    assert w.runs == [str(cp)] * 2, "fired while the day's robberies were spent"
    w._pause_until = 0.0
    w.tick()
    assert w.runs == [str(cp)] * 3, w.runs

    # A checkpoint nothing re-saw this window is not a target: its state is
    # unverifiable and a robbery aimed at it is an attempt thrown away.
    _checkpoint(cp, [_task(21, 60000701, "6000", 7)], age=100_000)
    w.tick()
    assert w.runs == [str(cp)] * 3, "fired at a stale checkpoint"


def test_autoloot_watcher_waits_for_the_filter_top_level():
    """With «от 1 до 7» ticked, a raidable level-6 star must NOT fire the watcher.

    The layer above the rule is where the day's five robberies are actually
    spent, so the level the operator asked for has to survive all the way here —
    this is the 2026-07-29 case, walked through the watcher itself.
    """
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    tmp = Path(tempfile.mkdtemp())
    cp = tmp / "secret_tasks.json"
    w = _Watcher(cp, level_from="1", level_to="7")

    # Every star in the scan is below the filter's top: hold fire.
    _checkpoint(cp, [_task(1, 60000501, "6000", 5), _task(2, 60000601, "6000", 6)])
    w.tick()
    w.tick()
    assert w.runs == [], "robbed below the filter's top level: %r" % (w.runs,)
    assert w._seen == set(), w._seen

    # A level-7 star comes free -> that one is robbed, and only that one.
    _checkpoint(cp, [_task(1, 60000501, "6000", 5), _task(2, 60000601, "6000", 6),
                     _task(3, 60000701, "6000", 7)])
    w.tick()
    assert w.runs == [str(cp)], w.runs
    assert w._seen == {3}, w._seen


def _vt_line(uuid: int, cfg_id: int, srv: int = 534, steals: int = 0) -> str:
    """One `ACT VT …` line as `secret_task_raidable_alliance()` would emit for a
    raidable tile: dispatch finished a minute ago, expires in an hour."""
    now = int(time.time() * 1000)
    return ("ACT VT uuid=%d cfg=%d srv=%d x=%d y=200 steals=%d done=%d exp=%d"
            % (uuid, cfg_id, srv, 100 + uuid, steals, now - 60_000, now + 3_600_000))


class _FakeClient:
    """A warm-daemon stand-in: every `run()` returns the same canned VT lines.

    Prefixed with the game's clock, because a real read carries it and a read that
    does NOT is how the tool knows the client has not logged in (#1227) — a fake
    without it would be modelling a login screen, not a session.
    """

    def __init__(self, lines):
        self.lines = list(lines)
        self.calls = 0

    def run(self, chunk, marker=None, settle=1.2):
        self.calls += 1
        return ["ACT NOWMS=%d" % int(time.time() * 1000)] + list(self.lines)


def test_autoloot_reads_live_vm():
    """With a live daemon and no checkpoint, the VM alone drives the watcher (#1124).

    This is the point of the change: a raidable star in the client's own alliance tasks
    is a target the instant it is there, with no capture running and no map panning.
    """
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    tmp = Path(tempfile.mkdtemp())
    cp = tmp / "secret_tasks.json"          # never written: the VM alone drives this
    w = _Watcher(cp)
    w.rt.game.up = lambda: True
    # A level-7 star and a plain (family 5000) level-7 in the client's alliance tasks.
    # Only the star is a target.
    w.rt.game.client = _FakeClient([_vt_line(3, 60000701), _vt_line(1, 50000704)])

    picked = w.vm_targets()
    assert [u for u, _s, _l in picked] == [3], picked

    # A full tick fires the child from the VM alone — checkpoint arg is None (no --from-scan).
    w.tick()
    assert w.runs == [None], w.runs
    assert w._seen == {3}, w._seen
    # Sent once: the tile stays raidable in the VM but must not be re-fired.
    w.tick()
    assert w.runs == [None], w.runs


def test_autoloot_unions_vm_and_checkpoint():
    """VM and checkpoint are two sources: a star in either is robbed, a shared one once."""
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    tmp = Path(tempfile.mkdtemp())
    cp = tmp / "secret_tasks.json"
    w = _Watcher(cp)
    w.rt.game.up = lambda: True
    # VM holds star #3; the checkpoint (an enemy tile the sweep panned over) holds star #7.
    w.rt.game.client = _FakeClient([_vt_line(3, 60000701)])
    _checkpoint(cp, [_task(7, 60000701, "6000", 7)])
    w.tick()
    assert w.runs == [str(cp)], w.runs      # checkpoint present -> it is passed to the child
    assert w._seen == {3, 7}, w._seen


def test_a_star_on_the_own_server_is_not_a_target_while_the_box_is_ticked():
    """«Не грабить на своём сервере» (#1209): the neighbour's tile is robbed, home is not.

    The prohibition is applied where the targets are CHOSEN, not after — so the rule
    still picks the best allowed star instead of picking a forbidden one and coming
    back with nothing.
    """
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    tmp = Path(tempfile.mkdtemp())
    cp = tmp / "secret_tasks.json"
    w = _Watcher(cp, level_from="1", level_to="7", skip_own=True, own_server=534,
                 vm_up=True)
    w.vm_targets = lambda: []              # the VM source has its own tests above
    _checkpoint(cp, [_task(3, 60000701, "6000", 7, server=534),     # home
                     _task(4, 60000701, "6000", 7, server=999)])    # a neighbour
    w.tick()
    assert w.runs == [str(cp)], w.runs
    assert w._seen == {4}, "the tile on the own server was taken as a target: %r" % (w._seen,)

    # Untick the box and the same home tile is a target again — nothing else changed.
    w2 = _Watcher(cp, level_from="1", level_to="7", skip_own=False, vm_up=True)
    w2.vm_targets = lambda: []
    _checkpoint(cp, [_task(3, 60000701, "6000", 7, server=534)])
    w2.tick()
    assert w2._seen == {3}, w2._seen


def test_an_unreadable_own_server_stops_the_robbery_instead_of_letting_it_through():
    """A prohibition that cannot be checked must pause the watcher, not lapse quietly."""
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    tmp = Path(tempfile.mkdtemp())
    cp = tmp / "secret_tasks.json"
    w = _Watcher(cp, level_from="1", level_to="7", skip_own=True, own_server=0,
                 vm_up=True)
    w.vm_targets = lambda: []
    _checkpoint(cp, [_task(4, 60000701, "6000", 7, server=999)])
    w.tick()
    w.tick()
    assert w.runs == [], "robbed while the own server was unknown: %r" % (w.runs,)
    assert sum("свой сервер не прочитан" in m for m in w.logs) == 1, w.logs


def test_the_prohibition_travels_to_both_children():
    """Each child re-reads the sources and re-applies the rule — so each is told.

    The same trap the level range was bitten by (#1099): a gate the panel obeys and the
    child it spawns does not is a gate that is not there.
    """
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    tmp = Path(tempfile.mkdtemp())
    cp = tmp / "secret_tasks.json"
    w = _Watcher(cp, level_from="1", level_to="7", skip_own=True, own_server=534)
    spawned: list = []
    w.rt.children.spawn_raw = lambda cmd, tag: spawned.append(cmd)
    w.start_push()                                  # the event-driven listener
    del w.run                                       # …and the poll's own child
    w.run(str(cp), vm_ready=False)
    assert len(spawned) == 2, spawned
    for cmd in spawned:
        assert "--skip-own-server" in cmd, cmd
        assert "--level-max" in cmd, cmd             # the old rule still travels too

    off = _Watcher(cp, level_from="1", level_to="7", skip_own=False)
    quiet: list = []
    off.rt.children.spawn_raw = lambda cmd, tag: quiet.append(cmd)
    off.start_push()
    assert quiet and "--skip-own-server" not in quiet[0], quiet


def test_the_watcher_says_what_it_is_doing_even_when_it_does_nothing():
    """Every silent end to a tick names itself on screen (#1227).

    «Автолут не работает совершенно» was four different states wearing one face: no
    source, an unreadable own server, a spent budget, and the ordinary "there is no
    star of that level on the map right now". None of them said anything after the
    first line, so from the operator's chair they were indistinguishable from a
    watcher that had never started.
    """
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    from panel.tabs.secret_tasks import autoloot as al

    tmp = Path(tempfile.mkdtemp())
    cp = tmp / "secret_tasks.json"
    w = _Watcher(cp)
    assert w.state()[0] == al.STATE_OFF, w.state()

    w.tick()                                       # no checkpoint, no live VM
    assert w.state()[0] == al.STATE_NO_SOURCE, w.state()

    _checkpoint(cp, [_task(1, 50000704, "5000", 7)])
    w.tick()                                       # a source, but nothing starred
    assert w.state()[0] == al.STATE_WATCHING, w.state()

    _checkpoint(cp, [_task(3, 60000701, "6000", 7)])
    w.tick()                                       # a star of the top level
    assert w.state() == (al.STATE_TARGETS, "1"), w.state()

    w._proc = object()                             # …a robbery in flight
    w.tick()
    assert w.state()[0] == al.STATE_ROBBING, w.state()
    w._proc = None

    w._pause_until = time.time() + 600             # …the day's five are spent
    w.tick()
    key, until = w.state()
    assert key == al.STATE_PAUSED and ":" in until, w.state()
    w._pause_until = 0.0

    # …and the own-server prohibition with nothing to compare against.
    blocked = _Watcher(cp, skip_own=True, own_server=0)
    blocked.tick()
    assert blocked.state()[0] == al.STATE_NO_OWN, blocked.state()

    # Every one of them is a real key in the shipped locales, and reads as a sentence.
    assert w.state_text(), "the state came out as an empty line"


def test_a_client_that_is_not_logged_in_is_said_out_loud_not_watched_in_silence():
    """The second profile's whole failure, in one tick (#1227).

    A client at the login screen answers every question and every answer is a
    plausible-looking lie — no alliance task, own server -1, all five robberies still
    unspent. The watcher used to take that at face value: it found no target, said
    nothing, and looked exactly like a watcher that had never started, which is what
    «автолут не работает совершенно» turned out to be.
    """
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    from panel.tabs.secret_tasks import autoloot as al

    class _LoginScreen:
        """Answers, and carries no clock — the one thing it cannot fake."""

        def run(self, _chunk, _marker=None, _settle=1.2):
            return []

    tmp = Path(tempfile.mkdtemp())
    cp = tmp / "secret_tasks.json"
    w = _Watcher(cp, level_from="1", level_to="7", vm_up=True)
    w.rt.game.client = _LoginScreen()
    w.rt.game.evaluator = lambda: _LoginScreen()

    w.tick()
    w.tick()
    assert w.runs == [], "robbed on the word of a client that is not logged in"
    assert w.state()[0] == al.STATE_NO_LOGIN, w.state()
    assert sum("не залогинен" in m for m in w.logs) == 1, w.logs


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())

r"""The panel's auto-loot watcher — what it decides to fire at, and when it does not.

The «Автолут ★» checkbox is a standing order: while it is ticked a watcher thread
re-reads the capture checkpoint and robs a starred task of the best level the moment
one is raidable (task #1109). *Which* task the rule picks is covered by
``test_secret_missions.py`` (``targets_from_scan``); what is tested here is the layer
above it — the part that can quietly burn the day's five robberies:

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

try:
    import tkinter  # noqa: F401
    _HAS_TK = True
except Exception:       # noqa: BLE001 — no display is fine, no module is not
    _HAS_TK = False

import lastwar_proto as proto  # noqa: E402


def _task(uuid: int, cfg_id: int, family: str, level: int, looted=()):
    """A raidable tile: dispatch finished a minute ago, expires in an hour."""
    now_ms = int(time.time() * 1000)
    return proto.SecretTask(
        uuid=uuid, server_id=534, x=100 + uuid, y=200, level=level,
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


class _Watcher:
    """A Panel stand-in carrying only what the watcher touches."""

    def __init__(self, checkpoint: Path):
        from panel.__main__ import Panel

        self.logs: list = []
        self.runs: list = []
        self._autoloot_proc = None
        self._autoloot_pause_until = 0.0
        self._autoloot_warned = False
        self._autoloot_seen: set = set()
        self._profiles = types.SimpleNamespace(tasks_json=lambda: str(checkpoint))
        self._log_put = self.logs.append
        self._autoloot_run = self.runs.append          # the child is never spawned here
        self._autoloot_targets = types.MethodType(Panel._autoloot_targets, self)
        self.tick = types.MethodType(Panel._autoloot_tick, self)


def test_autoloot_watcher_fires_once_per_target():
    """The whole watcher decision, walked as one session on a moving checkpoint."""
    if not _HAS_TK:
        print("  SKIP tkinter not importable — run under the Windows Python")
        return
    tmp = Path(tempfile.mkdtemp())
    cp = tmp / "secret_tasks.json"
    w = _Watcher(cp)

    # No checkpoint yet: say so once, not on every poll, and rob nothing.
    w.tick()
    w.tick()
    assert w.runs == [], w.runs
    assert sum("нет данных скана" in m for m in w.logs) == 1, w.logs

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
    assert w._autoloot_seen == {3}, w._autoloot_seen
    assert any("цель:" in m for m in w.logs), w.logs
    w.tick()
    w.tick()
    assert w.runs == [str(cp)], "re-fired at an already-sent target: %r" % (w.runs,)

    # A star that was not in the scan before is a fresh target.
    _checkpoint(cp, [_task(3, 60000701, "6000", 7), _task(9, 60000702, "6000", 7)])
    w.tick()
    assert w.runs == [str(cp)] * 2, w.runs
    assert w._autoloot_seen == {3, 9}, w._autoloot_seen

    # A robbery still running blocks a new one; so does the spent-budget pause.
    _checkpoint(cp, [_task(11, 60000701, "6000", 7)])
    w._autoloot_proc = object()
    w.tick()
    assert w.runs == [str(cp)] * 2, "fired while a robbery was still running"
    w._autoloot_proc = None
    w._autoloot_pause_until = time.time() + 60
    w.tick()
    assert w.runs == [str(cp)] * 2, "fired while the day's robberies were spent"
    w._autoloot_pause_until = 0.0
    w.tick()
    assert w.runs == [str(cp)] * 3, w.runs

    # A checkpoint nothing re-saw this window is not a target: its state is
    # unverifiable and a robbery aimed at it is an attempt thrown away.
    _checkpoint(cp, [_task(21, 60000701, "6000", 7)], age=100_000)
    w.tick()
    assert w.runs == [str(cp)] * 3, "fired at a stale checkpoint"


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

r"""The panel's own watchdog, and the two ways it must never be wrong (#1910, #1897).

A panel that has fallen over cannot report that it has fallen over. After #1910 the Lua
daemon starts unconditionally and survives a panel restart untouched, which makes it the
only process on the machine that can hold the watch — so it does
(`tools/lib/panel_guard.py`).

There was already a watch: `panel/runtime/autostart.py` registers a Windows task that
looks once an HOUR. That is right for «the machine rebooted» and useless for the incident
this is about — a panel that did not come back from an ORDERLY restart and was down for
nine minutes, entirely inside one hourly gap. So the guard does not reimplement the
launch; it runs that same check, sooner.

The two ways it must never be wrong, and both are pinned here:

* **it must not put back a panel a person closed.** Until now that was not even
  recordable: the panel DELETED its heartbeat on the way out, so «closed on purpose» and
  «never started here» were the same absence. A farewell note settles it.
* **it must not fight itself.** One panel per machine, several daemons — four daemons
  that each opened a panel would be the exact failure it exists to prevent. One exclusive
  file lock elects one guard.

And the threshold is measured rather than chosen: the beat is written once a minute, so
60 s is the floor below which the number measures luck; six orderly restarts of this
installation took 23–31 s.

    C:\Python312\python.exe tests\test_panel_guard.py
    python3 tests/test_panel_guard.py
"""
from __future__ import annotations

TIER = "unit"

import json
import os
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "tools" / "lib"))

import panel_guard  # noqa: E402


# --- a repository with profiles in it, and nothing else ----------------------
def _repo() -> str:
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "profiles"), exist_ok=True)
    return root


def _beat(root: str, name: str, *, age: float = 0.0) -> None:
    """Write a heartbeat `age` seconds old for one profile."""
    folder = os.path.join(root, "profiles", name)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "panel_alive.json"), "w", encoding="utf-8") as fh:
        json.dump({"pid": 4242, "exe": "python.exe",
                   "ts": time.time() - age, "profile": name}, fh)


def _left(root: str, name: str, why: str) -> None:
    """Write a farewell note — what the panel leaves when it goes on purpose."""
    folder = os.path.join(root, "profiles", name)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "panel_alive.json"), "w", encoding="utf-8") as fh:
        json.dump({"pid": 4242, "exe": "python.exe", "left": why,
                   "left_at": time.time(), "profile": name}, fh)


def _guard(root: str) -> panel_guard.PanelGuard:
    return panel_guard.PanelGuard(root, say=lambda _msg: None)


# --- the reading -------------------------------------------------------------
def test_a_beating_panel_is_left_alone():
    root = _repo()
    _beat(root, "one")
    assert _guard(root).verdict(time.time()) == ""


def test_a_silence_shorter_than_the_bar_is_not_an_incident():
    """The beat is written once a MINUTE. One missed write says nothing at all."""
    root = _repo()
    _beat(root, "one", age=panel_guard.SILENT_SEC - 30)
    assert _guard(root).verdict(time.time()) == ""


def test_a_silence_past_the_bar_is():
    root = _repo()
    _beat(root, "one", age=panel_guard.SILENT_SEC + 5)
    why = _guard(root).verdict(time.time())
    assert why and "no beat" in why, why


def test_the_bar_is_above_a_slow_orderly_restart_and_above_the_beat_itself():
    """The threshold, in the two facts it was derived from.

    Six orderly restarts of this installation took 23–31 s; the beat is written every
    60 s. A bar below either of those would fire on a panel that is perfectly fine.
    """
    assert panel_guard.SILENT_SEC >= 3 * 60, panel_guard.SILENT_SEC
    assert panel_guard.POLL_SEC < panel_guard.SILENT_SEC / 2, panel_guard.POLL_SEC


def test_any_page_beating_proves_the_window_is_up():
    """A panel holds a page per open profile — one beat is the whole window's."""
    root = _repo()
    _beat(root, "one", age=panel_guard.SILENT_SEC + 60)
    _beat(root, "two", age=1.0)
    assert _guard(root).verdict(time.time()) == ""


# --- «closed» is not «fell over» ---------------------------------------------
def test_a_panel_somebody_closed_is_left_closed():
    """The rule the operator asked for by name: «сегодня я сам закрывал, это норм».

    Nothing here is a guess — the panel says so on the way out, and only an orderly
    shutdown can write it. Anything that dies leaves no note, which is the difference.
    """
    root = _repo()
    _left(root, "one", panel_guard.__dict__.get("CLOSED", "closed"))
    assert _guard(root).verdict(time.time()) == ""


def test_a_panel_that_is_restarting_is_not_raced():
    """The other farewell: it is coming back on fresh code, seconds from now."""
    root = _repo()
    _left(root, "one", "restarting")
    assert _guard(root).verdict(time.time()) == ""


def test_a_machine_that_has_never_run_the_panel_is_not_this_guards_business():
    """No file at all is «never started here», and the hourly task owns that case."""
    root = _repo()
    os.makedirs(os.path.join(root, "profiles", "one"), exist_ok=True)
    assert _guard(root).verdict(time.time()) == ""


def test_a_crash_leaves_no_note_and_is_acted_on():
    """The whole point, stated as the pair it is: same silence, different explanation."""
    root = _repo()
    _beat(root, "one", age=panel_guard.SILENT_SEC + 5)
    assert _guard(root).verdict(time.time()) != ""
    _left(root, "one", "closed")
    assert _guard(root).verdict(time.time()) == ""


# --- one guard per machine ---------------------------------------------------
def test_only_one_daemon_becomes_the_guard():
    """Four daemons opening four panels is the failure this is meant to prevent."""
    root = _repo()
    first, second = _guard(root), _guard(root)
    assert first._elected() is True
    assert second._elected() is False, "two guards on one machine"


def test_the_lock_is_the_kernels_and_frees_itself():
    """A guard that dies must not take the watch with it — the lock is held, not owned."""
    root = _repo()
    first = _guard(root)
    assert first._elected() is True
    first._handle.close()                    # what a dying process does for free
    first._handle = None
    assert _guard(root)._elected() is True, "the watch was never handed on"


# --- it says nothing for a while after acting --------------------------------
def test_a_panel_that_was_just_started_is_not_counted_as_missing():
    """The check waits 45 s for a first beat; the guard must outwait that."""
    root = _repo()
    _beat(root, "one", age=panel_guard.SILENT_SEC + 5)
    guard = _guard(root)
    guard._quiet_until = time.time() + panel_guard.QUIET_AFTER_SEC
    assert guard.verdict(time.time()) == ""
    assert panel_guard.QUIET_AFTER_SEC > 45, panel_guard.QUIET_AFTER_SEC


# --- it runs the panel's own check, and not a launch of its own ---------------
def test_it_reuses_the_panels_own_check_rather_than_launching_by_hand():
    """Locks, hung panels, the open-profile set and the farewell all live in one place.

    A guard with a launch of its own would be a second opinion about every one of them,
    and the first time the two disagreed there would be two windows.
    """
    src = (_REPO / "tools" / "lib" / "panel_guard.py").read_text(encoding="utf-8")
    assert panel_guard.CHECK_MODULE == "panel.runtime.autostart", panel_guard.CHECK_MODULE
    assert "open_panel" not in src, "the guard grew a launch of its own"


def _main() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    bad = 0
    for fn in tests:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except AssertionError as exc:
            bad += 1
            print(f"  FAIL {fn.__name__}: {exc}")
    print(f"\n{len(tests) - bad}/{len(tests)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_main())

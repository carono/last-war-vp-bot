r"""Почему связь не поднимается — видно в логе, а не в закрытом stdout (задача #2060).

WHAT THIS FILE IS FOR. `tools/lua_daemon.py` says why an attach or a probe did not work,
and it said it by printing. That was right while it was a process of its own with a
supervisor reading its stdout. Since #1911 the panel holds the VM in-process and is
started detached, so it has no stdout at all — and the sentences went nowhere.

Measured live on 2026-08-28: one profile logged «45 probes in a row … attaching again»
859 times over 6.9 hours, and the reading that named the cause («no window this session
can see», stamped once at 23:26) was printed into a closed handle every single time. The
panel could not be told apart from the two other things that look the same, so the fault
stood all night.

What is pinned here:

  * the `Daemon` says its diagnosis through ONE door (`say`), never `print` directly;
  * that door defaults to stdout, which is what a standalone connector still needs;
  * the panel replaces it, so every line lands in the profile's own debug log.

    C:\Python312\python.exe tests\test_link_diagnosis_is_logged.py
    python3 tests/test_link_diagnosis_is_logged.py
"""
from __future__ import annotations

TIER = "pure"      # no game, no Tk, no socket — source and one method

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "tools", ROOT / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location(
    "lw_lua_service_diag", ROOT / "panel" / "runtime" / "lua_service.py")
lua_service = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lua_service)

DAEMON_SRC = (ROOT / "tools" / "lua_daemon.py").read_text(encoding="utf-8")
SERVICE_SRC = (ROOT / "panel" / "runtime" / "lua_service.py").read_text(encoding="utf-8")


class FakeLog:
    def __init__(self) -> None:
        self.lines: list = []

    def warning(self, msg, *args) -> None:
        self.lines.append(msg % args if args else msg)

    def info(self, msg, *args) -> None:
        self.lines.append(msg % args if args else msg)


def _daemon_class_body() -> str:
    """Just `class Daemon` — the half the panel imports and drives in-process.

    The free functions below it (`_watch_client`, `main`) run ONLY when this module is a
    process of its own, and a print there is read by whoever started that process.
    """
    lines = DAEMON_SRC.splitlines()
    start = next(n for n, line in enumerate(lines) if line.startswith("class Daemon:"))
    end = next(n for n, line in enumerate(lines[start + 1:], start + 1)
               if line and not line[0].isspace())
    return "\n".join(lines[start:end])


def test_the_daemon_never_prints_its_diagnosis_straight_out():
    """One door. A `print` inside the class is a sentence the panel can never read."""
    stray = [n for n, line in enumerate(_daemon_class_body().splitlines(), 1)
             if re.search(r"(?<![\w.])print\(", line)
             and not line.lstrip().startswith("#")]
    assert not stray, f"a diagnosis printed past the door: class Daemon lines {stray}"


def test_the_default_door_is_stdout_for_a_standalone_connector():
    assert "self.say = _to_stdout" in DAEMON_SRC
    assert "def _to_stdout" in DAEMON_SRC


def test_the_panel_takes_the_door_over_when_it_holds_the_vm():
    assert "self._daemon.say = self._relay" in SERVICE_SRC


def test_a_relayed_line_lands_in_the_log_with_its_cause_intact():
    svc = lua_service.LuaService.__new__(lua_service.LuaService)
    svc._dbg = FakeLog()
    svc._relay("[daemon] the probe did not reach the client (45 in a row): "
               "no window this session can see")
    assert svc._dbg.lines == [
        "the probe did not reach the client (45 in a row): "
        "no window this session can see"], svc._dbg.lines


def test_a_relayed_line_with_a_percent_in_it_is_not_a_format_string():
    """A cause may quote anything the game said; it is DATA, never a template."""
    svc = lua_service.LuaService.__new__(lua_service.LuaService)
    svc._dbg = FakeLog()
    svc._relay("[daemon] no client to attach to yet: 100% of nothing")
    assert svc._dbg.lines == ["no client to attach to yet: 100% of nothing"]


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

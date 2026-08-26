r"""What Windows is actually told to start, and what it hears back (#1976, P0).

A Windows service is a PROTOCOL, not a program Windows happens to launch. The first
registration missed that: `sc create` pointed at a script that ran a loop and never
connected to the Service Control Manager, so the SCM waited its whole timeout and called
the start failed. On the machine it looked like a hang; in the System log it was

    7009  Превышение времени ожидания (120000 мс) при ожидании подключения службы …
    7000  Сбой при запуске службы … из-за ошибки

There is no way to test the real dialogue without an administrator and a live SCM, so
what is pinned here is everything that CAN be checked without one — and every one of
these was wrong, or missing, on the day the service hung:

  * the registration names `--service`, in the line that creates it AND in the line that
    repairs an older one;
  * `tools/run_service.py` speaks the protocol: the dispatcher, a control handler and
    `SERVICE_RUNNING` — and it does so with the standard library, because a service that
    only starts where somebody already had `pywin32` is the hard-coded-path mistake in
    another costume (`CLAUDE.md`);
  * the panel is imported INSIDE the service entry point and never at module level: every
    second before the dispatcher connects is a second the SCM spends waiting;
  * and the log path is COMPUTED. The service runs as LocalSystem with no console and no
    profile, so a start that fails has exactly one witness and it must not be a path
    inherited from whoever happened to run something else.

    C:\Python312\python.exe tests\test_service_registration.py
    python3 tests/test_service_registration.py
"""
from __future__ import annotations

TIER = "offline"   # no Windows, no SCM, no administrator — it reads what is written

import ast
import importlib.util
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_RUNNER = _REPO / "tools" / "run_service.py"
_INSTALL = _REPO / "service_install.bat"


def _runner_module():
    """`tools/run_service.py` as a module — it imports nothing but the standard library."""
    spec = importlib.util.spec_from_file_location("_run_service_under_test", _RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _install_text() -> str:
    return _INSTALL.read_text(encoding="utf-8")


def _binpath() -> str:
    """What `!BINPATH!` expands to — the command line Windows is actually handed."""
    for line in _install_text().splitlines():
        stripped = line.strip()
        if stripped.startswith('set "BINPATH='):
            return stripped
    raise AssertionError("the installer no longer builds a command line")


def test_the_registration_starts_it_as_a_service_and_not_as_a_loop():
    text = _install_text()
    create = [ln for ln in text.splitlines() if "sc create %NAME%" in ln]
    assert create, "the installer no longer registers anything"
    assert "--service" in _binpath(), f"registered without the SCM protocol: {_binpath()}"
    for line in create:
        assert "!BINPATH!" in line, f"registers something else: {line}"
        assert "type= own" in line, f"an own-process service must say so: {line}"


def test_an_older_registration_is_repaired_rather_than_left_hanging():
    """The service that hung is already on somebody's machine. Running the installer
    again must fix it — being told «uninstall first» costs the same click and one more
    reboot."""
    text = _install_text()
    config = [ln for ln in text.splitlines() if "sc config %NAME%" in ln]
    assert config, "an existing registration is not brought up to date"
    for line in config:
        assert "!BINPATH!" in line, f"repaired into something else: {line}"
    assert "--service" in _binpath(), "repaired into the same hang"


def test_the_runner_speaks_the_managers_protocol_with_the_standard_library():
    text = _RUNNER.read_text(encoding="utf-8")
    for symbol in ("StartServiceCtrlDispatcherW", "RegisterServiceCtrlHandlerExW",
                   "SetServiceStatus", "SERVICE_RUNNING", "SERVICE_STOPPED"):
        assert symbol in text, f"the SCM dialogue is missing {symbol}"
    # The WORD may appear — the file explains at length why it does not use it. What may
    # not appear is an import of anything outside the standard library.
    imported = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add((node.module or "").split(".")[0])
    outside = imported - set(sys.stdlib_module_names) - {"panel", ""}
    assert not outside, f"a dependency the person's machine may not have: {sorted(outside)}"


def test_the_panel_is_imported_after_the_dispatcher_and_never_at_module_level():
    tree = ast.parse(_RUNNER.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            name = getattr(node, "module", "") or ""
            names = [a.name for a in node.names]
            assert not name.startswith("panel"), f"panel imported at module level: {name}"
            assert not any(n.startswith("panel") for n in names), names


def test_a_hand_run_is_told_apart_from_a_real_start():
    """1063 — «not started by the SCM» — is the ONE failure that means «run it here».
    Anything else is a failure and must not be silently turned into a foreground run."""
    mod = _runner_module()
    assert mod.ERROR_FAILED_SERVICE_CONTROLLER_CONNECT == 1063
    text = _RUNNER.read_text(encoding="utf-8")
    assert "ERROR_FAILED_SERVICE_CONTROLLER_CONNECT" in text.split("def main")[-1], (
        "`main` does not tell a hand-run apart from a broken dispatcher")


def test_the_log_is_computed_and_can_be_pointed_somewhere_else():
    mod = _runner_module()
    was = os.environ.get("LW_SERVICE_LOG")
    try:
        os.environ.pop("LW_SERVICE_LOG", None)
        default = mod.log_path()
        assert Path(default).name == "service.log", default
        assert Path(default).parent == _REPO, f"the log left the repository: {default}"
        os.environ["LW_SERVICE_LOG"] = os.path.join("somewhere", "else.log")
        assert mod.log_path().endswith("else.log"), mod.log_path()
    finally:
        os.environ.pop("LW_SERVICE_LOG", None)
        if was is not None:
            os.environ["LW_SERVICE_LOG"] = was


def test_the_log_survives_a_directory_that_cannot_be_written():
    """A service that cannot write its log still runs — the log is a witness, not a leg."""
    mod = _runner_module()
    was = os.environ.get("LW_SERVICE_LOG")
    try:
        os.environ["LW_SERVICE_LOG"] = os.path.join(os.sep, "no", "such", "dir", "s.log")
        mod.log("a line nobody can write")          # must not raise
    finally:
        os.environ.pop("LW_SERVICE_LOG", None)
        if was is not None:
            os.environ["LW_SERVICE_LOG"] = was


def main() -> int:
    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
        except Exception as exc:                    # noqa: BLE001 — a report, not a crash
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok   {name}")
    print("FAILED" if failed else "OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

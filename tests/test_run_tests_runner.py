r"""The suite runner says what it did WHILE it does it (task #2020).

`tools/run_tests.py` used to collect every file's result and print the lot at the end.
On this repository the offline tier is a hundred files and several minutes, and anything
that ends the run early — a CI step's limit, an agent's command timeout, a person's
Ctrl-C — took the whole report with it: exit code 1, not one line printed, and no way to
tell a red suite from a suite that never ran. Worse than useless, because «the runner
exits 1» reads as «the tests are red» and «it exits 0 through `| tail`» reads as green.

Two separate faults, both pinned here:

  * the report was buffered — nothing left the process until the last file was in, and a
    redirected stdout is block-buffered on top of that, so a kill lost even what had
    been printed;
  * a file that left a GRANDCHILD holding the stdout pipe hung the runner for ever after
    a timeout: `subprocess.run` kills the test, then blocks reading a pipe nobody closes.

And a run that did not finish must never come back 0.

    C:\Python312\python.exe tests\test_run_tests_runner.py
    python3 tests/test_run_tests_runner.py
"""
from __future__ import annotations

import importlib.util
import io
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent


def _runner():
    spec = importlib.util.spec_from_file_location(
        "_run_tests_under_test", _REPO / "tools" / "run_tests.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Stamped(io.StringIO):
    """A stdout that remembers WHEN each line was written."""

    def __init__(self) -> None:
        super().__init__()
        self.stamps: list[tuple[float, str]] = []

    def write(self, text: str) -> int:
        if text.strip():
            self.stamps.append((time.monotonic(), text.strip()))
        return super().write(text)

    def line_at(self, needle: str) -> float | None:
        for when, line in self.stamps:
            if needle in line:
                return when
        return None


def _scratch_tests(files: dict[str, str]) -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    for name, body in files.items():
        (Path(tmp.name) / name).write_text(body, encoding="utf-8")
    return tmp


def _run(mod, argv: list[str], tests_dir: str) -> tuple[int, _Stamped]:
    out = _Stamped()
    was_tests, was_stdout = mod.TESTS, sys.stdout
    mod.TESTS = Path(tests_dir)
    sys.stdout = out
    try:
        code = mod.main(argv)
    finally:
        mod.TESTS, sys.stdout = was_tests, was_stdout
    return code, out


def test_a_files_verdict_is_printed_while_the_run_is_still_going() -> None:
    """The whole point: the first file's line is out before the last file starts."""
    mod = _runner()
    tmp = _scratch_tests({
        "test_quick_one.py": "print('ok  quick')\n",
        "test_slow_one.py": "import time; time.sleep(2); print('ok  slow')\n",
    })
    try:
        code, out = _run(mod, ["offline"], tmp.name)
        first = out.line_at("test_quick_one.py")
        last = out.line_at("test_slow_one.py")
        assert code == 0, [ln for _, ln in out.stamps]
        assert first is not None and last is not None, [ln for _, ln in out.stamps]
        assert last - first > 1.5, (
            "both lines landed together — the report is still collected to the end")
    finally:
        tmp.cleanup()


def test_every_line_is_flushed_as_it_is_printed() -> None:
    """A redirected stdout is block-buffered: an unflushed line dies with the process."""
    source = (_REPO / "tools" / "run_tests.py").read_text(encoding="utf-8")
    assert "def _say(" in source, "the runner has no single place that prints"
    assert "print(line, flush=True)" in source, "a line that is not flushed is lost"
    assert "print(f\"  {mark}" not in source, (
        "a verdict is printed somewhere that does not flush")


def test_a_test_that_leaves_a_grandchild_behind_does_not_hang_the_runner() -> None:
    """`subprocess.run(timeout=…)` kills the test and then waits on the pipe its
    grandchild still holds — for ever. The runner has to come back red instead."""
    mod = _runner()
    tmp = _scratch_tests({"test_leaks_a_child.py": (
        "import subprocess, sys, time\n"
        # A grandchild holding the same stdout, outliving the test on purpose.
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "time.sleep(60)\n")})
    try:
        started = time.monotonic()
        result = mod.run_one(Path(tmp.name) / "test_leaks_a_child.py", 2.0)
        spent = time.monotonic() - started
        assert result.timed_out, result.code
        assert spent < 30, f"the runner sat on the pipe for {spent:.0f}s"
    finally:
        tmp.cleanup()


def test_a_run_that_did_not_finish_is_never_green() -> None:
    """Ctrl-C, a killed pool, an outer limit — a partial suite is not a pass."""
    mod = _runner()
    tmp = _scratch_tests({f"test_num_{i}.py": "pass\n" for i in range(4)})
    real = mod.run_one
    seen: list[Path] = []

    def stop_after_two(path: Path, timeout: float):
        seen.append(path)
        if len(seen) > 2:
            raise KeyboardInterrupt
        return real(path, timeout)

    mod.run_one = stop_after_two
    try:
        code, out = _run(mod, ["offline"], tmp.name)
        printed = "\n".join(ln for _, ln in out.stamps)
        assert code != 0, "an interrupted run came back green"
        assert "INCOMPLETE" in printed, printed
    finally:
        mod.run_one = real
        tmp.cleanup()


def test_a_worker_that_dies_names_the_file_it_died_on() -> None:
    """A crash inside the RUNNER used to travel up as a bare traceback with no file
    name in it — and under `--jobs` it took the whole run with it."""
    mod = _runner()
    tmp = _scratch_tests({f"test_num_{i}.py": "pass\n" for i in range(3)})
    real = mod.run_one

    def die_on_the_second(path: Path, timeout: float):
        if path.name == "test_num_1.py":
            raise RuntimeError("the pool worker fell over")
        return real(path, timeout)

    mod.run_one = die_on_the_second
    try:
        code, out = _run(mod, ["offline"], tmp.name)
        printed = "\n".join(ln for _, ln in out.stamps)
        assert code != 0, printed
        assert "test_num_1.py" in printed and "the pool worker fell over" in printed, \
            printed
        assert "2/3 files green" in printed, (
            "one file's crash stopped the other two — a death is one red line")
    finally:
        mod.run_one = real
        tmp.cleanup()


def test_a_run_killed_from_outside_still_says_what_had_passed() -> None:
    """SIGTERM is how an outer limit ends a run — a CI step, an agent's command
    timeout, a `kill`. The default disposition ends the process on the spot: no
    summary, no list, and a status nobody can tell from a red suite (#2020)."""
    tmp = _scratch_tests({
        "test_quick_one.py": "print('ok  quick')\n",
        "test_zzz_endless.py": "import time; time.sleep(120)\n",
    })
    driver = Path(tmp.name) / "driver.py"
    driver.write_text(
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('rt', r'{_REPO}/tools/run_tests.py')\n"
        "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)\n"
        "from pathlib import Path\n"
        f"mod.TESTS = Path(r'{tmp.name}')\n"
        "raise SystemExit(mod.main(['offline']))\n", encoding="utf-8")
    # Windows cannot be sent a catchable SIGTERM — `TerminateProcess` is not a signal
    # and cannot be handled — so the kill that a run must survive out loud is
    # Ctrl-Break, which needs its own process group to be sent into.
    windows = os.name == "nt"
    proc = subprocess.Popen(
        [sys.executable, "-u", str(driver)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if windows else 0)
    try:
        deadline = time.monotonic() + 30
        seen = ""
        while time.monotonic() < deadline and "test_quick_one.py" not in seen:
            seen += proc.stdout.readline()
        assert "test_quick_one.py" in seen, f"nothing was printed to kill into: {seen!r}"
        time.sleep(0.5)                  # let the next file actually start
        proc.send_signal(signal.CTRL_BREAK_EVENT if windows else signal.SIGTERM)
        rest = proc.stdout.read()
        code = proc.wait(timeout=30)
        printed = seen + rest
        assert code != 0, printed
        assert ("SIGBREAK" if windows else "SIGTERM") in printed, \
            f"a killed run said nothing about why: {printed!r}"
        assert "INCOMPLETE" in printed, f"a partial run looked whole: {printed!r}"
        assert "test_quick_one.py" in printed, "…and lost what HAD passed"
        assert "test_zzz_endless.py" in printed, (
            "the file it died in the middle of was not named — and its process was "
            "left running")
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
        tmp.cleanup()


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())

r"""The panel's technical debug log (panel/debug_log.py + panel/debug_sender.py).

Both halves are deliberately Tk-free — a rotating file logger keyed by component,
plus the zip-and-hand-off sender — so they pin down without a display. What is worth
holding still:

  * get_logger(component) tags every line with its component, and configure() wires
    ONE rotating file under all of them — a second configure() (a profile switch)
    re-points the file and never stacks two handlers;
  * the format is the specified `[ts.mmm] [LEVEL] [component] message`;
  * rotation actually caps the file — a tiny maxBytes rolls it over into the
    numbered backups instead of growing one file forever;
  * make_archive() bundles the newest few files and is truthful (an empty zip) when
    nothing has been logged yet;
  * send() writes the archive regardless and reports "disabled" for an empty URL,
    "stub" until a transport is wired.

Runs anywhere (no tkinter, no game):

    python3 tests/test_panel_debug_log.py
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from panel import debug_log as dbg
from panel import debug_sender as sender


def _reset() -> None:
    """A clean root logger between tests — no handlers left from a prior one."""
    dbg.shutdown()
    lg = logging.getLogger(dbg.ROOT_NAME)
    for h in list(lg.handlers):
        lg.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass


@contextlib.contextmanager
def _scratch():
    """A temp directory to log into, with the handlers let go BEFORE it is removed.

    `TemporaryDirectory` used to be entered directly and `_reset()` called after the
    block — which is one line too late on Windows: a rotating handler still holds
    `debug.log` open, `os.unlink` raises WinError 32, and the whole file dies in
    cleanup with no test having actually failed. The order is the fix; on Linux either
    order works, which is why it stayed unnoticed.
    """
    tmp = tempfile.mkdtemp(prefix="lw-debug-log-")
    try:
        yield tmp
    finally:
        _reset()
        shutil.rmtree(tmp, ignore_errors=True)


def test_level_of() -> None:
    assert dbg.level_of("debug") == logging.DEBUG
    assert dbg.level_of("INFO") == logging.INFO
    assert dbg.level_of("Warning") == logging.WARNING
    assert dbg.level_of("error") == logging.ERROR
    assert dbg.level_of("nonsense") == logging.DEBUG   # unknown -> DEBUG
    assert dbg.level_of(None) == logging.DEBUG


def test_configure_is_idempotent_and_creates_the_dir() -> None:
    _reset()
    with _scratch() as tmp:
        path = os.path.join(tmp, "sub", "debug.log")   # dir does not exist yet
        dbg.configure(path, level="INFO")
        dbg.configure(path, level="INFO")              # second call (profile switch)
        root = logging.getLogger(dbg.ROOT_NAME)
        ours = [h for h in root.handlers if getattr(h, "_panel_debug", False)]
        assert len(ours) == 1, f"expected one handler, got {len(ours)}"
        assert root.level == logging.INFO
        assert os.path.isdir(os.path.dirname(path)), "configure must create the dir"


def test_component_and_format() -> None:
    _reset()
    with _scratch() as tmp:
        path = os.path.join(tmp, "debug.log")
        dbg.configure(path, level="DEBUG")
        dbg.get_logger("timers").info("fired %s", "collect_base")
        dbg.get_logger().warning("panel-level line")     # component defaults to "panel"
        for h in logging.getLogger(dbg.ROOT_NAME).handlers:
            h.flush()
        text = Path(path).read_text(encoding="utf-8")
        # [2026-07-30 16:23:11.123] [INFO] [timers] fired collect_base
        assert re.search(r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}\] \[INFO\] \[timers\] "
                         r"fired collect_base$", text, re.M), text
        assert "[WARNING] [panel] panel-level line" in text


def test_rotation_caps_the_file() -> None:
    _reset()
    with _scratch() as tmp:
        path = os.path.join(tmp, "debug.log")
        # 1 KB per file, 3 backups: writing well past that must roll over.
        dbg.configure(path, max_bytes=1024, backups=3, level="DEBUG")
        log = dbg.get_logger("timers")
        for i in range(500):
            log.info("line %04d — some padding to fill the file quickly", i)
        for h in logging.getLogger(dbg.ROOT_NAME).handlers:
            h.flush()
        files = dbg.log_files(path)
        assert len(files) >= 2, "rotation should have produced at least one backup"
        assert len(files) <= 4, "backupCount=3 caps it at the log + three backups"
        for f in files:
            assert os.path.getsize(f) <= 2048, f"{f} blew past the rotation cap"


def test_make_archive_bundles_newest_files() -> None:
    _reset()
    with _scratch() as tmp:
        path = os.path.join(tmp, "debug.log")
        dbg.configure(path, max_bytes=1024, backups=5, level="DEBUG")
        log = dbg.get_logger("timers")
        for i in range(500):
            log.info("line %04d filler filler filler", i)
        for h in logging.getLogger(dbg.ROOT_NAME).handlers:
            h.flush()
        want = {os.path.basename(f) for f in dbg.log_files(path)[:sender.DEFAULT_KEEP]}
        archive = sender.make_archive(path=path)
        with zipfile.ZipFile(archive) as z:
            names = set(z.namelist())
        assert names == want, f"archive {names} != newest {want}"
        assert len(names) <= sender.DEFAULT_KEEP


def test_make_archive_when_empty_is_a_truthful_empty_zip() -> None:
    _reset()
    with _scratch() as tmp:
        path = os.path.join(tmp, "never-written.log")   # nothing logged
        archive = sender.make_archive(path=path)
        assert os.path.exists(archive)
        with zipfile.ZipFile(archive) as z:
            assert z.namelist() == []


def test_send_disabled_when_url_blank() -> None:
    _reset()
    with _scratch() as tmp:
        path = os.path.join(tmp, "debug.log")
        dbg.configure(path, level="INFO")
        dbg.get_logger("panel").info("something")
        status, archive, _detail = sender.send("", path=path)
        assert status == "disabled"
        assert os.path.exists(archive), "the zip is written even with nowhere to send it"


def test_send_stub_when_url_set() -> None:
    _reset()
    with _scratch() as tmp:
        path = os.path.join(tmp, "debug.log")
        dbg.configure(path, level="INFO")
        dbg.get_logger("panel").info("something")
        status, archive, detail = sender.send("https://logs.example/upload", path=path)
        assert status == "stub", "no transport is wired yet — it must report the stub"
        assert os.path.exists(archive)
        assert "logs.example" in detail


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

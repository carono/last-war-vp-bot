r"""The panel's technical debug log (panel/debug_log.py) — rotation, archive, send.

This half of the feature is deliberately Tk-free: a rotating file logger plus the
zip-and-hand-off helpers, so it can be pinned down without a display. What is worth
holding still:

  * setup() is idempotent — a second call (a profile switch) re-points the file and
    never stacks two handlers writing at once;
  * rotation actually caps the file — a tiny maxBytes rolls the log over into the
    numbered backups instead of growing one file forever;
  * make_archive() bundles the live log AND its backups, and is truthful (an empty
    zip) when nothing has been logged yet;
  * send_archive() always writes the archive and reports the destination is a stub
    until a transport is wired — and says "no destination" when the field is blank.

Runs anywhere (no tkinter, no game):

    python3 tests/test_panel_debug_log.py
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import zipfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from panel import debug_log as dbg


def _reset() -> None:
    """A clean logger between tests — no handlers left from a prior one."""
    dbg.shutdown()
    lg = dbg.get_logger()
    for h in list(lg.handlers):
        lg.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass


def test_level_of() -> None:
    assert dbg.level_of("debug") == logging.DEBUG
    assert dbg.level_of("INFO") == logging.INFO
    assert dbg.level_of("Warning") == logging.WARNING
    assert dbg.level_of("error") == logging.ERROR
    assert dbg.level_of("nonsense") == logging.DEBUG   # unknown -> DEBUG
    assert dbg.level_of(None) == logging.DEBUG


def test_setup_is_idempotent() -> None:
    _reset()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "sub", "debug.log")   # dir does not exist yet
        dbg.setup(path, max_kb=64, backups=2, level="INFO")
        dbg.setup(path, max_kb=64, backups=2, level="INFO")   # second call
        lg = dbg.get_logger()
        ours = [h for h in lg.handlers if getattr(h, "_panel_debug", False)]
        assert len(ours) == 1, f"expected one handler, got {len(ours)}"
        assert lg.level == logging.INFO
        lg.info("hello")
        assert os.path.exists(path), "setup must create the file's directory"
        assert "hello" in Path(path).read_text(encoding="utf-8")
    _reset()


def test_rotation_caps_the_file() -> None:
    _reset()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "debug.log")
        # 1 KB per file, 3 backups: writing well past that must roll over rather
        # than grow one unbounded file.
        dbg.setup(path, max_kb=1, backups=3, level="DEBUG")
        lg = dbg.get_logger()
        for i in range(500):
            lg.info("line %04d — some padding to fill the file quickly", i)
        for h in lg.handlers:
            h.flush()
        files = dbg.log_files(path)
        assert len(files) >= 2, "rotation should have produced at least one backup"
        assert len(files) <= 4, "backupCount=3 caps it at the log + three backups"
        for f in files:
            assert os.path.getsize(f) <= 4096, f"{f} blew past the rotation cap"
    _reset()


def test_make_archive_bundles_log_and_backups() -> None:
    _reset()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "debug.log")
        dbg.setup(path, max_kb=1, backups=3, level="DEBUG")
        lg = dbg.get_logger()
        for i in range(500):
            lg.info("line %04d filler filler filler", i)
        for h in lg.handlers:
            h.flush()
        want = {os.path.basename(f) for f in dbg.log_files(path)}
        archive = dbg.make_archive(path=path)
        assert archive.endswith(".zip")
        with zipfile.ZipFile(archive) as z:
            names = set(z.namelist())
        assert names == want, f"archive {names} != on-disk {want}"
    _reset()


def test_make_archive_when_empty_is_a_truthful_empty_zip() -> None:
    _reset()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "never-written.log")   # nothing logged
        archive = dbg.make_archive(path=path)
        assert os.path.exists(archive)
        with zipfile.ZipFile(archive) as z:
            assert z.namelist() == []
    _reset()


def test_send_archive_no_destination() -> None:
    _reset()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "debug.log")
        dbg.setup(path, max_kb=64, backups=1, level="INFO")
        dbg.get_logger().info("something")
        status, archive, _detail = dbg.send_archive("", path=path)
        assert status == "no_dest"
        assert os.path.exists(archive), "the zip is written even with nowhere to send it"
    _reset()


def test_send_archive_stub_when_destination_set() -> None:
    _reset()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "debug.log")
        dbg.setup(path, max_kb=64, backups=1, level="INFO")
        dbg.get_logger().info("something")
        status, archive, detail = dbg.send_archive("s3://bucket/logs", path=path)
        assert status == "stub", "no transport is wired yet — it must report the stub"
        assert os.path.exists(archive)
        assert "s3://bucket/logs" in detail
    _reset()


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

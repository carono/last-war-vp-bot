r"""Reading the Windows crash evidence — the parts that need no Windows (#2656).

`tools/crash_report.py` answers «why did the client vanish» from three places outside
this repository. Two of its jobs can be pinned without any of them:

  * **the event message is read by SHAPE, not by wording.** Event 1000 is translated —
    the machine this was written for reports it in Russian — so a parser that looks for
    «Faulting module name» finds nothing on most installs and quietly reports the
    program itself as the faulting module. What does NOT translate is the order: the
    crashing program first and the faulting module second, three 8-hex numbers of which
    the last is the exception code, one 16-hex offset.
  * **the panel's log is read once for every fault**, not once per fault. A busy
    profile's `panel.log` runs to hundreds of megabytes and a week holds dozens of
    faults; per-fault passes turn a two-second report into an afternoon.

    C:\Python312\python.exe tests\test_crash_report.py
    python3 tests/test_crash_report.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import crash_report as cr  # noqa: E402

# Event 1000, the two locales this has been seen in, with invented values throughout:
# no build of the game ever reported these numbers and no account is named by them.
_EN = ("Faulting application name: LastWar.exe, version: 2019.4.40.50731, time stamp: "
       "0x11111111 Faulting module name: UnityPlayer.dll, version: 2019.4.40.50731, "
       "time stamp: 0x22222222 Exception code: 0xc0000005 Fault offset: "
       "0x0000000000123456 Faulting process id: 0x1234")
_RU = ("Имя сбойного приложения: LastWar.exe, версия: 2019.4.40.50731, метка времени: "
       "0x11111111 Имя сбойного модуля: unknown, версия: 0.0.0.0, метка времени: "
       "0x00000000 Код исключения: 0xc0000005 Смещение ошибки: 0x00000000abcdef01")


def test_event_read_by_shape() -> None:
    en = cr.parse_event(_EN)
    assert en["module"] == "UnityPlayer.dll", en
    assert en["code"] == "0xc0000005", en
    assert en["offset"] == "0x0000000000123456", en

    ru = cr.parse_event(_RU)
    assert ru["module"] == "unknown", "a fault in no module at all is the interesting one"
    assert ru["code"] == "0xc0000005", ru
    assert ru["offset"] == "0x00000000abcdef01", ru


def test_event_that_says_nothing() -> None:
    blank = cr.parse_event("something else entirely")
    assert blank["module"] == "?" and blank["code"] == "?" and blank["offset"] == "?"


def test_panel_windows_one_pass() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "panel.log"
        start = dt.datetime(2026, 1, 2, 3, 0, 0)
        with log.open("w", encoding="utf-8") as fh:
            for i in range(600):
                when = start + dt.timedelta(seconds=i)
                fh.write(f"{when:%Y-%m-%d %H:%M:%S} [timer] line {i}\n")
            fh.write("a line with no stamp at all\n")

        opened = {"count": 0}
        real_open = Path.open

        def counting_open(self, *a, **kw):           # noqa: ANN001
            if self == log:
                opened["count"] += 1
            return real_open(self, *a, **kw)

        Path.open = counting_open
        try:
            moments = [start + dt.timedelta(seconds=n) for n in (100, 300, 500)]
            found = cr.panel_windows(log, moments, before=5, after=2)
        finally:
            Path.open = real_open

        assert opened["count"] == 1, f"one pass for three faults, not {opened['count']}"
        assert set(found) == set(moments)
        for at in moments:
            assert len(found[at]) == 8, f"5 before + the second itself + 2 after: {found[at]}"
            assert f"{at:%H:%M:%S}" in found[at][5]


def test_paths_are_asked_never_assumed() -> None:
    was_ps = os.environ.get("LW_POWERSHELL")
    was_dumps = os.environ.get("LW_CRASH_DUMPS")
    try:
        os.environ["LW_POWERSHELL"] = str(_REPO / "nothing" / "here.exe")
        assert cr.powershell() is None, "a named shell that is not there is not a shell"
        os.environ["LW_CRASH_DUMPS"] = str(_REPO / "somewhere" / "dumps")
        assert cr.dump_dir() == Path(_REPO / "somewhere" / "dumps")
        del os.environ["LW_CRASH_DUMPS"]
        assert cr.dump_dir().name == "CrashDumps", "and the ordinary spot otherwise"
    finally:
        for key, was in (("LW_POWERSHELL", was_ps), ("LW_CRASH_DUMPS", was_dumps)):
            if was is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = was


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

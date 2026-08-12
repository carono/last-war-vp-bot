r"""The window search survives a client that renames its window (#1320).

A client update is free to change the string in the title bar, and for a year the whole
of «which window is the game» was one literal compared against it. The day that string
changed, every reading in the panel would have reported no client about a client that
was plainly on screen — and «игра не найдена» is a true sentence for that, and for
nobody having started the game, and there is no way to tell the two apart from outside.

So: several titles are tried, and failing all of them the game's own PROCESS is asked,
loudly. What is pinned here is that the loud fallback exists, that it prefers the window
a person would be looking at, and that it never fires while a title does match — a
fallback that fires early would happily return the client of another build.

    C:\Python312\python.exe tests\test_find_window_by_process.py
    python3 tests/test_find_window_by_process.py
"""
from __future__ import annotations

import logging
import os
import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO / "tools" / "lib", _REPO / "src", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


class _Desktop:
    """A pretend Windows desktop: a handful of windows owned by pretend processes.

    Installed as `win32gui` / `win32process` / `psutil` for the length of a block, which
    is the only way to exercise this on a machine that is not Windows — and the only way
    to exercise it on one that IS without a real client running.
    """

    def __init__(self, windows) -> None:
        # (hwnd, title, pid, process, visible, area)
        self.windows = list(windows)
        self._saved: dict = {}

    def __enter__(self):
        by_hwnd = {w[0]: w for w in self.windows}

        win32gui = types.ModuleType("win32gui")
        win32gui.EnumWindows = lambda cb, ctx: [cb(w[0], ctx) for w in self.windows]
        win32gui.IsWindowVisible = lambda h: by_hwnd[h][4]
        win32gui.GetWindowText = lambda h: by_hwnd[h][1]
        win32gui.GetWindowRect = lambda h: (0, 0, by_hwnd[h][5], 1)

        win32process = types.ModuleType("win32process")
        win32process.GetWindowThreadProcessId = lambda h: (0, by_hwnd[h][2])

        class _Proc:
            def __init__(self, pid):
                found = [w for w in by_hwnd.values() if w[2] == pid]
                if not found:
                    raise psutil.NoSuchProcess(pid)
                self._name = found[0][3]

            def name(self):
                return self._name

        psutil = types.ModuleType("psutil")

        class NoSuchProcess(Exception):
            def __init__(self, pid=0):
                super().__init__(pid)

        psutil.NoSuchProcess = NoSuchProcess
        psutil.AccessDenied = type("AccessDenied", (Exception,), {})
        psutil.Process = _Proc

        for name, module in (("win32gui", win32gui), ("win32process", win32process),
                             ("psutil", psutil)):
            self._saved[name] = sys.modules.get(name)
            sys.modules[name] = module
        self._saved["__platform__"] = sys.platform
        sys.platform = "win32"
        return self

    def __exit__(self, *exc):
        sys.platform = self._saved.pop("__platform__")
        for name, old in self._saved.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old
        return False


class _Heard:
    """Collect what the search said about itself."""

    def __init__(self, logger_name: str) -> None:
        self.records: list = []
        self._log = logging.getLogger(logger_name)
        self._handler = logging.Handler()
        self._handler.emit = self.records.append

    def __enter__(self):
        self._log.addHandler(self._handler)
        self._log.setLevel(logging.DEBUG)
        return self

    def __exit__(self, *exc):
        self._log.removeHandler(self._handler)
        return False

    @property
    def warnings(self) -> list:
        return [r.getMessage() for r in self.records if r.levelno >= logging.WARNING]


class _env:
    def __init__(self, **values) -> None:
        self._want = values
        self._saved: dict = {}

    def __enter__(self):
        for key, value in self._want.items():
            self._saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, *exc):
        for key, old in self._saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        return False


#: The client, a helper window of its own, and something else entirely. The helper is
#: the reason «any window of that process» is not enough on its own: the real client
#: keeps an invisible 1×1 one beside it.
_GAME = 100, "Whatever The Build Calls Itself", 7, "LastWar.exe", True, 1700
_HELPER = 101, "GDI+ Window", 7, "LastWar.exe", False, 1
_OTHER = 102, "A Text Editor", 9, "editor.exe", True, 900


def test_a_matching_title_is_used_and_says_nothing():
    from lastwar_bot.perception import capture

    with _env(LW_WINDOW_TITLE="Whatever The Build"), _Desktop([_GAME, _HELPER, _OTHER]):
        with _Heard("lastwar_bot.perception.capture") as heard:
            found = capture.find_window()
        assert found.hwnd == 100
        assert not heard.warnings, "a search that worked must be quiet"


def test_a_renamed_window_is_still_found_by_its_process_and_says_so():
    from lastwar_bot.perception import capture

    with _env(LW_WINDOW_TITLE="The Name It Used To Have"):
        with _Desktop([_OTHER, _GAME, _HELPER]):
            with _Heard("lastwar_bot.perception.capture") as heard:
                found = capture.find_window()
    assert found.hwnd == 100, "the game's own process is the answer, whatever it is called"
    assert found.process_name == "LastWar.exe"
    said = " ".join(heard.warnings)
    assert said, "a fallback nobody is told about is a fault nobody can fix"
    assert "Whatever The Build Calls Itself" in said, "the new title is what belongs in the variable"
    assert "LW_WINDOW_TITLE" in said, "…and it says where to put it"


def test_the_fallback_never_returns_a_window_of_another_process():
    from lastwar_bot.perception import capture

    with _env(LW_WINDOW_TITLE="Nothing Matches This"):
        with _Desktop([_OTHER]):
            try:
                capture.find_window()
            except capture.WindowNotFoundError as exc:
                assert "Nothing Matches This" in str(exc)
            else:
                raise AssertionError("another program's window was taken for the game")


def test_the_biggest_window_of_the_process_is_the_client():
    """The client keeps a hidden 1×1 helper; a capture aimed at it produces nothing."""
    from lastwar_bot.perception import capture

    visible_helper = 103, "LastWar helper", 7, "LastWar.exe", True, 1
    with _env(LW_WINDOW_TITLE="No Such Title"):
        with _Desktop([visible_helper, _GAME]), _Heard("lastwar_bot.perception.capture"):
            found = capture.find_window()
    assert found.hwnd == 100


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

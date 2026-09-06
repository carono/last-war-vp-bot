r"""A restart brings back the profiles that are OPEN, not the ones argv asked for (#2578).

`relaunch` replays this process's own command line, and `HeadlessPanel.open` gives argv
priority over the standing list (`names = self._names or _last_open()`). Those two are
fine apart and wrong together: a panel started as `--profile a` that later opened `b` —
from the phone, or off the standing list — comes back holding only `a`, and `b` is left
closed with nothing anywhere saying it was dropped.

That happened live on 2026-09-06. A restart meant to deliver one account's fix took the
OTHER account off the game, and the only trace was a line in the relaunch log naming one
profile where the previous entries had named two.

What is pinned:

  * the replacement is asked for every profile that is open at the moment of the press;
  * the profiles are read BEFORE the shutdown, which is what closes them;
  * `--no-web` survives, because a panel that was told not to bind a port must not come
    back binding one.

    C:\Python312\python.exe tests\test_panel_restart_keeps_profiles.py
    python3 tests/test_panel_restart_keeps_profiles.py
"""
from __future__ import annotations

TIER = "offline"

import pathlib
import sys
import types

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))


def _stub_tk() -> None:
    class _W:
        def __init__(self, *a, **k) -> None:
            pass

        def __getattr__(self, _n):
            return lambda *a, **k: None

    def _module(name: str):
        mod = types.ModuleType(name)
        made: dict = {}

        def _make(attr: str):
            if attr not in made:
                made[attr] = type(attr, (_W,), {})
            return made[attr]

        mod.__getattr__ = _make
        return mod

    tk = _module("tkinter")
    tk.TclError = type("TclError", (Exception,), {})
    sys.modules["tkinter"] = tk
    for sub in ("ttk", "font", "messagebox", "simpledialog", "scrolledtext",
                "filedialog"):
        child = _module(f"tkinter.{sub}")
        sys.modules[f"tkinter.{sub}"] = child
        setattr(tk, sub, child)


_stub_tk()

from panel import headless as hl                              # noqa: E402


class _Session:
    def __init__(self, name: str) -> None:
        self.name = name


class _Workspace:
    def __init__(self, names) -> None:
        self.sessions = [_Session(n) for n in names]


def _panel(names, web: bool = True):
    """A HeadlessPanel with only what `_restart_now` touches."""
    p = object.__new__(hl.HeadlessPanel)
    p.workspace = _Workspace(names)
    p._web = web
    p._stop = types.SimpleNamespace(set=lambda: None)
    return p


def _press(panel, *, empty_on_shutdown: bool = True) -> list:
    """Run `_restart_now` with the relaunch captured. The argv it asked for."""
    seen: dict = {}
    real = hl.updatesmod.relaunch

    def fake(argv=None, **_kw):
        seen["argv"] = list(argv or [])
        return None

    def shutdown(**_kw) -> None:
        # THE SHUTDOWN IS WHAT CLOSES THE PROFILES. A `_restart_now` that read them
        # after this would ask for none of them, which is exactly the failure being
        # pinned — so the fake empties the workspace the way the real one does.
        if empty_on_shutdown:
            panel.workspace.sessions = []

    panel.shutdown = shutdown
    hl.updatesmod.relaunch = fake
    try:
        panel._restart_now()
    finally:
        hl.updatesmod.relaunch = real
    return seen.get("argv", [])


def test_every_open_profile_is_asked_for():
    argv = _press(_panel(["default", "sooperj"]))
    assert argv == ["--profile", "default", "--profile", "sooperj"], argv


def test_the_profiles_are_read_before_the_shutdown():
    """The whole bug in one assertion: read after the shutdown and the list is empty."""
    argv = _press(_panel(["default", "sooperj"]), empty_on_shutdown=True)
    assert "default" in argv and "sooperj" in argv, \
        f"the restart asked for nothing because the shutdown had already run: {argv}"


def test_a_single_profile_is_unchanged():
    assert _press(_panel(["sooperj"])) == ["--profile", "sooperj"]


def test_no_web_survives_the_restart():
    argv = _press(_panel(["sooperj"], web=False))
    assert argv[-1] == "--no-web", f"a portless panel came back binding a port: {argv}"


def test_a_panel_holding_nothing_asks_for_nothing():
    assert _press(_panel([])) == []


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
        else:
            print(f"  ok   {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())

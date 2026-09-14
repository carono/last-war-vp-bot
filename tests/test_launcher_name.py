r"""The launcher's FILENAME is a profile's setting, and it travels (task #2882).

Why it exists at all: an anti-virus can block one account's copy of the launcher by its
PATH while the byte-identical file under another name starts perfectly — measured live in
#2865, where a profile spent a night reported as «клиент не запущен» over a launcher that
was refused before it drew a window. The install itself stays the machine's own answer
(`tools/lib/game_paths.py`); the filename inside it is the one part of it an account may
legitimately differ in, so it is a setting, it is editable from the phone, and a name the
install does not have is refused rather than stored.

These pin the four places it has to reach and the guard that checks it. No Tk, no game,
no Windows.

    C:\Python312\python.exe tests\test_launcher_name.py
    python3 tests/test_launcher_name.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "lib"))
sys.path.insert(0, str(ROOT / "src"))

import game_client                                             # noqa: E402
import game_paths                                              # noqa: E402
from panel.runtime import game_process, settings as settingsmod  # noqa: E402


class _Settings:
    """The two knobs these functions read, and nothing else."""

    def __init__(self, name: str = "", user: str = "") -> None:
        self._name, self._user = name, user

    def opt_str(self, key: str) -> str:
        return {"launcher_exe": self._name, "rdp_user": self._user}.get(key, "")

    def opt_bool(self, key: str) -> bool:
        return bool(self._user) if key == "rdp_session" else False


def test_a_profile_that_was_never_asked_behaves_exactly_as_before():
    """Empty means «whatever this machine answers» — no profile changes behaviour."""
    assert settingsmod.DEFAULTS["launcher_exe"] == "", settingsmod.DEFAULTS["launcher_exe"]
    assert game_process.profile_launcher_exe(_Settings()) == game_paths.launcher_exe()


def test_a_name_the_profile_gave_is_what_comes_back():
    """…and only ever as a NAME: a path typed into it cannot reach the resolver."""
    assert game_process.profile_launcher_exe(_Settings("Other.exe")) == "Other.exe"
    assert game_process.profile_launcher_exe(
        _Settings(os.path.join("C:", os.sep, "x", "Other.exe"))) == "Other.exe"


def test_a_path_is_refused_and_an_empty_name_is_always_allowed():
    """Empty is how a profile goes back to the machine's answer, so it never refuses."""
    ok, _why = game_process.launcher_check(_Settings(), "")
    assert ok
    for typed in (r"C:\Games\LW\Launcher.exe", "sub/Launcher.exe", ".."):
        ok, why = game_process.launcher_check(_Settings(), typed)
        assert not ok and why == "opt.launcher_exe.not_a_name", (typed, why)


def test_a_name_the_install_does_not_have_is_refused_with_a_reason(tmp=None):
    """A folder we CAN read and no such file in it is a refusal — the whole guard."""
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        open(os.path.join(folder, "There.exe"), "w").close()
        saved = game_process.launcher_dir
        game_process.launcher_dir = lambda _s: folder
        try:
            ok, _why = game_process.launcher_check(_Settings(), "There.exe")
            assert ok, "a file that is right there was refused"
            ok, why = game_process.launcher_check(_Settings(), "Missing.exe")
            assert not ok and why == "opt.launcher_exe.missing", why
        finally:
            game_process.launcher_dir = saved


def test_a_folder_we_cannot_read_is_not_a_refusal():
    """«I could not check» is not «it is not there» — and the second account's install
    is exactly the folder this process may not be allowed to read."""
    saved = game_process.launcher_dir
    game_process.launcher_dir = lambda _s: ""
    try:
        ok, why = game_process.launcher_check(_Settings(user="player2"), "Anything.exe")
        assert ok, why
    finally:
        game_process.launcher_dir = saved


def test_the_name_reaches_the_start_on_this_desktop():
    """`start` joins it to the install it resolves — never to a path of its own."""
    seen: dict = {}
    saved = (game_client._start_here, game_client.default_launcher)
    game_client._start_here = lambda path, say, exe=None: seen.update(path=path, exe=exe)
    game_client.default_launcher = lambda: os.path.join("C:", os.sep, "LW",
                                                        "LastWarLauncher.exe")
    import test_mode

    # A test may not start the live client (`tools/lib/test_mode.py`, #2002), and this
    # one does not: `_start_here` is the stub above. The refusal has to be lifted for
    # the composition under it — which launcher path is built from which name — to be
    # reachable at all.
    in_test = test_mode.in_test_run
    test_mode.in_test_run = lambda *_a, **_k: False
    try:
        game_client.start(launcher_exe="Other.exe")
    finally:
        test_mode.in_test_run = in_test
    game_client._start_here, game_client.default_launcher = saved
    assert seen.get("exe") == "Other.exe", seen
    assert os.path.basename(seen.get("path", "")) == "Other.exe", seen


def test_the_stuck_launcher_sweep_looks_for_the_profiles_own_file():
    """A sweep that looked for the default name would leave the real one standing."""
    asked: list = []
    saved = game_client.proc_table.pids_named
    game_client.proc_table.pids_named = lambda name: asked.append(name) or []
    try:
        game_client.launcher_pids(exe="Other.exe")
        game_client.launcher_pids()
    finally:
        game_client.proc_table.pids_named = saved
    assert asked == ["Other.exe", game_paths.launcher_exe()], asked


def _run() -> int:
    bad = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
        except Exception as exc:                  # noqa: BLE001 — a report, not a crash
            bad += 1
            print(f"FAIL {name}: {exc}")
        else:
            print(f"  ok   {name}")
    print(f"\n{'all passed' if not bad else f'{bad} failed'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_run())

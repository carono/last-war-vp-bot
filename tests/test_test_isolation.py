r"""A TEST RUN MAY NOT TOUCH THE LIVE MACHINE (#2002).

The suite runs on the computer that is also farming. Nothing separates the two by itself —
the profiles tree is derived from where the repository is, the web port is the machine's,
the client is the one that is playing — so a test that reaches for «the panel» reaches for
the live one.

What that cost, live: `tests/test_panel_service.py` started a real `Service`, and a service
owns a `Keeper` that supervises the profiles this machine farms. So a plain
`python3 tools/run_tests.py` spawned `-m panel.headless --profile default` on the LIVE
account, DETACHED. It outlived the run (PPID 1), bound the panel's port, wrote into the
account's own `panel.log`, took the machine lease away from the real panel — which then sat
saying «клиент сейчас держит кто-то другой — жду» — and every five minutes played
`launch_game` against the real game client, for hours.

It was recognisable only by fingerprints a real panel cannot have: `No module named
'tkinter'`, «creationflags is only supported on Windows platforms», and a launcher path
built by a POSIX `os.path.join` out of an UNEXPANDED `~\AppData\Local`. The last of those
is fixed here too, because a wrong path that reads as a plausible one is how the ghost
stayed unnoticed.

What is pinned:

  * `tools/lib/test_mode.py` knows it is in a test run — by the runner's variable, or by
    being a file under `tests/` — and ARMS the variable so children know as well;
  * the runner hands the variable to every file it runs;
  * the three guards refuse: starting the game client, a keeper starting a panel, and a
    workspace opening one of THIS machine's profiles;
  * a scratch profiles tree is not refused, because that is what a well-behaved test does;
  * `tests/test_panel_service.py` switches the supervisor off in its own configs.

    C:\Python312\python.exe tests\test_test_isolation.py
    python3 tests/test_test_isolation.py
"""
from __future__ import annotations

TIER = "offline"

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import test_mode                                        # noqa: E402


class _Env:
    """`LW_TEST_RUN` put back exactly as it was, whatever the test did to it."""

    def __init__(self, value: "str | None") -> None:
        self._want = value

    def __enter__(self):
        self._had = os.environ.get(test_mode.ENV)
        if self._want is None:
            os.environ.pop(test_mode.ENV, None)
        else:
            os.environ[test_mode.ENV] = self._want
        return self

    def __exit__(self, *_exc) -> None:
        if self._had is None:
            os.environ.pop(test_mode.ENV, None)
        else:
            os.environ[test_mode.ENV] = self._had


# ---------------------------------------------------------------------------
def test_a_test_run_knows_itself_by_the_variable_or_by_its_own_file_name() -> None:
    with _Env("1"):
        assert test_mode.in_test_run(["anything"]) is True
    with _Env(None):
        assert test_mode.in_test_run(["tools/run_tests.py"]) is False
        assert test_mode.in_test_run([str(_REPO / "panel" / "headless.py")]) is False
        # …and a file under tests/ is one whatever started it.
        assert test_mode.in_test_run([str(_REPO / "tests" / "test_whatever.py")]) is True


def test_recognising_it_by_the_file_name_ARMS_it_for_the_children() -> None:
    """The damage was done by a GRANDCHILD, whose own command line said nothing.

    A panel spawned by a test has an ordinary panel's argv; the only thing that can tell
    it what it is part of is the environment it inherited.
    """
    with _Env(None):
        assert os.environ.get(test_mode.ENV) is None
        test_mode.in_test_run([str(_REPO / "tests" / "test_whatever.py")])
        assert os.environ.get(test_mode.ENV) == "1", "a child would not have known"
    with _Env(None):
        assert test_mode.in_test_run(["something-else"]) is False
        assert os.environ.get(test_mode.ENV) is None, "armed a run that is not a test"


def test_switching_it_off_is_possible_for_the_run_that_really_means_it() -> None:
    """A live-tier test that genuinely starts the client has a way to say so."""
    for said in ("", "0", "no", "false"):
        with _Env(said):
            assert test_mode.in_test_run(["anything"]) is False


def test_the_runner_hands_the_variable_to_every_file_it_runs() -> None:
    """Read by RUNNING the runner over a scratch file, not by reading its source."""
    import run_tests

    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "test_probe.py"
        probe.write_text("import os\n"
                         "print('SAW', os.environ.get('LW_TEST_RUN'))\n",
                         encoding="utf-8")
        result = run_tests.run_one(probe, timeout=60.0)
    assert result.ok, result.output
    assert "SAW 1" in result.output, result.output


# --------------------------------------------------------------- the guards --
def test_a_test_may_not_start_the_game_client() -> None:
    import game_client

    with _Env("1"):
        try:
            game_client.start()
        except RuntimeError as exc:
            assert "test run" in str(exc), exc
        else:
            raise AssertionError("a test started the game")


def test_the_launcher_that_really_starts_a_panel_refuses_in_a_test_run() -> None:
    """Guarded in the LAUNCHER, not in the keeper: a keeper handed a launcher of its own
    (`tests/test_service_keeper.py`) must go on exercising every branch it has."""
    from panel.service import session as sessionmod

    lines: list = []
    with _Env("1"):
        said = sessionmod.launch([sys.executable, "-m", "panel.headless",
                                  "--profile", "default"], log=lines.append)
    assert said.get("ok") is False and said.get("why") == "test_run", said
    assert any("test run" in ln for ln in lines), lines


def test_a_keeper_with_no_launcher_of_its_own_starts_nothing_in_a_test_run() -> None:
    """The path the ghost took: a real `Service` builds a keeper with the real launcher."""
    from panel.service import keeper as keepermod

    lines: list = []
    keep = keepermod.Keeper(None, {"keep": {"profiles": ["solo"]}}, log=lines.append)
    with _Env("1"):
        said = keep.launch(["solo"])
    assert said.get("ok") is False and said.get("why") == "test_run", said


def test_a_workspace_in_a_test_run_will_not_open_a_LIVE_profile() -> None:
    from panel import paths as pathsmod
    from panel import profile as profilemod
    from panel.runtime import workspace as wsmod

    saved = profilemod.PROFILES_DIR
    try:
        profilemod.PROFILES_DIR = os.path.join(pathsmod.PROJECT_DIR, "profiles")
        with _Env("1"):
            try:
                wsmod._refuse_a_live_profile_in_a_test("default")
            except RuntimeError as exc:
                assert "default" in str(exc), exc
            else:
                raise AssertionError("a test opened the live profile")
        # …and the PANEL itself is unaffected: outside a test run the guard is a
        # no-op, which cannot be shown by unsetting the variable here — this file is
        # under `tests/`, so `test_mode` recognises it and arms it again.
        real = test_mode.in_test_run
        test_mode.in_test_run = lambda *a, **kw: False
        try:
            wsmod._refuse_a_live_profile_in_a_test("default")
        finally:
            test_mode.in_test_run = real
    finally:
        profilemod.PROFILES_DIR = saved


def test_a_SCRATCH_profiles_tree_is_exactly_what_a_test_should_do() -> None:
    from panel import profile as profilemod
    from panel.runtime import workspace as wsmod

    saved = profilemod.PROFILES_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp, _Env("1"):
            profilemod.PROFILES_DIR = os.path.join(tmp, "profiles")
            wsmod._refuse_a_live_profile_in_a_test("solo")
    finally:
        profilemod.PROFILES_DIR = saved


def test_the_service_tests_switch_their_supervisor_off() -> None:
    """The file that started the ghost. Its own configs say `keep` now, every one."""
    source = (_REPO / "tests" / "test_panel_service.py").read_text(encoding="utf-8")
    made = [chunk for chunk in source.split("Service({")[1:]]
    assert made, "no service is built in there any more — check this test"
    for chunk in made:
        head = chunk.split("}")[0]
        assert '"keep"' in head, f"a Service with a live supervisor: Service({{{head}}}"


def test_the_local_appdata_fallback_is_a_path_and_not_a_tilde() -> None:
    """DEFECT 2, and the thing that gave the ghost away — under a POSIX interpreter
    `expanduser(r"~\\AppData\\Local")` came back verbatim, tilde and all."""
    import game_paths

    had = os.environ.pop("LOCALAPPDATA", None)
    try:
        said = game_paths.local_appdata()
    finally:
        if had is not None:
            os.environ["LOCALAPPDATA"] = had
    assert "~" not in said, said
    assert said.startswith(os.path.expanduser("~")), said
    assert os.path.basename(said) == "Local", said


# ---------------------------------------------------------------------------
def _run_them() -> int:
    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"ok   {name}")
        except Exception as exc:              # noqa: BLE001 — a test runner
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print("FAILED" if failed else "ALL PASSED")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_them())

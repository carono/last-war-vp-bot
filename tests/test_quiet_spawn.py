r"""No process is started with a console window — task #2874.

The panel runs windowless: as the `LastWarBot` service, or under `pythonw.exe`. A child
it starts therefore has nowhere to print, and Windows answers that by handing the child
a console OF ITS OWN — a black box drawn over whatever the person is looking at, for as
long as the child runs. A client restart used to cost several of them, and none of it
shows up in any log, because a flashing window is not an error.

The cure is one flag (`CREATE_NO_WINDOW`, `tools/lib/quiet_proc.py`), and the reason it
needs a test is that forgetting it is invisible: the code works, the exit codes are
right, and only somebody sitting at the machine ever finds out.

So this walks the source that the panel can reach and fails on a `subprocess.Popen` /
`subprocess.run` that has no way of being quiet. A spawn that MUST be seen is named in
:data:`VISIBLE`, with the reason beside it — that list is the whole record of what the
rule deliberately does not cover.

Run:
    C:\Python312\python.exe tests\test_quiet_spawn.py
    python3 tests/test_quiet_spawn.py
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

#: The trees a running panel actually reaches. `tools/dev`, `tools/archive` and
#: `tools/scratch` are a person's own command line and are left alone on purpose.
SCANNED = ["panel", "src/lastwar_bot", "tools"]
SKIP_DIRS = {"dev", "archive", "scratch", "__pycache__"}

#: The spawns that are meant to draw something, `path: reason`. Each one is a window a
#: person asked for; hiding it would hide the thing they asked for.
VISIBLE = {
    # `mstsc` IS the window — it draws the other session's desktop, and Windows may put
    # a credential dialog on it.
    "tools/rdp_instance.py": "mstsc draws the session; cmdkey reads a password from its "
                             "own console, and is fenced off by an isatty guard",
    # The file manager, the browser, the desktop's own opener: all GUI, all asked for.
    "panel/__main__.py": "explorer / open / xdg-open — a folder the person asked to see",
}

#: Spawns the rule does not reach, `path: reason` — never «not done yet».
EXEMPT = {
    # The helper itself: these two calls ARE the flag being applied.
    "tools/lib/quiet_proc.py": "this is where the flag is put on",
    # A person's own command line, run from a terminal that already has a console.
    "tools/run_tests.py": "the test runner — started from a terminal, by a person",
    # Linux only: `ip route` inside WSL, where the flag does not exist.
    "tools/golden_round.py": "asks WSL's own `ip`, never Windows",
    "tools/gpu_load.py": "asks the host's GPU from a terminal, by hand",
}

#: What makes a call quiet. Any of these in the call's own source is enough.
QUIET_MARKS = ("creationflags", "quiet_proc.", "_QUIET", "startupinfo")


def _files() -> list[Path]:
    found = []
    for root in SCANNED:
        base = _REPO / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if SKIP_DIRS & set(path.relative_to(_REPO).parts):
                continue
            found.append(path)
    return found


def _spawns(path: Path) -> list[tuple[int, str]]:
    """Every `subprocess.Popen` / `.run` / `.call` call in ``path``, as (line, source)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(text)
    lines = text.splitlines()
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("Popen", "run", "call", "check_call", "check_output"):
            continue
        owner = node.func.value
        if not (isinstance(owner, ast.Name) and owner.id == "subprocess"):
            continue
        end = getattr(node, "end_lineno", node.lineno) or node.lineno
        out.append((node.lineno, "\n".join(lines[node.lineno - 1:end])))
    return out


def test_every_spawn_is_quiet() -> None:
    """A spawn with no quiet mark, in a file that is not on the visible list."""
    loud = []
    for path in _files():
        rel = path.relative_to(_REPO).as_posix()
        if rel in VISIBLE or rel in EXEMPT:
            continue
        for line, source in _spawns(path):
            if not any(mark in source for mark in QUIET_MARKS):
                loud.append(f"{rel}:{line}")
    assert not loud, (
        "these start a process with a console window (#2874) — pass "
        "`creationflags=CREATE_NO_WINDOW`, or use tools/lib/quiet_proc.py:\n  "
        + "\n  ".join(loud))


def test_quiet_proc_is_a_noop_off_windows() -> None:
    """The helper must not put `creationflags` on a POSIX call — subprocess refuses it."""
    import sys
    sys.path.insert(0, str(_REPO / "tools" / "lib"))
    import quiet_proc                                   # noqa: PLC0415

    if quiet_proc.WINDOWS:
        assert quiet_proc.quiet({})["creationflags"] & quiet_proc.NO_WINDOW
    else:
        assert quiet_proc.quiet({"timeout": 5}) == {"timeout": 5}
        assert quiet_proc.flags() == 0
        assert quiet_proc.hidden_startupinfo() is None


def test_existing_flags_survive() -> None:
    """A caller that already asks for `DETACHED_PROCESS` keeps it — OR, not overwrite."""
    import sys
    sys.path.insert(0, str(_REPO / "tools" / "lib"))
    import quiet_proc                                   # noqa: PLC0415

    if not quiet_proc.WINDOWS:
        return
    got = quiet_proc.quiet({"creationflags": 0x00000008})["creationflags"]
    assert got & 0x00000008 and got & quiet_proc.NO_WINDOW


def test_visible_list_names_real_files() -> None:
    """A reason written for a file that has moved is a rule nobody is enforcing."""
    for rel in list(VISIBLE) + list(EXEMPT):
        assert (_REPO / rel).exists(), f"{rel} is on the visible list and does not exist"


def test_session_launch_hides_a_hidden_launch() -> None:
    """`--hidden` must ask for NO console, never a hidden one (the flash is the gap)."""
    text = (_REPO / "tools" / "session_launch.py").read_text(encoding="utf-8")
    assert "CREATE_NEW_CONSOLE if show else CREATE_NO_WINDOW" in text, \
        "a hidden session launch still asks Windows to draw a console"


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

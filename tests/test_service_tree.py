r"""The service is the ROOT of the process tree, and the tree dies with it (#2613).

    «Питоновские проекты нужно спавнить от службы, чтобы когда я отключаю службу,
      все дочерние скрипты умирали, а не висели в системе»

What is pinned here is the contract rather than the kernel: on Windows the real job is
made and joined (and a real child dies with a process holding one), and everywhere else
`hold()` says «not_windows» and the service runs as it always did. The two flags are
pinned by value because they are what makes the difference — kill on close is the whole
mechanism, and BREAKAWAY_OK is what keeps the service's own restarter alive.

    C:\Python312\python.exe tests\test_service_tree.py
    python3 tests/test_service_tree.py
"""
from __future__ import annotations

TIER = "offline"   # no game, no sockets — a job object and, on Windows, one child

import os
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel.service import tree                                        # noqa: E402

WINDOWS = sys.platform.startswith("win")


def test_flags_are_the_windows_ones() -> None:
    """The two limits, by value — a typo here is a tree that never dies."""
    assert tree.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE == 0x00002000
    assert tree.JOB_OBJECT_LIMIT_BREAKAWAY_OK == 0x00000800
    assert tree.JOB_OBJECT_EXTENDED_LIMIT_INFORMATION == 9


def test_a_machine_may_say_no() -> None:
    """`LW_SERVICE_NO_JOB=1` is the way out, and it is said in the log rather than mute."""
    said = []
    old = os.environ.get(tree.ENV_OFF)
    os.environ[tree.ENV_OFF] = "1"
    try:
        assert tree.wanted() is False
        if not tree.held():
            out = tree.hold(said.append)
            assert out["ok"] is False and out["why"] == "disabled", out
            assert said and "NOT held" in said[0], said
    finally:
        if old is None:
            os.environ.pop(tree.ENV_OFF, None)
        else:
            os.environ[tree.ENV_OFF] = old


def test_hold_says_what_happened() -> None:
    """It never raises: a service that could not make a job still runs."""
    out = tree.hold(lambda line: None)
    assert set(out) >= {"ok", "why"}, out
    if not WINDOWS:
        assert out["ok"] is False and out["why"] == "not_windows", out
    else:
        assert out["ok"] is True, out
        assert tree.held(), "the handle must be kept — it IS the mechanism"


def test_the_service_holds_it_before_it_spawns_anything() -> None:
    """`Service.start` takes the floor first, and never during a test run."""
    src = (_REPO / "panel" / "service" / "host.py").read_text(encoding="utf-8")
    start = src.index("    def start(self) -> None:")
    body = src[start + 10:]
    head = src[start:start + 10 + body.index("\n    def ")]
    assert "_hold_the_tree()" in head, "the job is made before the door and the keeper"
    assert head.index("_hold_the_tree()") < head.index("self.keeper.start()"), \
        "the keeper starts panels — the job has to exist before it does"
    assert "in_test_run()" in src[src.index("def _hold_the_tree"):][:800], \
        "a test run must not put the runner in a kill-on-close job"


def test_a_real_child_dies_with_the_holder() -> None:
    """Windows only, and it is the measurement: a grandchild outlives nothing."""
    if not WINDOWS:
        return
    # A CHAIN, not a child: the service starts a panel and the panel starts the captures,
    # the sniffers and the tools, so what has to die is the whole descent — and it does,
    # because a process created inside a job joins it and so does everything IT creates.
    grandchild = ("import subprocess, sys, time;"
                  "kid = subprocess.Popen([sys.executable, '-c',"
                  " 'import time; time.sleep(120)']);"
                  "print(kid.pid, flush=True);"
                  "time.sleep(120)")
    code = ("import sys, time, subprocess;"
            "sys.path.insert(0, r'%s');"
            "from panel.service import tree;"
            "tree.hold();"
            "kid = subprocess.Popen([sys.executable, '-c', %r],"
            " stdout=subprocess.PIPE, text=True);"
            "print(kid.pid, flush=True);"
            "print(kid.stdout.readline().strip(), flush=True);"
            "time.sleep(120)" % (str(_REPO), grandchild))
    holder = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                              text=True, cwd=str(_REPO))
    try:
        pids = [holder.stdout.readline().strip() for _ in range(2)]
        assert all(p.isdigit() for p in pids), f"the holder said {pids!r}"
        kin = [int(p) for p in pids]
        assert all(_alive(p) for p in kin), f"the chain never started: {kin}"
    finally:
        holder.kill()
        holder.wait(timeout=10)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and any(_alive(p) for p in kin):
        time.sleep(0.2)
    left = [p for p in kin if _alive(p)]
    assert not left, f"{left} outlived the process holding the job"


def _alive(pid: int) -> bool:
    """Is that pid still a running process? `OpenProcess` + exit code, no pywin32."""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, int(pid))    # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259                              # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


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

r"""Am I running inside the test suite? — the one place that answers it.

A test run is a run of THIS repository's own code, on a machine that is usually also
FARMING with it. Nothing separates the two by itself: the profiles tree, the web port,
the client and the game are the machine's, so a test that reaches for «the panel» reaches
for the live one.

That is not hypothetical. `tests/test_panel_service.py` started a real `Service`, whose
keeper supervises the machine's profiles — so a plain `python3 tools/run_tests.py` spawned
`-m panel.headless --profile default` on the LIVE account, detached. It outlived the run
(PPID 1), bound the panel's port, wrote into the account's own `panel.log`, took the
machine lease away from the real panel, and every five minutes played `launch_game`
against the real client (#2002).

So three questions get one answer here:

  * **`in_test_run()`** — is this process part of a test run? True when the runner said so
    (:data:`ENV`), or when the process was started as a file under ``tests/``. The second
    half matters because a test file is a self-running script (`AGENTS.md` §8) and is run
    directly at least as often as through the runner.
  * **the answer travels to CHILDREN.** Detecting it by argv arms :data:`ENV` as well, so
    anything the test spawns — a panel, a tool, a daemon — knows it is a test's child even
    though its own argv says nothing.
  * **`refuse(what)`** — the sentence a guard raises. One wording, so a refusal is
    recognisable wherever it comes from.

Guards that use it (each says so where it stands):

  * `tools/lib/game_client.py::start` — no test starts the game.
  * `panel/service/keeper.py::Keeper.launch` — no test spawns a supervised panel.
  * `panel/runtime/workspace.py::Workspace.open` — no test opens a LIVE profile.

What it deliberately does NOT do is switch behaviour off «for tests» anywhere else. A
guard here is about touching the live machine; anything else a test needs is arranged by
the test, in the test.
"""
from __future__ import annotations

import os
import sys

#: Set to ``1`` by `tools/run_tests.py`, and by this module when it recognises a test
#: file by name. Inherited by every child, which is the point — the damage in #2002 was
#: done by a grandchild whose own command line said nothing about tests.
ENV = "LW_TEST_RUN"

#: The directory a test file lives in. A file run from anywhere else is not a test.
TESTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "tests")


def _looks_like_a_test_file(argv0: str) -> bool:
    """``python3 tests/test_x.py`` — the ordinary way a file here is run."""
    path = (argv0 or "").strip()
    if not path:
        return False
    try:
        real = os.path.realpath(path)
    except OSError:                                   # noqa: PERF203 — a reading
        return False
    name = os.path.basename(real)
    if not name.startswith("test_") or not name.endswith(".py"):
        return False
    return os.path.dirname(real) == os.path.realpath(TESTS_DIR)


def arm() -> None:
    """Say, to this process and to everything it starts, that this is a test run."""
    os.environ[ENV] = "1"


def in_test_run(argv=None) -> bool:
    """Is this process part of a test run?

    Arms :data:`ENV` when it recognises the process by its own command line, so the
    answer reaches children that cannot work it out for themselves.
    """
    said = os.environ.get(ENV)
    if said is not None:
        # SET, WHATEVER IT SAYS, IS THE LAST WORD — including «off». A file under
        # `tests/` recognises itself, so a test that really does mean to start something
        # (an argument list read off a stubbed launcher, a live-tier probe) has no other
        # way to say so: it stands the variable aside for the length of the call.
        return said.strip().lower() not in ("", "0", "no", "false")
    argv0 = (list(argv) if argv is not None else sys.argv)[:1]
    if argv0 and _looks_like_a_test_file(argv0[0]):
        arm()
        return True
    return False


def refuse(what: str) -> RuntimeError:
    """The exception a guard raises. Never raised here — the caller does that, so the
    traceback points at the guard rather than at this module."""
    return RuntimeError(
        f"refusing to {what} from a test run: a test may not touch this machine's live "
        f"panel, profiles or game client (#2002). Point the test at a scratch tree, or "
        f"unset {ENV} if this really is not a test.")

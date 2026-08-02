"""Where the repo is, and putting its importable directories on `sys.path`.

The panel's shared libraries are not a package — `lua_client`, `lua_actions`, `coords`
and friends are imported by bare name from ``tools/lib/``, the entrypoints from
``tools/``, and the DSL interpreter from ``src/``. `panel/__main__.py` has always done
this bootstrap on the way in.

It has to live HERE too, and run on `import panel.runtime`, because the whole point of
the refactor is that a tab can be started without that file:

    python -m panel.tabs.rally

imports `panel.runtime` first and `panel.__main__` never. Importing this package is
therefore what makes the bare-name imports below it work, in either launch mode.

Cheap and idempotent: three `os.path` joins and a membership test.
"""
from __future__ import annotations

import os
import sys

# panel/runtime/paths.py -> panel/runtime -> panel -> the repo
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(REPO, "tools")
TOOLS_LIB = os.path.join(TOOLS, "lib")
SRC = os.path.join(REPO, "src")

# The daemon entrypoint, which the game link starts when nothing is listening.
LUA_DAEMON = os.path.join(TOOLS, "lua_daemon.py")


def ensure() -> None:
    """Put the repo's importable directories on `sys.path`, once."""
    for path in (REPO, TOOLS, TOOLS_LIB, SRC):
        if path not in sys.path:
            sys.path.insert(0, path)


def repo_rel(path: str) -> str:
    """A path as it reads in the log: relative to the repo, forward slashes.

    Falls back to the path itself for anything outside the repo (or on another drive,
    where relpath raises) — a display helper must never be the thing that breaks a
    dialog. Was `Panel._repo_rel`; a tab shows a path too (the rally monitor's log).
    """
    try:
        rel = os.path.relpath(path, REPO)
    except ValueError:
        return path
    return path if rel.startswith("..") else rel.replace(os.sep, "/")


ensure()

r"""Open the «Secret Tasks» tab on its own.

    C:\Python312\python.exe -m panel.tabs.secret_tasks --profile main

A window holding just this one starts the capture and both watchers the profile asked
for — the standing orders are the tab's, not the shell's.
"""
from __future__ import annotations

from ..base import run_tab
from .tab import SecretTasksTab

raise SystemExit(run_tab(SecretTasksTab))

r"""Open the «Секретный командный пункт» tab on its own.

    C:\Python312\python.exe -m panel.tabs.command_post --profile main

A window holding just this one still runs the «Операция Призрак» standing order the
profile asked for: the event is open one day a week, and an order that waits for
somebody to open a tab would miss it.
"""
from __future__ import annotations

from ..base import run_tab
from .tab import CommandPostTab

raise SystemExit(run_tab(CommandPostTab))

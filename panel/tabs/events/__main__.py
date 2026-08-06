r"""Open the «События» tab on its own.

    C:\Python312\python.exe -m panel.tabs.events --profile main

A package rather than a single module (the catalogue is worth testing without a window),
so the four lines every tab module ends with live here instead.
"""
from __future__ import annotations

from ..base import run_tab
from .tab import EventsTab

raise SystemExit(run_tab(EventsTab))

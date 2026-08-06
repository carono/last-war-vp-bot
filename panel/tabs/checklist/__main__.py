r"""Open the «Чеклист» tab on its own.

    C:\Python312\python.exe -m panel.tabs.checklist --profile main

A package rather than a single module (the list is worth testing without a window), so
the four lines every tab module ends with live here instead.
"""
from __future__ import annotations

from ..base import run_tab
from .tab import ChecklistTab

raise SystemExit(run_tab(ChecklistTab))

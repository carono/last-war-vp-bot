r"""Open the «Ралли» tab on its own.

    C:\Python312\python.exe -m panel.tabs.rally --profile main

A package rather than a single module (the form, the monitor, the settings page and the
daily caps are four files), so the four lines every tab module ends with live here
instead.
"""
from __future__ import annotations

from ..base import run_tab
from .tab import RallyTab

raise SystemExit(run_tab(RallyTab))

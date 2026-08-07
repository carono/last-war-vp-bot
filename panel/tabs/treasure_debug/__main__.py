r"""Open the «Сокровища» debug page on its own.

    C:\Python312\python.exe -m panel.tabs.treasure_debug --profile main

Which is how it is usually wanted: the feed is watched beside the game while a chest is
out, and a whole panel window in the way is a whole panel window in the way.
"""
from __future__ import annotations

from ..base import run_tab
from .tab import TreasureDebugTab

raise SystemExit(run_tab(TreasureDebugTab))

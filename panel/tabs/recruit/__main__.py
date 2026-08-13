r"""Open the «Найм» tab on its own.

    C:\Python312\python.exe -m panel.tabs.recruit --profile main
"""
from __future__ import annotations

from ..base import run_tab
from .tab import RecruitTab

raise SystemExit(run_tab(RecruitTab))

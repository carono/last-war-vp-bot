r"""Open the «Игроки» tab on its own.

    C:\Python312\python.exe -m panel.tabs.players --profile main

A window holding just this one reads the profile's own register and the capture's own
checkpoint; it starts no capture of its own, because the register is fed by the one the
«Секретки» tab already runs.
"""
from __future__ import annotations

from ..base import run_tab
from .tab import PlayersTab

raise SystemExit(run_tab(PlayersTab))

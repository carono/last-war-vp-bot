"""Runtime bot infrastructure: clean, modular layer over the research tooling.

Layout
------
    bot/core/protocol.py      transport primitives (TLV / XOR / zstd) — one source of truth
    bot/core/process.py       locate the game process + window
    bot/state/game_state.py   the GameState dataclass the rest of the bot reads
    bot/state/stream_reader.py passive TCP decoder that keeps GameState current
    bot/actions/input.py      cursor-free touch taps + screenshots
    bot/actions/navigation.py go_to_world() / go_to_base() driven by touch taps

Design rules
------------
* No duplication. The wire protocol lives in ``tools/lib/lastwar_proto.py`` and
  the window capture in ``lastwar_bot.perception.capture``; ``bot`` re-exports and
  composes them rather than re-implementing. ``tools/`` is never modified.
* The transport decode is passive only — scene, zoom and resources are inferred
  from server push messages, never from screenshots.

The research trees (``tools/`` and ``src/lastwar_bot``) are not always installed
as importable packages, so make them importable when this package is imported
from a repo checkout.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

for _extra in (_REPO_ROOT / "tools", _REPO_ROOT / "tools" / "lib", _REPO_ROOT / "src"):
    _p = str(_extra)
    if _extra.is_dir() and _p not in sys.path:
        sys.path.insert(0, _p)

REPO_ROOT = _REPO_ROOT

__all__ = ["REPO_ROOT"]

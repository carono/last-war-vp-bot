"""Machine/account-specific settings for the standalone ``tools/`` scripts.

These scripts drive one live game account on one machine. The values below used
to be hardcoded to a specific account and file layout; they now come from
environment variables (see ``.env.example``) so nothing account-specific is
baked into the repo.

All defaults are empty/neutral on purpose: the live game VM is the authoritative
source (e.g. ``formation_by_squad`` / ``pick_formation`` in ``rally_join.py``
read the real squad UUIDs off ``ArmyFormationDataManager``). The env values are
only a convenience fallback for callers that want a fixed default.
"""

from __future__ import annotations

import os
from pathlib import Path


def default_formation() -> str:
    """Default squad formation UUID, from ``LW_DEFAULT_FORMATION`` (empty if unset)."""
    return os.environ.get("LW_DEFAULT_FORMATION", "").strip()


def squad_formations() -> dict:
    """Optional squad-slot -> formation UUID fallback map, from ``LW_SQUAD_FORMATIONS``.

    Accepts ``"1:<uuid>,2:<uuid>,3:<uuid>"`` or a bare ``"<uuid>,<uuid>,<uuid>"``
    (positional, slots 1..N). Empty by default — the game VM is authoritative.
    """
    raw = os.environ.get("LW_SQUAD_FORMATIONS", "").strip()
    out: dict = {}
    if not raw:
        return out
    for i, part in enumerate(raw.split(","), 1):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            slot, uuid = part.split(":", 1)
            out[int(slot.strip())] = uuid.strip()
        else:
            out[i] = part
    return out


def default_server() -> str:
    """Default (home) server id, from ``LW_DEFAULT_SERVER`` (empty if unset)."""
    return os.environ.get("LW_DEFAULT_SERVER", "").strip()


def localappdata() -> str:
    """Windows ``%LOCALAPPDATA%`` (env), falling back to the current user's home.

    Never hardcodes a username: when the env var is missing (e.g. under WSL) it
    derives ``~/AppData/Local`` from the running user's home directory.
    """
    return os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")

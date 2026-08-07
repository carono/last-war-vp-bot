"""Per-player profile storage for the DSL bot's own ``--profile`` flag.

Each profile is one JSON file under ``<project>/profiles/_bot/<profile_id>.json``
(directory configurable). Multiple operators of the bot pick their
profile via the ``--profile`` CLI flag; the bot then loads it at
startup and makes it available to scripts as the ``profile`` namespace.

The schema is intentionally free-form: scripts assign whatever fields
they need via ``READ_TEXT ... INTO profile.<field>``. A typical first
capture writes ``name``, ``level``, ``server``; more fields accumulate
as scripts gain capabilities.

THESE ARE NOT THE PANEL'S PROFILES, AND THAT USED TO BE INVISIBLE (#1276). The panel
keeps a directory per account directly in ``<project>/profiles/``; this module used to
keep its flat json files in the very same place, under the very same name, addressed
RELATIVE TO THE WORKING DIRECTORY — so which ``profiles`` you got depended on where you
happened to launch from. A person opening the obvious folder to find their panel
settings found one stale file from months earlier instead, three times running.

So these moved one level down, into ``profiles/_bot/``, and the path is anchored to the
project rather than to the caller's cwd. An older ``profiles/<id>.json`` is picked up
where it lies and moved across the first time it is loaded — see :meth:`Profile.load`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The project root — this file is ``<project>/src/lastwar_bot/profile.py``.
_PROJECT_DIR = Path(__file__).resolve().parents[2]

DEFAULT_PROFILES_DIR = _PROJECT_DIR / "profiles" / "_bot"
#: Where they were until #1276: flat in the panel's own directory. Read once per load,
#: to bring an old file across; never written.
_LEGACY_PROFILES_DIR = _PROJECT_DIR / "profiles"
DEFAULT_PROFILE_ID = "default"


def _adopt_legacy(profile_id: str, path: Path) -> None:
    """Move a pre-#1276 ``profiles/<id>.json`` into ``profiles/_bot/``, once.

    Only when the new place has nothing of that name — an existing file is the answer,
    and an older one must not land on top of it. Failure is silent on purpose: not
    finding a profile is already handled (an absent file loads as ``{}``), and a bot run
    should not die because a directory was read-only.
    """
    legacy = _LEGACY_PROFILES_DIR / f"{profile_id}.json"
    if path.exists() or not legacy.is_file():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        legacy.replace(path)
    except OSError:
        pass


@dataclass
class Profile:
    profile_id: str
    path: Path
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, profile_id: str, profiles_dir: Path | None = None) -> "Profile":
        directory = Path(profiles_dir) if profiles_dir else DEFAULT_PROFILES_DIR
        path = directory / f"{profile_id}.json"
        if not profiles_dir:
            _adopt_legacy(profile_id, path)
        data: dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        return cls(profile_id=profile_id, path=path, data=data)

    def get(self, field_name: str, default: Any = None) -> Any:
        return self.data.get(field_name, default)

    def set(self, field_name: str, value: Any) -> None:
        self.data[field_name] = value
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def __repr__(self) -> str:
        return f"Profile(id={self.profile_id!r}, fields={list(self.data)})"

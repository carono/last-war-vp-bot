"""Per-player profile storage.

Each profile is one JSON file under ``./profiles/<profile_id>.json``
(directory configurable). Multiple operators of the bot pick their
profile via the ``--profile`` CLI flag; the bot then loads it at
startup and makes it available to scripts as the ``profile`` namespace.

The schema is intentionally free-form: scripts assign whatever fields
they need via ``READ_TEXT ... INTO profile.<field>``. A typical first
capture writes ``name``, ``level``, ``server``; more fields accumulate
as scripts gain capabilities.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_PROFILES_DIR = Path("profiles")
DEFAULT_PROFILE_ID = "default"


@dataclass
class Profile:
    profile_id: str
    path: Path
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, profile_id: str, profiles_dir: Path | None = None) -> "Profile":
        directory = Path(profiles_dir) if profiles_dir else DEFAULT_PROFILES_DIR
        path = directory / f"{profile_id}.json"
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

#!/usr/bin/env python3
"""Resolve a rally squad ``heroId`` to its extracted hero-icon PNG.

Rally captures (``results/rally/monitor.jsonl``) carry heroes as numeric ids
only -- the wire never ships a display name (see docs/research/protocol.md).
The extracted icons (``results/hero_icons/{big,small}/hero_icon_<Name>.png``,
tools/extract_hero_icons.py) are keyed by the hero's internal *resName*, not by
id. This module bridges the two.

What is verified vs. what is not
--------------------------------
* **Weapon grade** is slot field ``f15`` (0..30 in the sampled data). The
  ``_zw`` icon variant ("专武"/zhuanwu -- the awakened exclusive weapon skin,
  confirmed from the ``A_Hero@<Name>_zhuanwu_*`` fbx model names in the
  ``gameres`` index) is worn once the weapon reaches grade 30. Below 30 the
  base skin is used.
* The ``heroId -> resName`` table itself lives in the game's config datatable
  (``LocalLow/.../table/table_38321_*.data``), which is encrypted (``CHAC``
  magic); the locale blobs are encrypted too, and no public datamine exposes
  these internal ids. So only ids that have been eyeball-confirmed against the
  live game are listed in ``CONFIRMED`` below -- everything else returns
  ``None`` and callers should fall back to showing the raw ``#id``.

To extend the table: open the game, read the hero on the given id, and add
``id: "resName"`` (the icon stem without the ``hero_icon_`` prefix / ``.png``).
See docs/research/hero-icons.md for the full context and the candidate list.
"""

from __future__ import annotations

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
ICON_ROOT = os.path.join(_ROOT, "results", "hero_icons")

DRONE_ID = 1000000

#: Weapon grade at which the awakened-weapon ("专武"/zhuanwu, ``_zw``) skin shows.
ZW_GRADE = 30

#: Icon stems that ship an awakened-weapon (``_zw``) variant, derived from the
#: extracted icon set (``results/hero_icons``). Only these get the ``_zw``
#: suffix at grade >= ZW_GRADE; every other hero keeps its base icon.
ZW_HEROES = {
    "Audie_Murphy",
    "Carly",
    "Katyusha",
    "Nimitz",
    "Tesla",
    "Tom",
    "dva",
}

#: heroId -> icon stem, confirmed by eye against the live game. Grow this as
#: more ids are verified; unverified ids intentionally stay out (see module
#: docstring) so the report never renders the wrong hero.
CONFIRMED = {
    50006: "Audie_Murphy",
    50007: "Rick",
    50008: "Nimitz",
    50009: "Katyusha",
    50010: "Stetman",
}

#: heroIds observed in results/rally/monitor.jsonl (for reference / coverage).
SEEN_IDS = [
    50006, 50007, 50008, 50009, 50010,
    50013, 50014, 50015, 50016, 50017, 50018, 50019, 50020, 50021, 50022,
    50025, 50026, 50027,
]


def resname_for(hero_id: int) -> str | None:
    """Confirmed internal resName (icon stem) for ``hero_id``, or ``None``."""
    return CONFIRMED.get(hero_id)


def icon_stem(hero_id: int, weapon_grade: int | None = None) -> str | None:
    """Icon stem for a hero, applying the ``_zw`` skin at grade >= ZW_GRADE.

    Returns e.g. ``"hero_icon_Audie_Murphy"`` or ``"hero_icon_Audie_Murphy_zw"``.
    ``None`` when the id is not confirmed yet.
    """
    base = resname_for(hero_id)
    if base is None:
        return None
    if weapon_grade is not None and weapon_grade >= ZW_GRADE and base in ZW_HEROES:
        base = f"{base}_zw"
    return f"hero_icon_{base}"


def icon_path(hero_id: int, weapon_grade: int | None = None,
              size: str = "big") -> str | None:
    """Absolute path to the PNG for a hero, or ``None`` if unknown / missing.

    ``size`` is ``"big"`` or ``"small"``. Falls back to the base skin if the
    ``_zw`` file happens to be absent in the requested size.
    """
    stem = icon_stem(hero_id, weapon_grade)
    if stem is None:
        return None
    path = os.path.join(ICON_ROOT, size, f"{stem}.png")
    if not os.path.exists(path) and stem.endswith("_zw"):
        path = os.path.join(ICON_ROOT, size, f"{stem[:-3]}.png")
    return path if os.path.exists(path) else None


if __name__ == "__main__":
    print(f"{'heroId':>8}  {'grade':>5}  icon")
    for hid in SEEN_IDS:
        stem = icon_stem(hid, 30)
        print(f"{hid:>8}  {'>=30':>5}  {stem or '(unconfirmed)'}")
    print(f"{DRONE_ID:>8}  {'--':>5}  (air-support / drone slot)")

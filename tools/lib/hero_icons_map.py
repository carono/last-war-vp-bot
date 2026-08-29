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
#: This module lives in `tools/lib`, so the repository is TWO levels up. It used to go
#: up one, which pointed ICON_ROOT at `tools/results/hero_icons` — a directory that has
#: never existed, so `icon_path()` answered None for every hero however many icons had
#: been extracted (#1305).
_ROOT = os.path.dirname(os.path.dirname(_HERE))
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
    50013: "Ewan_McGregor",
    50014: "Fiona",
    50015: "Tom",
    50016: "Tesla",
    50022: "Adam",
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


# ---------------------------------------------------------------------------
# Serving one icon to the panel's web front-end (#2062).
#
# The squad picker draws the player's OWN heroes, and the stem it draws them by is read
# out of the live client rather than looked up here (`actions/read_squad_heroes.md`):
# the `heroId -> resName` table above is eyeball-confirmed and always will be partial,
# so it is the FALLBACK for an id the game would not name, never the source of truth.
#
# The same contract every other picture route keeps (`tools/lib/monster_icons.py`): a
# machine that has never run `tools/extract_hero_icons.py` answers `None` for every
# lookup, and the picker draws the squad's number instead of a broken image.

def name_for(stem: str, size: str = "small") -> str:
    """The file name the phone may ask for, or ``""`` when there is nothing on disk.

    ``stem`` is the icon's resName, with or without the ``hero_icon_`` prefix — the live
    read hands over whichever the game's own config column holds.
    """
    clean = str(stem or "").strip()
    if not clean:
        return ""
    if not clean.startswith("hero_icon_"):
        clean = "hero_icon_" + clean
    name = clean + ".png"
    return name if file_named(name, size) else ""


def file_named(name: str, size: str = "small") -> "str | None":
    """A bare file name back into a path inside the icon folder, or ``None``.

    The same three checks `monster_icons.file_named` makes and for the same reason: the
    route is reachable from a phone, so the name must be a plain name, carry the one
    suffix this folder holds, and land INSIDE the folder. ``small`` is tried first and
    ``big`` after it, because a squad picker wants the small art and an installation
    that extracted only one of the two sets should still draw faces.
    """
    clean = str(name or "").strip()
    if not clean or clean != os.path.basename(clean) or clean.startswith("."):
        return None
    if os.path.splitext(clean)[1].lower() != ".png":
        return None
    order = ("small", "big") if size != "big" else ("big", "small")
    for folder in order:
        root = os.path.abspath(os.path.join(ICON_ROOT, folder))
        full = os.path.abspath(os.path.join(root, clean))
        if os.path.dirname(full) != root:
            return None
        if os.path.isfile(full):
            return full
        # …and the same name in whatever case the extractor wrote it. The stem comes out
        # of the client's own config (`hero_icon_dva` against a file called
        # `hero_icon_DVA.png`), and a file system that cares about the difference would
        # otherwise drop a face the machine has (#2062). Windows never notices; Linux
        # does, and the tests run there.
        found = _listing(folder).get(clean.lower())
        if found:
            return os.path.join(root, found)
    return None


#: One listing per folder, remembered. The art is extracted by a person running a tool,
#: never while the panel is up, so re-reading the directory per picture buys nothing.
_LISTINGS: dict = {}


def _listing(folder: str) -> dict:
    """`{lowercased file name: the name on disk}` for one icon folder."""
    found = _LISTINGS.get(folder)
    if found is None:
        root = os.path.join(ICON_ROOT, folder)
        try:
            found = {name.lower(): name for name in os.listdir(root)}
        except OSError:
            found = {}
        _LISTINGS[folder] = found
    return found


if __name__ == "__main__":
    print(f"{'heroId':>8}  {'grade':>5}  icon")
    for hid in SEEN_IDS:
        stem = icon_stem(hid, 30)
        print(f"{hid:>8}  {'>=30':>5}  {stem or '(unconfirmed)'}")
    print(f"{DRONE_ID:>8}  {'--':>5}  (air-support / drone slot)")

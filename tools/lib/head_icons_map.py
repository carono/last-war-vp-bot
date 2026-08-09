#!/usr/bin/env python3
"""Resolve a player's ``headSkinId`` to its extracted avatar PNG.

The march envelope of an alliance rally carries the sender's avatar as a bare number
(`headSkinId`), and the pictures themselves are Unity sprites in the client's asset
bundles — `Assets/Main/Sprites/UI/UIHeadIcon`, extracted by::

    python tools/extract_hero_icons.py --sets head,head_s6 --out results/head_icons

That directory holds 57 sprites: `player_head_1` .. `player_head_25` (the avatars anybody
can pick), three `_big` variants of them, and a couple of dozen named ones belonging to
seasons and bosses (`head_icon_Satan`, `ljq_S5_boss_datouxiang`, …).

What is established and what is not
-----------------------------------
* **The pictures are real** — they come straight out of the bundles, no guessing.
* **The id → sprite table is not.** It lives in the game's config datatables, which are
  encrypted (`CHAC` magic — the same wall as the hero ids, see
  `docs/research/hero-icons.md`), and the live Lua VM exposes no `TableName` entry for
  head icons: probing every config name for `head` / `avatar` / `portrait` / `touxiang`
  returned nothing, and the only globals that mention one are the UI window names
  (`UIPlayerChangeHeadIcon`, `UIPlayerHeadIconSelect`), whose modules load with the
  window.

So `PICKABLE_BASE` below is a **hypothesis about the numbering**, not a confirmed table:
the ids observed on the wire are `20002` and `20012`, the pickable sprites are numbered
1..25, and `20000 + N` lands both of them inside that range. It is used only for the
`20xxx` family; anything else returns `None` and the caller shows a placeholder rather
than the wrong face. The `25xxx` family (`25000`, `25008` observed) is deliberately NOT
mapped — there is no numbering that fits it without inventing one.

To confirm or replace the rule: open the avatar picker in the game, note which picture
sits on which id, and write the ids down in `CONFIRMED`. A confirmed id always wins.
"""

from __future__ import annotations

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
#: This module lives in `tools/lib`, so the repository is TWO levels up — one is
#: `tools/`, and `tools/results/head_icons` is a directory that has never existed.
_ROOT = os.path.dirname(os.path.dirname(_HERE))

#: Where `tools/extract_hero_icons.py --sets head,head_s6` writes.
ICON_ROOT = os.path.join(_ROOT, "results", "head_icons")

#: The avatars a player can pick are `player_head_1` .. `player_head_25`.
PICKABLE_BASE = 20000
PICKABLE_MAX = 25

#: id -> sprite stem, for ids somebody has checked against the running game by eye.
#: Empty on purpose: nobody has done it yet. An entry here overrides the numbering rule.
CONFIRMED: dict = {}


def resname_for(head_id) -> "str | None":
    """The sprite stem for a `headSkinId`, or ``None`` when it cannot be resolved.

    ``None`` is the honest answer for every id outside the pickable range — see the
    module docstring on why the table itself is not available.
    """
    try:
        head_id = int(head_id)
    except (TypeError, ValueError):
        return None
    if head_id in CONFIRMED:
        return CONFIRMED[head_id]
    index = head_id - PICKABLE_BASE
    if 1 <= index <= PICKABLE_MAX:
        return f"player_head_{index}"
    return None


def icon_path(head_id, root: "str | None" = None) -> "str | None":
    """The extracted PNG for a `headSkinId`, or ``None`` when there is no file.

    Looks in every category directory under `root` (`head`, `head_s6`), so a season
    avatar extracted into its own folder is found without the caller knowing which.
    """
    stem = resname_for(head_id)
    if not stem:
        return None
    base = root or ICON_ROOT
    if not os.path.isdir(base):
        return None
    for category in sorted(os.listdir(base)):
        candidate = os.path.join(base, category, f"{stem}.png")
        if os.path.exists(candidate):
            return candidate
    return None


def available(root: "str | None" = None) -> dict:
    """``{stem: path}`` for every extracted head sprite — what the report can draw."""
    base = root or ICON_ROOT
    out: dict = {}
    if not os.path.isdir(base):
        return out
    for category in sorted(os.listdir(base)):
        directory = os.path.join(base, category)
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if name.endswith(".png"):
                out.setdefault(name[:-4], os.path.join(directory, name))
    return out


if __name__ == "__main__":                       # a quick look at what is on disk
    found = available()
    print(f"{len(found)} head sprite(s) in {ICON_ROOT}")
    for head_id in (PICKABLE_BASE + 1, PICKABLE_BASE + 2, PICKABLE_BASE + PICKABLE_MAX):
        print(f"  {head_id} -> {resname_for(head_id)} -> {icon_path(head_id)}")

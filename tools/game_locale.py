r"""Read the game's own translations — all nineteen languages it ships.

The client keeps every language on disk, next to the install: gzipped C#
``BinaryWriter`` tables under ``StreamingAssets/locale``, ~52 000 key→text pairs each,
and THE SAME keys in every language. So the way to learn what the game calls something
in Polish is to find the key by its English wording and read that key out of ``pl``.

That is what this is for. The panel must never invent a name for something the game has
already named (``CLAUDE.md``, «Not one word of the panel is written in the panel»), and
before this existed the only way to check was to ask somebody who plays in that
language.

    # what does the game call this, in every language the panel ships?
    C:\Python312\python.exe tools\game_locale.py --term "Doom Elite"

    # regenerate docs/game-glossary.md — the terms the panel uses, in all of them
    C:\Python312\python.exe tools\game_locale.py --glossary

    # what is on disk
    C:\Python312\python.exe tools\game_locale.py --langs

The format is documented in ``docs/research/game-locale-tables.md``.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from pathlib import Path

#: The languages the panel ships a locale for. The game has nineteen; these are the
#: ones on Latin and Cyrillic script. The rest — Chinese (zh_CN, zh_TW, gn_CN),
#: Japanese, Korean, Arabic, Thai — are deliberately NOT panel languages: Tcl/Tk 8.6
#: does no bidi reordering and no Arabic joining, and nobody on this side can proofread
#: the CJK ones. `vr` is not here either: it is a 99.7% copy of `vi`.
BASE_LANGS = ("en", "ru", "de", "fr", "es", "it", "pt", "pl", "tr", "id", "vi")

#: What the panel names, and what the GAME calls it — the English wording to look up.
#: Add a line here when a panel string starts naming something the game has a word for;
#: `--glossary` turns it into the table everybody translating a locale reads.
PANEL_TERMS = (
    ("the rally the panel raises and joins",      "Rally"),
    ("the boss a rally is raised on",             "Doom Elite"),
    ("the alliance's training rally",             "Alliance Exercise"),
    ("the weekly co-op robbery event",            "Ghost Ops"),
    ("the tab those events live on",              "Secret Command Post"),
    ("the alliance tasks with stars",             "Secret Task"),
    ("a mate's shared secret task",               "Secret Mobile Squad"),
    ("the chests an alliance radar drops",        "Hidden Treasures"),
    ("the player themselves",                     "Commander"),
    ("the rank the duel raises",                  "Overlord"),
    ("the wall the duel raises",                  "Wall of Honor"),
    ("the weapon the duel upgrades",              "Exclusive Weapon"),
    ("what the duel opens for hero XP",           "Hero EXP Chest"),
    ("the ministry that speeds building",         "Secretary of Development"),
    ("the ministry that speeds research",         "Secretary of Science"),
    ("the ministry the panel applies for",        "Secretary of Interior"),
    ("where the wounded are healed",              "Hospital"),
    ("what a squad is called",                    "Squad"),
    ("the drone the duel upgrades",               "Drone"),
    ("what the duel spends on the drone",         "Gear"),
    ("resource: food",                            "Food"),
    ("resource: wood",                            "Wood"),
    ("resource: metal",                           "Metal"),
    ("resource: oil",                             "Oil"),
    ("resource: gold",                            "Gold"),
)

_REPO = Path(__file__).resolve().parents[1]
_GLOSSARY = _REPO / "docs" / "game-glossary.md"


# -- finding the tables ------------------------------------------------------------

def locale_dir() -> Path:
    """Where the game keeps its language tables.

    ``LW_LOCALE_DIR`` wins; otherwise the launcher path the active profile already
    knows, because the panel needs it to start the game anyway.
    """
    if os.environ.get("LW_LOCALE_DIR"):
        return Path(os.environ["LW_LOCALE_DIR"])

    launcher = _launcher_from_profile()
    if launcher is None:
        raise SystemExit("no game found — set LW_LOCALE_DIR to .../StreamingAssets/locale/<build>")
    root = launcher.parent / "Game" / "LastWar_Data" / "StreamingAssets" / "locale"
    if not root.is_dir():
        raise SystemExit(f"no locale directory under {root}")
    # One directory per build; take the newest that actually holds tables.
    builds = sorted((d for d in root.iterdir() if d.is_dir() and any(d.glob("*.bin"))),
                    key=lambda d: d.stat().st_mtime)
    if not builds:
        raise SystemExit(f"no language tables under {root}")
    return builds[-1]


def _launcher_from_profile() -> Path | None:
    for cfg in sorted((_REPO / "panel" / "profiles").glob("*/config.json")):
        try:
            path = json.loads(cfg.read_text(encoding="utf-8")).get("launcher")
        except (OSError, ValueError):
            continue
        if path:
            # The profile stores a Windows path; under WSL the same file is on /mnt/<d>.
            p = Path(path)
            if not p.exists() and len(path) > 2 and path[1] == ":":
                p = Path("/mnt") / path[0].lower() / path[3:].replace("\\", "/")
            if p.exists():
                return p
    return None


# -- reading one ------------------------------------------------------------------

def _read7(b: bytes, i: int) -> tuple[int, int]:
    """BinaryWriter's 7-bit-encoded length prefix."""
    n = s = 0
    while True:
        c = b[i]
        i += 1
        n |= (c & 0x7f) << s
        if not c & 0x80:
            return n, i
        s += 7


def load(lang: str, root: Path | None = None) -> dict[str, str]:
    """``{key: text}`` for one language."""
    root = root or locale_dir()
    blob = gzip.decompress((root / f"{lang}.bin").read_bytes())
    out: dict[str, str] = {}
    i = 4                                   # a 4-byte header, then pair after pair
    while i < len(blob):
        try:
            ln, i = _read7(blob, i); key = blob[i:i + ln].decode("utf-8"); i += ln
            ln, i = _read7(blob, i); val = blob[i:i + ln].decode("utf-8"); i += ln
        except (IndexError, UnicodeDecodeError):
            break                           # a truncated tail is not worth a crash
        out[key] = val
    return out


def available(root: Path | None = None) -> list[str]:
    root = root or locale_dir()
    return sorted(p.stem for p in root.glob("*.bin"))


# -- looking a term up -------------------------------------------------------------

def find(term: str, tables: dict[str, dict[str, str]]) -> tuple[str | None, dict[str, str]]:
    """The game's key for an English term, and what every language says for it.

    Exact match on the English wording first — the tables hold the same sentence under
    several keys, and any of them answers. Falls back to the shortest value that merely
    CONTAINS the term, which is how a word that only ever appears inside a sentence
    («Rally Site:») is still findable.
    """
    english = tables["en"]
    for key, val in english.items():
        if val.strip().lower() == term.lower():
            return key, {l: t.get(key, "") for l, t in tables.items()}
    best = None
    for key, val in english.items():
        if term.lower() in val.lower() and (best is None or len(val) < len(english[best])):
            best = key
    if best is None:
        return None, {}
    return best, {l: t.get(best, "") for l, t in tables.items()}


def write_glossary(tables: dict[str, dict[str, str]]) -> str:
    langs = [l for l in BASE_LANGS if l in tables]
    rows, missing = [], []
    for what, term in PANEL_TERMS:
        key, said = find(term, tables)
        if key is None:
            missing.append(term)
            continue
        cells = " | ".join(said.get(l, "").replace("|", "¦") or "—" for l in langs)
        rows.append(f"| {what} | **{term}** | {cells} |")

    head = "| what the panel means | the game's English | " + " | ".join(langs) + " |"
    rule = "|---" * (2 + len(langs)) + "|"
    body = "\n".join(rows)
    note = ""
    if missing:
        note = ("\n> Not found in the tables, so the panel's own wording stands: "
                + ", ".join(f"«{m}»" for m in missing) + ".\n")
    return f"""# The game's words for the things the panel names

Generated — do not hand-edit. Re-run after a game update:

```
C:\\Python312\\python.exe tools\\game_locale.py --glossary
```

The panel may not invent a name for something the game has already named, in ANY of the
languages it ships. This is the list to translate a locale against: find the row, copy
the cell. Everything else in a locale file is the panel's own words and is translated
normally.

The columns are the panel's base languages. The game ships eight more — Chinese
(`zh_CN`, `zh_TW`, `gn_CN`), Japanese, Korean, Arabic, Thai, and `vr` (a copy of `vi`) —
and the panel deliberately does not: Tcl/Tk 8.6 does no bidi reordering and no Arabic
joining, and nobody here can proofread the CJK ones. `tools/game_locale.py --term` reads
them all anyway when a question needs answering.

{head}
{rule}
{body}
{note}
Where the tables came from, and how they are read:
[`docs/research/game-locale-tables.md`](research/game-locale-tables.md).
"""


def main() -> int:
    # This prints Polish, Vietnamese and Russian in the same run; a Windows console
    # defaults to a codepage that has none of them together and dies on the first «É».
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--term", help="an English term; prints it in every base language")
    ap.add_argument("--key", help="a game key; prints its text in every base language")
    ap.add_argument("--langs", action="store_true", help="what the game has on disk")
    ap.add_argument("--glossary", action="store_true", help="rewrite docs/game-glossary.md")
    ap.add_argument("--all-langs", action="store_true",
                    help="use every language on disk, not just the panel's")
    args = ap.parse_args()

    root = locale_dir()
    if args.langs:
        print(f"{root}\n  " + " ".join(available(root)))
        return 0

    wanted = available(root) if args.all_langs else [l for l in BASE_LANGS
                                                     if (root / f"{l}.bin").exists()]
    tables = {l: load(l, root) for l in wanted}

    if args.term or args.key:
        if args.key:
            key = args.key
            said = {l: t.get(key, "") for l, t in tables.items()}
            if not any(said.values()):
                print(f"no such key: {key}", file=sys.stderr)
                return 1
        else:
            key, said = find(args.term, tables)
            if key is None:
                print(f"the tables do not have «{args.term}» — the panel's own name stands")
                return 1
        print(f"[{key}]")
        for lang in wanted:
            print(f"  {lang:6} {said.get(lang, '')}")
        return 0

    if args.glossary:
        _GLOSSARY.write_text(write_glossary(tables), encoding="utf-8")
        print(f"{_GLOSSARY.relative_to(_REPO)} — {len(PANEL_TERMS)} terms "
              f"× {len(wanted)} languages")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

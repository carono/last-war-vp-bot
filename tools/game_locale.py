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
import sys
from pathlib import Path

#: The languages the panel ships a locale for. The game has nineteen; these are the
#: ones on Latin and Cyrillic script. The rest — Chinese (zh_CN, zh_TW, gn_CN),
#: Japanese, Korean, Arabic, Thai — are deliberately NOT panel languages: Tcl/Tk 8.6
#: does no bidi reordering and no Arabic joining, and nobody on this side can proofread
#: the CJK ones. `vr` is not here either: it is a 99.7% copy of `vi`.
BASE_LANGS = ("en", "ru", "de", "fr", "es", "it", "pt", "pl", "tr", "id", "vi")

#: What the panel names, and what the GAME calls it — the English wording to look up,
#: and optionally the exact key to read it from. PIN THE KEY whenever the English is a
#: word with more than one meaning: the tables hold «Gear» as both the drone currency
#: and a hero's equipment, «Oil» as both the resource and a cooking ingredient, and
#: the lookup cannot tell which one was meant. Add a line here when a panel string
#: starts naming something the game has a word for; `--glossary` turns it into the
#: table everybody translating a locale reads.
PANEL_TERMS = (
    ("the rally the panel raises and joins",      "Rally"),
    ("the boss a rally is raised on",             "Doom Elite"),
    ("the alliance's training rally",             "Alliance Exercise"),
    ("the weekly co-op robbery event",            "Ghost Ops"),
    ("the section the game's events live in",     "Events", "2000046"),
    ("the world-boss event, three attacks a day", "Codename", "100086"),
    ("the boss that event puts on the map",       "Wanted Boss", "activity_worldboss_title"),
    ("the biggest single hit on that boss",       "Highest Damage",
     "wantedBoss_record_highest"),
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
    ("the drone the duel upgrades",               "Drone", "alliance_duel_tips10005"),
    ("what the duel spends on the drone",         "Gear", "140404"),
    ("resource: food",                            "Food", "resource_name001"),
    ("resource: wood",                            "Wood", "180265"),
    ("resource: metal",                           "Metal", "resource_name002"),
    ("resource: oil",                             "Oil", "resource_name_23"),
    ("resource: gold",                            "Gold", "ghost_parkour_gold"),
)

#: Rows whose cells the game itself got wrong in some language, so a translator does
#: not copy nonsense out of the table. `Gear` is the one that bit: the single-word key
#: is «bieg» in Polish (a car's gear) and «gigi» in Indonesian (a tooth), while the
#: same currency inside a sentence is «elementy wyposażenia». Use the sane word and say
#: so, rather than shipping the game's slip.
KNOWN_BAD = {
    "Gear": "pl «bieg» and id «gigi» are the game's own homonym slips — "
            "use the wording the game uses in a sentence (`--term \"Use {0} Gears\"`)",
}

_REPO = Path(__file__).resolve().parents[1]
_GLOSSARY = _REPO / "docs" / "game-glossary.md"


# -- finding the tables ------------------------------------------------------------

def _game_paths():
    """`tools/lib/game_paths.py` — the ONE answer about where anything of the game is."""
    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    import game_paths                        # noqa: PLC0415 — path wired up just above

    return game_paths


def tables() -> dict[str, Path]:
    """``{language: its newest table on this machine}``.

    **Not one directory** (#1320). The install ships every language the client has and
    keeps that build for ever; an update downloads a fresher build into the client's own
    download tree holding only the languages actually being played in. Take «the newest
    build» whole and a glossary lookup loses eighteen languages the first time the client
    updates; take the newest table per language and each tree is used for what it has.

    Where a build lives, and which variable moves it, is `game_paths`' answer and not a
    second copy of it — this file used to spell the path out again from a launcher it
    dug out of a profile's config, and the two had already drifted (the folder it
    searched, `panel/profiles/`, has not been where profiles live for some time).
    """
    return {lang: Path(path) for lang, path in _game_paths().locale_tables().items()}


def locale_dir() -> Path:
    """The newest build directory — what `--langs` prints, and nothing depends on.

    Kept because a person asking «where are the tables» wants a folder, and because
    ``LW_LOCALE_DIR`` still names one outright. Anything READING a table should go
    through :func:`tables`, which does not assume they are all in one place.
    """
    found = _game_paths().locale_dir()
    if not found:
        raise SystemExit(
            "no game found — set LW_LOCALE_DIR to .../locale/<build>, "
            "or run `python tools/lib/game_paths.py` to see what is being looked at")
    return Path(found)


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
    """``{key: text}`` for one language.

    `root` pins the build to read it out of; left unsaid, the newest table this machine
    has for that language, wherever it happens to sit (:func:`tables`).
    """
    path = (root / f"{lang}.bin") if root is not None else tables().get(lang)
    if path is None:
        raise SystemExit(f"no table for {lang!r} on this machine")
    blob = gzip.decompress(path.read_bytes())
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
    """Which languages this machine has a table for — across every build, not one."""
    if root is not None:
        return sorted(p.stem for p in root.glob("*.bin"))
    return sorted(tables())


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
    rows, missing, caveats = [], [], []
    for entry in PANEL_TERMS:
        what, term, pinned = (entry + (None,))[:3]
        if pinned:
            key = pinned
            said = {l: t.get(pinned, "") for l, t in tables.items()}
        else:
            key, said = find(term, tables)
        if key is None or not any(said.values()):
            missing.append(term)
            continue
        mark = " ⚠" if term in KNOWN_BAD else ""
        if term in KNOWN_BAD:
            caveats.append(f"* **{term}** — {KNOWN_BAD[term]}")
        cells = " | ".join(said.get(l, "").replace("|", "¦") or "—" for l in langs)
        rows.append(f"| {what} | **{term}**{mark} | `{key}` | {cells} |")

    head = ("| what the panel means | the game's English | key | "
            + " | ".join(langs) + " |")
    rule = "|---" * (3 + len(langs)) + "|"
    body = "\n".join(rows)
    note = ""
    if missing:
        note = ("\n> Not found in the tables, so the panel's own wording stands: "
                + ", ".join(f"«{m}»" for m in missing) + ".\n")
    if caveats:
        note += ("\n### ⚠ Where the game contradicts itself\n\n"
                 + "\n".join(caveats) + "\n")
    return f"""# The game's words for the things the panel names

Generated — do not hand-edit. Re-run after a game update:

```
C:\\Python312\\python.exe tools\\game_locale.py --glossary
```

The panel may not invent a name for something the game has already named, in ANY of the
languages it ships. This is the list to translate a locale against: find the row, copy
the cell. Everything else in a locale file is the panel's own words and is translated
normally.

Every row is ONE key out of the game's tables, and the key is in the table so any cell
can be checked — `--key <key>` prints it again. Read a cell rather than trusting it:
the translators of the game were not always consistent, so a key that is a noun in one
language can be an imperative in another («Rally» → pt «Mobilizar»). When a cell reads
like the wrong part of speech, look the term up in a sentence instead:
`--term "Launch Rally"`.

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

    # One file per language, each from the newest build that has it — which after a
    # client update is not all the same directory (:func:`tables`).
    on_disk = tables()
    if args.langs:
        for lang in sorted(on_disk):
            print(f"{lang:<6} {on_disk[lang]}")
        return 0

    wanted = sorted(on_disk) if args.all_langs else [l for l in BASE_LANGS
                                                     if l in on_disk]
    texts = {l: load(l) for l in wanted}

    if args.term or args.key:
        if args.key:
            key = args.key
            said = {l: t.get(key, "") for l, t in texts.items()}
            if not any(said.values()):
                print(f"no such key: {key}", file=sys.stderr)
                return 1
        else:
            key, said = find(args.term, texts)
            if key is None:
                print(f"the tables do not have «{args.term}» — the panel's own name stands")
                return 1
        print(f"[{key}]")
        for lang in wanted:
            print(f"  {lang:6} {said.get(lang, '')}")
        return 0

    if args.glossary:
        _GLOSSARY.write_text(write_glossary(texts), encoding="utf-8")
        print(f"{_GLOSSARY.relative_to(_REPO)} — {len(PANEL_TERMS)} terms "
              f"× {len(wanted)} languages")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""A name the GAME wrote, said in the language the PANEL is in (#2645).

THE PROBLEM, in the person's words: «Проверяй переводы, вещи не переведены на языки» —
and, asked where, «Названия из игры (здания, чипы, фазы)». A building's name, an item's
name, a phase's name are not the panel's words at all: they are read off the running
client, which resolved them in the language THAT client is playing in. A panel switched
to Polish therefore shows Russian building names, and no amount of locale files fixes it,
because there is no key on our side to translate.

THE ANSWER IS THE GAME'S OWN TABLES, never a translation of ours (`CLAUDE.md`:
«Anything the game has already named is copied out of its own tables rather than
translated»). The client ships every language it has as a gzipped key→text table next to
the install (`docs/research/game-locale-tables.md`), and the KEYS are the same in all of
them. So a name is turned round in two steps:

    the client's text  --(that language's table, read backwards)-->  the game's key
    the game's key     --(the panel language's table)-->             the name we draw

WHICH LANGUAGE THE CLIENT IS IN IS NOT ASKED, IT IS LEARNT. The client's own
`LanguageManager` hands back a C# object the VM cannot marshal, and guessing from the
machine's locale is exactly the sort of «true on this computer» answer this repository
forbids. Instead the first name that has to be translated is looked for in the panel's
own language first (found — it is already right, and nothing is loaded twice), then in
English, then in whatever else this machine has. The language that answers is remembered
and every later name goes straight to it.

NOTHING HERE ASKS THE GAME ANYTHING. It reads files off the disk, once, and holds what it
read. A machine with no game (a test, a checkout on another computer) gets the text back
unchanged — an untranslated name is a small loss; a crash on a page is not a small loss.
"""
from __future__ import annotations

import os
import sys
import threading

#: The languages worth trying, in the order they are tried after the panel's own and
#: English. It is the panel's own set (`panel/locales/`) and not a table of the game's:
#: a client playing in Japanese is a client whose names we cannot draw anyway, because
#: the panel has no Japanese to draw them in.
from .. import i18n as i18nmod

_LOCK = threading.RLock()
#: `{language: {key: text}}` — the game's own tables, as they are read.
_TABLES: dict = {}
#: `{language: {text: key}}` — the same tables backwards, built only for the language
#: that turns out to be the client's.
_INDEX: dict = {}
#: `{profile: language}` — the language THAT profile's client turned out to be playing
#: in, learnt from the first name it could place. Per profile and not one global fact:
#: two accounts on one machine may run two clients in two languages, and «a profile is a
#: whole panel of its own» (`CLAUDE.md`). The tables themselves are the MACHINE's and are
#: shared on purpose — they are files on its disk, identical for every account.
_CLIENT: dict = {}


def _tables_on_disk() -> dict:
    """`{language: path}` — the game's own answer, asked exactly once per call site."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tools = os.path.join(root, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    try:
        import game_locale                   # noqa: PLC0415 — path wired up just above

        return game_locale.tables()
    except Exception:                        # noqa: BLE001 — no game is no translation
        return {}


def _table(lang: str) -> dict:
    """`{key: text}` for one language, read once and kept."""
    with _LOCK:
        if lang in _TABLES:
            return _TABLES[lang]
    table: dict = {}
    try:
        import game_locale                   # noqa: PLC0415 — `_tables_on_disk` wired it

        path = _tables_on_disk().get(lang)
        if path is not None:
            table = game_locale.load(lang)
    except Exception:                        # noqa: BLE001 — a reading, never the page
        table = {}
    with _LOCK:
        _TABLES.setdefault(lang, table)
        return _TABLES[lang]


def _index(lang: str) -> dict:
    """`{text: key}` for one language — the table read backwards.

    The first key wins: the tables hold the same wording under several keys, and any of
    them answers, because what is wanted back is the same wording in another language.
    """
    with _LOCK:
        if lang in _INDEX:
            return _INDEX[lang]
    table = _table(lang)
    back: dict = {}
    for key, text in table.items():
        text = (text or "").strip()
        if text and text not in back:
            back[text] = key
    with _LOCK:
        _INDEX.setdefault(lang, back)
        return _INDEX[lang]


def _client_builds() -> list:
    """The languages the CLIENT itself is carrying, newest build first.

    Not every language the game has: an update downloads only the ones the player is
    actually using (`tools/lib/game_paths.py`), so the newest build's folder is the
    shortest honest guess at «what this client might be running in». It is what keeps
    the scan below bounded — without it a name nobody can place would read nineteen
    tables off the disk to find that out.
    """
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tools = os.path.join(root, "tools", "lib")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    try:
        import game_paths                    # noqa: PLC0415 — path wired up just above

        dirs = list(game_paths.locale_dirs())
    except Exception:                        # noqa: BLE001 — no game is no translation
        return []
    if not dirs:
        return []
    try:
        names = sorted(os.listdir(dirs[0]))
    except OSError:
        return []
    return [name[:-len(".bin")] for name in names if name.endswith(".bin")]


def _candidates(want: str) -> list:
    """Which languages to look the text up in, cheapest first, and never more than four.

    The panel's own first — a name already in it costs one table and no translation at
    all. Then English, which is what a client nobody switched is in. Then whatever the
    client's own newest build carries, which is the short list of languages this player
    actually uses. The cap is the point: a name that is in none of them is answered by
    handing it back, not by reading every table the game ships.
    """
    seen, out = set(), []
    for lang in [want, i18nmod.DEFAULT_LANG] + _client_builds():
        if not lang or lang in seen:
            continue
        if lang not in i18nmod.available_langs():
            continue                         # a language the panel cannot draw anyway
        seen.add(lang)
        out.append(lang)
        if len(out) >= 4:
            break
    return out


def say(text, want: str, scope: str = "") -> str:
    """`text`, as the game itself words it in `want`. Unchanged when it cannot be.

    `scope` is the profile the name was read for: the language its client plays in is
    remembered under it, so one account's client being in German says nothing about
    another's. Never raises and never asks the game — an unknown name, a machine with no
    tables and a language the panel cannot draw all come back as what was handed in.
    """
    text = "" if text is None else str(text)
    stripped = text.strip()
    if not stripped or not want:
        return text
    with _LOCK:
        client = _CLIENT.get(scope)
    for lang in ([client] if client else _candidates(want)):
        key = _index(lang).get(stripped)
        if key is None:
            continue
        if lang == want:
            # The name is already in the panel's language. It is NOT taken as proof of
            # which language the client is in: a word can stand in two tables — a name,
            # a number, an abbreviation — and pinning on one of those would leave every
            # later name untranslated.
            return text
        with _LOCK:
            _CLIENT[scope] = lang
        return _table(want).get(key) or text
    return text

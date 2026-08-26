r"""«Сервер находится на техническом обслуживании» — the closed door, read as a state.

THE STATE. Server maintenance was caught live on 2026-08-19 and written up in
`docs/research/server-maintenance.md`. The finding was not the maintenance itself — it
was that **every indicator the panel had stayed green through the whole window**:
`game=up link=online daemon=warm`. The client was up, the panel could drive it, and the
account was sitting on a dialog nobody had a word for, so the person at the machine could
not tell «wait» from «something is broken».

This module is the word. It is the same technique `tools/lib/game_kick.py` uses for the
session kick, and for the same reason: the client renders the message from a KEY of its
own language tables, so the sentence can be recognised in whatever language the game is
being played in, without asking the player which one that is.

WHAT IS RECOGNISED. Two different things, and they must not be confused:

* **the door is SHUT** — :data:`CLOSED`. Any of the login-time maintenance keys
  (`login_err_tips_maintenance_new`, `login_err_tips_maintenance`, `E100069`, `129012`,
  `2700002`). Nothing to do but wait; the panel already knocks on a clock
  (`panel/runtime/recovery.py`).
* **the door is CLOSING** — :data:`CLOSING`, with the game's own countdown. Keys
  `120036` («… in {0}-min») and `120037` («… in {0}s») are the ONE time the game names,
  and it is the time until the shutdown, never the time it ends: the message on the
  closed door carries no deadline at all (research §4b).

WHAT IS DELIBERATELY NOT RECOGNISED. `server_open_tips001` and `server_maintenance_001`
say somebody ELSE'S warzone is closed while this account's is playable — a refused jump
and a refused duel. Treating those as «our server is down» would park a working account.

IT FAILS CLOSED, in both directions of not knowing, exactly as the kick does: a dialog
that cannot be read is ``None`` («could not tell»), and tables that cannot be found are
``None`` from :func:`judge` — never a maintenance verdict guessed from a generic dialog.

    game_maintenance.read(ev)      # (CLOSED / CLOSING / "" / None, seconds or None)
"""
from __future__ import annotations

import gzip
import re
import unicodedata

import game_paths

#: The door is shut: the account cannot get in until the server comes back.
CLOSED = "closed"
#: The game has announced a shutdown and is counting down to it.
CLOSING = "closing"

#: Keys whose sentence means «this server is under maintenance», with no time in it.
#: `E100069` and `129012` are the error-code namespace — the same family the session
#: kick lives in — and the two `login_err_tips_maintenance*` are what the login screen
#: draws. `2700002` is the update notice's own title.
CLOSED_KEYS = ("login_err_tips_maintenance_new", "login_err_tips_maintenance",
               "E100069", "129012", "2700002")

#: …and the two that COUNT DOWN to it, with the unit each of them speaks.
CLOSING_KEYS = {"120036": 60.0, "120037": 1.0}

#: The marker the read tags its line with, as every other Lua read.
MARKER = "MAINTQ"

#: `{key: {sentence, …}}` for every language on disk, or `{}` while it has not been read
#: / could not be. Filled once per process: the tables do not change under a running
#: client and re-reading them on a poll would be a second of I/O every eight seconds.
_phrases: dict = {}
_looked = False

#: A placeholder in the game's own templates: `({0}) Server is under maintenance.`
_SLOT = re.compile(r"\{\d+\}")

#: A fragment shorter than this decides nothing — `(` and `)` are in every language's
#: punctuation and would match any sentence at all.
_MIN_PART = 3
#: …and at least one fragment has to be a real phrase rather than punctuation.
_MIN_ANCHOR = 8


def phrases() -> dict:
    """The game's own maintenance wordings, per key, in every language it ships.

    Empty when the install cannot be found — a real answer, not a failure: :func:`judge`
    then declines to judge rather than guessing (see the module docstring).
    """
    global _phrases, _looked
    if _looked:
        return _phrases
    _looked = True
    _phrases = _read_tables()
    return _phrases


def forget() -> None:
    """Drop the cached sentences — for a test, and for a client that has updated."""
    global _phrases, _looked
    _phrases, _looked = {}, False


def _read_tables() -> dict:
    """Scan every `<lang>.bin` for every key wanted. Anything unreadable is skipped.

    One walk per table for all the keys rather than one walk per key: the format has to
    be read sequentially anyway (`docs/research/game-locale-tables.md`), so seven keys
    cost what one costs.
    """
    want = set(CLOSED_KEYS) | set(CLOSING_KEYS)
    out: dict = {}
    for _lang, path in sorted(game_paths.locale_tables().items()):
        try:
            found = _find_keys(path, want)
        except Exception:                    # noqa: BLE001 — a table is not a fault
            continue
        for key, value in found.items():
            if value:
                out.setdefault(key, set()).add(value)
    return out


def _find_keys(path: str, keys: set) -> dict:
    """Several keys out of one table, in one pass, without building the other 52 000.

    The format is a gzipped C# `BinaryWriter` dump — a 4-byte header, then key, value,
    key, value, each string behind its 7-bit-encoded byte length.
    """
    with open(path, "rb") as handle:
        blob = gzip.decompress(handle.read())
    want = {key.encode("utf-8"): key for key in keys}
    out: dict = {}
    i, size = 4, len(blob)
    while i < size and len(out) < len(want):
        try:
            n, i = _read7(blob, i); name = blob[i:i + n]; i += n
            n, i = _read7(blob, i); value = blob[i:i + n]; i += n
        except IndexError:
            break                            # a truncated tail is not worth a crash
        key = want.get(name)
        if key is not None:
            try:
                out[key] = value.decode("utf-8")
            except UnicodeDecodeError:
                out[key] = ""
    return out


def _read7(blob: bytes, i: int) -> tuple:
    """BinaryWriter's 7-bit-encoded length prefix."""
    n = shift = 0
    while True:
        c = blob[i]
        i += 1
        n |= (c & 0x7f) << shift
        if not c & 0x80:
            return n, i
        shift += 7


def normalise(text) -> str:
    """A form two spellings of one sentence agree on — the kick's rule, word for word.

    NFKC, format characters dropped (Thai breaks its words with U+200B), every run of
    whitespace gone, case folded. What is left still differs between two DIFFERENT
    sentences: this is not a fuzzy match, it is the same sentence written twice.
    """
    raw = "" if text is None else str(text)
    out = [ch for ch in unicodedata.normalize("NFKC", raw)
           if unicodedata.category(ch) != "Cf" and not ch.isspace()]
    return "".join(out).casefold()


def _parts(template: str) -> list:
    """The fixed fragments of a template, normalised, with the placeholders taken out.

    `The server will shut down for maintenance in {0}-min` is three tokens to a reader
    and two fragments to a matcher, and the number between them is the only part of the
    sentence that is not in the table.
    """
    return [p for p in (normalise(one) for one in _SLOT.split(template)) if p]


def _matches(template: str, said: str) -> bool:
    """Does the rendered text say this template, whatever number was put in its slot?

    Fragments in ORDER, punctuation-sized ones ignored, and at least one fragment long
    enough to be a phrase — otherwise a template that is mostly a placeholder would
    match every dialog the client ever draws.
    """
    if not said:
        return False
    if not _SLOT.search(template):
        one = normalise(template)
        return bool(one) and (said in one or one in said)
    parts = [p for p in _parts(template) if len(p) >= _MIN_PART]
    if not parts or max(len(p) for p in parts) < _MIN_ANCHOR:
        return False
    at = 0
    for part in parts:
        at = said.find(part, at)
        if at < 0:
            return False
        at += len(part)
    return True


def _number(template: str, said: str) -> "float | None":
    """The number the game put in the template's slot, or ``None``.

    Built as a regex out of the normalised fragments so it reads the digits from the
    same string :func:`_matches` judged — the raw text may carry the dialog's own
    padding and a different digit shape.
    """
    parts = [normalise(one) for one in _SLOT.split(template)]
    pattern = r"(\d+)".join(re.escape(p) for p in parts)
    found = re.search(pattern, said)
    if not found:
        return None
    try:
        return float(found.group(1))
    except (TypeError, ValueError):
        return None


def judge(text) -> tuple:
    """Judge one dialog's text: ``(state, seconds)``.

    ``state`` is :data:`CLOSED`, :data:`CLOSING`, ``""`` («not a maintenance message»)
    or ``None`` («cannot judge» — the language tables could not be read at all, so the
    caller must not treat the text as innocent). ``seconds`` is the countdown the game
    named, and only :data:`CLOSING` ever has one: the closed door carries no deadline.
    """
    known = phrases()
    if not known:
        return None, None
    said = normalise(text)
    if not said:
        return "", None
    for key, unit in CLOSING_KEYS.items():
        for template in known.get(key, ()):  # the countdown first: it carries a number
            if _matches(template, said):
                num = _number(template, said)
                return CLOSING, (None if num is None else num * unit)
    for key in CLOSED_KEYS:
        for template in known.get(key, ()):
            if _matches(template, said):
                return CLOSED, None
    return "", None


def read(ev) -> tuple:
    """Is this client sitting on a closed server?  ``(state, seconds)``.

    ``(None, None)`` is «could not tell» — the client would not answer, or its tables
    are not on this machine — and it is never `False` dressed up: a caller that cannot
    tell must keep whatever it last knew rather than declaring the door open.

    The dialog is read the way the kick's is (`tools/lib/lua_actions.kick_tip`): the
    client's own generic message window, whose TEXT is the only thing that says which
    message it is. A maintenance notice drawn by some other window therefore reads as
    «no dialog», which is «cannot tell» rather than «all is well» — the panel's other
    readings still have the client outside the game and knock on it regardless (#1549).
    """
    text = tip(ev)
    if text is None:
        return None, None                    # the client would not answer
    if not text.strip():
        return "", None                      # no dialog on screen
    return judge(text)


def tip(ev) -> "str | None":
    """The text of the open message dialog — `''` when none is open, ``None`` on error.

    One round trip, ~90 ms against a warm client, and never raises: a read that fails is
    ``None``. Same expression the kick uses, so a caller taking both readings in one
    poll pays for one of them (see `panel/__main__.py`, which reads the tip once).
    """
    import lua_actions                        # lazy: keeps a plain import cheap

    try:
        lines = ev.run(
            'CS.UnityEngine.Debug.LogError("%s tip=" .. tostring(%s))'
            % (MARKER, lua_actions.kick_tip()), marker=MARKER, settle=0.4, early=True)
    except Exception:                         # noqa: BLE001 — a reading, never the fault
        return None
    for line in lines or ():
        if "tip=" in line:
            return line.split("tip=", 1)[1].strip()
    return None

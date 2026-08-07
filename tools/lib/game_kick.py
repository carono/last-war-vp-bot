r"""«Вход с другого устройства» — the kick, read as a state of its own.

THE STATE. The game is single-session: logging the account in anywhere else takes this
client off the server and puts the game's own modal on its screen. The client goes on
drawing, its Lua answers every getter with the numbers it last received, and every send
returns `true` while nothing arrives — the state
`docs/research/server-link-status.md` §1 says has no symptom.

**And its sockets may look perfectly healthy.** That is the whole reason this module
exists. On 2026-08-07 the account was taken at ~04:38 and the client kept ONE established
conversation on the game's own port with five half-closed beside it, so `game_link`
answered `online, dead=0` — honestly, by its own definition. The kick flag was read only
while the link already said `lost`, so the one reading that could have named the state
was never consulted, and the panel played timers into a deaf client from 05:13 to 07:27
(§5.3, and the sixth row of §5's table).

So the kick is asked as its OWN question, on every poll and in front of every send,
whatever the sockets say.

WHY THE READING HAD TO GET NARROWER FIRST. The flag is a WINDOW — there is no manager
holding a «kicked» field, because the disconnect flow is C# and nothing in the client's
Lua so much as mentions it (`docs/research/session-kick.md` §3). What opens is
`UICommonMessageTip`, and that is the client's GENERIC dialog: it is used for anything.
While the question was only ever asked on a lost link, «a tip is open» was conclusive
enough — a lost link and a dialog together are a kick. Asked on a healthy client it is
not: any ordinary message would read as a kick, and the cure for a kick is a restart,
which is the expensive direction to be wrong in (it closes the window somebody is
playing in).

**So the text is compared with the game's own sentence.** The client renders the modal
from key `E100083` of its locale tables, and those tables are on disk in every language
it ships (`docs/research/game-locale-tables.md`) — nineteen of them, the same key in
each. Read live off this machine's install, one targeted scan per language costs ~60 ms
and the whole set 1.2 s, once per process:

    ru  В ваш аккаунт был выполнен вход с другого устройства
    en  Your account is currently active on a different device!
    de  Dein Konto ist derzeit auf einem anderen Gerät aktiv!
    …

Comparing against ALL of them rather than the account's own language is the point: what
language the player plays in is not something the panel knows or should ask.

**It fails CLOSED, in both directions of not knowing.** A tip that cannot be read is
«no kick»; tables that cannot be found are «cannot judge the text», and then the reading
falls back to exactly what it was before — a tip with text counts only while the link is
already lost. A machine where the install cannot be located is therefore no worse off
than it was, and never worse off than a false restart.

    game_kick.read(ev)                    # True / False / None ("could not tell")
    game_kick.read(ev, link_lost=True)    # …with the old pair rule as a fallback
"""
from __future__ import annotations

import gzip
import os
import unicodedata

import game_paths

#: The server error code the client renders when the account is taken. Server codes are
#: `E1000xx`; the server sends the number and the client looks the wording up
#: (`docs/research/session-kick.md` §2).
KEY = "E100083"

#: The marker the read tags its line with, as every other Lua read.
MARKER = "KICKQ"

#: The game's sentence in every language on disk, or `()` while it has not been read /
#: could not be. Filled once per process — the tables do not change under a running
#: client, and re-reading them on a poll would be a second of I/O every eight seconds.
_phrases: tuple = ()
_looked = False


def phrases() -> tuple:
    """The game's own «logged in on another device», every language it ships.

    Empty when the install cannot be found — which is a real answer and not a failure:
    see :func:`judge`, which then declines to judge rather than guessing.
    """
    global _phrases, _looked
    if _looked:
        return _phrases
    _looked = True
    _phrases = tuple(sorted(_read_tables()))
    return _phrases


def forget() -> None:
    """Drop the cached sentences — for a test, and for a client that has updated."""
    global _phrases, _looked
    _phrases, _looked = (), False


def _read_tables() -> set:
    """Scan every `<lang>.bin` for :data:`KEY`. Anything unreadable is simply skipped."""
    out: set = set()
    root = game_paths.locale_dir()
    if not root:
        return out
    try:
        names = sorted(f for f in os.listdir(root) if f.endswith(".bin"))
    except OSError:
        return out
    for name in names:
        try:
            value = _find_key(os.path.join(root, name), KEY)
        except Exception:                    # noqa: BLE001 — a table is not a fault
            continue
        if value:
            out.add(value)
    return out


def _find_key(path: str, key: str) -> "str | None":
    """One key out of one table, without building the other 52 000 pairs.

    The format is a gzipped C# `BinaryWriter` dump — a 4-byte header, then key, value,
    key, value, each string behind its 7-bit-encoded byte length
    (`docs/research/game-locale-tables.md`). Walking it to the key wanted costs about
    60 ms; loading the whole table into a dict costs several times that and 19 times
    over, for one sentence.
    """
    with open(path, "rb") as handle:
        blob = gzip.decompress(handle.read())
    want = key.encode("utf-8")
    i, size = 4, len(blob)
    while i < size:
        try:
            n, i = _read7(blob, i); name = blob[i:i + n]; i += n
            n, i = _read7(blob, i); value = blob[i:i + n]; i += n
        except IndexError:
            return None                      # a truncated tail is not worth a crash
        if name == want:
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return None
    return None


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
    """A form two spellings of one sentence agree on.

    The tables carry zero-width joiners (Thai breaks its words with U+200B), the client
    may hand back the text with the dialog's own padding, and a build may add or drop a
    trailing «!». So: NFKC, format characters dropped, every run of whitespace gone,
    case folded. What is left still differs between two DIFFERENT sentences — this is
    not a fuzzy match, it is the same sentence written twice.
    """
    raw = "" if text is None else str(text)
    out = [ch for ch in unicodedata.normalize("NFKC", raw)
           if unicodedata.category(ch) != "Cf" and not ch.isspace()]
    return "".join(out).casefold()


def judge(text) -> "bool | None":
    """Is this modal text the game's own kick sentence?  ``None`` = cannot judge.

    ``None`` is not a maybe: it means the language tables could not be read at all, so
    the caller must fall back on whatever other evidence it has rather than treat the
    text as innocent. A dialog is generic — silence about it is the only honest answer
    when there is nothing to compare it with.
    """
    known = phrases()
    if not known:
        return None
    said = normalise(text)
    if not said:
        return False
    return any(said in normalise(one) or normalise(one) in said for one in known)


def tip(ev) -> "str | None":
    """The text of the open message dialog — `''` when none is open, ``None`` on error.

    One round trip, ~90 ms against a warm daemon. Never raises: a read that fails is
    ``None``, «could not tell».

    THE SETTLE IS A DEADLINE, NOT A PAUSE (`early`, #1290). The dialog is on the
    client's own screen — nothing is asked of the server — so the line is in the answer
    file before the injection returns and the rest of the 0.4 s was pure waiting
    (measured live: 450 ms patient against 90 ms early). This read stands in the link
    gate of every scenario, and #1290 found it being made TWICE per run there.
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


def read(ev, *, link_lost: bool = False) -> "bool | None":
    """Has this client been kicked?  ``True`` / ``False`` / ``None`` («could not tell»).

    ``link_lost`` is the caller's own socket verdict, and it is used for ONE thing: the
    fallback when the game's language tables cannot be read. There it restores exactly
    the rule that shipped with #1259 — a lost link AND a dialog with text is a kick —
    because on a lost link the pair is conclusive enough and a machine without the
    tables must not lose the reading it already had. It never makes a kick MORE likely
    on a healthy client: with the tables present the text decides on its own.
    """
    text = tip(ev)
    if text is None:
        return None                          # the client would not answer
    if not text.strip():
        return False                         # no dialog on screen — not a kick
    verdict = judge(text)
    if verdict is not None:
        return verdict
    return bool(link_lost)                   # no tables: the pre-#1270 pair rule

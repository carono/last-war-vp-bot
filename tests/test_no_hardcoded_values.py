r"""Nothing about THIS machine is written into the code — task #1220.

The repository is public and gets installed on other people's computers. Everything
that is true of one machine and not another — where the game is installed, what its
window and its process are called, which Windows account a second client runs as,
where the Python that drives it lives — is a question with one answer per machine, so
it belongs to `tools/lib/game_paths.py` (and, for the account-shaped ones, to an
environment variable or a registry file) and to nowhere else.

The rule this file enforces is in `CLAUDE.md`. Two things make it enforceable rather
than merely written down:

* **Quoted occurrences only.** A literal in quotes is a value being *used* — building
  a path, filtering a process list, matching a window. The same words in a comment or
  a docstring are prose explaining why the launcher is not the client, and prose is
  worth keeping. So the check is on `"FunFly"`, never on the word FunFly.
* **One place is allowed to spell each value out**, and the test names it. That is the
  point of a resolver: the literal still exists, exactly once, with an environment
  variable in front of it.

And one thing had to change before either of those meant anything — task #1234:

* **The guard does not carry the data it guards.** A list of banned nicknames, logins
  and account ids is a list of real people, and it was sitting here in plain text,
  greppable and indexable, in a public repository. Every one of them is a SHA-256 of
  the normalised value now, the failure message names the FILE and the KIND
  («a player nickname») and never the value, and nothing in this file is exempt from
  the personal-data check any more — it reads itself along with everything else.

  Adding a name therefore never means typing it into a commit:

      C:\Python312\python.exe tests\test_no_hardcoded_values.py --hash "the value"

  prints the digest to paste into :data:`PERSONAL_DIGESTS`. Be honest about what this
  is: a hash of a short nickname is guessable by anyone who already knows the
  nickname. It is not secrecy — it is the difference between data that is published
  and data that is merely checkable, and that difference is the whole of it.

Run:
    C:\Python312\python.exe tests\test_no_hardcoded_values.py
"""
from __future__ import annotations

import hashlib
import os
import re
import pathlib
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "tools" / "lib"))

import game_paths as gp  # noqa: E402


# Which files the INSTALL-literal check skips, and it is now a very short list.
#
# `docs/` and `tests/` were on it, and that is precisely how 35 lines of real logins,
# nicknames, a game uid and one developer's actual working directory sat in this
# repository while this file reported ten passes. A guard that does not look does not
# report «I did not look» — it reports «clean». The two are indistinguishable from the
# outside, which makes an unexamined exclusion the most expensive line in a test.
#
# So: prose may SAY «FunFly» while explaining what the launcher is, and a test may
# assert against a literal, because asserting is its job. Neither may carry a real
# person, and neither may carry somebody's actual machine — `test_no_personal_identity_is_shipped`
# and `test_no_absolute_path_of_one_machine` read every tracked file with no
# exceptions at all.
#
# `tools/archive/` and `tools/scratch/` used to be named here too. They are not any
# more, and not because the rule stopped applying: they are git-ignored, so
# `git ls-files` never offers them and there is nothing left to exclude. An exception
# that excludes nothing is worse than no exception — it reads as though those paths
# are still shipped and still forgiven.
SKIP_PREFIXES = ("docs/", "tests/")

#: Everything tracked, prose included. What the personal-data and absolute-path checks
#: walk, because neither has any business skipping a file.
ALL_GLOBS = ("*.py", "*.bat", "*.cmd", "*.ps1", "*.json", "*.sh", "*.md", "*.lua",
             "*.js", "*.txt", "*.cfg", "*.ini", "*.yml", "*.yaml", "*.toml", "LICENSE")

#: Where each value is allowed to be spelled out — the resolver, plus the files that
#: legitimately show it to a person rather than use it.
ALLOWED = {
    "FunFly": {"tools/lib/game_paths.py"},
    "LastWarLauncher.exe": {
        "tools/lib/game_paths.py",
        # The panel's settings field shows it greyed out as «what goes here» — a
        # translated hint in every locale, not a path this code builds.
        *(f"panel/locales/{loc}.json" for loc in
          ("en", "ru", "de", "fr", "es", "it", "pt", "pl", "tr", "id", "vi")),
    },
    "LastWar.exe": {"tools/lib/game_paths.py"},
    "Last War-Survival Game": {"tools/lib/game_paths.py"},
}

#: Every kind of file that can hold a decision. **The list matters more than it looks:**
#: the first cut of this test read `.py`, `.bat` and `.json`, and `tools/start_instance.cmd`
#: sat outside it with the interpreter, the install path and the port all written out.
#: A guard that covers most of the tree reads exactly like one that covers all of it.
SOURCE_GLOBS = ("*.py", "*.bat", "*.cmd", "*.ps1", "*.json", "*.sh")


def _quoted(value: str) -> re.Pattern:
    """A quoted value, in Python or JSON alike — and in EITHER case.

    Case-insensitively on purpose: `GAME_PROCESS = "lastwar.exe"` in the capture tools
    is the same decision as `"LastWar.exe"` anywhere else, and a case-sensitive first
    cut of this test walked straight past two of them.
    """
    return re.compile(r"""["']""" + re.escape(value) + r"""["']""", re.IGNORECASE)


def _tracked(*globs: str) -> list[str]:
    globs = globs or SOURCE_GLOBS
    out = subprocess.run(["git", "ls-files", *globs], cwd=_REPO,
                         capture_output=True, text=True, check=True).stdout.split("\n")
    return [f for f in out if f and not f.startswith(SKIP_PREFIXES)]


def _all_tracked() -> list[str]:
    """Every tracked file, with NO exclusions — prose, tests and fixtures included."""
    out = subprocess.run(["git", "ls-files", *ALL_GLOBS], cwd=_REPO,
                         capture_output=True, text=True, check=True).stdout.split("\n")
    return [f for f in out if f]


def _read(rel: str) -> str:
    return (_REPO / rel).read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------------


def test_where_the_game_is_installed_is_spelled_out_once():
    """The publisher folder, the launcher and the client, each in one file only."""
    for value, allowed in ALLOWED.items():
        pat = _quoted(value)
        for rel in _tracked():
            if rel in allowed:
                continue
            hit = pat.search(_read(rel))
            assert not hit, (
                f"{rel} spells out {value!r}. Ask tools/lib/game_paths.py instead — "
                f"that is the one place a machine can answer differently."
            )


def test_the_resolver_still_answers_all_of_them():
    """…and «spelled out once» means the answers are still there to be had."""
    assert gp.game_folder().startswith("FunFly")
    assert gp.launcher_exe() == "LastWarLauncher.exe"
    assert gp.game_exe() == "LastWar.exe"
    assert gp.window_title() == "Last War-Survival Game"


def test_every_knob_moves_exactly_what_it_names():
    """A machine that is not ordinary changes one variable and nothing else."""
    cases = [
        ("LW_WINDOW_TITLE", "Another Window", gp.window_title),
        ("LW_LOCALLOW", os.path.join("Z:", os.sep, "low"), gp.local_low),
        ("LW_GAME_DATA_DIR", os.path.join("Z:", os.sep, "data"), gp.data_dir),
        ("LW_CHAT_PHOTOS", os.path.join("Z:", os.sep, "pics"), gp.chat_photos_dir),
        ("LW_GAMERES", os.path.join("Z:", os.sep, "gameres"), gp.gameres),
        ("LW_ASSET_CACHE", os.path.join("Z:", os.sep, "cache"), gp.asset_cache),
        ("LW_WIRESHARK_DIR", os.path.join("Z:", os.sep, "ws"),
         lambda: gp.wireshark_dirs()[0]),
    ]
    for name, value, read in cases:
        old = os.environ.get(name)
        os.environ[name] = value
        try:
            assert read() == value, f"{name} did not move {read.__name__}()"
        finally:
            os.environ.pop(name, None)
            if old is not None:
                os.environ[name] = old


def test_an_empty_variable_is_not_an_answer():
    """Set-but-empty is how a shell passes «unset»; it must not blank a path."""
    for name in ("LW_WINDOW_TITLE", "LW_GAMERES", "LW_CHAT_PHOTOS"):
        old = os.environ.get(name)
        os.environ[name] = ""
        try:
            assert gp.window_title() and gp.gameres() and gp.chat_photos_dir()
        finally:
            os.environ.pop(name, None)
            if old is not None:
                os.environ[name] = old


def test_the_download_tree_is_not_the_install_tree():
    """LocalLow (what the client downloads) is never Local (what it shipped with).

    Confusing the two is the bug this pair of helpers exists to prevent: chat photos
    live under `persistentDataPath`, the asset bundles under the install.
    """
    for name in ("LW_LOCALLOW", "LW_GAME_DATA_DIR", "LW_GAME_DIR", "LW_CHAT_PHOTOS"):
        os.environ.pop(name, None)
    assert gp.data_dir() != gp.game_dir()
    assert gp.chat_photos_dir().startswith(gp.data_dir())
    assert gp.gameres().startswith(gp.game_dir())


#: Cyrillic letters that are drawn exactly like Latin ones. A word mixing the two reads
#: as ordinary text and matches nothing a plain pattern looks for — which is how
#: `P:\projects abandoned\карono\…`, a real working directory, sat in a test through
#: several green runs of this file. Every line is folded to Latin before it is
#: searched, so a mixed-alphabet spelling meets the same pattern as a plain one.
#:
#: Folding happens BEFORE hashing as well as before matching, and that ordering is the
#: whole reason a digest can replace a pattern here: a name written with a Cyrillic `а`
#: in the middle normalises to the same letters as the plain spelling, so it lands on
#: the same digest. Hash first and the two are unrelated numbers, and the homoglyph
#: spelling walks past a guard that looks like it is working.
HOMOGLYPHS = str.maketrans({
    "а": "a", "А": "A", "е": "e", "Е": "E", "о": "o", "О": "O",
    "р": "p", "Р": "P", "с": "c", "С": "C", "х": "x", "Х": "X",
    "у": "y", "У": "Y", "к": "k", "К": "K", "м": "m", "М": "M",
    "т": "t", "Т": "T", "в": "b", "В": "B", "н": "h", "Н": "H",
    "і": "i", "І": "I", "ѕ": "s", "Ѕ": "S", "ј": "j", "Ј": "J",
})


def _fold(line: str) -> str:
    """The line as it LOOKS, not as it is encoded — see :data:`HOMOGLYPHS`."""
    return line.translate(HOMOGLYPHS)


#: A run of letters and digits — the unit a name is written in. Everything between the
#: runs (spaces, dots, brackets, quotes, underscores) is separator, so `"casparov_x"`,
#: `casparov.log` and `[casparov]` all offer the same word to the check.
WORD = re.compile(r"[0-9A-Za-z]+")

#: Nothing shorter is a name worth banning, and nothing longer than a two-word handle
#: is one either. The bounds are here so the scan is not a SHA-256 of every token in
#: the repository — they are deliberately independent of what is actually banned,
#: because the digests cannot tell us how long the values were and must not.
MIN_LEN, MAX_LEN = 3, 40


def _norm(value: str) -> str:
    """The value as a name, stripped of how it happened to be written.

    Folded to Latin shapes, lower-cased, and reduced to letters and digits: `Marrow 88`,
    `marrow-88` and `MARROW88` are one value, and so is the same word with a Cyrillic
    letter in it. Normalising before hashing is what makes a digest as forgiving as the
    case-insensitive, homoglyph-folding pattern it replaced.

    (The example is invented — writing a real one here is the bug this file was fixed
    for, and the guard caught exactly that in the first draft of this docstring.)
    """
    return re.sub(r"[^0-9a-z]+", "", _fold(value).lower())


def _digest(value: str) -> str:
    return hashlib.sha256(_norm(value).encode("utf-8")).hexdigest()


def _hit(line: str, digests: dict[str, str]) -> str | None:
    """What KIND of personal value this line carries, or None. Never the value itself.

    Single words and adjacent pairs both, because a handle can be written with a space
    in it and normalisation joins it back up.
    """
    words = WORD.findall(_fold(line).lower())
    for i, word in enumerate(words):
        pair = word + words[i + 1] if i + 1 < len(words) else ""
        for cand in (word, pair):
            if MIN_LEN <= len(cand) <= MAX_LEN and not cand.isdigit():
                what = digests.get(hashlib.sha256(cand.encode("utf-8")).hexdigest())
                if what:
                    return what
    return None


#: The people this repository is not allowed to name, as digests of their normalised
#: spelling — see the module docstring for why, and for `--hash` to add one.
#:
#: They arrived in the two shapes the tree kept collecting: Windows logins, and game
#: identities copied out of a live session into a fixture or a research note. The
#: second kind is mostly not the author's — they are other players who happened to be
#: on screen when a capture was recorded, which is exactly why publishing the list to
#: protect them was the wrong shape of fix.
#:
#: The KIND is written out on purpose: a failure has to be actionable («line 12 names a
#: player nickname») without the reader, the log, the CI output or the next search
#: engine learning who. Account ids are absent from this table by design — sixteen
#: digits is a SHAPE, and :func:`test_no_live_account_id_is_shipped` reads it directly.
PERSONAL_DIGESTS = {
    "81fdff283ec2829b4002384ad18370f64e7a48618c45058e3d112d965e27f72e": "a Windows login",
    "73facd83f2b2a650ad2f292103d0c05048d20a88bccb5fb51fc78bc8a7ae47c1": "a Windows login",
    "3b8009df5b442d0182d64d6ebd42388d11431b28622a256e2997f7d8e2e423cf": "a player nickname",
    "85cc260c0f43b61de66c3bc169ee39bce818118301ee51452d2def470969b904": "a player nickname",
    "4703c73aa8bf17d5af773722f9ce800ab0eaea70238809a578030653eb7f4112": "a player nickname",
    "c53ceffe2a6ac8679ed63b47ee35f9b1ebc9526415215ca2413261e17279c8d3": "a player nickname",
    "95c6cac5663f0ae96eec60b9126996811ef1f0a304199eb6fa6a6dbb0ad03b3d": "a player nickname",
    "45a98030b3446fd4035393096704bf5e55e88f04bbbfc72d2572bf90bb8c6e4c": "a player nickname",
    "5497c9722ef6130bf094db941a3cb9b32c68b3145a713350df8cd0bccce9aa97": "a player nickname",
    "abc41ec8c9e58b14c50eef1db12910914b13e9b23abeee836912d52fe2d17dfb": "a player nickname",
    "5620b4c0722d246e44003e49be984bff6d3c900a4da840d4b024b523cf5a8f0f": "a player nickname",
    "be28df538a5c732658750b179278bbbf275afa5baeab134576e2fb6ede09bd9d": "a player nickname",
    "cb0471a04689afb69c26137a18ea632e1c8446ec506f3248802228f5975cfba0": "an alliance tag",
    "3620d818217973204d3975354dca9bee92f869b39b7f0fe2a367068b47c3af5a": "an alliance tag",
    "e09567fee4f8e4aef530e5f182534fde1e2e1e333977c1601271590b0dfc8d32": "an alliance tag",
}

#: The repository's own address is not personal data — it is where the project lives,
#: and it has to be the real one for anybody to download it. Any line carrying it is
#: exempt, and nothing else is.
REPO_URL = re.compile(r"github\.com(:\d+)?[/:]carono|carono/last-war-vp-bot")

#: **Nothing is exempt from the personal-data check.** There used to be one entry here
#: — this file, because it named every banned value in order to ban them — and that
#: exemption was the leak (#1234): the one file nobody checked was the one holding the
#: list. Digests removed the reason for it, so the set is empty and stays empty; a
#: legitimate exception is a LINE shape (below), never a file.
PERSONAL_ALLOWED: set[str] = set()

#: The one LINE shape where a real name is the point: a copyright holder and a package
#: author field. Deliberately a line rule and not a file rule — exempting the whole of
#: `LICENSE` and `pyproject.toml` would mean anything else added to them goes unread,
#: and «not searched» is the failure this entire file exists to stop repeating.
ATTRIBUTION = re.compile(r"^\s*(#\s*)?(Copyright\b|authors?\s*=|author\s*=)", re.I)


def test_no_personal_identity_is_shipped():
    """No real person — a Windows login, a game nickname, an alliance, an account id.

    **Tests are checked too**, and that is the point rather than an afterthought: the
    other assertions here skip `tests/`, because a test writes literals on purpose. But
    a fixture recorded from a live session is not a literal written on purpose — it is
    a real account, and the first cut of this guard skipped the whole directory and so
    walked past a live player's nickname and uid sitting in a committed fixture.

    Whole lines, quoted or not: comments and docstrings are exactly where the last
    Windows logins were hiding.

    **`docs/` is checked too.** It was skipped as «prose the author signs», and that
    reasoning was wrong twice over: research prose had 35 lines of real logins, a real
    nickname, an alliance tag, a game uid and a `C:\\Users\\<login>\\…` path — and half
    of those people are not the author, they are other players who happened to be on
    screen when a capture was recorded. Prose is exactly where recorded data goes to
    be forgotten.

    **And this file is checked too**, which it was not until #1234. The failure names
    the place and the kind and stops there: printing the value would put it back into
    the CI log, the terminal history and whatever reads them.
    """
    for rel in _all_tracked():
        if rel in PERSONAL_ALLOWED:
            continue
        for i, line in enumerate(_read(rel).splitlines(), 1):
            if REPO_URL.search(line) or ATTRIBUTION.match(line):
                continue
            what = _hit(line, PERSONAL_DIGESTS)
            assert not what, (
                f"{rel}:{i} names {what} — a real person. Use a placeholder; a fixture "
                f"recorded live has to be anonymised before it is committed. (The value "
                f"is not printed on purpose: read the line.)"
            )


#: An account id as this game writes them: sixteen digits, and a shape rather than a
#: list — which is why not one of them is in :data:`PERSONAL_DIGESTS`. A digest can
#: only ban the ids somebody has already seen; the shape bans the next one too.
ACCOUNT_ID = re.compile(r"(?<!\d)\d{16}(?!\d)")

#: What an anonymised id looks like once a fixture has been cleaned: the ten-digit
#: `1000000000` prefix and a made-up tail, or a run of zeros where the id was a device
#: rather than a player. Every id in `tests/fixtures/` and in `docs/research/` already
#: reads like one of the two, so the rule below costs nothing to keep and fails the
#: moment a fresh recording is committed unread.
PLACEHOLDER_ID = re.compile(r"^(1000000000\d{6}|0+)$")


def test_no_live_account_id_is_shipped():
    """A sixteen-digit id is either the anonymised shape or it is somebody's account.

    Shape, not identity: the guard cannot know whose account a number is, and does not
    need to. It knows that a real one has never been cleaned, and that a cleaned one is
    recognisable at a glance — by the author writing it and by a reviewer reading the
    diff, which is the property the old list of seven remembered ids never had.
    """
    for rel in _all_tracked():
        for i, line in enumerate(_read(rel).splitlines(), 1):
            for m in ACCOUNT_ID.finditer(line):
                assert PLACEHOLDER_ID.match(m.group(0)), (
                    f"{rel}:{i} carries a sixteen-digit account id that has not been "
                    f"anonymised. Replace it with a 1000000000xxxxxx placeholder — a "
                    f"recording is not a fixture until it is."
                )


#: A long run of hex that contains at least one letter: a device id, an alliance uuid,
#: a session token — the shapes a live capture leaves behind. All-zero placeholders
#: have no letter in them and so are never flagged, which is the point of writing them
#: that way.
HEX_BLOB = re.compile(r"(?<![0-9A-Za-z])(?=[0-9a-f]*[a-f])[0-9a-f]{24,}(?![0-9A-Za-z])",
                      re.IGNORECASE)

#: The two files whose long hex is not an identity, each for a reason that is written
#: down rather than assumed.
HEX_ALLOWED = {
    # The digests above. This file is exempt from THIS check and from nothing else —
    # the personal-data check reads it like any other file now.
    "tests/test_no_hardcoded_values.py",
    # The published checksums of the Python and Git installers it downloads. They
    # describe a file on a vendor's server, not a person.
    "install.bat",
}


def test_no_identifier_blob_is_shipped():
    """No 24-plus hex identifier outside the two files that have a reason for one.

    A capture is full of them, and they are the one kind of personal value nobody
    recognises on sight — a reviewer skims a 32-character uuid the way they skim
    whitespace. So the guard fails on the shape and asks for a zeroed placeholder,
    which is what the fixtures that have already been cleaned use.
    """
    for rel in _all_tracked():
        if rel in HEX_ALLOWED:
            continue
        for i, line in enumerate(_read(rel).splitlines(), 1):
            m = HEX_BLOB.search(line)
            assert not m, (
                f"{rel}:{i} carries a {len(m.group(0))}-character identifier. If it "
                f"came off a live session it is somebody's — zero it out the way the "
                f"cleaned fixtures do."
            )


def test_the_second_client_asks_which_account_rather_than_guessing():
    """`tools/rdp_instance.py` ships no default user, and no default second instance.

    Both used to name one developer's login, so on anybody else's machine the tool
    went looking for a session that could not exist and reported it as «not running».
    """
    text = _read("tools/rdp_instance.py")
    assert "LW_SECOND_USER" in text, "the account has to come from somewhere"
    assert re.search(r"DEFAULT_USER\s*=\s*\(os\.environ", text), \
        "DEFAULT_USER is a literal again"

    sys.path.insert(0, str(_REPO / "tools" / "lib"))
    import instance_manager  # noqa: PLC0415

    users = [i.get("user") for i in instance_manager.DEFAULT_INSTANCES]
    assert users == [""], \
        f"the built-in registry names an account: {users!r} — register it instead"


#: Any absolute path — a drive letter, or a WSL/Linux root. Deliberately broad: the
#: point is that every one of them has to be JUSTIFIED below rather than merely look
#: innocent, because «looks like an example» is exactly how a real working directory
#: got in.
MACHINE_PATH = re.compile(
    r"""(?:(?<![A-Za-z\\])[A-Za-z]:[\\/](?![\\/])|/mnt/[a-z]/|/home/[a-z])""")
#             ^ a `\` before the letter means an escape (`\d\d:\d\d` is a timestamp
#               regex, not drive D:), never a disk.
#            ^ `http://…` is `p:` + `//`, not drive P: — a URL is not a disk.

#: Paths that name nothing real. A `<placeholder>`, an environment variable, an
#: ellipsis or a `path/to` — all of them say «a path goes here» rather than «this
#: path».
PATH_PLACEHOLDER = re.compile(
    r"<[^>]+>|PUT-A-|path[\\/]to|путь[\\/]к|\.\.\.|…|%[A-Za-z_]+%|\$\{?[A-Za-z_]+"
    r"|\{[a-z_]+\}")

#: The absolute paths this repository is allowed to write out, and why. **This list is
#: the test.** Everything here is either a Windows location that is the same on every
#: Windows, the installer's own documented default, or a made-up path used as an
#: example or as test input — a name nobody's disk actually has.
#:
#: Adding a row is a decision: if a new path is real, it does not belong in the
#: repository, and if it is invented, say so here. That is the whole mechanism —
#: `P:\projects abandoned\…` would never have been written into this list, which is
#: precisely why it has to exist for the check to mean anything.
ILLUSTRATIVE = re.compile(
    r"""(?ix)
      C:[\\/]{1,2}Windows            # where Windows is on every Windows
    | C:[\\/]{1,2}Python312          # install.bat's documented default
    | C:[\\/]{1,2}Program\ Files
    | /mnt/c/(Windows|Program\ Files|Python312)  # …the same three, seen from WSL
    | (C:[\\/]{1,2}|/mnt/c/)Users[\\/]{1,2}(player2|you|\*|"\*")  # anonymised accounts
    | C:[\\/]{1,2}tmp[\\/]                              # an invented scratch path
    | [CD]:[\\/]{1,2}(Games|py|repos|LW)[\\/]       # invented example roots
    | C:[\\/]{1,2}(LastWar|LastWarBot|a\.exe|nope|x\b)  # invented test inputs
    | D:[\\/]{1,2}мои\ проекты                        # the Cyrillic-path test case
    | Z:[\\/]                                          # the env-override test's drive
    """)

#: Where a concrete path is the subject rather than a decision.
PATH_ALLOWED = {
    "tests/test_no_hardcoded_values.py",   # this file spells them out to ban them
    "tools/lib/game_paths.py",             # the resolver: the one place that may
}


def test_no_absolute_path_of_one_machine():
    """No path that is true of one computer's disk and nobody else's.

    This check did not exist, and on its absence `P:\\projects abandoned\\карono\\…` —
    a real working directory, half-spelled in Cyrillic — rode into a test and sat
    there through several green runs.

    It is broad on purpose and forgiving only by name: every absolute path either
    carries a `<placeholder>`, or is listed in :data:`ILLUSTRATIVE` as invented. There
    is no rule that can tell a real `P:\\…` from an invented `D:\\…` by looking, so the
    test does not try — it asks the author to have said which it is.
    """
    for rel in _all_tracked():
        if rel in PATH_ALLOWED:
            continue
        for i, line in enumerate(_read(rel).splitlines(), 1):
            folded = _fold(line)
            hit = MACHINE_PATH.search(folded)
            if not hit or PATH_PLACEHOLDER.search(folded) or ILLUSTRATIVE.search(folded):
                continue
            assert False, (
                f"{rel}:{i} carries an absolute path ({hit.group(0)!r}). If it is real, "
                f"ask tools/lib/game_paths.py or an environment variable; if it is an "
                f"example, write a <placeholder> or declare it in ILLUSTRATIVE.\n"
                f"    {line.strip()[:100]}"
            )


def test_a_homoglyph_spelling_does_not_slip_past():
    """A word spelled half in Cyrillic must meet the same pattern as a plain one.

    Not hypothetical: `P:\\projects abandoned\\карono\\…` — a real working directory,
    with к-а-р in Cyrillic — sat in `tests/test_panel_autostart.py` through several
    green runs of this file. A plain pattern cannot see it, and neither can a reviewer
    reading the diff.

    Folding is by SHAPE, not by sound: Cyrillic `к` is drawn like `k`, so `карono`
    folds to `kapono`. That is the point — the spelling stops being invisible, and the
    literal it hides behind stops being unsearchable.
    """
    assert _fold("карono") == "kapono"
    assert _fold("Р:\\рrojects") == "P:\\projects"
    assert MACHINE_PATH.search(_fold("Р:\\x")), \
        "a folded drive letter must still match"


def test_the_guard_catches_what_is_planted_in_front_of_it():
    """Push values at the checker and watch it flag them — the digests changed how it
    remembers, and this is what says they did not change what it catches.

    The values here are invented, so the test proves the mechanism without the file
    holding a real one — which is the entire trick. Every spelling a person might reach
    for is tried: the plain one, another case, a homoglyph, a separator, a word wrapped
    in punctuation, and a handle written with a space in it.
    """
    planted = {_digest("Quillonbrek"): "an invented nickname",
               _digest("Marrow 88"): "an invented handle"}

    for spelling in ("Quillonbrek", "QUILLONBREK", "quillonbrek",
                     "Quillоnbrek",                       # Cyrillic о
                     "  name = 'Quillonbrek'  ", "[Quillonbrek]", "quillonbrek_2",
                     "path/to/Quillonbrek.log"):
        assert _hit(spelling, planted) == "an invented nickname", \
            f"a planted value walked past the guard: {spelling!r}"

    for spelling in ("Marrow 88", "Marrow-88", "marrow88", "«Marrow 88»"):
        assert _hit(spelling, planted) == "an invented handle", \
            f"a planted two-word handle walked past the guard: {spelling!r}"

    # …and it stays quiet on ordinary text, or the whole tree fails and nobody reads it.
    for innocent in ("the marrow of the matter", "quill on brek", "88", "",
                     "collect_healed xall", "def test_the_guard(): pass"):
        assert _hit(innocent, planted) is None, f"false positive on {innocent!r}"


def test_the_guard_still_flags_the_shapes_it_no_longer_lists():
    """The ids and blobs left the digest table for a shape check; push those at it too.

    A live id and a cleaned one, side by side: what the check has to tell apart is not
    who they belong to but whether anybody cleaned them.
    """
    # Invented, and spelled in two halves so that this file does not itself carry a
    # sixteen-digit run — the check reads its own source like everybody else's, and
    # writing the example out in one piece is how you find that out.
    live = "2468013579" + "246801"
    assert ACCOUNT_ID.search(live) and not PLACEHOLDER_ID.match(live)
    assert PLACEHOLDER_ID.match("1000000000000935"), "a cleaned fixture id must pass"
    assert not ACCOUNT_ID.search("100000000000093"), "fifteen digits is not an id"
    assert not ACCOUNT_ID.search("10000000000009351"), "…nor is seventeen"

    assert HEX_BLOB.search('"allianceId": "a3f9c1d0e4b27856aa910c33de77f102"')
    assert not HEX_BLOB.search('"allianceId": "00000000000000000000000000000000"'), \
        "a zeroed placeholder is what a cleaned fixture looks like"
    assert not HEX_BLOB.search("commit 26bbbfc"), "a short sha is a reference, not an id"


def test_the_table_of_digests_holds_no_plaintext():
    """The guard's own list must be unreadable — that is the whole of task #1234.

    Two ways it could quietly stop being: a value pasted in beside its digest, and a
    «category» that is really the value with a label's punctuation on it. The second is
    checked by hashing the category and looking for it in the table.
    """
    for digest, what in PERSONAL_DIGESTS.items():
        assert re.fullmatch(r"[0-9a-f]{64}", digest), \
            f"{what}: not a SHA-256 digest — use --hash, never the value"
        assert _digest(what) not in PERSONAL_DIGESTS, \
            "a category names its own value; describe the KIND instead"
        assert " " in what, f"{digest[:8]}…: a category reads like «a player nickname»"
    assert _digest("") not in PERSONAL_DIGESTS, "an empty value would ban every line"
    assert len(set(PERSONAL_DIGESTS)) == len(PERSONAL_DIGESTS)


#: Directories that hold live data from a real account, on the machine that plays.
#: Each is git-ignored, and that ignore is the ONLY thing between them and the public
#: repository — there is no second line of defence, because the files are genuinely
#: there in the working tree while the bot runs.
PRIVATE_TREES = [
    ("panel/profiles", "chat logs (real DMs, sender names and uids), per-account "
                       "settings, session state"),
    ("results",        "captures, traces and scans recorded off a live account"),
    ("tools/scratch",  "throwaway RE probes"),
    ("tools/archive",  "superseded probes, written against one machine"),
]


def test_the_trees_that_hold_live_data_stay_ignored():
    """The private directories are ignored — checked, not assumed.

    This test exists because of a near miss. A background grep, finished long after it
    was started, surfaced `panel/profiles/default/chat_log.jsonl`: real direct
    messages, with the sender names, the uids and the alliance of two actual people.
    It was ignored and never at risk — but nothing verified that, and every other
    check in this file reads only tracked files, so all of them would have gone on
    reporting «clean» for as long as the ignore held and the exact moment it stopped.

    An ignore rule is one line, edited by hand, with no test under it. Now there is
    one: delete the line and this fails.
    """
    for path, what in PRIVATE_TREES:
        if not (_REPO / path).exists():
            continue          # not every machine has run every part of the bot
        ignored = subprocess.run(["git", "check-ignore", "-q", path], cwd=_REPO).returncode
        assert ignored == 0, (
            f"{path}/ is NOT git-ignored, and it holds {what}. One `git add -A` "
            f"publishes it."
        )


def test_nothing_untracked_is_waiting_to_be_committed_by_accident():
    """Whatever `git add -A` would sweep up must be something we meant to ship.

    The complement of the test above: a private tree can also leak by a file landing
    OUTSIDE it. Anything untracked and unignored is listed here so a stray capture or
    a pasted log is noticed while it is still a working-tree file.
    """
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                         cwd=_REPO, capture_output=True, text=True, check=True).stdout
    stray = [l[3:] for l in out.split("\n") if l.startswith("??")]
    # Source being added in the same commit is normal; data is not.
    data = [f for f in stray if pathlib.Path(f).suffix.lower() in
            (".jsonl", ".log", ".pcap", ".pcapng", ".png", ".jpg", ".csv", ".db")]
    assert not data, (
        f"untracked data files are neither ignored nor committed: {data[:5]}. "
        f"Either they belong in a private tree, or .gitignore is missing a rule."
    )


def test_the_capture_tools_ask_rather_than_pin_the_port():
    """A capture filtered on a port that has moved does not fail — it goes quiet.

    That is why this one is worth a test of its own: `17935` was pinned in two files
    while a live client had connected out on `10012`, and the tools reported an empty
    capture, which reads exactly like «nothing is happening in the game».
    """
    old = os.environ.get("LW_GAME_PORT")
    os.environ["LW_GAME_PORT"] = "10012"
    try:
        assert gp.game_port() == 10012
    finally:
        os.environ.pop("LW_GAME_PORT", None)
        if old is not None:
            os.environ["LW_GAME_PORT"] = old
    assert gp.game_port() == gp.DEFAULT_GAME_PORT
    # Nonsense must not crash a capture that would otherwise have worked.
    os.environ["LW_GAME_PORT"] = "not-a-port"
    try:
        assert gp.game_port() == gp.DEFAULT_GAME_PORT
    finally:
        os.environ.pop("LW_GAME_PORT", None)


def test_the_installer_puts_python_where_it_is_told():
    """`C:\\Python312` is the installer's *default*, not its decision.

    It stays a literal in exactly two places — `install.bat`'s default and the
    resolver's — and both are reachable: `--pydir` on the command line, `LW_PY_DIR`
    in the environment.
    """
    bat = _read("install.bat")
    assert "--pydir" in bat, "the installer offers no way to choose the location"
    assert 'if not defined LW_PY_DIR' in bat, \
        "the installer's default is not an overridable one"
    # …and the launchers find it there rather than assuming the default.
    for rel in ("panel.bat", "daemon.bat", "update.bat", "tools/start_instance.cmd"):
        text = _read(rel)
        assert "LW_WIN_PYTHON" in text and "LW_PY_DIR" in text, \
            f"{rel} cannot find a Python installed anywhere but the default"


def test_the_interpreter_is_decided_in_one_place():
    """Several files SHOW the interpreter in a «run it like this» line, which is
    documentation and stays. What may not come back is a second file that DECIDES it."""
    assigns = re.compile(r"=\s*r?[\"']C:\\+Python312")
    for rel in _tracked("*.py"):
        if rel == "tools/lib/game_paths.py":
            continue
        hit = assigns.search(_read(rel))
        assert not hit, f"{rel} decides the interpreter for itself"
    assert gp.DEFAULT_WIN_PYTHON == r"C:\Python312\python.exe", \
        "…and this is the one place that does"


def _main() -> int:
    # `--hash "a value"` — the only way a new banned name should ever be added. It
    # prints the digest and nothing else, so the value stays in the shell that typed it
    # and never reaches a commit, a diff or a review comment.
    if len(sys.argv) > 1 and sys.argv[1] == "--hash":
        if len(sys.argv) < 3:
            print('usage: --hash "the value to ban"')
            return 2
        for value in sys.argv[2:]:
            print(f'    "{_digest(value)}": "a player nickname",   '
                  f'# describe the KIND, never the value')
        return 0

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())

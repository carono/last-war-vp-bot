r"""Every file cmd.exe reads ends its lines the way cmd.exe counts them (task #1225).

cmd.exe does not read a batch file line by line. It remembers a BYTE OFFSET, reads a
line, executes it, then seeks back to where it thinks the next one starts — and the
arithmetic assumes CRLF. Give it an LF-only file and the offset drifts a byte per line
until it resumes in the MIDDLE of a line, so what runs is the tail of a comment:

    'the' is not recognized as an internal or external command
    'all.bat' is not recognized as an internal or external command
    'not' is not recognized as an internal or external command

That is `panel.bat` failing to start with the ends of its own `REM` lines and of
`install.bat`. The drift cuts multi-byte UTF-8 in half too, so the Russian the player is
meant to read arrives as mojibake and looks like a separate encoding bug. It is not:
one file, one cause, and the file's syntax is perfectly correct throughout.

Nothing warns about it. `.gitattributes` asks for `eol=crlf`, so a fresh clone is fine —
but the attribute normalises CRLF back to LF on the way IN, which means an editor (or an
agent) that rewrites a .bat with Unix endings produces a working tree that is broken and
a `git diff` that is empty. The launcher stops working and version control has nothing
to say about it.

So the check is on the WORKING TREE, where cmd.exe will actually read the file:

  * every .bat and .cmd in the checkout ends its lines with CRLF;
  * `.gitattributes` claims every extension cmd.exe reads, so the next clone gets CRLF
    for the ones committed today AND for a .cmd added tomorrow;
  * none of them carries a UTF-8 BOM — the launchers switch the console to 65001
    themselves, and the BOM bytes would land in front of the first command.

    C:\Python312\python.exe tests\test_batch_line_endings.py
    python3 tests/test_batch_line_endings.py
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# What cmd.exe will execute. Directories git never sees, or that hold generated files,
# are not ours to fix: a venv ships whatever it ships, and results/ is scratch.
_SUFFIXES = (".bat", ".cmd")
_SKIP_DIRS = {".git", ".venv", "results", "screenshots", "__pycache__", "node_modules"}


def _scripts() -> list[Path]:
    found = []
    for path in sorted(_REPO_ROOT.rglob("*")):
        if path.suffix.lower() not in _SUFFIXES or not path.is_file():
            continue
        if _SKIP_DIRS.intersection(path.relative_to(_REPO_ROOT).parts):
            continue
        found.append(path)
    return found


def test_scripts_are_found_at_all() -> None:
    """A checkout with no launcher in it would pass every other check silently."""
    names = {p.name for p in _scripts()}
    for expected in ("panel.bat", "install.bat", "daemon.bat", "update.bat"):
        assert expected in names, f"{expected} is missing from the checkout"


def test_every_line_ends_with_crlf() -> None:
    """The whole of task #1225: an LF-only line is a line cmd.exe will mis-seek past."""
    broken = []
    for path in _scripts():
        raw = path.read_bytes()
        # An LF that is not the second half of a CRLF is a line cmd.exe counts wrong.
        lone = raw.replace(b"\r\n", b"").count(b"\n")
        if lone:
            rel = path.relative_to(_REPO_ROOT).as_posix()
            broken.append(f"{rel} ({lone} LF-only line(s))")
    assert not broken, (
        "cmd.exe reads these by byte offset and assumes CRLF; with LF it resumes "
        "mid-line and runs the ends of comments: " + ", ".join(broken)
    )


def test_gitattributes_claims_every_extension() -> None:
    """A .cmd nobody declared is checked out LF on the next clone and breaks there."""
    attributes = (_REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    declared = {
        line.split()[0].lower()
        for line in attributes.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "eol=crlf" in line
    }
    for path in _scripts():
        pattern = "*" + path.suffix.lower()
        assert pattern in declared, (
            f"{path.relative_to(_REPO_ROOT).as_posix()} is read by cmd.exe but "
            f"'{pattern} text eol=crlf' is not in .gitattributes"
        )


def test_no_byte_order_mark() -> None:
    """The launchers call `chcp 65001` themselves; a BOM only prefixes the first line."""
    marked = [
        p.relative_to(_REPO_ROOT).as_posix()
        for p in _scripts()
        if p.read_bytes().startswith(b"\xef\xbb\xbf")
    ]
    assert not marked, f"a UTF-8 BOM would run as part of the first command: {marked}"


def _main() -> int:
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

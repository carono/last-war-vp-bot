r"""install.bat: the installer that works out of the folder it was unpacked into (#1196).

The bot is downloaded as an archive and unpacked wherever the person likes, so the
installer's job is no longer "clone this repository somewhere" but "set up the machine
around the folder I am sitting in". Which makes three things worth a test:

  * **it refuses the folders it cannot install into** — one that is not the bot's, one
    Windows made to preview a .zip in (and deletes again afterwards), and one whose path
    has a "!" or a "%" in it. All three are checked before anything is downloaded and
    before the UAC prompt;
  * **it works from anywhere else** — spaces and Cyrillic in the path included, with the
    shortcuts it makes pointing back at that folder and taking it as their working
    directory;
  * **it can attach the folder to the repository** — an archive has no history, so the
    panel's «Обновить» and update.bat would have nothing to pull. The attach turns the
    folder into a checkout where it stands, and a `pull` has to work afterwards, which
    is the part a shallow fetch could quietly break.

The real batch file is run through cmd.exe, with only its heavy subroutines replaced:
downloading and installing Python, Git and npcap, running pip, and the administrator
check. Everything the task is about — the guards, the paths, the attach, the shortcuts —
is the file's own code, unmodified. A renamed subroutine fails the stub loudly rather
than passing a test that no longer exercises anything.

Windows only: it drives cmd.exe. Under WSL it finds cmd.exe and git through /mnt/c, so
it runs there too as long as the scratch directory can be reached from both sides.

    C:\Python312\python.exe tests\test_installer.py
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "install.bat"

#: Scratch lives under the home directory, never under %TEMP%: the installer refuses to
#: run from a temporary folder, which is exactly one of the things tested here.
SCRATCH = Path(os.environ.get("USERPROFILE") or Path.home()) / ".lw-installer-tests"

#: The subroutines a test must not really run, and what they become instead. The keys
#: are checked against the file — a rename breaks the stub rather than the assertions.
STUBS = {
    "is_admin": "exit /b 0",
    "ensure_python": 'set "PY=C:\\Python312\\python.exe"\r\necho     [stub] python\r\nexit /b 0',
    # Not "pretend git is there": the attach step needs a real one, so the stub only
    # skips DOWNLOADING it and keeps the file's own lookup.
    "ensure_git": 'call :find_git\r\necho     [stub] git: !GIT!\r\nexit /b 0',
    "install_requirements": "echo     [stub] pip\r\nexit /b 0",
    "offer_npcap": "echo     [stub] npcap\r\nexit /b 0",
}

CMD = os.environ.get("COMSPEC") or "C:\\Windows\\System32\\cmd.exe"
if not Path(CMD).exists():                       # WSL
    CMD = "/mnt/c/Windows/System32/cmd.exe"


# -- running the thing ---------------------------------------------------------
def _win(path: Path) -> str:
    """`path` as Windows spells it — the same string under Windows, mapped under WSL."""
    text = str(path)
    if text.startswith("/mnt/") and len(text) > 6 and text[6] == "/":
        return f"{text[5].upper()}:\\" + text[7:].replace("/", "\\")
    return text


def _run(bat: Path, *args: str, cwd: Path | None = None) -> tuple[int, str]:
    """Run a batch file through cmd.exe with no stdin, and return (exit code, output).

    The command line is built by hand rather than by subprocess, because `cmd /c` has a
    quoting rule of its own: it strips ONE outer pair of quotes and runs what is left, so
    a path with a space in it needs quotes inside quotes. Let subprocess quote the list
    and cmd tries to run the whole line as the name of a program.

    `<nul` matters too: every refusal ends in `pause`, and a test that blocked there
    would hang instead of failing.
    """
    inner = " ".join([f'"{_win(bat)}"', *args, "<nul"])
    proc = subprocess.run(f'"{CMD}" /c "{inner}"', capture_output=True,
                          cwd=str(cwd or SCRATCH))
    # The batch file talks UTF-8 (it sets the codepage itself); cmd's own complaints come
    # back in the OEM one, which is why nothing here decodes strictly.
    out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    return proc.returncode, out


def _rmtree(path: Path) -> None:
    """Delete a tree, read-only files included.

    git marks everything under `.git/objects` read-only, and Windows refuses to unlink a
    read-only file — so a plain rmtree leaves half a repository behind and the next run
    trips over it. Failing to delete is still not worth failing a test over: an
    already-gone path and a file some other process is holding both just get skipped.
    """
    if not path.exists():
        return

    def _clear(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    key = "onexc" if sys.version_info >= (3, 12) else "onerror"
    shutil.rmtree(path, **{key: _clear})


def _shortcuts(desktop: Path) -> list:
    """Every .lnk in `desktop`, read back as ``"target|working directory"``.

    Through a .ps1 file rather than `-Command`: a script full of `$` and quotes handed to
    cmd on a command line comes out the other side as something else entirely.
    """
    script = SCRATCH / "read-shortcuts.ps1"
    script.write_text(
        "$w = New-Object -ComObject WScript.Shell\r\n"
        f"Get-ChildItem -LiteralPath '{_win(desktop)}' -Filter *.lnk | ForEach-Object {{\r\n"
        "  $s = $w.CreateShortcut($_.FullName)\r\n"
        '  "$($s.TargetPath)|$($s.WorkingDirectory)"\r\n'
        "}\r\n", encoding="utf-8")
    proc = subprocess.run(
        f'"{CMD}" /c "powershell -NoProfile -ExecutionPolicy Bypass -File "{_win(script)}""',
        capture_output=True)
    out = proc.stdout.decode("utf-8", "replace")
    return [line.strip() for line in out.splitlines() if "|" in line]


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", _win(repo), *args], capture_output=True, text=True,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} in {repo}:\n{proc.stderr}")
    return proc.stdout.strip()


# -- the folders a test installs into ------------------------------------------
def _stub_installer(folder: Path) -> Path:
    """A copy of the real install.bat with only its heavy subroutines replaced."""
    # newline="" both ways: the CRLF a .bat lives by must survive the round trip, and
    # Path.read_text/write_text only learned the argument in 3.13.
    with open(INSTALLER, encoding="utf-8", newline="") as fh:
        text = fh.read()
    for name, body in STUBS.items():
        pattern = re.compile(r"(?m)^:%s\r\n.*?(?=^:[a-z_]+\r\n)" % name, re.S)
        match = pattern.search(text)
        assert match, f":{name} is not in install.bat any more — this stub is stale"
        text = text[:match.start()] + f":{name}\r\n{body}\r\n\r\n" + text[match.end():]
    # CRLF throughout, or cmd.exe mis-seeks on a `goto` out of a block — silently.
    assert "\n" not in text.replace("\r\n", ""), "the stub grew a bare LF"
    target = folder / "install.bat"
    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return target


def _tree(name: str, *, stub: bool = True, real: bool = False) -> Path:
    """A folder that looks like an unpacked archive, under a fresh scratch directory."""
    folder = SCRATCH / name
    if folder.exists():
        _rmtree(folder)
    (folder / "panel").mkdir(parents=True)
    (folder / "panel" / "__main__.py").write_text("", encoding="utf-8")
    (folder / "requirements.txt").write_text("", encoding="utf-8")
    (folder / "pyproject.toml").write_text("", encoding="utf-8")
    if real:
        shutil.copyfile(INSTALLER, folder / "install.bat")
    elif stub:
        _stub_installer(folder)
    return folder


def _origin(name: str) -> tuple[Path, str]:
    """A bare repository standing in for github, with one commit on branch `v2`."""
    bare = SCRATCH / f"{name}.git"
    work = SCRATCH / f"{name}-work"
    for path in (bare, work):
        _rmtree(path)
    bare.mkdir(parents=True)
    _git(bare, "init", "--bare", "--initial-branch=v2")
    work.mkdir(parents=True)
    _git(work, "init", "--initial-branch=v2")
    _git(work, "config", "user.email", "test@example.invalid")
    _git(work, "config", "user.name", "Test")
    _git(work, "config", "commit.gpgsign", "false")
    (work / "panel").mkdir()
    (work / "panel" / "__main__.py").write_text("# upstream\n", encoding="utf-8")
    (work / "requirements.txt").write_text("", encoding="utf-8")
    (work / "pyproject.toml").write_text("", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "first")
    _git(work, "remote", "add", "origin", _win(bare))
    _git(work, "push", "-u", "origin", "v2")
    return work, _win(bare)


# -- what it refuses -----------------------------------------------------------
def test_refuses_a_folder_that_is_not_the_bots():
    """install.bat on its own, away from the tree it belongs to, installs nothing."""
    folder = SCRATCH / "bare"
    _rmtree(folder)
    folder.mkdir(parents=True)
    shutil.copyfile(INSTALLER, folder / "install.bat")
    code, out = _run(folder / "install.bat")
    assert code == 1, out
    assert "не папка бота" in out, out


def test_refuses_a_run_out_of_the_zip_preview():
    """Started from inside the .zip window, everything would be deleted afterwards."""
    temp = Path(os.environ.get("TEMP") or "C:\\Windows\\Temp") / "Temp1_lwbot.zip" / "lwbot"
    _rmtree(temp.parent)
    (temp / "panel").mkdir(parents=True)
    (temp / "panel" / "__main__.py").write_text("", encoding="utf-8")
    (temp / "requirements.txt").write_text("", encoding="utf-8")
    (temp / "pyproject.toml").write_text("", encoding="utf-8")
    shutil.copyfile(INSTALLER, temp / "install.bat")
    try:
        code, out = _run(temp / "install.bat")
        assert code == 1, out
        assert "временной папки" in out, out
    finally:
        _rmtree(temp.parent)


def test_refuses_a_path_with_a_bang_in_it():
    """"!" is eaten by delayed expansion — the refusal is the only honest answer."""
    folder = _tree("bang!dir", stub=False, real=True)
    code, out = _run(folder / "install.bat")
    assert code == 1, out
    assert "«!»" in out, out


# -- what it accepts -----------------------------------------------------------
def test_help_offers_no_directory_to_install_into():
    """There is nowhere to choose any more: the folder it runs from IS the install."""
    folder = _tree("help", stub=False, real=True)
    code, out = _run(folder / "install.bat", "--help")
    assert code == 0, out
    assert "--profile" in out, out
    for gone in ("--dir", "C:\\LastWarBot"):
        assert gone not in out, f"{gone} is still offered:\n{out}"


def test_installs_from_a_path_with_spaces_and_cyrillic():
    """Unpacked into «Мои документы\\бот 2»? Then that is where it installs."""
    folder = _tree("папка с пробелами и кириллицей")
    desktop = SCRATCH / "рабочий стол"
    _rmtree(desktop)
    desktop.mkdir(parents=True)
    code, out = _run(folder / "install.bat", "--yes", "--no-attach", "--no-npcap",
                     "--desktop", f'"{_win(desktop)}"')
    assert code == 0, out
    assert "Готово" in out, out
    assert _win(folder) in out, out
    assert (desktop / "Last War — панель.lnk").exists(), sorted(p.name for p in desktop.iterdir())


def test_the_shortcuts_point_back_at_the_unpacked_folder():
    """A shortcut carrying an absolute path from somewhere else is the old bug."""
    folder = _tree("ярлыки")
    desktop = SCRATCH / "desk"
    _rmtree(desktop)
    desktop.mkdir(parents=True)
    code, out = _run(folder / "install.bat", "--yes", "--no-attach", "--no-npcap",
                     "--profile", "second", "--desktop", f'"{_win(desktop)}"')
    assert code == 0, out
    lines = _shortcuts(desktop)
    assert lines, f"no shortcuts read back from {desktop}"
    for line in lines:
        target, workdir = line.split("|")
        assert target.startswith(_win(folder)), f"{target} is not in {folder}"
        assert workdir == _win(folder), f"working directory {workdir} is not {folder}"
    assert any(t.endswith("panel.bat") for t in (ln.split("|")[0] for ln in lines)), lines


# -- updating an archive install -----------------------------------------------
def test_attach_turns_the_folder_into_a_checkout():
    """The archive has no history; attaching gives «Обновить» something to pull."""
    _work, origin = _origin("attach-origin")
    folder = _tree("attach")
    code, out = _run(folder / "install.bat", "--yes", "--no-npcap", "--no-shortcuts",
                     "--repo", f'"{origin}"', "--branch", "v2")
    assert code == 0, out
    assert (folder / ".git").is_dir(), out
    assert _git(folder, "rev-parse", "--abbrev-ref", "HEAD") == "v2"
    assert _git(folder, "rev-parse", "--abbrev-ref", "--symbolic-full-name",
                "@{u}") == "origin/v2"
    # Clean, and holding the upstream content: an install that left the tree "modified"
    # would make the panel report uncommitted changes and refuse to update for ever.
    assert _git(folder, "status", "--porcelain", "--untracked-files=no") == ""
    assert (folder / "panel" / "__main__.py").read_text(encoding="utf-8") == "# upstream\n"


def test_a_pull_works_after_attaching():
    """The shallow fetch must not cost the update it exists for — this is that check."""
    work, origin = _origin("pull-origin")
    folder = _tree("pull")
    code, out = _run(folder / "install.bat", "--yes", "--no-npcap", "--no-shortcuts",
                     "--repo", f'"{origin}"', "--branch", "v2")
    assert code == 0, out
    (work / "panel" / "__main__.py").write_text("# newer\n", encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "second")
    _git(work, "push", "origin", "v2")
    # What panel/runtime/updates.py does on «Обновить»: fetch the one branch, then a
    # merge that can only fast-forward.
    _git(folder, "fetch", "--quiet", "origin", "v2")
    _git(folder, "merge", "--ff-only", "origin/v2")
    assert (folder / "panel" / "__main__.py").read_text(encoding="utf-8") == "# newer\n"


def test_attach_that_cannot_reach_the_remote_leaves_no_half_repository():
    """A folder that was an archive before a failed attach is an archive after it."""
    folder = _tree("attach-fail")
    code, out = _run(folder / "install.bat", "--yes", "--no-npcap", "--no-shortcuts",
                     "--repo", f'"{_win(SCRATCH / "no-such-repo.git")}"', "--branch", "v2")
    assert code == 0, out          # a failed attach is a warning, not a failed install
    assert not (folder / ".git").exists(), "a half-made repository was left behind"
    assert "Готово" in out, out


def test_attach_can_be_declined():
    """--no-attach is the "leave my folder alone" answer, and it installs anyway."""
    folder = _tree("no-attach")
    code, out = _run(folder / "install.bat", "--yes", "--no-attach", "--no-npcap",
                     "--no-shortcuts")
    assert code == 0, out
    assert not (folder / ".git").exists(), out
    assert "новым архивом" in out, out


def _main() -> int:
    # Windows only, and deliberately not "WSL too": cmd.exe reached through /mnt/c gets
    # the quotes rewritten on the way in, which is the one thing every call here needs
    # kept intact. Run it with the Windows interpreter.
    if os.name != "nt":
        print("  skipped: install.bat is a Windows batch file — run this with"
              " C:\\Python312\\python.exe")
        return 0
    # A failure message quotes the installer's own Russian output; the default console
    # encoding cannot always spell it, and a test suite must not die of its own report.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    SCRATCH.mkdir(parents=True, exist_ok=True)
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    _rmtree(SCRATCH)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())

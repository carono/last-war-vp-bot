r"""Why the client vanished — the Windows evidence, beside what the panel was doing.

«Клиент пропал — процесса игры больше нет» is the panel saying it can no longer find
the process. It never says WHY, and the three answers look identical from inside the
panel: the game crashed, the game was closed, or the server kicked the account and the
client quit on its own. Telling them apart takes three sources that live outside the
repository, and looking each of them up by hand is what made «клиент пропадает N раз в
день» a guess for months (#2066, #2656).

So: one command, three sources, one table.

    python3 tools/crash_report.py --days 1 --profile <name>
    C:\Python312\python.exe tools\crash_report.py --days 7

  * **The Windows Application log** (`Application Error`, event 1000) — the authority on
    whether the process FAULTED. It names the faulting module, the offset inside it and
    the exception code. A disappearance with no entry here is not a crash: the client
    exited, and the reason is the game's own (a kick, an update, somebody closing it).
  * **The crash dumps** Windows keeps under `%LOCALAPPDATA%\CrashDumps`, when the machine
    is configured to write them. This reads the exception record and the faulting
    instruction pointer out of the minidump without a debugger, and says which module
    that address is in — `None` means the thread was executing memory that belongs to no
    module at all, the signature this repository has its own reason to care about.
  * **A profile's `panel.log`**, when `--profile` is given: the lines the panel wrote in
    the seconds before the fault, so «what were we doing» is read rather than recalled.

Nothing here is specific to one machine: the client's process name comes from
`tools/lib/game_paths.py`, and the PowerShell used to ask the event log is looked up
(`LW_POWERSHELL` overrides it). Run it from WSL or from Windows — both work.

`docs/research/client-crashes.md` is what the numbers meant the two times this was asked.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import game_paths  # noqa: E402


# --- the shell that can ask Windows ---------------------------------------------------

def powershell() -> str | None:
    """A PowerShell this machine can run, or None when there is none to be had.

    Asked in the order that costs least: an explicit answer, then whatever is on PATH
    (Windows, and WSL with interop on), then the interpreter's own Windows directory,
    then the mount a WSL install normally has. Never a literal drive letter on its own.
    """
    named = (os.environ.get("LW_POWERSHELL") or "").strip()
    if named:
        return named if os.path.exists(named) or shutil.which(named) else None
    for name in ("powershell.exe", "pwsh.exe", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    tails = (r"System32\WindowsPowerShell\v1.0\powershell.exe",
             "System32/WindowsPowerShell/v1.0/powershell.exe")
    roots = [os.environ.get("SystemRoot") or "", "/mnt/c/Windows"]
    for root in roots:
        for tail in tails:
            if root and os.path.exists(os.path.join(root, tail)):
                return os.path.join(root, tail)
    return None


_PS = r"""
Get-WinEvent -FilterHashtable @{{LogName='Application'; ProviderName='Application Error';
  StartTime=[datetime]'{start}'}} -ErrorAction SilentlyContinue |
  Where-Object {{ $_.Message -like '*{exe}*' }} |
  ForEach-Object {{
    '{{0}}~|~{{1}}' -f $_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss'), ($_.Message -replace '\s+', ' ')
  }}
"""

#: Event 1000's wording is translated, its VALUES are not. Whatever the locale, the
#: message names the crashing program first and the faulting module second, its three
#: 8-hex numbers are the two build stamps and then the exception code, and the single
#: 16-hex one is the offset inside the faulting module. So the fields are read by shape.
_MODULE = re.compile(r"[A-Za-z0-9_.\-]+\.(?:dll|exe|sys)|unknown")
_HEX8 = re.compile(r"0x[0-9a-fA-F]{8}\b")
_HEX16 = re.compile(r"0x[0-9a-fA-F]{16}\b")


def parse_event(message: str) -> dict:
    """Faulting module, exception code and offset out of one event-1000 message."""
    mods = _MODULE.findall(message)
    hex8 = [h.lower() for h in _HEX8.findall(message)]
    hex16 = _HEX16.findall(message)
    return {"module": mods[1] if len(mods) > 1 else (mods[0] if mods else "?"),
            "code": hex8[-1] if hex8 else "?",
            "offset": hex16[0].lower() if hex16 else "?"}


def windows_crashes(days: int, exe: str) -> list[dict]:
    """Event 1000 for the client, newest first. Empty when the log cannot be asked."""
    shell = powershell()
    if not shell:
        print("[crash] no PowerShell here — the Windows event log cannot be asked "
              "(set LW_POWERSHELL)", file=sys.stderr)
        return []
    start = (dt.datetime.now() - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    script = _PS.format(start=start, exe=exe)
    try:
        out = subprocess.run([shell, "-NoProfile", "-Command", script],
                             capture_output=True, timeout=180).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[crash] the event log refused: {exc}", file=sys.stderr)
        return []
    rows = []
    for line in out.decode("utf-8", "replace").replace("\r", "").splitlines():
        stamp, sep, message = line.strip().partition("~|~")
        if not sep:
            continue
        try:
            when = dt.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        rows.append({"at": when, **parse_event(message)})
    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows


# --- the dumps ------------------------------------------------------------------------

def dump_dir() -> Path:
    """Where Windows drops a faulting process's minidump, when it is asked to."""
    named = (os.environ.get("LW_CRASH_DUMPS") or "").strip()
    return Path(named) if named else Path(game_paths.local_appdata()) / "CrashDumps"


def read_dump(path: Path) -> dict:
    """Exception code, faulting address and the module RIP was in — no debugger.

    A minidump is a header, a directory of streams and then the streams; the two this
    needs are the exception record (which carries a whole CONTEXT) and the module list.
    Everything else is skipped, so this stays cheap on a 45 MB file.
    """
    out: dict = {"file": path.name}
    try:
        with path.open("rb") as fh:
            head = fh.read(32)
            if head[:4] != b"MDMP":
                return {**out, "error": "not a minidump"}
            nstream, diro = struct.unpack_from("<II", head, 8)
            fh.seek(diro)
            dirs = fh.read(12 * nstream)
            streams = {}
            for i in range(nstream):
                kind, size, rva = struct.unpack_from("<III", dirs, 12 * i)
                streams[kind] = (size, rva)

            def stream(kind: int) -> bytes:
                size, rva = streams[kind]
                fh.seek(rva)
                return fh.read(size)

            if 6 in streams:                                   # ExceptionStream
                b = stream(6)
                code = struct.unpack_from("<I", b, 8)[0]
                addr = struct.unpack_from("<Q", b, 24)[0]
                nparam = struct.unpack_from("<I", b, 32)[0]
                params = struct.unpack_from("<15Q", b, 40)[:nparam]
                ctx_size, ctx_rva = struct.unpack_from("<II", b, 40 + 15 * 8)
                fh.seek(ctx_rva)
                ctx = fh.read(ctx_size)
                out.update(code=f"0x{code:08x}", address=f"0x{addr:016x}",
                           params=[f"0x{p:x}" for p in params],
                           rip=struct.unpack_from("<Q", ctx, 0xF8)[0] if len(ctx) > 0x100 else 0)
            if 4 in streams and out.get("rip"):                # ModuleListStream
                b = stream(4)
                count = struct.unpack_from("<I", b, 0)[0]
                rip, off = out["rip"], 4
                out["in_module"] = None
                for _ in range(count):
                    base = struct.unpack_from("<Q", b, off)[0]
                    size = struct.unpack_from("<I", b, off + 8)[0]
                    name_rva = struct.unpack_from("<I", b, off + 20)[0]
                    off += 108
                    if base <= rip < base + size:
                        fh.seek(name_rva)
                        ln = struct.unpack("<I", fh.read(4))[0]
                        name = fh.read(ln).decode("utf-16le", "replace")
                        out["in_module"] = f"{name.split(chr(92))[-1]}+0x{rip - base:x}"
                        break
                out["rip"] = f"0x{out['rip']:016x}"
    except (OSError, struct.error, KeyError, IndexError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def dumps(days: int, exe: str) -> list[dict]:
    d = dump_dir()
    if not d.is_dir():
        return []
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    rows = []
    stem = exe.lower()
    for f in sorted(d.glob("*.dmp")):
        if not f.name.lower().startswith(stem):
            continue
        when = dt.datetime.fromtimestamp(f.stat().st_mtime)
        if when < cutoff:
            continue
        rows.append({"at": when, **read_dump(f)})
    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows


# --- what the panel was doing ---------------------------------------------------------

_STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) ")


def panel_windows(log: Path, moments: list[dt.datetime], before: int,
                  after: int) -> dict[dt.datetime, list[str]]:
    """The profile's own lines around EVERY moment, in one pass of the file.

    One pass, not one per crash: a busy profile's `panel.log` runs to hundreds of
    megabytes and a week of faults is dozens of moments — reading it per moment turns a
    two-second report into an afternoon.
    """
    spans = [(m, m - dt.timedelta(seconds=before), m + dt.timedelta(seconds=after))
             for m in moments]
    if not spans:
        return {}
    first = min(lo for _, lo, _ in spans)
    last = max(hi for _, _, hi in spans)
    found: dict[dt.datetime, list[str]] = {m: [] for m in moments}
    with log.open("rb") as fh:
        for raw in fh:
            line = raw.decode("utf-8", "replace")
            m = _STAMP.match(line)
            if not m:
                continue
            when = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            if when < first:
                continue
            if when > last:
                break
            for at, lo, hi in spans:
                if lo <= when <= hi:
                    found[at].append(line.rstrip("\n"))
    return found


def profile_log(name: str) -> Path:
    return Path(game_paths.repo_dir()) / "profiles" / name / "panel.log"


# --- the report -----------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=1, help="how far back to look (default 1)")
    ap.add_argument("--profile", help="a profile whose panel.log to quote around each fault")
    ap.add_argument("--panel-log", help="that log by path, for a panel that runs elsewhere")
    ap.add_argument("--before", type=int, default=25, help="seconds of panel log before")
    ap.add_argument("--after", type=int, default=5, help="seconds of panel log after")
    ap.add_argument("--lines", type=int, default=12, help="how many of those lines to print")
    ap.add_argument("--dumps", action="store_true", help="also read the minidumps")
    args = ap.parse_args()

    exe = game_paths.game_exe()
    crashes = windows_crashes(args.days, exe)
    print(f"{exe}: {len(crashes)} fault(s) in the Windows log over {args.days} day(s)")
    if crashes:
        tally: dict[tuple[str, str], int] = {}
        for c in crashes:
            key = (c["module"], c["code"])
            tally[key] = tally.get(key, 0) + 1
        print("\n  faulting module           exception     count")
        for (mod, code), n in sorted(tally.items(), key=lambda kv: -kv[1]):
            print(f"  {mod:<24}  {code:<12}  {n}")
        print("\n  'unknown' means the address is in no loaded module — the thread was "
              "executing memory\n  that belongs to nobody. See docs/research/client-crashes.md.")

    log = Path(args.panel_log) if args.panel_log else (
        profile_log(args.profile) if args.profile else None)
    if log and not log.is_file():
        print(f"\n[crash] no panel.log at {log}", file=sys.stderr)
        log = None

    around = panel_windows(log, [c["at"] for c in crashes], args.before,
                           args.after) if log else {}
    for c in crashes:
        print(f"\n{c['at']:%Y-%m-%d %H:%M:%S}  {c['module']}  {c['code']}  at {c['offset']}")
        if log:
            lines = around.get(c["at"], [])
            for line in lines[-args.lines:]:
                print("    " + line[:160])
            if not lines:
                print("    (the profile's log says nothing in that window)")

    if args.dumps:
        rows = dumps(args.days, exe)
        print(f"\n{len(rows)} minidump(s) under {dump_dir()}")
        for r in rows:
            where = r.get("in_module") or "NO MODULE (private memory)"
            print(f"  {r['at']:%Y-%m-%d %H:%M:%S}  {r.get('code', '?')}  "
                  f"rip={r.get('rip', '?')}  {where}  params={r.get('params', [])}"
                  + (f"  [{r['error']}]" if r.get("error") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

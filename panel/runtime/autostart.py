r"""Keeping the panel up: the beat it writes, and the hourly look that reads it.

A panel that is not open does nothing — no schedule, no triggers, no auto-loot. The
machine reboots, Windows installs an update, somebody closes the window by accident, and
the account simply stops being farmed until a person notices. This is the answer: a task
in the Windows scheduler that looks once an hour and opens the panel if it is not there.

Two halves, and they only make sense together.

**The beat.** The panel writes ``panel_alive.json`` into its profile every minute —
:func:`beat`, armed on the Tk `after` queue (`panel/runtime/host.py`). That queue is the
point. A file written by a background thread would keep saying "alive" for a window that
has been white and unresponsive for an hour; a file written by the event loop stops the
moment the event loop does. So the beat is not "the process exists", it is "the panel is
still answering", which is the difference the task was asked to tell.

**The look.** :func:`check` reads that file and decides one of three things:

===============  =======================================================  ==============
verdict          what it saw                                              what it does
===============  =======================================================  ==============
``running``      a beat younger than :data:`STALE_SEC`, its pid alive     nothing
``stopped``      no file, or its pid is gone                              opens the panel
``hung``         a stale beat whose pid is STILL there                    kills it, opens
===============  =======================================================  ==============

Every verdict is written to ``autostart.json`` in the same profile, which is what the
Settings page shows: the scheduler's own «last run» column says a task ran, not what it
made of what it found.

WHAT GETS REGISTERED. **One task — ``Last War Bot\panel`` — for one panel**, whose
action is *this* installation's interpreter running ``-m panel.runtime.autostart`` with
the repository as its working directory. Nothing is guessed and nothing is hard-coded:
the paths come from :data:`REPO` and `sys.executable`, so a panel that was copied
elsewhere registers the copy, and a second install registers itself.

ONE PANEL, SEVERAL PROFILES (#1207). It used to be a task per profile (#1203), and since
#1206 that is the wrong shape: a panel holds a PAGE per open profile, so two tasks meant
two windows — and on this machine that was two panels driving one game client through one
daemon port. So the task names no profile at all. What it opens is read at the moment it
fires, from the set the panel itself saved (`open_profiles` in `panel/settings.json`,
:func:`open_set`), and one window comes up holding all of it. The set therefore follows
the person: open a second profile, close one, and the next hourly look already knows.
The liveness question is asked the same way — a panel is *there* if ANY of those profiles
is beating, because they are pages of one window, and «one page is missing» is never
answered by opening a second panel on top of the first.

A per-profile task left over from #1203 is swept away when this one is registered, and is
harmless in the meantime: it runs the same check, which sees the window that is up and
leaves it alone.

RIGHTS. The panel is normally started elevated — it reads another process' memory and
npcap wants the rights too (`install.bat` sets the flag on the shortcut). A task that
started it *without* them would come up crippled, so the task mirrors the panel that
registered it: ``HighestAvailable`` from an elevated panel, ``LeastPrivilege`` from a
plain one. That is also what keeps registration free of a UAC prompt in the second case
— asking Windows for a task that runs elevated is what needs administrator rights, and
the Settings page says so when Windows refuses.

It builds no widget and opens no window — the Settings page draws the answer, this
decides what the answer is (`panel/runtime/updates.py` is the same shape). The hourly
run is a headless `pythonw.exe` and must stay one.

    C:\Python312\python.exe -m panel.runtime.autostart --status
    C:\Python312\python.exe -m panel.runtime.autostart
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field

from .. import profile as profilemod
from ..i18n import Message
from .paths import REPO

import proc_table            # noqa: E402 — a bare name, reachable only once `paths` ran

WINDOWS = os.name == "nt"

# Creation flags (Windows). NO_WINDOW keeps `schtasks` from flashing a console over the
# panel; DETACHED + NEW_GROUP is how the panel outlives the check that started it —
# the scheduler ends its task the moment `pythonw -m panel.runtime.autostart` returns.
NO_WINDOW = 0x08000000          # CREATE_NO_WINDOW
DETACHED = 0x00000008           # DETACHED_PROCESS
NEW_GROUP = 0x00000200          # CREATE_NEW_PROCESS_GROUP

#: How often the panel says it is alive.
BEAT_SEC = 60
#: How old a beat may get before the panel counts as gone. Ten beats: the Tk loop is
#: also what draws a modal dialog and what a long read blocks, and a panel waiting on a
#: game round trip is not a panel to kill. The look happens hourly, so being generous
#: here costs nothing and being tight would eventually restart a working panel.
STALE_SEC = 600
#: How long the check waits for a panel it has just started to say its first beat.
LAUNCH_WAIT_SEC = 45
#: The scheduler's repetition interval, ISO 8601 — the «раз в час» of the task.
CHECK_EVERY = "PT1H"
#: Where the tasks live, so all of them can be found (and removed) in one place.
TASK_FOLDER = "Last War Bot"
#: THE task. One panel, one task — the profiles it opens are read when it fires, not
#: baked into its name (see the module docstring).
TASK = f"{TASK_FOLDER}\\panel"
#: What a task from #1203 was called. Only swept away now.
LEGACY_PREFIX = f"{TASK_FOLDER}\\panel-"
#: Cap on the launch log; it holds the stdout of every panel this ever started.
LOG_MAX_BYTES = 512 * 1024


# ---------------------------------------------------------------- the beat --
def _write_json(path: str, data) -> None:
    """Atomically write ``data`` as JSON (best-effort — a beat is never worth a crash)."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _exe_name() -> str:
    return os.path.basename(sys.executable or "").lower()


def beat(profiles, name: str | None = None) -> None:
    """Write this panel's heartbeat into ``name`` (default: the active profile).

    Called from the Tk `after` queue once a minute. The executable name travels with the
    pid so a recycled pid cannot pass for a live panel: Windows hands the number out
    again within minutes, and "pid 8124 exists" would then be a lie told by whatever got
    it next.
    """
    _write_json(profiles.heartbeat(name), {
        "pid": os.getpid(),
        "exe": _exe_name(),
        "ts": time.time(),
        "profile": name or profiles.active,
    })


# ------------------------------------------------------ the instance lock --
#
# «A panel is on this profile» answered by the KERNEL rather than by a file's contents.
#
# The obvious instrument for this is a port, and the obvious port is the Lua daemon's.
# It does not work, and the reason is written in `panel/runtime/daemon.py`'s own comment:
# the daemon is started DETACHED, «so the daemon outlives the panel that started it». It
# has no idle timeout and no parent watch (tools/lua_daemon.py is a bare `while True:
# accept()`), the panel never shuts it down on close, and `daemon.bat` exists precisely
# to run one with no panel at all. So a listening port means «a daemon is up», which is
# true with the panel closed, true while the panel is wedged, and true for a daemon
# somebody started by hand — every case the check has to tell apart.
#
# An exclusive lock on a file in the profile directory is the same idea with the right
# owner: the panel PROCESS holds it, and the OS drops it the moment that process dies —
# no stale state, nothing to expire, and no port to allocate per profile. It cannot go
# stale the way the heartbeat can, and the heartbeat says the one thing it cannot: that
# the window is still ANSWERING. Both, therefore, and neither alone.
def _lock_exclusive(handle) -> bool:
    """Take the lock on byte 0 without blocking. ``False`` if somebody else holds it.

    THE SEEK IS LOAD-BEARING. `msvcrt.locking` locks a range starting at the file's
    current position, and the handle is opened for append — so once the first holder had
    written its pid, the next one to ask locked the byte AFTER it, was granted, and both
    believed they held the profile. Byte 0 every time, whatever the file contains.
    """
    try:
        handle.seek(0)
        if WINDOWS:
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def take_lock(profiles, name: str | None = None):
    """Hold this profile's instance lock for as long as the returned handle lives.

    The panel keeps the handle open for its whole life, so «is the lock held» is exactly
    «is a panel process on this profile». Returns ``None`` when it is already held —
    which the panel only logs: refusing to open a window a person asked for is a
    different decision from refusing to open one nobody asked for.
    """
    path = profiles.lock_file(name)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handle = open(path, "a+b")
    except OSError:
        return None
    if not _lock_exclusive(handle):
        handle.close()
        return None
    try:                                      # for a person reading the folder
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n".encode())
        handle.flush()
    except OSError:
        pass
    return handle


def drop_lock(handle) -> None:
    """Let it go early. The OS does this anyway when the process ends."""
    if handle is None:
        return
    try:
        if WINDOWS:
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        handle.close()
    except OSError:
        pass


def locked(profiles, name: str | None = None) -> bool:
    """Is a panel process holding this profile? Asked by taking the lock and giving it back.

    A lock this process could take was, by definition, held by nobody — and it is
    released again immediately, so asking never blocks the panel that is about to start.
    """
    handle = take_lock(profiles, name)
    if handle is None:
        return True
    drop_lock(handle)
    return False


def holder(profiles, name: str | None = None) -> "int | None":
    """The pid of the panel holding this profile, or ``None`` if nobody holds it.

    ONE PANEL PER PROFILE, not one panel per machine. Two windows on two profiles are a
    supported way to work — a second account, or an instance of one's own inside an RDP
    session — and nothing here stands in their way: the lock is per profile directory.
    Two windows on the SAME profile are the thing that breaks, because they write one
    `config.json` over each other and both drive one daemon.

    The pid comes from the heartbeat, which is a nicety for the log; the LOCK is what
    decides. A profile held by a panel that has not beaten yet is still held.
    """
    if not locked(profiles, name):
        return None
    saved = _read_json(profiles.heartbeat(name))
    try:
        return int(saved.get("pid"))
    except (TypeError, ValueError):
        return None


def focus_panel(profiles, name: str | None = None) -> bool:
    """Bring the panel that holds this profile to the front. Best-effort.

    What a person expects from clicking a shortcut twice: not a second window and not
    only a refusal, but the window they already have. Never the reason a launch fails —
    every part of it is optional and any of it may be missing.
    """
    pid = holder(profiles, name)
    if not pid or not WINDOWS:
        return False
    try:
        import win32con
        import win32gui
        import win32process
    except Exception:                         # noqa: BLE001 — no pywin32 here
        return False
    found = []

    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        _tid, owner = win32process.GetWindowThreadProcessId(hwnd)
        if owner == pid and win32gui.GetWindowText(hwnd):
            found.append(hwnd)

    try:
        win32gui.EnumWindows(visit, None)
        if not found:
            return False
        hwnd = found[0]
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:                         # noqa: BLE001 — a courtesy, not a step
        return False


def clear(profiles, name: str | None = None) -> None:
    """Drop the heartbeat — the panel is closing on purpose."""
    try:
        os.unlink(profiles.heartbeat(name))
    except OSError:
        pass


@dataclass(frozen=True)
class Liveness:
    """What the heartbeat says about a profile's panel."""

    state: str                  # "running" | "stopped" | "hung"
    pid: int | None = None
    age: float | None = None    # seconds since the last beat, None when there is none

    @property
    def running(self) -> bool:
        return self.state == "running"


def _pid_alive(pid: int | None, exe: str = "") -> bool | None:
    """Is that process still there? ``None`` when this machine cannot tell.

    Without psutil there is no answer worth having, and guessing one would mean either
    killing a live panel or never restarting a dead one — so the caller is told plainly
    and falls back on the age of the beat alone.
    """
    if not pid:
        return False
    try:
        import psutil
    except Exception:                       # noqa: BLE001 — not installed here
        return None
    try:
        proc = psutil.Process(int(pid))
        if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
            return False
        # A recycled pid is somebody else's process, not a panel.
        return not exe or (proc.name() or "").lower() == exe
    except Exception:                       # noqa: BLE001 — gone, or not ours to look at
        return False


def probe(profiles, name: str | None = None) -> Liveness:
    """Read the heartbeat and say whether that profile's panel is alive."""
    saved = _read_json(profiles.heartbeat(name))
    if not saved:
        return Liveness("stopped")
    pid = saved.get("pid")
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        pid = None
    # A clock that moved backwards (or a file from the future) must not read as stale.
    age = max(0.0, time.time() - float(saved.get("ts") or 0))
    alive = _pid_alive(pid, str(saved.get("exe") or ""))
    if age < STALE_SEC:
        # Fresh AND the process is gone = it died in the last minute; still "stopped".
        return Liveness("running" if alive is not False else "stopped", pid, age)
    # Stale. A process that is still there is not answering its own event loop, which is
    # the case this whole file exists for; one that is gone simply left the file behind.
    return Liveness("hung" if alive else "stopped", pid, age)


def _panel_profile(cmdline: list) -> "str | None":
    """The profile a command line opens the panel on — ``None`` if it is not a panel.

    Matched on the module argument being exactly ``panel``, so this file's own hourly run
    (``-m panel.runtime.autostart``) and a tab opened on its own (``-m panel.tabs.rally``)
    are not mistaken for the panel itself. A panel started without ``--profile`` is on
    whatever the saved pointer said, which is what the empty answer means.
    """
    parts = [str(a) for a in (cmdline or [])]
    try:
        module = parts[parts.index("-m") + 1]
    except (ValueError, IndexError):
        return None
    if module != "panel":
        return None
    try:
        return profilemod.sanitize(parts[parts.index("--profile") + 1])
    except (ValueError, IndexError):
        return ""                             # the active profile, whatever it is


def panel_pids(profiles, name: str | None = None) -> list:
    """Every OTHER live process holding a panel window on this profile.

    The second guard, and the one that does not depend on a file. Two panels on one
    profile write one `config.json` over each other, so the check must never open a
    second — and a heartbeat can be missing for reasons that have nothing to do with the
    panel being gone (the file deleted by hand, a profile directory restored from a
    backup, a panel built before the beat existed).

    Best-effort by nature: reading another process' command line is refused when it is
    more privileged than this one (the panel is normally elevated, the check need not
    be), and a process that cannot be read is simply not counted. That is why this backs
    the heartbeat up rather than replacing it.

    NARROW FIRST, THEN OPEN (#1214). `psutil.process_iter(["pid", "name", "cmdline"])`
    read the command line of every process on the machine — 7.7 seconds of held
    interpreter lock, measured, for an answer about four pythons. The names come from
    `tools/lib/proc_table.py` now and only the pythons are opened; the reading is the
    same one, taken in a fortieth of the time.
    """
    profile = profilemod.sanitize(name or "") or profiles.active
    try:
        import psutil
    except Exception:                         # noqa: BLE001 — nothing to scan with
        return []
    mine, found = os.getpid(), []
    for pid, exe in proc_table.names():
        if pid == mine or not (exe or "").lower().startswith("python"):
            continue
        try:
            on = _panel_profile(psutil.Process(int(pid)).cmdline())
        except Exception:                     # noqa: BLE001 — gone, or refused: not counted
            continue
        if on is None:
            continue
        if on == profile or (on == "" and profiles.active == profile):
            found.append(pid)
    return found


def stop(pid: int) -> bool:
    """End a wedged panel. Politely first, then not."""
    try:
        import psutil
    except Exception:                       # noqa: BLE001
        if not WINDOWS:
            return False
        return _run("taskkill", "/PID", str(pid), "/T", "/F")[0]
    try:
        proc = psutil.Process(int(pid))
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except psutil.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        return True
    except Exception:                       # noqa: BLE001 — already gone is a success
        return not _pid_alive(pid)


# ------------------------------------------------------- opening the panel --
def panel_python(python: str | None = None) -> str:
    """The interpreter to open the panel with — the windowed twin where there is one.

    `sys.executable` is this installation, which is the whole point: whatever Python is
    running the panel now is the one the task will run it with. `pythonw.exe` because
    nobody is there to look at a console window at three in the morning.
    """
    exe = python or sys.executable or ""
    if os.path.basename(exe).lower() == "python.exe":
        windowed = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(windowed):
            return windowed
    return exe


def _trim_log(path: str) -> None:
    try:
        if os.path.getsize(path) > LOG_MAX_BYTES:
            os.replace(path, path + ".1")
    except OSError:
        pass


def _log(profiles, name: str, line: str) -> None:
    """One line into the profile's ``autostart.log`` — also where a launch's output goes."""
    path = profiles.autostart_log(name)
    _trim_log(path)
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except OSError:
        pass


def open_panel(profiles, name: str) -> "subprocess.Popen | None":
    """Start the panel on ``name``, detached, with its output kept.

    Detached on purpose: the scheduled task finishes as soon as this module returns, and
    a panel that was its child would go with it. What the panel prints before its own
    logging is up (an import error, a missing package) has nowhere else to land, so it
    goes to ``autostart.log`` beside the verdicts.
    """
    cmd = [panel_python(), "-m", "panel", "--profile", name]
    _log(profiles, name, f"launch: {' '.join(cmd)}")
    flags = (DETACHED | NEW_GROUP) if WINDOWS else 0
    try:
        sink = open(profiles.autostart_log(name), "a", encoding="utf-8")
    except OSError:
        sink = subprocess.DEVNULL
    try:
        return subprocess.Popen(cmd, cwd=REPO, stdin=subprocess.DEVNULL,
                                stdout=sink, stderr=subprocess.STDOUT,
                                creationflags=flags, close_fds=True)
    except Exception as exc:                # noqa: BLE001 — the verdict says what happened
        _log(profiles, name, f"launch failed: {exc}")
        return None
    finally:
        if sink is not subprocess.DEVNULL:
            try:
                sink.close()
            except OSError:
                pass


# --------------------------------------------------------- the hourly look --
def open_set(profiles, first: str | None = None) -> list:
    """The profiles ONE panel opens — the page that is on screen first.

    Read from what the panel itself saved (`open_profiles`, `panel/runtime/workspace.py`)
    rather than from anything this task remembers: a task that froze the list when it was
    registered would go on opening yesterday's profiles for ever. An empty answer means
    the active profile alone, which is every panel there was before #1206.

    ``first`` is the `--profile` of a legacy task or of the CLI: it names the page to put
    on top. A name no profile directory answers to is IGNORED here, unlike the panel's own
    `--profile`, which creates it — a #1203 task left pointing at a deleted profile would
    otherwise re-create it, empty, and open a panel on it every hour for ever.
    """
    wanted = [n for n in profiles.open_profiles()]
    head = profilemod.sanitize(first or "")
    if not head or not profiles.exists(head):
        head = wanted[0] if wanted else profiles.active
    return [head] + [n for n in wanted if n != head]


def _pids_of(profiles, names) -> list:
    """Every live panel process holding any of ``names`` — one window may hold several."""
    found = []
    for name in names:
        for pid in panel_pids(profiles, name):
            if pid not in found:
                found.append(pid)
    return found


def check(profile: str | None = None, *, launch: bool = True) -> dict:
    """Look once: start the panel if it is not there, restart it if it is wedged.

    Returns the record it wrote to the ``autostart.json`` of every profile the panel
    holds — ``state`` is one of ``running`` / ``started`` / ``restarted`` / ``failed``,
    which is what the Settings page reads back.

    ONE PANEL FOR THE WHOLE SET (#1207). A panel is a window with a page per open profile,
    so the question is not «is a panel on this profile» but «is the panel up»: ANY profile
    of the set still beating means the window is there, and nothing is opened. The other
    way round — one page missing while the window is up — is not something a second panel
    could fix; it would fight the first for that profile's `config.json` and its daemon.

    NEVER two panels on one profile, therefore, gated three times: on the heartbeat, on
    the instance lock (the kernel's answer, which cannot go stale), and on a scan for a
    panel process anyway. Only a verdict of «hung» opens one on top of something, and only
    after closing it: a beat that started and then stopped is proof of a wedge, where a
    beat that never existed is just as likely to be a deleted file.
    """
    profiles = profilemod.ProfileManager()
    wanted = open_set(profiles, profile)
    head = wanted[0]
    live = {name: probe(profiles, name) for name in wanted}
    running = [n for n in wanted if live[n].running]
    hung = [n for n in wanted if live[n].state == "hung"]
    # Whose reading the record shows: the page that proves the window is up, then the one
    # that proves it is wedged, and the head when neither says anything.
    shown = live[running[0]] if running else live[hung[0]] if hung else live[head]
    record = {"ts": time.time(), "profile": head, "profiles": list(wanted),
              "seen": shown.state, "pid": shown.pid, "age": round(shown.age or 0)}

    held = [] if (running or not launch) else [n for n in wanted if locked(profiles, n)]
    others = [] if (running or not launch) else _pids_of(profiles, wanted)
    record["locked"] = bool(held)

    if running:
        record["state"] = "running"
    elif not launch:
        record["state"] = shown.state
    elif (held or others) and not hung:
        # A panel is there; it is simply not saying so. Leaving it alone is the whole
        # point — a second one on any of these profiles costs the profile itself.
        _log(profiles, head, f"no beat, but the panel is held (lock={held}, "
                             f"pids={others}) — left alone")
        record.update(state="running", seen="lock" if held else "process",
                      pid=others[0] if others else None)
    else:
        doomed = [live[n].pid for n in hung if live[n].pid]
        doomed += [pid for pid in others if pid not in doomed]
        for pid in doomed:
            _log(profiles, head, f"panel {pid} has not beaten for "
                                 f"{int(shown.age or 0)}s — stopping it")
            stop(pid)
        # ONE window for the whole set: `--profile` only says which page is on top, and
        # the panel opens the rest of `open_profiles` itself as it comes up.
        started = open_panel(profiles, head)
        ok = started is not None and _await_beat(profiles, head)
        record["state"] = ("restarted" if hung else "started") if ok else "failed"
        if not ok:
            record["error"] = "no heartbeat after launch"

    _log(profiles, head, f"check: {','.join(wanted)} seen={record['seen']} "
                         f"-> {record['state']}")
    for name in wanted:
        _write_json(profiles.autostart_state(name), record)
    return record


def _await_beat(profiles, name: str) -> bool:
    """Wait for the panel we just started to say its first beat."""
    deadline = time.time() + LAUNCH_WAIT_SEC
    while time.time() < deadline:
        if probe(profiles, name).running:
            return True
        time.sleep(1.0)
    return False


# ------------------------------------------------- the Windows task itself --
def task_name() -> str:
    """``Last War Bot\\panel`` — ONE task, because one panel holds every open profile."""
    return TASK


def legacy_task_name(profile: str) -> str:
    """What #1203 called this profile's task, before one panel could hold several."""
    return f"{LEGACY_PREFIX}{profilemod.sanitize(profile) or 'default'}"


def elevated() -> bool:
    """Is this panel running as administrator?"""
    if not WINDOWS:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:                       # noqa: BLE001
        return False


def _account() -> str:
    """``DOMAIN\\user`` — who the task runs as, which is whoever registered it."""
    user = os.environ.get("USERNAME") or ""
    domain = os.environ.get("USERDOMAIN") or ""
    return f"{domain}\\{user}" if domain and user else (user or "")


def _run(*args: str) -> tuple[bool, str]:
    """Run a console tool without flashing a window. ``(ok, output)``."""
    try:
        done = subprocess.run(list(args), capture_output=True, text=True,
                              errors="replace",
                              creationflags=NO_WINDOW if WINDOWS else 0)
    except Exception as exc:                # noqa: BLE001 — no schtasks on this box
        return False, str(exc)
    return done.returncode == 0, (done.stdout or "") + (done.stderr or "")


#: The task definition, in the element order Windows itself writes one in. That order
#: is not decoration: the scheduler's parser is picky about it, and a hand-arranged file
#: is rejected with «the task XML contains a value which is incorrectly formatted» and
#: no hint as to which value. XML carries no braces of its own, so `str.format` is safe.
TASK_TEMPLATE = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>Last War Bot</Author>
    <Description>{description}</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>{every}</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{begin}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
{logon_user}      <Delay>PT1M</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
{principal_user}      <LogonType>InteractiveToken</LogonType>
      <RunLevel>{level}</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{exe}</Command>
      <Arguments>{args}</Arguments>
      <WorkingDirectory>{cwd}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def task_xml(*, python: str | None = None, repo: str | None = None,
             account: str | None = None, run_level: str | None = None,
             start: str | None = None) -> str:
    """The task, as Task Scheduler XML.

    It names NO profile (#1207). What one panel opens is the set the panel saved, read
    when the task fires — see :func:`open_set` and the module docstring.

    Written out rather than assembled with `schtasks /Create /SC HOURLY` because the
    switches cannot say half of what this needs: a working directory, an interactive
    logon (a task with no desktop can start no window at all), «run it anyway if the
    machine was asleep at the hour», and a repetition that does not expire.

    Two triggers on purpose. The repeating one is the hourly look; the logon one is so a
    machine that has just come back does not sit panel-less until the next full hour.

    Every path in it is this installation's — the interpreter running right now and the
    repository this file is in — so a copy of the panel somewhere else registers the
    copy, not whatever the first machine happened to have.

    The XML escaper is imported HERE rather than at the top of the file (#1282): this is
    the only function in the module that needs it, it runs when somebody ticks a
    checkbox, and `xml.sax.saxutils` drags in `urllib.request` — with `http.client` and
    `ssl` behind it — for 47 ms of every panel start, every `python -m panel.tabs.<id>`
    and every child process that touches the runtime.
    """
    from xml.sax.saxutils import escape

    who = escape(account if account is not None else _account())
    user = f"      <UserId>{who}</UserId>\n" if who else ""
    # A boundary in the past plus StartWhenAvailable means the first look happens now
    # rather than at the top of the next hour.
    return TASK_TEMPLATE.format(
        description=escape("Checks once an hour that the Last War panel is running and "
                           "opens it when it is not — one panel, holding whichever "
                           "profiles were open in it."),
        every=CHECK_EVERY,
        begin=start or time.strftime("%Y-%m-%dT%H:%M:%S"),
        logon_user=user,
        principal_user=user,
        level=run_level or ("HighestAvailable" if elevated() else "LeastPrivilege"),
        exe=escape(python or panel_python()),
        args="-m panel.runtime.autostart",
        cwd=escape(repo or REPO),
    )


def registered() -> bool:
    """Is the task there? Asked of Windows, never of a profile file.

    The scheduler is the truth: a task removed by hand in `taskschd.msc`, or one that
    survived a profile being deleted, must show as it is — a checkbox reading back its
    own saved value would say whatever it said last.
    """
    if not WINDOWS:
        return False
    return _run("schtasks", "/Query", "/TN", TASK)[0]


def legacy_tasks() -> list:
    """The per-profile tasks of #1203 that are still in the scheduler.

    Found by asking Windows for its whole list rather than by guessing names from the
    profiles that exist now: the one that matters most is a task whose profile has since
    been deleted, and no profile file names that.
    """
    if not WINDOWS:
        return []
    ok, out = _run("schtasks", "/Query", "/FO", "CSV", "/NH")
    if not ok:
        return []
    import csv
    import io

    found = []
    for row in csv.reader(io.StringIO(out)):
        name = (row[0] if row else "").strip().lstrip("\\")
        if name.startswith(LEGACY_PREFIX) and name not in found:
            found.append(name)
    return found


def drop_legacy(profile: str | None = None) -> list:
    """Remove the #1203 task(s) — one profile's, or every one that is left.

    Returns the names it could not remove, which is all the reporting this needs: a
    leftover is harmless (it runs the same check, which sees the window that is up and
    leaves it alone), so a scheduler that refuses is not worth failing a registration —
    or a profile rename — over.
    """
    if not WINDOWS:
        return []
    names = [legacy_task_name(profile)] if profile else legacy_tasks()
    left = []
    for name in names:
        if not _run("schtasks", "/Query", "/TN", name)[0]:
            continue
        if not _run("schtasks", "/Delete", "/TN", name, "/F")[0]:
            left.append(name)
    return left


def register(*, python: str | None = None) -> None:
    """Create (or replace) the hourly task. Raises with a translatable why."""
    if not WINDOWS:
        raise RuntimeError(Message("autostart.error.unsupported",
                                   "the task scheduler is Windows-only"))
    xml = task_xml(python=python)
    handle, path = tempfile.mkstemp(suffix=".xml", prefix="lw-autostart-")
    os.close(handle)
    try:
        # UTF-16: schtasks refuses to read a task definition in anything else.
        with open(path, "w", encoding="utf-16") as fh:
            fh.write(xml)
        ok, out = _run("schtasks", "/Create", "/TN", TASK, "/XML", path, "/F")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if ok:
        # …and the per-profile ones go, or the machine would keep both models and open a
        # second window on a client the first one is already driving.
        drop_legacy()
        return
    tail = " ".join(out.split())[-300:]
    if _denied(out):
        raise RuntimeError(Message("autostart.error.admin",
                                   f"access denied: {tail}", error=tail))
    raise RuntimeError(Message("autostart.error.failed",
                               f"schtasks refused: {tail}", error=tail))


def unregister() -> None:
    """Remove the task. One that is already gone is not an error."""
    if not WINDOWS:
        return
    drop_legacy()
    if not registered():
        return
    ok, out = _run("schtasks", "/Delete", "/TN", TASK, "/F")
    if ok:
        return
    tail = " ".join(out.split())[-300:]
    if _denied(out):
        raise RuntimeError(Message("autostart.error.admin",
                                   f"access denied: {tail}", error=tail))
    raise RuntimeError(Message("autostart.error.failed",
                               f"schtasks refused: {tail}", error=tail))


def _denied(out: str) -> bool:
    """Did Windows refuse for want of rights? Its wording is localised; its code is not.

    ``0x80070005`` is E_ACCESSDENIED, printed by schtasks whatever language the machine
    speaks; the English and Russian phrasings are there for the versions that print only
    those.
    """
    low = out.lower()
    return ("0x80070005" in low or "access is denied" in low
            or "отказано в доступе" in low)


@dataclass(frozen=True)
class Status:
    """Everything the Settings page needs to describe the autostart in one glance."""

    profile: str
    supported: bool
    registered: bool
    elevated: bool
    task: str
    #: Every profile the one task opens, the page on screen first (#1207).
    profiles: tuple = ()
    last: dict = field(default_factory=dict)


def _daemon_port(profiles, name: str | None = None) -> int:
    """This profile's daemon port, read from its saved settings.

    The knob lives in the profile (`daemon_port`), so a second account in its own Windows
    session drives its own client on its own port — read here from the file rather than
    from a Tk variable, because nothing in this module has a window.
    """
    import lua_client

    saved = profiles.load(name) if name else profiles.load()
    try:
        port = int(float(str(saved.get("daemon_port")).strip()))
    except (TypeError, ValueError, AttributeError):
        return int(lua_client.DEFAULT_PORT)
    return port if 1 <= port <= 65535 else int(lua_client.DEFAULT_PORT)


def daemon_up(profiles, name: str | None = None) -> bool:
    """Is this profile's Lua daemon answering? **Not** whether the panel is running.

    Worth showing when something is being diagnosed, and worth nothing as a gate. The
    daemon is a separate process the panel starts DETACHED — `panel/runtime/daemon.py`
    says so in as many words, «so the daemon outlives the panel that started it» — with
    no idle timeout and no parent watch, which the panel never shuts down on close and
    which `daemon.bat` is there to run without a panel at all. So a listening port is
    true with the panel closed (the check would then never open it again) and true while
    the panel is wedged (the very case it exists to catch). The lock and the beat answer
    those two questions; this one answers «can I drive the game».
    """
    try:
        import lua_client
        return bool(lua_client.is_running(port=_daemon_port(profiles, name)))
    except Exception:                         # noqa: BLE001 — a diagnostic, never a crash
        return False


def status(profiles, name: str | None = None) -> Status:
    """What is set up on this machine, and what the last look made of it.

    ``name`` is only the page asking — the task is the same one whichever page's Settings
    is open, and so is the verdict it wrote.
    """
    profile = name or profiles.active
    return Status(profile=profile, supported=WINDOWS, registered=registered(),
                  elevated=elevated(), task=TASK,
                  profiles=tuple(open_set(profiles)),
                  last=_read_json(profiles.autostart_state(profile)))


def set_enabled(profiles, enabled: bool, name: str | None = None) -> Status:
    """Turn the hourly check on or off, and report where that left it."""
    if enabled:
        register()
    else:
        unregister()
    return status(profiles, name or profiles.active)


def rename(old: str, new: str) -> None:
    """A profile was renamed. Since #1207 there is nothing to re-point.

    The task names no profile, and the set it opens is read from the panel's own saved
    list — which the rename has already updated. All that is left is a #1203 task named
    after the profile that has just stopped existing.
    """
    drop_legacy(old)


# ------------------------------------------------------------ the CLI half --
def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="panel.runtime.autostart",
        description="Check that the Last War panel is running, and open it if not.")
    parser.add_argument("--profile", metavar="NAME", default=None,
                        help="which page to put on top (default: the panel's own last "
                             "one). The panel opens the whole saved set either way.")
    parser.add_argument("--status", action="store_true",
                        help="say what it sees and do nothing")
    parser.add_argument("--register", action="store_true",
                        help="create the hourly task")
    parser.add_argument("--unregister", action="store_true",
                        help="remove the hourly task")
    args = parser.parse_args(argv)

    profiles = profilemod.ProfileManager()
    wanted = open_set(profiles, args.profile)
    name = wanted[0]

    if args.register or args.unregister:
        try:
            set_enabled(profiles, bool(args.register), name)
        except RuntimeError as exc:
            print(f"{name}: {exc}")
            return 1
        print(f"{'registered' if args.register else 'removed'} {TASK}"
              f" — profiles: {', '.join(wanted)}")
        return 0

    if args.status:
        info = status(profiles, name)
        live = probe(profiles, name)
        print(f"profiles  : {', '.join(info.profiles)}")
        print(f"profile   : {info.profile}")
        print(f"task      : {info.task} "
              f"{'registered' if info.registered else 'not registered'}")
        print(f"elevated  : {info.elevated}")
        print(f"panel     : {live.state}"
              + (f" (pid {live.pid}, beat {int(live.age)}s ago)"
                 if live.pid and live.age is not None else ""))
        print(f"held      : {locked(profiles, name)}"
              f"   pids: {panel_pids(profiles, name) or '-'}")
        # Diagnostics only, and labelled as such. A listening daemon is NOT a running
        # panel: it is started detached and outlives the panel that started it, it has
        # no idle timeout, and `daemon.bat` runs one with no panel at all — so it can
        # say «up» with nothing open, and says nothing at all about a wedged window.
        print(f"daemon    : port {_daemon_port(profiles, name)} "
              f"{'up' if daemon_up(profiles, name) else 'down'} (not a liveness test)")
        if info.last:
            print(f"last check: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(info.last.get('ts') or 0))}"
                  f" -> {info.last.get('state')}")
        return 0

    record = check(name)
    print(f"{name}: {record.get('seen')} -> {record.get('state')}")
    return 0 if record.get("state") != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

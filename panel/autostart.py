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

WHAT GETS REGISTERED. One task per profile, ``Last War Bot\panel-<profile>``, whose
action is *this* installation's interpreter running ``-m panel.autostart --profile
<name>`` with the repository as its working directory. Nothing is guessed and nothing is
hard-coded: the paths come from :data:`REPO` and `sys.executable`, so a panel that was
copied elsewhere registers the copy, and a second install registers itself.

RIGHTS. The panel is normally started elevated — it reads another process' memory and
npcap wants the rights too (`install.bat` sets the flag on the shortcut). A task that
started it *without* them would come up crippled, so the task mirrors the panel that
registered it: ``HighestAvailable`` from an elevated panel, ``LeastPrivilege`` from a
plain one. That is also what keeps registration free of a UAC prompt in the second case
— asking Windows for a task that runs elevated is what needs administrator rights, and
the Settings page says so when Windows refuses.

Deliberately import-light: no tkinter, no `panel.runtime` (importing that package pulls
Tk in). The hourly run is a headless `pythonw.exe` and must stay one.

    C:\Python312\python.exe -m panel.autostart --status
    C:\Python312\python.exe -m panel.autostart --profile main
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from . import profile as profilemod
from .i18n import Message

# panel/autostart.py -> panel -> the repo. Spelled out rather than taken from
# `panel.runtime.paths`, because importing that package brings tkinter with it and this
# module is what runs headless once an hour.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WINDOWS = os.name == "nt"

# Creation flags (Windows). NO_WINDOW keeps `schtasks` from flashing a console over the
# panel; DETACHED + NEW_GROUP is how the panel outlives the check that started it —
# the scheduler ends its task the moment `pythonw -m panel.autostart` returns.
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
def check(profile: str | None = None, *, launch: bool = True) -> dict:
    """Look once: start the panel if it is not there, restart it if it is wedged.

    Returns the record it wrote to the profile's ``autostart.json`` — ``state`` is one
    of ``running`` / ``started`` / ``restarted`` / ``failed``, which is what the
    Settings page reads back.
    """
    profiles = profilemod.ProfileManager()
    name = profilemod.sanitize(profile) if profile else profiles.active
    live = probe(profiles, name)
    record = {"ts": time.time(), "profile": name, "seen": live.state,
              "pid": live.pid, "age": round(live.age or 0)}

    if live.running:
        record["state"] = "running"
    elif not launch:
        record["state"] = live.state
    else:
        if live.state == "hung" and live.pid:
            _log(profiles, name, f"panel {live.pid} has not beaten for "
                                 f"{int(live.age or 0)}s — stopping it")
            stop(live.pid)
        started = open_panel(profiles, name)
        ok = started is not None and _await_beat(profiles, name)
        record["state"] = ("restarted" if live.state == "hung" else "started") if ok \
            else "failed"
        if not ok:
            record["error"] = "no heartbeat after launch"

    _log(profiles, name, f"check: seen={live.state} -> {record['state']}")
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
def task_name(profile: str) -> str:
    """``Last War Bot\\panel-<profile>`` — one task per profile, all in one folder."""
    return f"{TASK_FOLDER}\\panel-{profilemod.sanitize(profile) or 'default'}"


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


def task_xml(profile: str, *, python: str | None = None, repo: str | None = None,
             account: str | None = None, run_level: str | None = None,
             start: str | None = None) -> str:
    """The task, as Task Scheduler XML.

    Written out rather than assembled with `schtasks /Create /SC HOURLY` because the
    switches cannot say half of what this needs: a working directory, an interactive
    logon (a task with no desktop can start no window at all), «run it anyway if the
    machine was asleep at the hour», and a repetition that does not expire.

    Two triggers on purpose. The repeating one is the hourly look; the logon one is so a
    machine that has just come back does not sit panel-less until the next full hour.

    Every path in it is this installation's — the interpreter running right now and the
    repository this file is in — so a copy of the panel somewhere else registers the
    copy, not whatever the first machine happened to have.
    """
    who = escape(account if account is not None else _account())
    user = f"      <UserId>{who}</UserId>\n" if who else ""
    # A boundary in the past plus StartWhenAvailable means the first look happens now
    # rather than at the top of the next hour.
    return TASK_TEMPLATE.format(
        description=escape(f"Checks once an hour that the Last War panel is running "
                           f"on profile {profile!r} and opens it when it is not."),
        every=CHECK_EVERY,
        begin=start or time.strftime("%Y-%m-%dT%H:%M:%S"),
        logon_user=user,
        principal_user=user,
        level=run_level or ("HighestAvailable" if elevated() else "LeastPrivilege"),
        exe=escape(python or panel_python()),
        args=escape(f'-m panel.autostart --profile "{profile}"'),
        cwd=escape(repo or REPO),
    )


def registered(profile: str) -> bool:
    """Is there a task for this profile? Asked of Windows, never of the profile file.

    The scheduler is the truth: a task removed by hand in `taskschd.msc`, or one that
    survived a profile being deleted, must show as it is — a checkbox reading back its
    own saved value would say whatever it said last.
    """
    if not WINDOWS:
        return False
    return _run("schtasks", "/Query", "/TN", task_name(profile))[0]


def register(profile: str, *, python: str | None = None) -> None:
    """Create (or replace) this profile's hourly task. Raises with a translatable why."""
    if not WINDOWS:
        raise RuntimeError(Message("autostart.error.unsupported",
                                   "the task scheduler is Windows-only"))
    xml = task_xml(profile, python=python)
    handle, path = tempfile.mkstemp(suffix=".xml", prefix="lw-autostart-")
    os.close(handle)
    try:
        # UTF-16: schtasks refuses to read a task definition in anything else.
        with open(path, "w", encoding="utf-16") as fh:
            fh.write(xml)
        ok, out = _run("schtasks", "/Create", "/TN", task_name(profile),
                       "/XML", path, "/F")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if ok:
        return
    tail = " ".join(out.split())[-300:]
    if _denied(out):
        raise RuntimeError(Message("autostart.error.admin",
                                   f"access denied: {tail}", error=tail))
    raise RuntimeError(Message("autostart.error.failed",
                               f"schtasks refused: {tail}", error=tail))


def unregister(profile: str) -> None:
    """Remove this profile's task. A task that is already gone is not an error."""
    if not WINDOWS or not registered(profile):
        return
    ok, out = _run("schtasks", "/Delete", "/TN", task_name(profile), "/F")
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
    last: dict = field(default_factory=dict)


def status(profiles, name: str | None = None) -> Status:
    """What is set up for this profile, and what the last look made of it."""
    profile = name or profiles.active
    return Status(profile=profile, supported=WINDOWS, registered=registered(profile),
                  elevated=elevated(), task=task_name(profile),
                  last=_read_json(profiles.autostart_state(profile)))


def set_enabled(profiles, enabled: bool, name: str | None = None) -> Status:
    """Turn the hourly check on or off for a profile, and report where that left it."""
    profile = name or profiles.active
    if enabled:
        register(profile)
    else:
        unregister(profile)
    return status(profiles, profile)


def rename(old: str, new: str) -> None:
    """Follow a profile that was renamed: the task names the profile it opens.

    Silent about a profile that had no task — most do not, and «the rename worked but
    said something about the scheduler» is worse than nothing.
    """
    if not WINDOWS or not registered(old):
        return
    try:
        register(new)
        unregister(old)
    except RuntimeError:
        pass


# ------------------------------------------------------------ the CLI half --
def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="panel.autostart",
        description="Check that the Last War panel is running, and open it if not.")
    parser.add_argument("--profile", metavar="NAME", default=None,
                        help="which profile to watch (default: the active one)")
    parser.add_argument("--status", action="store_true",
                        help="say what it sees and do nothing")
    parser.add_argument("--register", action="store_true",
                        help="create the hourly task for this profile")
    parser.add_argument("--unregister", action="store_true",
                        help="remove the hourly task for this profile")
    args = parser.parse_args(argv)

    profiles = profilemod.ProfileManager()
    name = profilemod.sanitize(args.profile) if args.profile else profiles.active

    if args.register or args.unregister:
        try:
            set_enabled(profiles, bool(args.register), name)
        except RuntimeError as exc:
            print(f"{name}: {exc}")
            return 1
        print(f"{name}: {'registered' if args.register else 'removed'} {task_name(name)}")
        return 0

    if args.status:
        info = status(profiles, name)
        live = probe(profiles, name)
        print(f"profile   : {info.profile}")
        print(f"task      : {info.task} "
              f"{'registered' if info.registered else 'not registered'}")
        print(f"elevated  : {info.elevated}")
        print(f"panel     : {live.state}"
              + (f" (pid {live.pid}, beat {int(live.age)}s ago)"
                 if live.pid and live.age is not None else ""))
        if info.last:
            print(f"last check: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(info.last.get('ts') or 0))}"
                  f" -> {info.last.get('state')}")
        return 0

    record = check(name)
    print(f"{name}: {record.get('seen')} -> {record.get('state')}")
    return 0 if record.get("state") != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

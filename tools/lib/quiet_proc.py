r"""One answer to «start a Windows process without a console flashing over the desktop».

The panel runs windowless — as a service, or under `pythonw.exe` — and a process it
starts inherits nothing to print into. Windows answers that by GIVING the child a
console of its own: a black box that appears over whatever the person is looking at,
lives for as long as the child does, and goes away again. Two of them per client
restart is «постоянное мелькание CMD» (#2874), and none of it is visible in any log,
because a flashing window is not an error.

Two flags stop it, and they answer different halves of the question:

* ``CREATE_NO_WINDOW`` — the child gets a console, but that console has no WINDOW. This
  is the one that matters for a CONSOLE program (`cmd.exe`, `git.exe`, `taskkill.exe`,
  `powershell.exe`, `dumpcap.exe`): they keep their stdout and their exit code, and
  nothing is drawn.
* ``STARTUPINFO.wShowWindow = SW_HIDE`` — the first window a GUI program shows comes up
  hidden. It does nothing at all to a console program, and it is deliberately NOT what
  this module applies by default: hiding a GUI a person asked for (`mstsc`, the game's
  own launcher) is a different decision from not drawing a console nobody asked for.

So :func:`run` and :func:`popen` are the ordinary subprocess calls with the first flag
on, and :func:`hidden_startupinfo` is there for the rare caller that means the second.

Everything here is a no-op off Windows — the flags do not exist there, and passing
``creationflags`` to `subprocess` on Linux raises.
"""

from __future__ import annotations

import os
import subprocess

#: `CREATE_NO_WINDOW`. Named rather than imported: the attribute is absent on the
#: Python that runs the tests in WSL, and the number is part of the Windows API.
NO_WINDOW = 0x08000000

WINDOWS = os.name == "nt"


def hidden_startupinfo() -> "subprocess.STARTUPINFO | None":
    """A `STARTUPINFO` that asks a GUI child to come up hidden. ``None`` off Windows."""
    if not WINDOWS:
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0                      # SW_HIDE
    return info


def flags(extra: int = 0) -> int:
    """``CREATE_NO_WINDOW`` (plus ``extra``) on Windows, ``0`` anywhere else."""
    return (NO_WINDOW | int(extra)) if WINDOWS else 0


def quiet(kwargs: dict, *, hide_gui: bool = False) -> dict:
    """The keyword arguments of a subprocess call, with the console silenced.

    A caller that already passes ``creationflags`` keeps them — the flag is OR-ed in
    rather than overwritten, so `DETACHED_PROCESS` or `CREATE_NEW_PROCESS_GROUP` on the
    same call survive.
    """
    if not WINDOWS:
        return kwargs
    out = dict(kwargs)
    out["creationflags"] = int(out.get("creationflags", 0)) | NO_WINDOW
    if hide_gui and out.get("startupinfo") is None:
        out["startupinfo"] = hidden_startupinfo()
    return out


def run(cmd, **kwargs):
    """`subprocess.run` with no console window."""
    return subprocess.run(cmd, **quiet(kwargs))


def popen(cmd, **kwargs):
    """`subprocess.Popen` with no console window."""
    return subprocess.Popen(cmd, **quiet(kwargs))

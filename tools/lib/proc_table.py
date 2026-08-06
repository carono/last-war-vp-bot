"""Every process on the box, WITHOUT opening a handle to each one (#1214).

`psutil.process_iter(["pid", "name"])` is the obvious way to ask what is running, and on
Windows it is a trap. `Process.name()` there is `os.path.basename(self.exe())`, and
`exe()` is `cext.proc_exe(pid)` — one `OpenProcess` per process, with a slow fallback
whenever the handle is refused. Measured on this box, 389 processes:

    psutil.process_iter(["pid", "name"])            3.96 s   (cold; 0.03 s warm)
    psutil.process_iter(["pid", "name", "cmdline"]) 7.66 s
    win32ts.WTSEnumerateProcesses(0, 1, 0)          0.027 s  (always — nothing is cached)

**And a walk is not free just because it is on a thread.** It is Python holding Python's
lock: while one runs, everything the Tk thread does is ten to forty times slower — one
ttk widget goes from 1 ms to 37–74 ms, a tab that builds in 180 ms takes nine seconds
(docs/research/panel-freezes.md §1). The stall sampler named the frame outright:
``meanwhile 100% — panel-child-sweep: _pswindows.py:758 exe``. Lowering
`sys.setswitchinterval` does not help; the walk simply must not be that expensive.

So the table comes from the terminal-services enumeration, which returns the session, the
pid and the image name of every process in ONE call and never opens anything. psutil is
kept as the fallback for a machine that cannot be asked that way — not Windows, or no
pywin32 — where it is the only answer there is.

**Narrow first, then open.** What a caller usually wants is a handful of processes out of
four hundred: the pythons, or the clients. Take the names from here, filter, and only
then ask psutil for the `cmdline()`, `environ()` or `create_time()` of the few that are
left — that is 0.003 s for four pythons against the 7.66 s of asking all of them. The
rule is the whole point of this module: **never ask every process a question you only
need answered about a few.**
"""
from __future__ import annotations


def wts_rows() -> list:
    """``(session, pid, name)`` for every process on this machine.

    RAISES where the enumeration cannot be had — not Windows, no pywin32, an API that
    refused. That is deliberate: a caller has to be able to tell "this box has no answer"
    from "there are no processes", and an empty list back would read as the second.

    Through `WTSEnumerateProcesses` rather than a per-process lookup, for the reason
    `tools/rdp_instance.py` and `game_link._pids_in_session` both give: the per-process
    call needs query rights, so another user's process comes back as session 0 — which
    reads as a service and is exactly the process being looked for.
    """
    import win32ts                            # noqa: PLC0415 — Windows-only, pywin32
    return [(int(sid), int(pid), (name or ""))
            for sid, pid, name, _owner in win32ts.WTSEnumerateProcesses(0, 1, 0)]


def names() -> list:
    """``(pid, name)`` for every process on this machine. Never raises.

    The cheap enumeration where there is one, psutil where there is not, and an empty
    list on a machine that has neither. An empty list means «could not be read» and every
    caller must treat it as such: it is NOT proof that a process is gone, and acting on
    it as if it were is how a cleanup ends up killing nothing or a watchdog relaunching
    something that is alive.
    """
    try:
        return [(pid, name) for _sid, pid, name in wts_rows()]
    except Exception:                         # noqa: BLE001 — not Windows, or refused
        pass
    try:
        import psutil                         # noqa: PLC0415
        return [(int(p.info["pid"]), (p.info["name"] or ""))
                for p in psutil.process_iter(["pid", "name"])]
    except Exception:                         # noqa: BLE001 — nothing to walk with
        return []


def pids_named(wanted: str) -> list:
    """Every pid whose image name is ``wanted``, case-insensitively. Never raises."""
    want = (wanted or "").lower()
    return [pid for pid, name in names() if name.lower() == want]

"""«Стоп всё» and «Включить обратно» — whether this profile is stopped, and since when.

The emergency button was only half a control. It stops every monitor, every watcher,
the sweep, a running scenario and the schedule — and then says so in ONE line in the
log, which scrolls away. Nothing on screen afterwards says the panel is holding still;
the profile simply does nothing, exactly as it would if everything were merely idle.

That is not a hypothetical. On 2026-08-06 «Стоп всё» was pressed at 12:44, the line was
said, and the schedule stayed off for the rest of the day: the client lost its server at
18:58, died at 20:02 and was still dead two hours later, with the panel open in front of
somebody the whole time. Seven hours went past a log line.

So this holds two things and nothing else:

* **that the profile is stopped**, for as long as it is, so both front-ends can put a
  mark where a mark cannot scroll away;
* **when it happened**, so the mark can say «уже 7 часов» rather than «остановлено» —
  the number is what makes it uncomfortable enough to act on.

WHAT IT DOES NOT HOLD IS THE SNAPSHOT. What was switched on before the stop belongs to
whoever owns the switch — each tab remembers its own in :meth:`panel.tabs.base.PanelTab.panic`
and puts it back in :meth:`~panel.tabs.base.PanelTab.resume`. A central register of
other people's switches is a second copy of state that has to be kept in step with the
first, and the first is a Tk variable that can be moved by hand at any moment. So
«Включить обратно» restores what was ON rather than starting everything there is: a
watcher the person had deliberately left off must not come back running.
"""
from __future__ import annotations


class Panic:
    """One profile's «is everything stopped, and since when».

    Not thread-safe and not required to be: it is written from the button press and
    read from the paint, both on the Tk thread, and the web reads a snapshot dict.
    """

    __slots__ = ("_at", "_count")

    def __init__(self) -> None:
        #: When «Стоп всё» was last pressed, or 0.0 while the profile is running.
        self._at = 0.0
        #: How many times this session — so «нажали и забыли» and «нажимают всё время»
        #: do not look the same.
        self._count = 0

    @property
    def stopped(self) -> bool:
        return self._at > 0.0

    def mark(self, now: float) -> None:
        """«Стоп всё» was pressed."""
        self._at = now
        self._count += 1

    def clear(self) -> None:
        """«Включить обратно» was pressed — or a profile switch made the mark meaningless."""
        self._at = 0.0

    def state(self, now: float) -> dict:
        """What both front-ends draw. Numbers, never words (`CLAUDE.md`)."""
        return {"stopped": self.stopped,
                "for_sec": int(now - self._at) if self.stopped else 0,
                "count": self._count}


# -- the press, for the front-end that is not the window ----------------------
#
# «Включить обратно» has to be reachable from the phone for the same reason «Стоп всё»
# is worth having at all: the moment it matters is the moment nobody is standing at the
# machine. It is the SHELL's press — only the window knows which profiles are open and
# which tabs each of them has — so the shell registers what to run and everything else
# only asks whether there is anything registered, exactly as
# `panel/runtime/panel_control.py` does for the panel's own restart.
_handler = None


def set_handler(fn) -> None:
    """The shell says how «Включить обратно» is carried out. A standalone tab says nothing."""
    global _handler
    _handler = fn


def available() -> bool:
    """Is there anything that could carry the press out in this process?"""
    return _handler is not None


def run() -> bool:
    """Carry it out. ``False`` when there is nobody to — a tab launched on its own."""
    if _handler is None:
        return False
    _handler()
    return True

"""The log SINK: where a line goes, and what it is.

Six producers write into one log — the panel itself, the captures, the timers, the
triggers, the robberies, the chat reader — and every one of them can be running while
nobody is looking at a window. So the sink is separate from any widget:

    line ──> LogBus.put ──┬──> the profile's debug.log   (at its severity, under `ui`)
                          ├──> stdout                     (a standalone tab's console)
                          ├──> whoever is tapping         (the phone's feed)
                          └──> the queue ──> LogSpool.pump ──┬──> panel.log (the record)
                                             (the Tk thread) ├──> the history
                                                             └──> a LogPane, if drawn

The widget is deliberately NOT here — nor, since #1391, anywhere the shell can reach.
The pane and the stamped history live in `panel/runtime/log_view.py` and are drawn by
the «Разработка» tab; a profile without it, and a tab launched on its own, keep the
whole of the record in the two files and simply have nothing on screen. Which is why
the queue is drained by the SPOOL and not by a widget: a session with nobody looking
must still write its log and must not grow a queue for ever.

Severity is decided by KEYWORD, not by a level the producer passes in: half the lines
are a child process's own output, so there is nobody to ask. The word lists live here
because the classifier does.
"""
from __future__ import annotations

import logging
import os
import queue
import re
import sys
import time

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# The filter's "show everything" entry. A sentinel rather than the empty string so the
# combobox has something to display.
FILTER_ALL = "*"


# Russian entries are STEMS (`не подтвержд` covers -ено / -ена / -ена за) because the
# ending moves with the noun. Latin ones carry `\b` on purpose: `ok` as a bare substring
# also matches "token" and "look", which is exactly the sort of quiet mis-colouring
# nobody would ever chase down.
def _sev(*words: str) -> "tuple[re.Pattern, ...]":
    return tuple(
        re.compile(w if any("а" <= c.lower() <= "я" or c in "ёЁ" for c in w)
                   else r"\b" + re.escape(w) + r"\b", re.IGNORECASE)
        for w in words)


# Order matters — the bad news first, so a line that says both «ошибка» and «готово»
# reads as the error it is.
SEVERITY_WORDS: tuple[tuple[str, tuple], ...] = (
    ("error", _sev("ошибк", "не удалось", "не поднялся", "не подтвержд",
                   "недоступ", "не читается", "НЕ ГОТОВ",
                   "error", "failed", "cannot", "could not", "traceback",
                   "NOT READY", "unconfirmed")),
    ("warn", _sev("занят", "пауза", "паузу", "пропущ", "останов", "выключен",
                  "стоп", "завершён", "ЧАСТИЧНО",
                  "warn", "skip", "skipped", "stopped", "off", "paused",
                  "PARTLY READY", "spent", "lost")),
    ("ok", _sev("готов", "сохранён", "сохранена", "сохранено", "запущен",
                "включён", "присоединяюсь",
                "ok", "ready", "READY", "done", "saved", "running", "on")),
)


def strip_ansi(line: str) -> str:
    return _ANSI.sub("", line)


def tag_of(line: str) -> str:
    """The producer of a line — the `[secret]` it opens with, or ``""``."""
    clean = strip_ansi(line).lstrip()
    if not clean.startswith("["):
        return ""
    end = clean.find("]")
    return clean[1:end] if end > 1 else ""


def severity_of(line: str) -> str:
    """``"error"`` / ``"warn"`` / ``"ok"`` / ``""`` — how the line is coloured."""
    clean = strip_ansi(line)
    for level, patterns in SEVERITY_WORDS:
        for pattern in patterns:
            if pattern.search(clean):
                return level
    return ""


class LogBus:
    """One door for everything the panel says, and the two files it says it into.

    ``echo`` is for a tab running on its own: with no widget draining the queue, the
    console it was launched from is the only place a line would otherwise be visible.
    """

    def __init__(self, translate=None, debug_logger=None, echo: bool = False) -> None:
        self.q: "queue.Queue[str]" = queue.Queue()
        self._t = translate or (lambda key, **fmt: key)
        self._dbg = debug_logger
        self._echo = echo
        self._fh = None                 # the panel.log handle, held open
        self._taps: list = []           # see `tap` — readers beside the drawing one

    # -- writing ------------------------------------------------------------
    def put(self, line: str) -> None:
        """One raw line — a child's own output, or data already in its own words."""
        self._mirror_debug(line)
        self._mirror_taps(line)
        if self._echo:
            try:
                print(strip_ansi(line), flush=True)
            except Exception:           # noqa: BLE001 — a closed console is not fatal
                pass
        self.q.put(line)

    def say(self, tag: str, key: str, **fmt) -> None:
        """Log one TRANSLATED line under ``[tag]``.

        Everything the panel says goes through here. The raw :meth:`put` stays for the
        lines that are a child's own output (already in the child's language) and for
        the handful that are pure data.
        """
        self.put(f"[{tag}] " + self._t(key, **fmt))

    # -- a second reader ----------------------------------------------------
    def tap(self, func):
        """Be handed every line as well, and return the callable that stops it.

        :meth:`drain` EMPTIES the queue, so there can only ever be one drawing side —
        a second reader would take lines away from the window rather than see a copy
        of them. Anything that watches the log without owning it (the web front-end
        reading over the network, a future notifier) taps instead.

        Called on whatever thread produced the line, inside `put`, so a tap does the
        least possible: append to a deque, set an event. One that raises is dropped
        rather than allowed to fault the producer — a log line must never be the reason
        an errand fails.
        """
        self._taps.append(func)

        def _off() -> None:
            try:
                self._taps.remove(func)
            except ValueError:
                pass
        return _off

    def _mirror_taps(self, line: str) -> None:
        for func in list(self._taps):
            try:
                func(line)
            except Exception:           # noqa: BLE001 — a reader, never the producer
                pass

    def take(self) -> "str | None":
        """The oldest line waiting, or ``None``. What the spool pumps with.

        One line at a time rather than :meth:`drain`'s whole list, because the caller
        writes each of them to three places as it goes (`panel/runtime/log_view.py`) and
        a list handed over in one piece is a list that is lost if the pump raises
        halfway down it.
        """
        try:
            return self.q.get_nowait()
        except queue.Empty:
            return None

    def drain(self) -> list:
        """Every line waiting, oldest first. The drawing side calls this."""
        out = []
        while True:
            try:
                out.append(self.q.get_nowait())
            except queue.Empty:
                return out

    # -- the on-disk mirror -------------------------------------------------
    def open_file(self, path: str) -> None:
        """Point the mirror at a profile's panel.log, keeping the handle.

        Reopening the file for every line was fine at a handful a minute and wasteful
        the moment a tracer streams thousands. Line-buffered append, so the file is
        never behind the widget even if the panel is killed.
        """
        self.close_file()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self._fh = open(path, "a", encoding="utf-8", buffering=1)
        except OSError:
            self._fh = None             # logging must never stop the panel

    def close_file(self) -> None:
        fh, self._fh = self._fh, None
        if fh is not None:
            try:
                fh.close()
            except Exception:           # noqa: BLE001
                pass

    def append_file(self, line: str) -> None:
        """Mirror a line to panel.log.

        The file keeps the full date (the widget only has room for the clock) and is
        never trimmed: the widget is a window onto the session, the file is the record.
        """
        fh = self._fh
        if fh is None:
            return
        try:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {strip_ansi(line)}\n")
        except Exception:
            pass                        # logging must never crash the panel

    # -- the debug log ------------------------------------------------------
    def set_debug_logger(self, logger) -> None:
        self._dbg = logger

    def _mirror_debug(self, line: str) -> None:
        """Mirror one line into the debug log, at its severity, under `ui`."""
        if self._dbg is None:
            return
        clean = strip_ansi(line)
        level = {"error": logging.ERROR,
                 "warn": logging.WARNING}.get(severity_of(clean), logging.INFO)
        try:
            self._dbg.log(level, "%s", clean)
        except Exception:               # noqa: BLE001 — logging must never crash it
            pass

    # -- diagnostics --------------------------------------------------------
    def pending(self) -> int:
        return self.q.qsize()


def stdout_is_a_console() -> bool:
    """Is there anywhere for `echo` to go? (pythonw has no stdout.)"""
    return bool(getattr(sys, "stdout", None))

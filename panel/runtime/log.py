"""The log SINK: where a line goes, and what it is.

Six producers write into one log — the panel itself, the captures, the timers, the
triggers, the robberies, the chat reader — and every one of them can be running while
nobody is looking at a window. So the sink is separate from any widget:

    line ──> LogBus.put ──┬──> the profile's panel.log   (the record)
                          ├──> the profile's debug.log   (at its severity, under `ui`)
                          ├──> stdout                     (a standalone tab's console)
                          └──> the queue, drained by whoever is drawing (the shell)

The widget is deliberately NOT here. «Главная» keeps it, in the container, and a tab
launched on its own has no log pane at all — it shows its own content and leaves the
same record behind in the two files (docs/research/panel-tabs-refactor.md §4.4). A tab
therefore calls `rt.say(...)` without ever knowing which of the two it is running in.

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

    # -- writing ------------------------------------------------------------
    def put(self, line: str) -> None:
        """One raw line — a child's own output, or data already in its own words."""
        self._mirror_debug(line)
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

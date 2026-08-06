"""«Уже поделились» — the tab's half of the shared-with-the-alliance mark (#1245).

A raid worth forwarding is worth forwarding ONCE. After that the people who were going
to march have seen it, and a second post says nothing — so both tables on this tab mark
the tiles that have already been shared, and the mark is not the panel's private
memory of its own button: it is the fact, whoever produced it.

There are two producers, and this class is the reader of both:

* **the panel**, when its own «Поделиться» lands — :meth:`mark_panel`, called from the
  tab's `_share_done`;
* **the game**, whenever anyone presses share in the client — the player included. That
  broadcast is on the wire (`push.alliance.share.mission.add`), and the standing list of
  what is currently shared arrives on login (`get.alliance.share.mission.list`); the two
  capture children this tab already runs — «Мониторинг» (`secret_task_capture.py`) and
  the auto-loot listener (`secret_share_autoloot.py`) — decode them and append a mark of
  their own.

That is why the store is a file rather than a dict: the writers are separate processes.
`tools/lib/share_marks.py` owns its shape; this class holds the profile's path, reloads
it when it moves, and answers the one question the rows ask.

**A reload is a file stat, not a read.** :meth:`apply` runs on the tab's per-second tick
for both tables, so it checks the mtime and only parses when the file has actually
changed — a tab sitting with nothing being shared costs one `os.stat` a second.
"""
from __future__ import annotations

import os

# The runtime first — importing it is what puts the repo's `tools/lib` on sys.path, and
# `share_marks` is one of the bare-name modules that live there (see capture.py, whose
# import order is load-bearing for the same reason).
from ...runtime.paths import TOOLS       # noqa: F401  (imported for its side effect)

import share_marks                        # noqa: E402  (see above)


class SharedMarks:
    """Which of this profile's secret tasks have already been shared."""

    def __init__(self, rt) -> None:
        self.rt = rt
        self._marks: dict = {}
        self._stamp = None                # (mtime, size) of the file as last parsed
        self._path = None                 # the profile whose file `_marks` came from

    # -- the file ------------------------------------------------------------
    def path(self) -> str:
        return self.rt.profiles.secret_shared_json()

    def reload(self, force: bool = False) -> bool:
        """Re-read the store if it moved. Returns whether the marks changed.

        A profile switch changes the path under us, so the path is part of what is
        compared — otherwise the new profile would be shown the old one's marks until
        somebody happened to share something.
        """
        path = self.path()
        try:
            info = os.stat(path)
            stamp = (info.st_mtime_ns, info.st_size)
        except OSError:
            stamp = None
        if not force and path == self._path and stamp == self._stamp:
            return False
        self._path, self._stamp = path, stamp
        before = set(self._marks)
        self._marks = share_marks.load(path) if stamp is not None else {}
        return set(self._marks) != before

    def clear(self) -> None:
        """Forget what was loaded — the profile switched, or the tab is closing."""
        self._marks, self._stamp, self._path = {}, None, None

    # -- the question a row asks ---------------------------------------------
    def has(self, uuid) -> bool:
        return str(uuid) in self._marks

    def via(self, uuid) -> str:
        """Where the mark came from — `share_marks.VIA_PANEL` / `VIA_GAME`, or ""."""
        record = self._marks.get(str(uuid))
        return str(record.get("via") or "") if record else ""

    def apply(self, rows) -> bool:
        """Stamp `row["shared"]` on every row of a grid; return whether any flipped.

        The tables call this before they draw. A flip is what makes a tick redraw
        rather than only repaint the countdown, so a task shared in the game while the
        panel sat open appears marked within the second, with nobody pressing anything.
        """
        self.reload()
        changed = False
        for key, row in (rows or {}).items():
            was = bool(row.get("shared"))
            now = self.has(row.get("uuid") or key)
            if was != now:
                row["shared"] = now
                changed = True
        return changed

    # -- the panel's own share -----------------------------------------------
    def mark_panel(self, uuid) -> bool:
        """Record a share the panel just made. Returns whether it was written.

        Appended like any other, so the fact reads the same afterwards whichever side
        produced it — and kept in memory straight away, because the tab redraws the row
        before the next reload would have noticed the file.
        """
        key = str(uuid or "")
        if not key:
            return False
        ok = share_marks.mark(self.path(), key, share_marks.VIA_PANEL)
        self._marks[key] = {"uuid": key, "via": share_marks.VIA_PANEL,
                            "ts": share_marks.now_ms(), "uid": ""}
        return ok

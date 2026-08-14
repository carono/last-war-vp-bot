"""«Занятость» — the busy debugger, drawn on «Разработка» (#1392).

WHAT IT IS FOR. A panel that is not doing what it was told looks exactly like a panel
that is idle: the log is quiet because nothing HAPPENED, the window redraws because the
Tk thread is fine, and the errand somebody is waiting for is sitting behind a claim
another profile took four minutes ago. This block answers, at one instant, «чем панель
занята и кто кого ждёт» — the threads at work, the queue behind them, the claims and who
is queued for them, the timers and what is overdue, and a short list of the signs a jam
leaves.

WHERE THE DATA COMES FROM: `panel/runtime/busy.py::snapshot`, which reads dicts under
locks that are already held for microseconds and touches neither Tk nor the game. This
file is the drawing and nothing else — it composes lines out of locale keys, and the
whole block is one `Text` rewritten in place, because forty labels re-configured once a
second is exactly the Tk cost the panel spent #1226 getting rid of.

THREE THINGS IT DELIBERATELY DOES NOT DO:

* **it does not watch when nobody is looking.** The refresh is armed on `on_show` and
  disarmed on `on_hide`, and the tick is skipped while the tick box is off. An
  observation that runs all day to describe a fault that lasts a minute is a cost with no
  reader;
* **it does not ask the game anything.** The whole point is to explain a panel that is
  not answering — a read would join the very queue being measured;
* **it does not go to the phone.** «Разработка» declares `WEB_SCREEN = False`, and that
  is the tab's standing exception rather than a new one (`CLAUDE.md`,
  `docs/panel-tabs.md`). What a jam looks like from a phone is a different question and
  is asked of the person before anything is drawn.

The claim registry and the thread list are process-wide on purpose — that is what they
ARE (`panel/runtime/claims.py`) — so every row of them says whose it is and the rows of
the profile doing the looking are marked and sorted first.
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from ..runtime import busy as busymod

#: How often the block re-reads while it is being watched. A second is the resolution of
#: everything it shows (a step, a wait, a queue) and one snapshot is dict reads.
REFRESH_MS = 1000

#: The name the refresh chain is armed under. One chain per name (panel/runtime/tick.py).
TICK = "develop_busy"

#: How many rows one section may draw before it says «…and N more». A debugger that
#: needs scrolling to reach the third section is a debugger nobody reads to the end.
ROWS = 8

#: The urgency levels, as locale keys — `claims.BACKGROUND` / `EXPRESS` / `HUMAN`.
LEVELS = {0: "busy.level.background", 1: "busy.level.express", 2: "busy.level.human"}

#: How much of a DSL step is shown. A step is the line as the recipe wrote it, and a
#: `READ_LUA` step is a whole Lua chunk — measured live at 1 700 characters, which is
#: forty lines of the block for one row and every other section pushed off the screen.
#: What identifies the step is its beginning, so the beginning is what is kept.
STEP_CHARS = 110


def _step(text: str) -> str:
    """One step, short enough to read beside the others. Data, so it is cut, not said."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= STEP_CHARS else text[:STEP_CHARS - 1] + "…"


class BusyView:
    """The «Занятость» block: a header row, a text panel, and a refresh on a tick.

    Built by :class:`~panel.tabs.develop.DevelopTab`, which owns the page; kept apart in
    its own module so the tab file stays about the sniffer and the scenarios.
    """

    def __init__(self, tab) -> None:
        self.tab = tab
        self.rt = tab.rt
        self._text = None
        self._watch = None
        self._shown = ""                     # what is on screen, to skip a same rewrite
        self._steps = busymod.StepWatch()
        self._visible = False

    # -- drawing --------------------------------------------------------------
    def build(self, parent) -> None:
        box = self.tab.tr(ttk.LabelFrame(parent, padding=8), "busy.frame")
        box.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        bar = ttk.Frame(box)
        bar.pack(fill="x")
        self._watch = tk.BooleanVar(master=self.rt.root, value=True)
        self.tab.tr(ttk.Checkbutton(bar, variable=self._watch,
                                    command=self._on_watch), "busy.watch").pack(
            side="left")
        self.tab.tr(ttk.Button(bar, command=self.refresh), "busy.refresh").pack(
            side="left", padx=(8, 0))
        self.tab.tr(ttk.Button(bar, command=self._copy), "busy.copy").pack(
            side="left", padx=(4, 0))

        self._text = ScrolledText(box, wrap="none", height=16, font=("Consolas", 9))
        self._text.pack(fill="both", expand=True, pady=(6, 0))
        self._text.configure(state="disabled")

        self.tab.tr(ttk.Label(box, foreground="#888", wraplength=660, justify="left"),
                    "busy.hint").pack(anchor="w", pady=(6, 0))
        self.refresh()

    # -- lifecycle ------------------------------------------------------------
    def on_show(self) -> None:
        self._visible = True
        self.refresh()
        self._arm()

    def on_hide(self) -> None:
        self._visible = False
        self.rt.tick.disarm(TICK)

    def shutdown(self) -> None:
        self.rt.tick.disarm(TICK)

    def on_language_change(self) -> None:
        self._shown = ""                     # every line is a key: say them again
        self.refresh()

    def _arm(self) -> None:
        if self._visible and self._watch is not None and self._watch.get():
            self.rt.tick.arm(TICK, REFRESH_MS, self._tick)

    def _on_watch(self) -> None:
        if self._watch.get():
            self._arm()
        else:
            self.rt.tick.disarm(TICK)

    def _tick(self) -> None:
        self.refresh()
        self._arm()

    # -- the reading ----------------------------------------------------------
    def refresh(self) -> None:
        """Take one snapshot and draw it. On the Tk thread, and cheap enough to be."""
        if self._text is None:
            return
        snap = busymod.snapshot(self.rt)
        self._steps.feed(snap)
        text = "\n".join(self.lines(snap))
        if text == self._shown:
            return                           # nothing moved: do not touch the widget
        self._shown = text
        try:
            self._text.configure(state="normal")
            self._text.delete("1.0", "end")
            self._text.insert("1.0", text)
            self._text.configure(state="disabled")
        except tk.TclError:
            pass                             # the tab is going away

    def _copy(self) -> None:
        """Put what is on screen on the clipboard — a jam is usually reported, not fixed."""
        try:
            self.rt.root.clipboard_clear()
            self.rt.root.clipboard_append(self._shown)
        except tk.TclError:
            return
        self.tab.say("panel", "busy.copied")

    # -- the lines ------------------------------------------------------------
    def lines(self, snap: dict) -> list:
        """The whole block as text: sections of `t(key, …)`, in order of suspicion.

        Separate from :meth:`refresh` so a test can read what the debugger would show
        without a window (`tests/test_panel_busy.py`).
        """
        t = self.tab.t
        out: list = []

        def section(key: str, rows: list) -> None:
            out.append(f"== {t(key)} ==")
            out.extend(rows[:ROWS] if rows else [t("busy.none")])
            if len(rows) > ROWS:
                out.append(t("busy.more", count=len(rows) - ROWS))
            out.append("")

        section("busy.section.jam",
                [t(v["key"], **v["fmt"]) for v in busymod.verdicts(snap)])

        runs = []
        for run in snap["runs"]:
            key = "busy.run.stopping" if run.get("asked") else "busy.run"
            runs.append(t(key, name=run["name"], who=run["tag"] or "?",
                          secs=int(run["secs"]), step=_step(run["step"]) or "—"))
        for step in snap["steps"]:
            runs.append(t("busy.step", what=t(step["key"], **step["fmt"]),
                          secs=int(step["secs"])))
        section("busy.section.runs", runs)

        section("busy.section.queue", self._queue_lines(snap.get("queue") or {}))
        section("busy.section.claims", self._claim_lines(snap))
        section("busy.section.timers", self._timer_lines(snap))
        section("busy.section.slowest", self._slow_lines(snap))
        section("busy.section.threads",
                [t("busy.thread", name=row["name"], where=row["where"])
                 for row in snap["threads"]])
        out.append(t("busy.posted", count=int(snap.get("posted", 0))))
        return out

    def _queue_lines(self, queue: dict) -> list:
        t = self.tab.t
        if not queue:
            return [t("busy.queue.off")]
        rows = []
        if queue.get("running"):
            rows.append(t("busy.queue.running", name=queue["running"],
                          secs=int(queue.get("running_secs", 0))))
        if queue.get("express"):
            rows.append(t("busy.queue.express", names=", ".join(queue["express"])))
        for item in queue.get("waiting", []):
            rows.append(t("busy.queue.waiting", name=item["name"],
                          secs=int(item["secs"])))
        if queue.get("held"):
            rows.append(t("busy.queue.held", names=", ".join(queue["held"]),
                          secs=int(queue.get("hold_secs", 0))))
        if not rows:
            rows.append(t("busy.queue.idle" if queue.get("alive")
                          else "busy.queue.off"))
        return rows

    def _claim_lines(self, snap: dict) -> list:
        t = self.tab.t
        rows = []
        for row in snap["claims"]:
            mark = "→ " if row.get("mine") else "  "
            # `lock=`, never `key=`: the words are said through `t(key, **fmt)`, whose
            # own first argument is called `key` — a placeholder of that name collides
            # with it and every one of these lines fails with «multiple values for
            # argument». The same trap `interrupt.asked` walked into with `tag`.
            rows.append(mark + t("busy.claim", lock=_key(row["key"]),
                                 owner=row["owner"], secs=int(row["secs"]),
                                 refused=int(row.get("refused", 0))))
        for row in snap["waiting"]:
            rows.append("  " + t("busy.wait", lock=_key(row["key"]),
                                 owner=row["owner"], secs=int(row["secs"]),
                                 level=t(LEVELS.get(row["level"],
                                                    "busy.level.background"))))
        return rows

    def _timer_lines(self, snap: dict) -> list:
        t = self.tab.t
        rows = []
        for row in snap["timers"]:
            last = time.strftime("%H:%M", time.localtime(row["last"])) if row["last"] \
                else "—"
            key = "busy.timer.overdue" if row["due_in"] < 0 else "busy.timer"
            rows.append(t(key, name=row["name"], secs=int(abs(row["due_in"])),
                          last=last, state=t(f"busy.state.{row['state']}")))
        for row in snap["ticks"]:
            if row["due_in"] < 0:
                rows.append(t("busy.tick.late", name=row["name"],
                              secs=int(-row["due_in"])))
        return rows

    def _slow_lines(self, snap: dict) -> list:
        t = self.tab.t
        rows = [t("busy.slow.run", name=row["name"], who=row.get("tag") or "?",
                  secs=int(row.get("secs", 0)))
                for row in snap["slowest"]]
        rows += [t("busy.slow.step", name=row["name"], step=_step(row["step"]),
                   secs=int(row["secs"]))
                 for row in self._steps.top()]
        return rows


def _key(key) -> str:
    """A claim key as one short word: a client is its port, the foreground is its name."""
    if isinstance(key, tuple):
        return ":".join(str(part) for part in key)
    return str(key)

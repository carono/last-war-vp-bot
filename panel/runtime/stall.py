"""What is holding the Tk thread right now — sampled, from outside it.

A freeze is the one panel fault that leaves no trace of itself. The log says what
HAPPENED, the activity strip says what was STARTED, and neither of them can say what
the main thread was executing during the four seconds the window did not redraw:
whatever it was, it was on the Tk thread, so nothing on the Tk thread could write it
down. Every measurement of a freeze made from inside the freeze — a timer around the
switch, a stopwatch around the build — measures only the call it was wrapped around,
which is why «280 ms per switch» and «панель висит» can both be true at once.

So this watches from a THREAD OF ITS OWN and never touches Tk:

* a heartbeat, armed with `after`, stamps the clock from inside the event loop;
* a sampler wakes every few milliseconds and looks at the stamp. While the stamp keeps
  moving the loop is alive and nothing is recorded;
* once the stamp is older than `threshold_ms` the loop is BLOCKED — and from then on
  every sample grabs the main thread's stack (`sys._current_frames`), which is the one
  thing that says what is holding it;
* when the beat comes back a report is emitted: how long, what was on screen at the
  time, and the sampled stacks folded by how many samples each one held.

Reading the report: the folded stacks are the answer. A stall whose samples all end in
the same frame is that frame's fault; a stall spread over fifty different leaves is the
sum of a thousand small calls (a page being built, a widget tree being laid out) and the
line to look at is the deepest frame they SHARE, printed as «common».

Nothing here is on by the default panel run. `panel/__main__.py` starts it when
``LW_PANEL_STALL_MS`` is set in the environment — the number of milliseconds a freeze
must last to be worth a report — and the reports go to the debug log and to stderr,
never to the log widget: a diagnostic that draws is a diagnostic that changes what it
measures.

    LW_PANEL_STALL_MS=200 C:\\Python312\\python.exe -m panel

`tools/dev/panel_switch_bench.py` drives the switches for you and prints the same
reports; that is the tool the profile-switch freeze was found with (#1211).
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from collections import Counter

#: How often the heartbeat re-arms itself. Small enough that the gap it leaves in a
#: healthy loop (one beat) is well under any threshold worth reporting.
BEAT_MS = 20
#: How often the sampler looks. A stall of 200 ms is then ~20 stacks — enough to tell
#: one heavy call from a thousand light ones.
SAMPLE_MS = 10
#: Frames of one sampled stack kept in the fold. The whole stack is Tk's mainloop plus
#: the panel's; the tail is what says which call it is.
KEEP_FRAMES = 14

#: A thread sitting in one of these is waiting, not competing: it has released Python's
#: lock and cannot be why the Tk thread is slow.
_PARKED = frozenset({"wait", "acquire", "sleep", "select", "poll", "read", "readline",
                     "recv", "recv_into", "accept", "join", "_wait_for_tstate_lock"})


class Stall:
    """One recorded freeze: how long, what was happening, and what held the thread."""

    __slots__ = ("started", "duration", "label", "samples", "_stacks", "_others")

    def __init__(self, started: float, label: str) -> None:
        self.started = started
        self.duration = 0.0
        self.label = label
        self.samples = 0
        self._stacks: Counter = Counter()
        #: What the OTHER threads were running meanwhile, by name. A freeze is not
        #: always the Tk thread's own fault: Python's lock is one, so a worker thread
        #: walking the process list makes every Tk call on the main thread ten to forty
        #: times slower without appearing in its stack at all (#1211). This is the only
        #: way that shows up in a report.
        self._others: Counter = Counter()

    def add(self, stack: tuple, others=()) -> None:
        self.samples += 1
        self._stacks[stack] += 1
        for name, frame in others:
            self._others[(name, frame)] += 1

    @property
    def ms(self) -> int:
        return int(self.duration * 1000)

    def common(self) -> str:
        """The deepest frame every sample shares — the call the whole stall is under."""
        stacks = list(self._stacks)
        if not stacks:
            return ""
        shared = []
        for frames in zip(*stacks):
            first = frames[0]
            if any(f != first for f in frames):
                break
            shared.append(first)
        return shared[-1] if shared else ""

    def top(self, limit: int = 3) -> list:
        """``(samples, stack)`` for the stacks that held the thread longest."""
        return [(n, stack) for stack, n in self._stacks.most_common(limit)]

    def report(self) -> str:
        lines = [f"STALL {self.ms} ms  ({self.samples} samples)"
                 + (f"  while: {self.label}" if self.label else "")]
        common = self.common()
        if common:
            lines.append(f"  common: {common}")
        for n, stack in self.top():
            share = int(100 * n / max(1, self.samples))
            lines.append(f"  {share:3d}% ({n})")
            lines.extend(f"      {frame}" for frame in stack)
        for (name, frame), n in self._others.most_common(3):
            share = int(100 * n / max(1, self.samples))
            lines.append(f"  meanwhile {share:3d}% — {name}: {frame}")
        return "\n".join(lines)


class StallWatch:
    """Sample the Tk thread from outside it and report every freeze it has.

    ``label`` is whatever the panel was doing, set by whoever drives it (`note`); it is
    carried into the report so a stall can be read without a stopwatch beside it.
    """

    def __init__(self, root, *, threshold_ms: int = 250, sample_ms: int = SAMPLE_MS,
                 report=None, keep: int = 200) -> None:
        self._root = root
        self._threshold = threshold_ms / 1000.0
        self._sample = sample_ms / 1000.0
        self._report = report or (lambda text: print(text, file=sys.stderr))
        self._keep = keep
        self._beat = time.monotonic()
        self._main = threading.main_thread().ident
        self._stop = threading.Event()
        self._thread = None
        self._label = ""
        self._armed = None
        #: Every stall this run, newest last — a bench reads them back at the end.
        self.stalls: list = []

    # -- driving -------------------------------------------------------------
    def start(self) -> "StallWatch":
        if self._thread is not None:
            return self
        self._pulse()
        self._thread = threading.Thread(target=self._watch, daemon=True,
                                        name="stall-watch")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._armed is not None:
                self._root.after_cancel(self._armed)
        except Exception:                    # noqa: BLE001 — a watchdog, never the app
            pass
        self._armed = None

    def note(self, label: str) -> None:
        """Name what the panel is about to do, so the next stall says so."""
        self._label = label

    # -- the two halves ------------------------------------------------------
    def _pulse(self) -> None:
        """On the Tk thread: I am alive at this instant. Re-arms itself."""
        self._beat = time.monotonic()
        if self._stop.is_set():
            return
        try:
            self._armed = self._root.after(BEAT_MS, self._pulse)
        except Exception:                    # noqa: BLE001 — the window is going away
            self._armed = None

    def _watch(self) -> None:
        """On our own thread: nothing here may touch Tk, and nothing here does."""
        current: "Stall | None" = None
        while not self._stop.wait(self._sample):
            beat = self._beat
            gap = time.monotonic() - beat
            if gap < self._threshold:
                if current is not None:
                    self._finish(current, beat)
                    current = None
                continue
            if current is None:
                current = Stall(beat, self._label)
            frames = sys._current_frames()
            stack = self._main_stack(frames)
            if stack:
                current.add(stack, self._others(frames))
        if current is not None:
            self._finish(current, self._beat)

    def _finish(self, stall: "Stall", beat: float) -> None:
        stall.duration = beat - stall.started
        self.stalls.append(stall)
        del self.stalls[:-self._keep]
        try:
            self._report(stall.report())
        except Exception:                    # noqa: BLE001 — a report, not the panel
            pass

    def _main_stack(self, frames: dict) -> tuple:
        """The Tk thread's stack, innermost LAST, trimmed to what says anything."""
        frame = frames.get(self._main)
        if frame is None:
            return ()
        try:
            stack = traceback.extract_stack(frame)
        except Exception:                    # noqa: BLE001 — a racing frame
            return ()
        return tuple(f"{_short(f.filename)}:{f.lineno} {f.name}"
                     for f in stack[-KEEP_FRAMES:])

    def _others(self, frames: dict) -> list:
        """``(thread name, innermost frame)`` for every OTHER thread with Python on it.

        Only the innermost frame: what is wanted here is «who else was running», not a
        second traceback per sample. A thread parked in `wait`, `select` or `sleep` is
        not competing for the lock and is left out — otherwise every report would be
        three quarters idle pollers.
        """
        out = []
        living = {t.ident: t.name for t in threading.enumerate()}
        for ident, frame in frames.items():
            if ident == self._main or ident == threading.get_ident():
                continue
            try:
                stack = traceback.extract_stack(frame)
            except Exception:                # noqa: BLE001 — a racing frame
                continue
            if not stack:
                continue
            last = stack[-1]
            if last.name in _PARKED:
                continue
            out.append((living.get(ident, f"thread-{ident}"),
                        f"{_short(last.filename)}:{last.lineno} {last.name}"))
        return out


def _short(path: str) -> str:
    """`…/panel/tabs/chat.py` → `panel/tabs/chat.py`, and leave the rest alone."""
    parts = path.replace("\\", "/").split("/")
    for anchor in ("panel", "tools", "src", "tests"):
        if anchor in parts:
            return "/".join(parts[parts.index(anchor):])
    return parts[-1]


def from_env(root, *, report=None) -> "StallWatch | None":
    """Start a watch if ``LW_PANEL_STALL_MS`` asks for one; else nothing at all."""
    raw = os.environ.get("LW_PANEL_STALL_MS", "").strip()
    if not raw:
        return None
    try:
        threshold = int(raw)
    except ValueError:
        return None
    if threshold <= 0:
        return None
    return StallWatch(root, threshold_ms=threshold, report=report).start()

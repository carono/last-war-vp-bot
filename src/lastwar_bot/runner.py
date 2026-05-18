"""Bot runner — start/stop a background loop that does perception work.

For now the loop is a heartbeat: every `tick_interval` seconds it locates
the Last War window, captures a frame, reports basic stats through the
`on_event` callback, and overwrites a rolling `screenshots/live.png`.

Real activities (mail, radar, …) will plug into `_tick` once the
executor and skill catalogue exist.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import cv2

from .perception.capture import WindowNotFoundError, find_window, grab

EventCallback = Callable[[str], None]


class BotRunner:
    """Runs the bot loop on a background thread. Thread-safe start/stop/restart."""

    def __init__(
        self,
        *,
        window_title: str = "Last War-Survival Game",
        process_name: str = "LastWar.exe",
        tick_interval: float = 5.0,
        screenshot_dir: Path | str = "screenshots",
    ) -> None:
        self.window_title = window_title
        self.process_name = process_name
        self.tick_interval = tick_interval
        self.screenshot_dir = Path(screenshot_dir)

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._on_event: EventCallback | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, on_event: EventCallback | None = None) -> None:
        if self.is_running:
            return
        self._on_event = on_event
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="bot-runner", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            self._thread = None

    def _emit(self, msg: str) -> None:
        cb = self._on_event
        if cb is None:
            return
        try:
            cb(msg)
        except Exception as exc:  # pragma: no cover — defensive
            print(f"[runner] on_event callback raised: {exc!r}")

    def _run(self) -> None:
        self._emit("Bot started.")
        try:
            self.screenshot_dir.mkdir(parents=True, exist_ok=True)
            while not self._stop_event.is_set():
                self._tick()
                # `wait` returns early if stop is set during sleep.
                self._stop_event.wait(self.tick_interval)
        except Exception as exc:
            self._emit(f"Runner crashed: {exc!r}")
            raise
        finally:
            self._emit("Bot stopped.")

    def _tick(self) -> None:
        try:
            info = find_window(self.window_title, self.process_name)
        except WindowNotFoundError as exc:
            self._emit(f"Window not found: {exc}")
            return
        try:
            img = grab(info.hwnd)
        except Exception as exc:
            self._emit(f"Capture failed: {exc!r}")
            return
        height, width = img.shape[:2]
        mean = float(img.mean())
        cv2.imwrite(str(self.screenshot_dir / "live.png"), img)
        self._emit(f"tick: {width}x{height}, mean={mean:.1f}")

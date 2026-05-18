"""Tk control window: Start / Stop the bot, status indicator, live log.

Launch:
    python -m lastwar_bot.ui
"""

from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import scrolledtext, ttk

from .config import AppSettings
from .runner import BotRunner


class BotWindow(tk.Tk):
    POLL_MS = 100

    def __init__(self) -> None:
        super().__init__()
        self.title("Last War Bot")
        self.geometry("720x440")
        self.minsize(560, 320)

        self._settings = AppSettings()
        self._runner = BotRunner()
        self._messages: queue.Queue[str] = queue.Queue()

        self._build_ui()
        self._poll_messages()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ----- layout -----

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(10, 10, 10, 4))
        header.pack(side="top", fill="x")

        ttk.Label(header, text="Status:").pack(side="left")
        self._status_var = tk.StringVar(value="Idle")
        self._status_label = ttk.Label(header, textvariable=self._status_var, foreground="#666")
        self._status_label.pack(side="left", padx=(4, 20))

        ttk.Label(
            header,
            text=f"LLM: {self._settings.llm_provider}   ·   Vision: {self._settings.vision_provider}",
            foreground="#888",
        ).pack(side="left")

        buttons = ttk.Frame(self, padding=(10, 0, 10, 6))
        buttons.pack(side="top", fill="x")

        self._start_btn = ttk.Button(buttons, text="Start", command=self._on_start)
        self._start_btn.pack(side="left")
        self._stop_btn = ttk.Button(buttons, text="Stop", command=self._on_stop, state="disabled")
        self._stop_btn.pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Clear log", command=self._clear_log).pack(side="right")

        log_frame = ttk.LabelFrame(self, text="Log", padding=6)
        log_frame.pack(side="top", fill="both", expand=True, padx=10, pady=(4, 10))
        self._log = scrolledtext.ScrolledText(log_frame, height=14, state="disabled", wrap="word")
        self._log.pack(fill="both", expand=True)

    # ----- event plumbing -----

    def _enqueue(self, msg: str) -> None:
        """Runner thread → UI message queue. Safe to call from any thread."""
        self._messages.put(msg)

    def _poll_messages(self) -> None:
        try:
            while True:
                self._append_log(self._messages.get_nowait())
        except queue.Empty:
            pass
        self.after(self.POLL_MS, self._poll_messages)

    def _append_log(self, line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._log.configure(state="normal")
        self._log.insert("end", f"{stamp}  {line}\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _clear_log(self) -> None:
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    # ----- buttons -----

    def _on_start(self) -> None:
        self._runner.start(on_event=self._enqueue)
        self._set_status("Running", "#2a7a2a")
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")

    def _on_stop(self) -> None:
        self._stop_btn.configure(state="disabled")
        self._set_status("Stopping…", "#8a6a00")
        # Stop on a worker thread so the UI stays responsive.
        threading.Thread(target=self._do_stop, daemon=True).start()

    def _do_stop(self) -> None:
        self._runner.stop()
        self.after(0, self._post_stop)

    def _post_stop(self) -> None:
        self._set_status("Idle", "#666")
        self._start_btn.configure(state="normal")

    def _set_status(self, text: str, color: str) -> None:
        self._status_var.set(text)
        self._status_label.configure(foreground=color)

    def _on_close(self) -> None:
        try:
            self._runner.stop(timeout=2.0)
        finally:
            self.destroy()


def main() -> int:
    BotWindow().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

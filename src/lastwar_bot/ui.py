"""Tk control window: Main and Debug tabs.

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
from .game.skills import navigate
from .perception.capture import (
    MIN_CLIENT_HEIGHT,
    MIN_CLIENT_WIDTH,
    WindowNotFoundError,
    ensure_client_size,
    find_window,
    grab,
)
from .profile import DEFAULT_PROFILE_ID, Profile
from .runner import BotRunner
from .script_engine import run_action

WINDOW_TITLE = "Last War-Survival Game"
PROCESS_NAME = "LastWar.exe"


class BotWindow(tk.Tk):
    POLL_MS = 100

    def __init__(self, profile_id: str = DEFAULT_PROFILE_ID) -> None:
        super().__init__()
        self.title(f"Last War Bot — {profile_id}")
        self.geometry("780x560")
        self.minsize(560, 380)

        self._settings = AppSettings()
        self._profile = Profile.load(profile_id)
        self._runner = BotRunner(profile=self._profile)
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

        ttk.Label(
            header,
            text=f"   ·   Profile: {self._profile.profile_id}",
            foreground="#888",
        ).pack(side="left")

        notebook = ttk.Notebook(self)
        notebook.pack(side="top", fill="x", padx=10, pady=4)
        notebook.add(self._build_main_tab(notebook), text="Main")
        notebook.add(self._build_debug_tab(notebook), text="Debug")

        log_frame = ttk.LabelFrame(self, text="Log", padding=6)
        log_frame.pack(side="bottom", fill="both", expand=True, padx=10, pady=(0, 10))
        self._log = scrolledtext.ScrolledText(log_frame, height=12, wrap="word")
        self._log.pack(fill="both", expand=True)
        self._make_log_readonly()

    def _build_main_tab(self, parent: ttk.Notebook) -> tk.Widget:
        f = ttk.Frame(parent, padding=10)
        self._start_btn = ttk.Button(f, text="Start", command=self._on_start)
        self._start_btn.pack(side="left")
        self._stop_btn = ttk.Button(f, text="Stop", command=self._on_stop, state="disabled")
        self._stop_btn.pack(side="left", padx=(8, 0))
        ttk.Button(f, text="Clear log", command=self._clear_log).pack(side="right")
        return f

    def _build_debug_tab(self, parent: ttk.Notebook) -> tk.Widget:
        f = ttk.Frame(parent, padding=10)

        row1 = ttk.Frame(f)
        row1.pack(side="top", fill="x")
        ttk.Label(row1, text="Current screen:").pack(side="left")
        self._screen_var = tk.StringVar(value="—")
        ttk.Label(
            row1, textvariable=self._screen_var, font=("TkDefaultFont", 10, "bold")
        ).pack(side="left", padx=(6, 12))
        self._detect_btn = ttk.Button(row1, text="Detect", command=self._on_detect)
        self._detect_btn.pack(side="left")

        ttk.Separator(f, orient="horizontal").pack(side="top", fill="x", pady=8)

        row2 = ttk.Frame(f)
        row2.pack(side="top", fill="x")
        self._goto_base_btn = ttk.Button(row2, text="Go to Base", command=lambda: self._navigate("base"))
        self._goto_base_btn.pack(side="left")
        self._goto_world_btn = ttk.Button(row2, text="Go to World", command=lambda: self._navigate("world"))
        self._goto_world_btn.pack(side="left", padx=(8, 0))

        ttk.Separator(f, orient="horizontal").pack(side="top", fill="x", pady=8)

        row3 = ttk.Frame(f)
        row3.pack(side="top", fill="x")
        ttk.Label(
            row3,
            text=f"Resize window if smaller than {MIN_CLIENT_WIDTH}x{MIN_CLIENT_HEIGHT}:",
        ).pack(side="left")
        self._fix_size_btn = ttk.Button(row3, text="Fix window size", command=self._on_fix_size)
        self._fix_size_btn.pack(side="left", padx=(8, 0))

        ttk.Separator(f, orient="horizontal").pack(side="top", fill="x", pady=8)

        row4 = ttk.Frame(f)
        row4.pack(side="top", fill="x")
        ttk.Label(row4, text="Player profile metadata:").pack(side="left")
        self._capture_profile_btn = ttk.Button(
            row4, text="Capture profile", command=self._on_capture_profile,
        )
        self._capture_profile_btn.pack(side="left", padx=(8, 0))

        return f

    # ----- logging plumbing -----

    def _enqueue(self, msg: str) -> None:
        """Worker-thread → UI message queue. Thread-safe."""
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
        self._log.insert("end", f"{stamp}  {line}\n")
        self._log.see("end")

    def _clear_log(self) -> None:
        self._log.delete("1.0", "end")

    def _make_log_readonly(self) -> None:
        """Allow text selection and Ctrl+C / Ctrl+A but block any editing.

        Tk's ``state='disabled'`` makes the widget completely inert
        (no selection either). To preserve copy/paste UX while keeping
        the buffer immutable from the keyboard, we leave state='normal'
        and short-circuit every keystroke that isn't a navigation or
        copy hotkey.
        """
        navigation_keys = {
            "Left", "Right", "Up", "Down",
            "Home", "End", "Prior", "Next",
            "Shift_L", "Shift_R", "Control_L", "Control_R",
            "Alt_L", "Alt_R", "Meta_L", "Meta_R",
        }

        def block_edits(event: tk.Event) -> str | None:  # type: ignore[type-arg]
            if event.keysym in navigation_keys:
                return None
            # event.state & 0x4 is the Control modifier on Tk.
            if (event.state & 0x4) and event.keysym.lower() in ("c", "a"):
                return None
            return "break"

        self._log.bind("<Key>", block_edits)

        menu = tk.Menu(self._log, tearoff=0)
        menu.add_command(
            label="Copy",
            command=lambda: self._log.event_generate("<<Copy>>"),
        )
        menu.add_command(
            label="Select all",
            command=lambda: (self._log.tag_add("sel", "1.0", "end-1c"), "break"),
        )
        menu.add_separator()
        menu.add_command(label="Clear", command=self._clear_log)

        def popup(event: tk.Event) -> None:  # type: ignore[type-arg]
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        self._log.bind("<Button-3>", popup)

    # ----- main tab handlers -----

    def _on_start(self) -> None:
        self._runner.start(on_event=self._enqueue)
        self._set_status("Running", "#2a7a2a")
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")

    def _on_stop(self) -> None:
        self._stop_btn.configure(state="disabled")
        self._set_status("Stopping...", "#8a6a00")
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

    # ----- debug tab handlers -----

    def _on_detect(self) -> None:
        self._set_debug_buttons(False)
        threading.Thread(target=self._do_detect, daemon=True).start()

    def _do_detect(self) -> None:
        try:
            info = find_window(WINDOW_TITLE, PROCESS_NAME)
        except WindowNotFoundError as exc:
            self._enqueue(f"Detect: window not found — {exc}")
            self.after(0, lambda: self._set_debug_buttons(True))
            return
        img = grab(info.hwnd)
        screen = navigate.identify_screen(img)
        text = screen or "unknown"
        self.after(0, lambda: self._screen_var.set(text))
        self._enqueue(f"Detect: current screen = {text}")
        self.after(0, lambda: self._set_debug_buttons(True))

    def _navigate(self, target: str) -> None:
        self._set_debug_buttons(False)
        threading.Thread(target=lambda: self._do_navigate(target), daemon=True).start()

    def _do_navigate(self, target: str) -> None:
        """Run the high-level navigation script for `target` ('base' or 'world').

        Scripts live in src/lastwar_bot/actions/*.md and are executed by
        the DSL interpreter in script_engine.py. The Python `navigate`
        module is still used internally (identify_screen, templates) but
        the orchestration is now declarative.
        """
        try:
            info = find_window(WINDOW_TITLE, PROCESS_NAME)
        except WindowNotFoundError as exc:
            self._enqueue(f"Navigate->{target}: window not found — {exc}")
            self.after(0, lambda: self._set_debug_buttons(True))
            return
        action_name = "go_to_base" if target == "base" else "go_to_world"
        ok = run_action(action_name, info.hwnd, on_event=self._enqueue, profile=self._profile)
        # Refresh the indicator from the final state.
        try:
            final_screen = navigate.identify_screen(grab(info.hwnd)) or "unknown"
        except Exception:
            final_screen = "unknown"
        self.after(0, lambda: self._screen_var.set(final_screen))
        self._enqueue(f"Action {action_name}: {'OK' if ok else 'FAILED'}; screen now = {final_screen}")
        self.after(0, lambda: self._set_debug_buttons(True))

    def _on_fix_size(self) -> None:
        self._set_debug_buttons(False)
        threading.Thread(target=self._do_fix_size, daemon=True).start()

    def _do_fix_size(self) -> None:
        try:
            info = find_window(WINDOW_TITLE, PROCESS_NAME)
        except WindowNotFoundError as exc:
            self._enqueue(f"Fix size: window not found — {exc}")
            self.after(0, lambda: self._set_debug_buttons(True))
            return
        try:
            result = ensure_client_size(info.hwnd)
        except Exception as exc:  # pragma: no cover — defensive
            self._enqueue(f"Fix size: failed — {exc!r}")
            self.after(0, lambda: self._set_debug_buttons(True))
            return
        if result.resized:
            self._enqueue(
                f"Fix size: resized {result.before[0]}x{result.before[1]} -> "
                f"{result.after[0]}x{result.after[1]} (target {result.target[0]}x{result.target[1]})"
            )
        else:
            self._enqueue(
                f"Fix size: no action — current {result.before[0]}x{result.before[1]} "
                f"already >= {MIN_CLIENT_WIDTH}x{MIN_CLIENT_HEIGHT}"
            )
        self.after(0, lambda: self._set_debug_buttons(True))

    def _on_capture_profile(self) -> None:
        self._set_debug_buttons(False)
        threading.Thread(target=self._do_capture_profile, daemon=True).start()

    def _do_capture_profile(self) -> None:
        try:
            info = find_window(WINDOW_TITLE, PROCESS_NAME)
        except WindowNotFoundError as exc:
            self._enqueue(f"Capture profile: window not found — {exc}")
            self.after(0, lambda: self._set_debug_buttons(True))
            return
        ok = run_action("capture_profile", info.hwnd, on_event=self._enqueue, profile=self._profile)
        self._enqueue(
            f"Capture profile: {'OK' if ok else 'FAILED'}; "
            f"profile.data now has: {list(self._profile.data) or '(empty)'}"
        )
        self.after(0, lambda: self._set_debug_buttons(True))

    def _set_debug_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (
            self._detect_btn, self._goto_base_btn, self._goto_world_btn,
            self._fix_size_btn, self._capture_profile_btn,
        ):
            btn.configure(state=state)

    # ----- lifecycle -----

    def _on_close(self) -> None:
        try:
            self._runner.stop(timeout=2.0)
        finally:
            self.destroy()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Last War Bot control UI.")
    parser.add_argument(
        "--profile", default=DEFAULT_PROFILE_ID,
        help="Profile id to load (default: %(default)s). Stored in ./profiles/<id>.json.",
    )
    args = parser.parse_args()

    BotWindow(profile_id=args.profile).mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

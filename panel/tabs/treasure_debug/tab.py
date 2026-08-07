"""The «Сокровища» debug page: every treasure message the game sees, as it sees it.

«Мне нужна страница для отладки — я хочу видеть все сообщения, которые поймает игра: что
есть сокровища, что отряд был отправлен, что сокровище было взято.» That is three
moments of one ability, and none of them can be recorded the ordinary way: a world-map
treasure is out for minutes, the alliance digs it together, and by the time anybody has
started the sniffer pair the chest is gone. So this page is the other shape of the same
tool — something that is ALREADY listening, and keeps what it heard until somebody
looks.

**Nothing here presses anything in the game.** The two switches arm and disarm a hook on
the client's own network doors; the feed is drained and drawn. No march goes out from
this page and no chest is claimed from it — the ability itself is
`actions/dev/work_treasure.md`, and it has its own home on «Командный пункт».

**Where the messages are kept, and why not here.** The ring lives in the game VM
(`lua_actions`, «The watcher»), so a panel restart, a profile switch or a closed window
loses nothing. This page's own ring is the second copy, for what a GAME restart would
wipe. Between the two there is no moment where a message exists in one place only, which
is what «не терять сообщения, если человек не смотрит» actually asks for.

**It is EAGER on purpose**, which almost nothing is. The drain has to run whether or not
this page is the one on screen — a feed that only fills while you are looking at it is
the exact failure the person named. It costs nothing when the watch is off: no timer, no
game call, one built page on a tab that is off by default anyway.

**Why it is its own tab and not a block on «Разработка».** It is gated by the same
switch — `IN_DEVELOPMENT`, so the page does not exist unless «Разработка» is on
(`panel.tabs.DEV_TAB`, #1273) — and it opens on its own with
`python -m panel.tabs.treasure_debug`, which a block inside another tab cannot. That is
the whole rule in `docs/panel-tabs.md`: a new page is a plugin, and «Разработка» is the
shell for the sniffers rather than a place to put things.

**The phone gets the same page**, because the rule is that an edit travels both ways in
the same commit (`CLAUDE.md`) — the same feed, the same two switches, the same filter, in
`web_view` / `web_press`. It is not LISTED for a phone yet only because an
`IN_DEVELOPMENT` tab hands out no screen at all; the day the mark comes off, the screen
is already there rather than a thing somebody has to remember.

**And what is on it is the ACCOUNT's** — uuids, servers, coordinates, alliance tags. That
is exactly why it belongs on screen and in `results/` (git-ignored) and nowhere near a
commit. A line pasted into an issue, a fixture or a doc gets its values replaced with
invented ones of the same shape FIRST (`CLAUDE.md`).
"""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import messagebox, ttk

from ...runtime.paths import repo_rel
from ...widgets import font as ui_font, tk_stringvar
from ..base import PanelTab
from . import model as modelmod

import run_output       # noqa: E402  (results/<subdir>/<stamp>_… — the saved fragment)

#: How a kind is drawn. A glyph and a colour: the glyph needs no translating, the colour
#: is what makes the three moments findable in a feed that scrolls.
_LOOK = {
    modelmod.FOUND: ("◆", "#1976d2"),
    modelmod.MARCH: ("▶", "#f57c00"),
    modelmod.TAKEN: ("★", "#388e3c"),
    modelmod.OTHER: ("·", "#888888"),
}

_GREY = "#888888"


class TreasureDebugTab(PanelTab):
    """The treasure feed: arm the watch, drain it, read it, keep a piece of it."""

    ID = "treasure_debug"
    TITLE_KEY = "tab.treasure_debug"
    ORDER = 340
    #: A developer's page. Off in a fresh profile, and hidden entirely unless
    #: «Разработка» is on — it arms a hook inside the client, which is not something an
    #: ordinary panel should be able to do by clicking around.
    DEFAULT_ENABLED = False
    IN_DEVELOPMENT = True
    PREFERRED_SIZE = "900x640"
    LOCALE_NS = ("treasure_debug",)
    #: The client, to hook and to drain; the scenarios, to do both WITH.
    NEEDS = frozenset({"daemon", "actions"})
    WEB_SCREEN = True
    #: The drain must run while somebody is looking at another tab entirely — see the
    #: module docstring. Nothing starts until the watch is switched on.
    EAGER = True
    SETTINGS: dict = {}

    #: How often the ring in the game is drained while the watch is on. The game-side
    #: ring holds 400, and a treasure session is tens of messages — two seconds is far
    #: more often than it needs and still cheap (one round trip, ~0.15 s).
    DRAIN_MS = 2_000
    #: A drain that reports `more` is followed immediately by another rather than waiting
    #: out the period: the cap is a line-length limit, not a rate limit.
    AGAIN_MS = 150
    #: What the page keeps of its own. The game's ring is the one that must not overflow.
    RING = 2000

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        #: The panel's copy of the feed.
        self._ring = modelmod.Ring(self.RING)
        #: Is the watch supposed to be on? The persisted answer, and what the timer asks.
        self._want = False
        #: …and wide? Kept beside it because both travel to the game as one press.
        self._wide = False
        #: Which kinds are drawn. All four by default: this is a debug page, and a
        #: filter that starts narrow hides the message somebody opened it to find.
        self._show = dict.fromkeys(modelmod.KINDS, True)
        #: The last drain, for the status line and the phone.
        self._last = None
        self._busy = False
        #: Everything below is a widget and exists only after `build`.
        self._feed = None
        self._status = None
        self._watch_var = None
        self._wide_var = None
        self._show_vars: dict = {}

    # -- the page -----------------------------------------------------------
    def build(self) -> None:
        head = ttk.Frame(self.parent)
        head.pack(fill="x", padx=10, pady=(10, 2))
        self.tr(ttk.Label(head, font=ui_font(size=15, weight="bold")),
                "tab.treasure_debug").pack(side="left")

        self.tr(ttk.Label(self.parent, foreground=_GREY, wraplength=820,
                          justify="left"), "treasure_debug.hint").pack(
            anchor="w", padx=10, pady=(0, 8))

        switches = self.tr(ttk.LabelFrame(self.parent, padding=8),
                           "treasure_debug.watch.frame")
        switches.pack(fill="x", padx=10, pady=(0, 6))
        self._watch_var = tk.BooleanVar(master=self.rt.root, value=self._want)
        self.tr(ttk.Checkbutton(switches, variable=self._watch_var,
                                command=self._toggle_watch),
                "treasure_debug.watch.on").pack(anchor="w")
        self._wide_var = tk.BooleanVar(master=self.rt.root, value=self._wide)
        self.tr(ttk.Checkbutton(switches, variable=self._wide_var,
                                command=self._toggle_wide),
                "treasure_debug.watch.wide").pack(anchor="w", pady=(4, 0))
        self.tr(ttk.Label(switches, foreground=_GREY, wraplength=800,
                          justify="left"), "treasure_debug.watch.hint").pack(
            anchor="w", pady=(6, 0))

        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(0, 4))
        for key in modelmod.KINDS:
            var = tk.BooleanVar(master=self.rt.root, value=self._show[key])
            self._show_vars[key] = var
            glyph, colour = _LOOK[key]
            box = ttk.Frame(bar)
            box.pack(side="left", padx=(0, 10))
            ttk.Label(box, text=glyph, foreground=colour).pack(side="left")
            self.tr(ttk.Checkbutton(box, variable=var, command=self._render),
                    "treasure_debug.kind." + key).pack(side="left")

        self.tr(ttk.Button(bar, command=self.copy_feed),
                "treasure_debug.copy").pack(side="right")
        self.tr(ttk.Button(bar, command=self.save_feed),
                "treasure_debug.save").pack(side="right", padx=(0, 6))
        self.tr(ttk.Button(bar, command=self.clear_feed),
                "treasure_debug.clear").pack(side="right", padx=(0, 6))

        body = ttk.Frame(self.parent)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        self._feed = tk.Text(body, wrap="none", height=20, state="disabled",
                             font=ui_font(size=9))
        scroll = ttk.Scrollbar(body, orient="vertical", command=self._feed.yview)
        self._feed.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self._feed.pack(side="left", fill="both", expand=True)
        for key, (_glyph, colour) in _LOOK.items():
            self._feed.tag_configure(key, foreground=colour)

        self._status = tk_stringvar(self.rt.root)
        ttk.Label(self.parent, textvariable=self._status, foreground=_GREY).pack(
            anchor="w", padx=10, pady=(0, 8))
        self._render()

    # -- lifecycle ----------------------------------------------------------
    def ensure_loaded(self) -> None:
        """Pick the watch back up if the profile had it on — the page is EAGER, so this
        runs at boot and the feed fills whether or not anybody opens the tab."""
        if self._want:
            self._arm()
        self._refresh_status()

    def on_show(self) -> None:
        self._refresh_status()

    def on_language_change(self) -> None:
        self._render()

    def on_profile_switch(self) -> None:
        """A different account is a different game: forget the feed and stop asking.

        The hook itself belongs to the CLIENT, not to the profile, so it is not disarmed
        from here — the new profile's own `ensure_loaded` decides what it wants.
        """
        self._ring.clear()
        self._last = None
        self.rt.tick.disarm("treasure_debug_drain")
        self._render()

    def panic(self) -> None:
        """«Стоп всё»: stop draining. What is on screen stays, and so does the hook —
        removing it is a call into the game, which is the one thing panic must not make."""
        self.rt.tick.disarm("treasure_debug_drain")

    def resume(self) -> None:
        if self._want:
            self._schedule(self.DRAIN_MS)

    def shutdown(self) -> None:
        self.rt.tick.disarm("treasure_debug_drain")

    def config(self) -> dict:
        return {"watch": bool(self._want), "wide": bool(self._wide),
                "show": {k: bool(v) for k, v in self._show.items()}}

    def apply_config(self, raw) -> None:
        if not isinstance(raw, dict):
            return
        self._want = bool(raw.get("watch", False))
        self._wide = bool(raw.get("wide", False))
        shown = raw.get("show")
        if isinstance(shown, dict):
            for key in modelmod.KINDS:
                self._show[key] = bool(shown.get(key, True))
        if self._watch_var is not None:
            self._watch_var.set(self._want)
            self._wide_var.set(self._wide)
            for key, var in self._show_vars.items():
                var.set(self._show[key])
            self._render()

    # -- the two switches ---------------------------------------------------
    def _toggle_watch(self) -> None:
        self.set_watch(bool(self._watch_var.get()))

    def _toggle_wide(self) -> None:
        self._wide = bool(self._wide_var.get())
        if self._want:
            self._arm()                    # re-arm: the flag travels with the press
        self._refresh_status()

    def set_watch(self, on: bool) -> bool:
        """Arm or disarm the hook. Returns whether the scenario was started.

        The answer on screen is the READING the scenario brings back, never this press:
        a client restarted since the last arming has an empty VM and no hook at all, and
        the press returning cleanly would say nothing about that.
        """
        self._want = bool(on)
        if self._watch_var is not None:
            self._watch_var.set(self._want)
        if self._want:
            return self._arm()
        self.rt.tick.disarm("treasure_debug_drain")
        started = self.rt.play_async(modelmod.UNWATCH_ACTION, tag="treasure",
                                     on_result=self._state_back)
        self._refresh_status()
        return started

    def _arm(self) -> bool:
        started = self.rt.play_async(
            modelmod.WATCH_ACTION, {"wide": bool(self._wide)}, tag="treasure",
            on_result=self._state_back, on_done=lambda: self._schedule(self.AGAIN_MS))
        if not started:
            self.say("treasure", "treasure_debug.log.busy")
        self._refresh_status()
        return started

    def _state_back(self, outcome) -> None:
        """What the arming scenario read back — the hook's own account of itself."""
        if outcome is None or not getattr(outcome, "ok", False):
            self.say("treasure", "treasure_debug.log.failed",
                     error=(getattr(outcome, "reason", "") or "?"))
            return
        ctx = getattr(outcome, "ctx", None)
        state = modelmod.parse_state((getattr(ctx, "vars", {}) or {}).get(
            modelmod.STATE_VARIABLE))
        self.say("treasure", "treasure_debug.log.watch",
                 on=state.get("on", 0), wide=state.get("wide", 0),
                 buf=state.get("buf", 0))
        self._refresh_status()

    # -- the drain ----------------------------------------------------------
    def _schedule(self, delay_ms: int) -> None:
        if self._want:
            self.rt.tick.arm("treasure_debug_drain", delay_ms, self._drain)

    def _drain(self) -> None:
        """Take whatever the game has kept since the last time, and draw it."""
        if not self._want or self._busy:
            self._schedule(self.DRAIN_MS)
            return
        self._busy = True
        started = self.rt.play_async(modelmod.READ_ACTION, tag="treasure",
                                     on_result=self._feed_back,
                                     on_done=self._drain_done)
        if not started:                    # something else is driving the game
            self._busy = False
            self._schedule(self.DRAIN_MS)

    def _feed_back(self, outcome) -> None:
        at = time.time()
        if outcome is None or not getattr(outcome, "ok", False):
            self._last = modelmod.Drain(
                error=(getattr(outcome, "reason", "") or "failed"), at=at)
            return
        ctx = getattr(outcome, "ctx", None)
        drain = modelmod.parse((getattr(ctx, "vars", {}) or {}).get(
            modelmod.FEED_VARIABLE), at=at)
        self._last = drain
        if drain.entries:
            self._ring.add(drain.entries)
            self._append(drain.entries)
        if drain.drop:
            #: The game's ring overflowed — say it once, loudly. Silence here would read
            #: as a quiet client, which is the opposite of what happened.
            self.say("treasure", "treasure_debug.log.dropped", count=drain.drop)

    def _drain_done(self) -> None:
        self._busy = False
        self._refresh_status()
        more = getattr(self._last, "more", 0) if self._last is not None else 0
        self._schedule(self.AGAIN_MS if more else self.DRAIN_MS)

    # -- what is on screen --------------------------------------------------
    def _kinds(self) -> tuple:
        """The kinds the filter is letting through, read off the widgets when there are
        any and off the saved answer when the page has never been drawn."""
        if self._show_vars:
            for key, var in self._show_vars.items():
                self._show[key] = bool(var.get())
        return tuple(k for k in modelmod.KINDS if self._show.get(k, True))

    def _append(self, entries) -> None:
        """Add the newest lines without redrawing the whole feed.

        Follows the tail only when the view is ALREADY at the bottom: a person scrolled
        back to read something has said where they want to be, and yanking them down is
        how a live feed becomes unreadable.
        """
        if self._feed is None:
            return
        wanted = set(self._kinds())
        rows = [e for e in entries if e.kind in wanted]
        if not rows:
            return
        try:
            at_end = self._feed.yview()[1] >= 0.999
            self._feed.configure(state="normal")
            for entry in rows:
                self._feed.insert("end", modelmod.line(entry) + "\n", entry.kind)
            self._feed.configure(state="disabled")
            if at_end:
                self._feed.see("end")
        except tk.TclError:                 # the window is going away
            pass

    def _render(self) -> None:
        """Redraw the whole feed — after a filter change, a clear or a language switch."""
        if self._feed is None:
            return
        try:
            self._feed.configure(state="normal")
            self._feed.delete("1.0", "end")
            for entry in self._ring.select(self._kinds()):
                self._feed.insert("end", modelmod.line(entry) + "\n", entry.kind)
            self._feed.configure(state="disabled")
            self._feed.see("end")
        except tk.TclError:
            pass
        self._refresh_status()

    def _refresh_status(self) -> None:
        if self._status is None:
            return
        try:
            self._status.set(self._status_text())
        except tk.TclError:
            pass

    def _status_text(self) -> str:
        last = self._last
        if last is not None and last.error:
            return self.t("treasure_debug.status.error", error=last.error)
        if not self._want:
            return self.t("treasure_debug.status.off", kept=len(self._ring))
        seq = last.seq if last is not None else 0
        return self.t("treasure_debug.status.on", kept=len(self._ring), seen=seq,
                      queued=(last.more if last is not None else 0))

    # -- keeping a piece of it ----------------------------------------------
    def copy_feed(self) -> int:
        """Put the visible feed on the clipboard. Returns how many lines went."""
        rows = self._ring.select(self._kinds())
        text = "\n".join(modelmod.line(e) for e in rows)
        try:
            self.rt.root.clipboard_clear()
            self.rt.root.clipboard_append(text)
        except tk.TclError:
            return 0
        self.say("treasure", "treasure_debug.log.copied", count=len(rows))
        return len(rows)

    def save_feed(self) -> str:
        """Write the visible feed to `results/treasure_watch/` and say where it went.

        `results/` is git-ignored, and that is the point rather than a convenience: every
        line of this is somebody's account (`CLAUDE.md`). The path is reported relative to
        the repo, which is how every other run file is named in the log.
        """
        rows = self._ring.select(self._kinds())
        if not rows:
            self.say("treasure", "treasure_debug.log.nothing")
            return ""
        try:
            path = run_output.new_run_path("treasure_watch", "feed.log")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(modelmod.line(e) for e in rows) + "\n")
        except OSError as exc:
            if self._feed is not None:
                messagebox.showerror(self.t("treasure_debug.save.error.title"),
                                     self.t("treasure_debug.save.error", error=exc))
            return ""
        shown = repo_rel(path)
        self.say("treasure", "treasure_debug.log.saved", count=len(rows), path=shown)
        return shown

    def clear_feed(self) -> None:
        """Empty the page's own copy. The game's ring is untouched — it is the one that
        must survive, and clearing what is on screen is not a reason to lose it."""
        self._ring.clear()
        self._render()

    # -- the phone's copy ---------------------------------------------------
    def web_view(self) -> "dict | None":
        """The same page: the two switches, the filter's four counts, and the tail.

        The tail rather than the whole ring — a phone that asked for two thousand lines
        would be asking for a megabyte of somebody's account over the network every few
        seconds. The window keeps the lot; the phone shows what is happening now, which
        is what it is for.
        """
        kinds = self._kinds()
        rows = self._ring.select(kinds)
        tail = [modelmod.line(e) for e in rows[-40:]]
        counted = [{"label": "treasure_debug.kind." + key,
                    "value": str(len(self._ring.select((key,))))}
                   for key in modelmod.KINDS]
        last = self._last
        state = [{"label": "treasure_debug.web.watch",
                  "value": self.t("treasure_debug.web.on" if self._want
                                  else "treasure_debug.web.off")},
                 {"label": "treasure_debug.watch.wide",
                  "value": self.t("treasure_debug.web.on" if self._wide
                                  else "treasure_debug.web.off")},
                 {"label": "treasure_debug.web.kept", "value": str(len(self._ring))},
                 {"label": "treasure_debug.web.seen",
                  "value": str(last.seq if last is not None else 0)}]
        if last is not None and last.error:
            state.append({"label": "treasure_debug.web.error", "value": last.error})
        cards = [{"title": "treasure_debug.web.state", "rows": state},
                 {"title": "treasure_debug.web.counts", "rows": counted},
                 {"title": "treasure_debug.web.feed",
                  "rows": [{"label": "", "value": one} for one in tail]
                          or [{"label": "", "value": self.t("treasure_debug.web.empty")}]}]
        actions = [{"id": "watch_off" if self._want else "watch_on",
                    "label": ("treasure_debug.web.stop" if self._want
                              else "treasure_debug.web.start")},
                   {"id": "wide", "label": "treasure_debug.watch.wide"},
                   {"id": "save", "label": "treasure_debug.save"},
                   {"id": "clear", "label": "treasure_debug.clear"}]
        return {"cards": cards, "actions": actions, "now": time.time()}

    def web_press(self, action: str, args: dict) -> dict:
        """The window's own four presses, and nothing the window does not have.

        Each one plays a scenario or edits what is on this page — there is no hand-driven
        game step behind any of them, which is what lets them travel to the phone at all
        (`CLAUDE.md`, «A press travels only when the ability is a scenario»).
        """
        if action == "watch_on":
            return {"ok": self.set_watch(True)}
        if action == "watch_off":
            return {"ok": self.set_watch(False)}
        if action == "wide":
            self._wide = not self._wide
            if self._wide_var is not None:
                self._wide_var.set(self._wide)
            if self._want:
                self._arm()
            return {"ok": True, "wide": self._wide}
        if action == "save":
            path = self.save_feed()
            return {"ok": bool(path), "path": path}
        if action == "clear":
            self.clear_feed()
            return {"ok": True}
        return {"error": "unknown"}

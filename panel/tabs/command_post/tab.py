"""The «Секретный командный пункт» tab — the three raids the in-game panel offers.

The Secret Command Post is one screen in the game with three things behind it, and
until now each of them was reachable from a different corner of this panel (or from a
command line only). This tab puts them side by side, one inner page each:

1. **«Операция Призрак»** (`ghost.recon.*`) — the weekly co-op event. The client already
   knows every squad that is out, so the page asks the game for the list, shows each
   squad with the game's own verdict on it («можно ограбить» / «ещё рано» / …), and robs
   the ones it says may be robbed. The five-a-day standing order (the checkbox that used
   to sit on the «Секретки» tab) lives here too.
2. **«Секретный мобильный отряд»** (`alliance.share.mission.*`) — the raids an
   alliancemate shares. There is nothing to poll: a share is a push, so the page listens
   to the wire and a shared mission appears the moment the broadcast crosses it. It can
   watch only, or rob what matches the rule as it lands.
3. **«Скрытые сокровища»** (`detect.event.claim.treasure`) — the chests an alliance's
   detect event drops on the map. The page asks the server for the treasure list, parks
   what came back, and offers each target the two presses it can need: dig it (march) or,
   once it is dug, take it.

What is proven and what is not differs per page, and each says so in its own hint: the
ghost robbery has never had a live squad to fire at (the event runs one day a week), the
shared-mission listener is the panel's own auto-loot path, and no live detect event has
put a treasure on the map yet — so the treasure page's dig/claim are built and compile
in the live VM but have never completed a round trip. See docs/research/ghost-recon-steal.md,
docs/research/secret-task-steal.md and docs/research/world-treasures.md.

Kept Tk-thin the way the other data tabs are: every game round trip runs on a background
thread and degrades gracefully — no daemon, no game, or a manager that is not loaded yet
leaves a page empty and never crashes the panel.
"""
from __future__ import annotations

import os
import re
import threading
import tkinter as tk
from tkinter import ttk

from ...runtime.paths import TOOLS
from ...widgets import (NumericEntry, ScrollableFrame, tk_stringvar,
                        font as ui_font)
from ..base import PanelTab
from .ghost import GhostOrder

#: Marker every chunk in tools/lib/lua_actions.py logs under.
MARKER = "ACT"

# ANSI colour codes a child's output carries — stripped before a line is parsed.
ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Row colours: the green a target that can be acted on right now is drawn in, the amber
# of one that is merely waiting, and the panel's usual muted grey.
READY_COLOR = "#4fe08a"
WAIT_COLOR = "#e0a84f"
DIM = "#888"

STAR_GLYPH = "⭐"
GHOST_GLYPH = "🪖"
SHARE_GLYPH = "📣"
TREASURE_GLYPH = "💰"

# `GhostreconPointStealType` → the locale key that spells it out. Same four values as
# lua_actions.GHOST_STEAL_NAMES, translated instead of logged.
GHOST_STATE_KEYS = {
    1: "cmdpost.ghost.state.preview",
    2: "cmdpost.ghost.state.can",
    3: "cmdpost.ghost.state.no_steal",
    4: "cmdpost.ghost.state.not_shown",
}

# The tail of a `secret_share_autoloot.py` line, whichever verdict it carries:
#   «… * lvl 7  #946  cfg 60000701  uuid 1394584906709054020»
# The tool prints the same label for a match and for a mission left alone, so one
# pattern reads both and the «SHARE MATCH» prefix is what tells them apart.
SHARE_LINE = re.compile(
    r"lvl\s+(?P<lvl>\d+|\?)\s+#(?P<srv>\d+)\s+cfg\s+(?P<cfg>\S+)\s+uuid\s+(?P<uuid>\d+)")

# How long to wait before re-reading the ghost list after a robbery was handed to the
# standalone tool — it spawns a child that walks the VM a few times.
GHOST_RERE_MS = 9000

# How long a map scan listens, and how often it flushes its checkpoint. A tile only
# crosses the wire while the map moves, so the window has to be long enough for the
# «Автообъезд карты» sweep (or a person) to pan somewhere — but it is a window, not a
# standing capture: the scan is a button, and a button that never ends is a leak.
SCAN_SECONDS = 180
SCAN_INTERVAL = 5
# Where the two scan children live, relative to tools/.
GHOST_SCAN_SCRIPT = os.path.join("dev", "secret_mission_capture.py")
TREASURE_SCAN_SCRIPT = os.path.join("dev", "treasure_capture.py")

# Squads a treasure dig may be sent with, and the one preselected.
TREASURE_SQUADS = (1, 2, 3)


def _int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _level_text(value) -> str:
    """A saved level bound as the box shows it: a number, or blank for «no bound».

    A profile is a file a person may have edited, so anything that is not a whole
    number reads as blank — an unreadable bound must widen nothing.
    """
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value) if value > 0 else ""
    text = str(value).strip() if value is not None else ""
    return text if text.isdigit() else ""


def _short(uuid) -> str:
    """The last 8 digits of a uuid — its tail is what tells two targets apart."""
    s = str(uuid)
    return "…" + s[-8:] if len(s) > 8 else s


def _fields(line: str, needle: str) -> dict:
    """`{key: value}` of the `k=v` tokens that follow `needle` on a marker line."""
    _head, sep, tail = line.partition(needle)
    if not sep:
        return {}
    out = {}
    for token in tail.split():
        key, sep2, value = token.partition("=")
        if sep2:
            out[key] = value
    return out


class _Pane:
    """One inner page: a header with a «Обновить» button, a status line and a list.

    Subclasses fill :meth:`build` (UI), :meth:`fetch` (background — returns whatever the
    page needs, or raises) and :meth:`render` (Tk thread, paints it). The load is lazy:
    the tab calls :meth:`ensure_loaded` the first time the page is shown, so a panel that
    never opens this tab never touches the game.
    """

    #: Locale keys for the page's title and its explanatory line under the header.
    TITLE_KEY = ""
    HINT_KEY = ""
    #: The `[tag]` this page's lines are logged under.
    LOG_TAG = "panel"

    def __init__(self, rt, tab, parent) -> None:
        self.rt = rt
        self.tab = tab                 # the page above, for the things a page shares
        self.parent = parent
        self._loaded = False
        self._busy = False
        # The map-scan child, while one is listening (pages that offer a scan).
        self._scan_child = None
        self._scan_btn = None
        self._status_var = tk_stringvar(self.rt.root)
        self._info_var = tk_stringvar(self.rt.root)
        self.build()

    def after(self, func) -> None:
        """Run ``func`` on the Tk thread; a window that has gone simply drops it."""
        try:
            self.rt.root.after(0, func)
        except (tk.TclError, RuntimeError):
            pass

    def evaluator(self):
        """This profile's warm-daemon evaluator (raises if there is no daemon)."""
        return self.rt.game.evaluator()

    # -- lifecycle ----------------------------------------------------------
    def ensure_loaded(self) -> None:
        if not self._loaded:
            self._loaded = True
            self.refresh()

    def refresh(self) -> None:
        """Re-read the page off the game, on a background thread. Coalesces."""
        if self._busy:
            return
        self._busy = True
        self._status("cmdpost.loading")
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        try:
            data = self.fetch()
        except Exception:              # noqa: BLE001 — a failed read is an empty page
            data = None
        self.after(lambda: self._finish(data))

    def _finish(self, data) -> None:
        self._busy = False
        if data is None:
            self._status("cmdpost.no_game")
            return
        try:
            self.render(data)
        except Exception:              # noqa: BLE001 — never let a paint kill the panel
            self._status("cmdpost.no_game")

    # -- the shapes every page shares ---------------------------------------
    def _header(self):
        """Title + «Обновить» + status line; returns the frame the body goes in."""
        bar = ttk.Frame(self.parent)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.rt.tr(ttk.Label(bar, font=ui_font(size=14, weight="bold")),
                     self.TITLE_KEY).pack(side="left")
        self.rt.tr(ttk.Button(bar, width=12, command=self.refresh),
                     "tabx.refresh").pack(side="right")
        ttk.Label(bar, textvariable=self._status_var, foreground=DIM).pack(
            side="right", padx=8)
        if self.HINT_KEY:
            self.rt.tr(ttk.Label(self.parent, foreground=DIM, wraplength=760,
                                   justify="left"), self.HINT_KEY).pack(
                anchor="w", padx=10, pady=(0, 6))
        body = ttk.Frame(self.parent)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        return body

    def _list(self, parent):
        """The scrolling list every page paints its targets into."""
        scroll = ScrollableFrame(parent)
        scroll.pack(fill="both", expand=True)
        return scroll

    def _clear_list(self) -> None:
        for child in self._scroll.winfo_children():
            child.destroy()

    def _empty(self, key: str) -> None:
        self.rt.tr(ttk.Label(self._scroll, foreground=DIM), key).pack(
            anchor="w", pady=6)

    # -- the map scan -------------------------------------------------------
    # Two of the three pages find their targets by *panning the map*: a ghost-recon
    # squad and a treasure are both `world.get.block` tiles, handed to whoever pans
    # over them and to nobody else. So the scan is a passive capture child, exactly
    # like the «Секретки» monitor — it writes a checkpoint this page then merges.
    # Nothing pans by itself here: «Автообъезд карты» on the «Секретки» tab is what
    # moves the camera, and each page's hint says so.

    def _scan_toggle(self, script: str, checkpoint: str, extra=()) -> None:
        """The «Сканировать» button: start a listening window, or stop it early."""
        if self._scan_child is not None:
            self._scan_stop()
        else:
            self._scan_start(script, checkpoint, extra)

    def _scan_start(self, script: str, checkpoint: str, extra=()) -> None:
        cmd = [self.rt.children.python(), "-u", os.path.join(TOOLS, script),
               "--json", checkpoint,
               "--seconds", str(SCAN_SECONDS),
               "--interval", str(SCAN_INTERVAL), *extra]
        child = self.rt.children.spawn(self.LOG_TAG, cmd, on_exit=self._scan_ended)
        if not child.start():
            return
        self._scan_child = child
        self._scan_label("cmdpost.scan_stop")
        self._log("cmdpost.scan_on", n=SCAN_SECONDS)

    def _scan_stop(self) -> None:
        child, self._scan_child = self._scan_child, None
        if child is not None:
            child.stop()
            self._scan_label("cmdpost.scan")
            self._log("cmdpost.scan_off")

    def _scan_ended(self) -> None:
        """The window ran out (or the child died): merge what it wrote."""
        self._scan_child = None
        self._scan_label("cmdpost.scan")
        self.refresh()

    def _scan_label(self, key: str) -> None:
        if self._scan_btn is not None:
            try:
                self._scan_btn.configure(text=self.rt.t(key))
            except Exception:          # noqa: BLE001 — the widget may be gone
                pass

    def shutdown(self) -> None:
        """Stop whatever this page has running. Subclasses extend, never replace."""
        self._scan_stop()

    def restart(self) -> None:
        """Profile switched: a scan captures for one client, so it does not carry."""
        self._scan_stop()

    # -- talking to the panel (safe from any thread) ------------------------
    def _status(self, key: str, **fmt) -> None:
        text = self.rt.t(key, **fmt) if key else ""
        self.after(lambda: self._status_var.set(text))

    def _info(self, key: str, **fmt) -> None:
        text = self.rt.t(key, **fmt) if key else ""
        self.after(lambda: self._info_var.set(text))

    def _log(self, key: str, **fmt) -> None:
        self.after(lambda: self.rt.say(self.LOG_TAG, key, **fmt))

    # -- subclass hooks -----------------------------------------------------
    def build(self) -> None:            # pragma: no cover - overridden
        raise NotImplementedError

    def fetch(self):                    # pragma: no cover - overridden
        raise NotImplementedError

    def render(self, data) -> None:     # pragma: no cover - overridden
        raise NotImplementedError


# ---------------------------------------------------------------------------
class GhostReconPane(_Pane):
    """«Операция Призрак» — the weekly co-op event's squads, and robbing them.

    No map scan and no capture: `ghost.recon.get.task.list` hands the client every squad
    that is out, so «Обновить» asks for that list, prints each squad with the game's own
    `GhostreconPointStealType` verdict, and lights the «Ограбить» button only on the ones
    the game itself calls robbable. Six days a week the event is shut, the list is empty
    and every press is held — which the header says in as many words rather than looking
    broken.

    The robbery is one message (`ghost.recon.steal {uuid, ownerServer}`), gated in the VM
    on the open day and on the five-a-day budget, so a doomed press never reaches the
    wire. It has never been fired at a live squad — see the module docstring.
    """

    TITLE_KEY = "cmdpost.ghost.title"
    HINT_KEY = "cmdpost.ghost.hint"
    LOG_TAG = "ghost"

    def __init__(self, rt, tab, parent) -> None:
        # Created before `build`, which draws the box bound to it — and read by the
        # profile load, which happens whether or not the page has ever been shown.
        self.autoloot_var = tk.BooleanVar(master=rt.root, value=False)
        self.order = GhostOrder(rt, self)
        super().__init__(rt, tab, parent)

    def shutdown(self) -> None:
        super().shutdown()
        self.order.stop()

    def build(self) -> None:
        body = self._header()
        self._build_autoloot_bar(body)
        ttk.Label(body, textvariable=self._info_var, foreground=DIM).pack(
            anchor="w", pady=(6, 4))
        act = ttk.Frame(body)
        act.pack(fill="x", pady=(0, 6))
        self._all_btn = self.rt.tr(ttk.Button(act, width=18, command=self._steal_all),
                                     "cmdpost.ghost.steal_all")
        self._all_btn.pack(side="left")
        self._scan_btn = self.rt.tr(ttk.Button(act, width=16, command=self._scan),
                                      "cmdpost.scan")
        self._scan_btn.pack(side="left", padx=(6, 0))
        self._scroll = self._list(body)

    def _scan(self) -> None:
        """Scan the map for `f2 = 29` tiles — the squads the client's own list misses.

        The two sources answer different questions and both are wanted. The client's
        `ghost.recon.get.task.list` knows this alliance's squads in full; the map
        knows whatever has been panned over, including other alliances' — the ones a
        robbery is actually aimed at. So a scan ADDS to the list rather than replacing
        it, and a row says which it came from.
        """
        self._scan_toggle(GHOST_SCAN_SCRIPT, self.rt.profiles.ghost_json())

    def _build_autoloot_bar(self, parent) -> None:
        """The «Операция Призрак» standing order: five robberies a day, unattended.

        The box, the variable behind it and the watcher it starts are all this page's
        (:mod:`panel.tabs.command_post.ghost`). They used to be split three ways — the
        widget on the «Секретки» tab, the var on the app, the loop in the panel.
        """
        box = self.rt.tr(ttk.LabelFrame(parent, padding=8), "ghost.frame")
        box.pack(fill="x")
        self.rt.tr(ttk.Checkbutton(box, variable=self.autoloot_var,
                                   command=self.order.toggle),
                   "ghost.autoloot").pack(side="left")
        self.rt.tr(ttk.Label(box, foreground=DIM, wraplength=520, justify="left"),
                   "ghost.hint").pack(side="left", padx=10)

    # -- reading the game ---------------------------------------------------
    def fetch(self):
        """`(status, targets)` — the event's state and every squad with its verdict.

        Closed day: the list is asked for anyway, because the honest answer to "why is
        this empty" is the status line, not a guess. `robbable` asks the game per squad,
        so this page never second-guesses the client's own rules.
        """
        import ghost_recon_steal as grs
        ev = self.evaluator()
        status = grs.read_status(ev)
        targets = grs.read_targets(ev) if status.get("open") else []
        can = set()
        if targets:
            can = {t.get("uuid") for t in grs.robbable(ev, targets)}
        for t in targets:
            t["can"] = t.get("uuid") in can
            t["scanned"] = False
        targets += self._scanned_targets({str(t.get("uuid")) for t in targets})
        targets.sort(key=lambda t: (not t.get("can"), -t.get("done", 0)))
        return status, targets

    def _scanned_targets(self, known: set) -> list:
        """The scan checkpoint's squads that the client's own list does not carry.

        The game's per-tile gate (`GetPointStealType`) only answers for a squad in
        `taskList`, so a foreign-alliance tile off the map has no verdict from it —
        its readiness is the clock instead (the squad is back and the tile has not
        expired), which is what `GhostReconMission.can_loot` reads. The event-day and
        budget halves still gate the send itself in the VM, and the server has the
        last word either way.

        No checkpoint (a scan never ran) is simply no extra rows.
        """
        import lastwar_proto as proto
        try:
            missions = proto.load_fresh_ghost_recon(self.rt.profiles.ghost_json())
        except Exception:              # noqa: BLE001 — no file, or a half-written one
            return []
        out = []
        for m in missions:
            if m.uuid is None or str(m.uuid) in known or m.empty:
                continue
            out.append({
                "uuid": str(m.uuid), "cfg": m.cfg_id or 0,
                "srv": m.owner_server or m.target_server or 0,
                "x": m.x or 0, "y": m.y or 0,
                "done": m.completion_time or 0, "ends": m.expire_time or 0,
                "looted": m.steal_count,
                # Deliberately NOT the tile's own `state` (f9): that is a different
                # enum from the steal verdict this column shows, and on a ghost tile
                # it reads 3 whether the squad is back or not. A scanned row is
                # labelled off the clock instead — see `_row`.
                "state": None,
                "mine": False, "can": bool(m.can_loot), "scanned": True,
            })
        return out

    def render(self, data) -> None:
        status, targets = data
        self._status("")
        self._info("cmdpost.ghost.info",
                   state=self.rt.t("cmdpost.ghost.open" if status.get("open")
                                     else "cmdpost.ghost.closed"),
                   left=status.get("left", 0), queued=status.get("queued", 0))
        self._clear_list()
        if not targets:
            self._empty("cmdpost.ghost.empty" if status.get("open")
                        else "cmdpost.ghost.closed_empty")
            return
        for target in targets:
            self._row(target).pack(fill="x", pady=1)

    def _row(self, target):
        import coords as coords_fmt
        import lastwar_proto as proto
        family, level = proto.ghost_recon_level(target.get("cfg"))
        can = bool(target.get("can"))
        frame = ttk.Frame(self._scroll)
        ttk.Label(frame, text=STAR_GLYPH if family == proto.GHOST_STAR_FAMILY
                  else GHOST_GLYPH, font=ui_font(size=14)).pack(side="left", padx=(0, 6))
        lvl = ttk.Label(frame, width=10, font=ui_font(weight="bold"),
                        text=self.rt.t("cmdpost.level", n=level or 0))
        lvl.configure(foreground=READY_COLOR if can else WAIT_COLOR)
        lvl.pack(side="left", padx=(0, 8))
        ttk.Label(frame, width=22, text=coords_fmt.fmt(
            target.get("x", 0), target.get("y", 0), target.get("srv", 0))).pack(
            side="left", padx=(0, 8))
        ttk.Label(frame, width=18, foreground=DIM,
                  text=self.rt.t(self._state_key(target))).pack(
            side="left", padx=(0, 8))
        ttk.Label(frame, width=12, foreground=DIM, text=self.rt.t(
            "cmdpost.ghost.looted", n=target.get("looted", 0))).pack(
            side="left", padx=(0, 8))
        ttk.Label(frame, text=_short(target.get("uuid")), foreground=DIM).pack(
            side="left", padx=(0, 8))
        if target.get("mine"):
            self.rt.tr(ttk.Label(frame, foreground=DIM), "cmdpost.ghost.own").pack(
                side="right", padx=(4, 0))
        elif can:
            self.rt.tr(ttk.Button(frame, width=12,
                                    command=lambda t=target: self._steal(t)),
                         "cmdpost.steal").pack(side="right", padx=(4, 0))
        self.rt.tr(ttk.Button(frame, width=10,
                                command=lambda t=target: self._jump(t)),
                     "cmdpost.jump").pack(side="right")
        return frame

    @staticmethod
    def _state_key(target) -> str:
        """The locale key for a row's state column.

        A row read from the client carries the game's own `GhostreconPointStealType`
        and is labelled with it. A row that came off the map has no such verdict —
        the gate only answers for squads in the client's own list — so it is labelled
        off the clock and says «с карты», rather than borrowing a word the game did
        not say.
        """
        if target.get("scanned"):
            return ("cmdpost.ghost.state.map_ready" if target.get("can")
                    else "cmdpost.ghost.state.map_running")
        return GHOST_STATE_KEYS.get(target.get("state"),
                                    "cmdpost.ghost.state.not_shown")

    # -- actions ------------------------------------------------------------
    def _jump(self, target) -> None:
        x, y = _int(target.get("x")), _int(target.get("y"))
        if x or y:
            self.rt.game.jump(x, y, _int(target.get("srv")) or None)

    def _steal(self, target) -> None:
        """Rob one squad, off the Tk thread; the VM gate decides whether it sends."""
        uuid, server = _int(target.get("uuid")), _int(target.get("srv"))
        if not uuid:
            return

        def work():
            ok = False
            try:
                import game_buttons
                import lua_actions
                ev = self.evaluator()
                lines = ev.run(lua_actions.ghost_recon_steal(uuid, server),
                               marker=MARKER, settle=1.6)
                ok = any("ghost_steal_sent" in ln for ln in (lines or []))
                if ok:
                    button = game_buttons.get("dismiss_ghost_recon_reward")
                    if button is not None:
                        ev.run(button.lua, marker=MARKER, settle=button.wait)
            except Exception:          # noqa: BLE001 — a failed send is a log line
                ok = False
            self._log("cmdpost.ghost.log_sent" if ok else "cmdpost.ghost.log_held",
                      uuid=_short(uuid))
            self.after(self.refresh)

        threading.Thread(target=work, daemon=True).start()

    def _steal_all(self) -> None:
        """Hand the whole robbable set to the standalone tool (the same one the standing
        order spawns), then re-read the list once it has had time to walk the VM."""
        self.order.rob(self.order.limit())
        # Named: pressing «ограбить всё» twice must leave ONE re-read pending,
        # not one per press (see Panel._arm).
        self.rt.tick.arm("cmdpost_ghost_reread", GHOST_RERE_MS, self.refresh)


# ---------------------------------------------------------------------------
class SharedMissionsPane(_Pane):
    """«Секретный мобильный отряд» — the raids an alliancemate shares, as they land.

    A shared mission is not a tile anyone can pan over: it is a push
    (`push.alliance.share.mission.add`) the server sends the alliance when a member
    presses «поделиться» on a raidable secret task. So there is nothing to poll, and this
    page is a listener: tick «Слушать эфир» and every share appears here the moment it
    crosses the wire, with its level, its star and the server the tile sits on.

    Two modes, one checkbox apart. Watching only (the default) decodes and lists; «грабить
    сразу» hands the same rule the panel's auto-loot uses to the listener, which robs a
    matching mission in under a second — the case a person used to win by reading the
    broadcast faster than a poll could. Either way the day's five robberies are the scarce
    thing, so the level range gates what is worth one.
    """

    TITLE_KEY = "cmdpost.shared.title"
    HINT_KEY = "cmdpost.shared.hint"
    LOG_TAG = "autoloot"

    def __init__(self, rt, tab, parent) -> None:
        # uuid (str) -> the decoded mission and its row, so a repeated push does not
        # double a line and a robbery can find its target again.
        self._rows: dict[str, dict] = {}
        self._child = None
        super().__init__(rt, tab, parent)

    def build(self) -> None:
        body = self._header()
        self._build_listener_bar(body)
        ttk.Label(body, textvariable=self._info_var, foreground=DIM).pack(
            anchor="w", pady=(6, 4))
        self._scroll = self._list(body)
        self._paint()

    def _build_listener_bar(self, parent) -> None:
        box = self.rt.tr(ttk.LabelFrame(parent, padding=8), "cmdpost.shared.frame")
        box.pack(fill="x")
        row1 = ttk.Frame(box)
        row1.pack(fill="x")
        self._listen_var = tk.BooleanVar(master=self.rt.root, value=False)
        self.rt.tr(ttk.Checkbutton(row1, variable=self._listen_var,
                                command=self._toggle_listen),
                "cmdpost.shared.listen").pack(side="left")
        self._rob_var = tk.BooleanVar(master=self.rt.root, value=False)
        self.rt.tr(ttk.Checkbutton(row1, variable=self._rob_var,
                                command=self._on_rule_change),
                "cmdpost.shared.rob").pack(side="left", padx=(12, 0))
        self._star_var = tk.BooleanVar(master=self.rt.root, value=True)
        self.rt.tr(ttk.Checkbutton(row1, variable=self._star_var,
                                command=self._on_rule_change),
                "cmdpost.shared.stars_only").pack(side="left", padx=(12, 0))

        row2 = ttk.Frame(box)
        row2.pack(fill="x", pady=(6, 0))
        self.rt.tr(ttk.Label(row2), "cmdpost.shared.level_from").pack(side="left")
        self._from_var = tk_stringvar(self.rt.root)
        NumericEntry(row2, textvariable=self._from_var, width=4).pack(
            side="left", padx=(4, 0))
        self.rt.tr(ttk.Label(row2), "cmdpost.shared.level_to").pack(side="left", padx=(8, 0))
        self._to_var = tk_stringvar(self.rt.root)
        NumericEntry(row2, textvariable=self._to_var, width=4).pack(
            side="left", padx=(4, 0))
        self.rt.tr(ttk.Button(row2, width=14, command=self._clear),
                "cmdpost.shared.clear").pack(side="right")

    # -- the listener -------------------------------------------------------
    def _toggle_listen(self) -> None:
        if self._listen_var.get():
            self._start_listener()
        else:
            self._stop_listener()

    def _start_listener(self) -> None:
        """Spawn `tools/secret_share_autoloot.py` and read its lines into the list.

        Watching only is the tool's own `--dry-run`: it decodes and decides but never
        sends, so the page can sit on all evening without touching the daily budget.
        """
        if self._child is not None:
            return
        cmd = [self.rt.children.python(), "-u",
               os.path.join(TOOLS, "secret_share_autoloot.py"),
               "--limit", str(self.rt.settings.opt_int("autoloot_limit", low=1, high=50))]
        if not self._rob_var.get():
            cmd.append("--dry-run")
        if self._star_var.get():
            cmd.append("--star-max")
        lo, hi = self._levels()
        if lo is not None:
            cmd += ["--level-min", str(lo)]
        if hi is not None:
            cmd += ["--level-max", str(hi)]
        child = self.rt.children.spawn("autoloot", cmd, on_line=self._on_line,
                                on_exit=self._on_child_exit)
        if not child.start():
            self._listen_var.set(False)
            return
        self._child = child
        self._log("cmdpost.shared.log_on")

    def _stop_listener(self) -> None:
        child, self._child = self._child, None
        if child is not None:
            child.stop()
            self._log("cmdpost.shared.log_off")

    def _on_child_exit(self) -> None:
        """The listener died on its own — untick the box rather than lie about it."""
        self._child = None
        try:
            self._listen_var.set(False)
        except Exception:              # noqa: BLE001 — panel already gone
            pass

    def _on_rule_change(self) -> None:
        """A rule box was toggled: restart the listener so the change takes effect."""
        if self._child is None:
            return
        self._stop_listener()
        self._start_listener()

    def _on_line(self, line: str) -> None:
        """One line of the listener's output → a row, when it names a mission.

        Returns ``None`` so the line still reaches the log: the tool narrates what it
        decided (matched / left alone / robbed / budget spent) and that narration is
        worth reading beside the list.
        """
        clean = ANSI.sub("", line)
        match = SHARE_LINE.search(clean)
        if match is None:
            return None
        mission = {
            "uuid": match.group("uuid"),
            "server": _int(match.group("srv")),
            "cfg": match.group("cfg"),
            "level": _int(match.group("lvl"), 0),
            "star": "*" in clean.split("lvl", 1)[0],
            "matched": "SHARE MATCH" in clean,
            "robbed": "robbed" in clean,
        }
        self.after(lambda: self._add(mission))
        return None

    def _add(self, mission: dict) -> None:
        key = mission["uuid"]
        row = self._rows.get(key)
        if row is None:
            self._rows[key] = mission
        else:
            # A later line about the same mission only ever adds to what is known
            # (matched → robbed); it never downgrades a verdict already seen.
            row["matched"] = row.get("matched") or mission["matched"]
            row["robbed"] = row.get("robbed") or mission["robbed"]
        self._paint()

    # -- reading the game ---------------------------------------------------
    def fetch(self):
        """The day's remaining secret-task robberies — the budget a share would spend."""
        import lua_actions
        ev = self.evaluator()
        chunk = ('CS.UnityEngine.Debug.LogError("ACT left="..tostring(%s))'
                 % lua_actions.secret_task_steals_left())
        for line in ev.run(chunk, marker=MARKER, settle=0.9) or ():
            if "left=" in line:
                return _int(line.split("left=", 1)[1].split()[0])
        return 0

    def render(self, left) -> None:
        self._status("")
        self._info("cmdpost.shared.info", left=left, n=len(self._rows))
        self._paint()

    def _paint(self) -> None:
        self._clear_list()
        if not self._rows:
            self._empty("cmdpost.shared.empty")
            return
        rows = sorted(self._rows.values(),
                      key=lambda m: (not m.get("matched"), -(m.get("level") or 0)))
        for mission in rows:
            self._row(mission).pack(fill="x", pady=1)

    def _row(self, mission: dict):
        import coords as coords_fmt
        frame = ttk.Frame(self._scroll)
        ttk.Label(frame, text=STAR_GLYPH if mission.get("star") else SHARE_GLYPH,
                  font=ui_font(size=14)).pack(side="left", padx=(0, 6))
        lvl = ttk.Label(frame, width=10, font=ui_font(weight="bold"),
                        text=self.rt.t("cmdpost.level", n=mission.get("level") or 0))
        lvl.configure(foreground=READY_COLOR if mission.get("matched") else WAIT_COLOR)
        lvl.pack(side="left", padx=(0, 8))
        ttk.Label(frame, width=12, text=coords_fmt.fmt(0, 0, mission.get("server"))
                  .split()[0]).pack(side="left", padx=(0, 8))
        ttk.Label(frame, width=12, foreground=DIM,
                  text=str(mission.get("cfg") or "")).pack(side="left", padx=(0, 8))
        ttk.Label(frame, text=_short(mission.get("uuid")), foreground=DIM).pack(
            side="left", padx=(0, 8))
        if mission.get("robbed"):
            self.rt.tr(ttk.Label(frame, foreground=READY_COLOR),
                         "cmdpost.shared.robbed").pack(side="right", padx=(4, 0))
        else:
            self.rt.tr(ttk.Button(frame, width=12,
                                    command=lambda m=mission: self._steal(m)),
                         "cmdpost.steal").pack(side="right", padx=(4, 0))
        return frame

    # -- actions ------------------------------------------------------------
    def _levels(self):
        """The «уровень от / до» pair as ints, either end ``None`` when left blank."""
        def bound(var):
            raw = var.get().strip()
            return int(raw) if raw.isdigit() else None
        return bound(self._from_var), bound(self._to_var)

    # -- what is remembered between sessions --------------------------------
    def config(self) -> dict:
        """The robbery rule as it is stored in the profile.

        «Слушать эфир» is deliberately not in it: a listener is a running capture, not a
        setting, and a tick restored without one would say the air is being watched when
        nothing is.
        """
        lo, hi = self._levels()
        return {
            "rob": bool(self._rob_var.get()),
            "stars_only": bool(self._star_var.get()),
            "level_from": "" if lo is None else str(lo),
            "level_to": "" if hi is None else str(hi),
        }

    def apply_config(self, raw) -> None:
        """Restore the rule from a profile's block (anything unreadable -> the default)."""
        raw = raw if isinstance(raw, dict) else {}
        self._rob_var.set(bool(raw.get("rob", False)))
        self._star_var.set(bool(raw.get("stars_only", True)))
        for key, var in (("level_from", self._from_var), ("level_to", self._to_var)):
            var.set(_level_text(raw.get(key)))

    def persist_vars(self) -> list:
        """The controls a change of has to be written to the profile."""
        return [self._rob_var, self._star_var, self._from_var, self._to_var]

    def _steal(self, mission: dict) -> None:
        """Rob one shared mission by hand — `hero.dispatch.steal {uuid, targetServer}`.

        The same send the «Секретки» tab makes, because a shared mission IS a secret
        task: the push carries the tile's uuid and the server it sits on, so no
        coordinate-to-uuid resolve is needed.
        """
        uuid, server = _int(mission.get("uuid")), _int(mission.get("server"))
        if not uuid:
            return

        def work():
            ok = False
            try:
                import lua_actions
                ev = self.evaluator()
                lines = ev.run(lua_actions.secret_task_steal(uuid, server),
                               marker=MARKER, settle=1.4)
                ok = any("steal_sent" in ln for ln in (lines or []))
            except Exception:          # noqa: BLE001
                ok = False
            self._log("cmdpost.shared.log_sent" if ok else "cmdpost.shared.log_held",
                      uuid=_short(uuid))
            if ok:
                mission["robbed"] = True
            self.after(self._paint)

        threading.Thread(target=work, daemon=True).start()

    def _clear(self) -> None:
        self._rows.clear()
        self._paint()

    def shutdown(self) -> None:
        super().shutdown()
        self._stop_listener()

    def restart(self) -> None:
        """Bounce the listener onto the profile the panel just switched to."""
        super().restart()
        if self._child is None:
            return
        self._stop_listener()
        self._start_listener()


# ---------------------------------------------------------------------------
class TreasuresPane(_Pane):
    """«Скрытые сокровища» — the detect-event chests on the world map.

    Nothing polls for a treasure by itself: the client only knows about one after a
    treasure-list reply has arrived, and an empty list means «nobody asked» just as often
    as «there is none». So «Обновить» does what the finder tool does — asks the server
    for each activity the account tracks, reads the manager back, and parks whatever came
    with it — and the header says which of those two empties it is looking at.

    Each parked target gets the press it needs: «Копать» sends the chosen squad to the
    tile while it is still being dug, «Забрать» claims it once it is. Both are built and
    compile in the live VM, but no detect event has put a treasure on the map since they
    were written, so neither has completed a round trip — the hint says so.
    """

    TITLE_KEY = "cmdpost.treasure.title"
    HINT_KEY = "cmdpost.treasure.hint"
    LOG_TAG = "action"

    def build(self) -> None:
        body = self._header()
        box = self.rt.tr(ttk.LabelFrame(body, padding=8), "cmdpost.treasure.frame")
        box.pack(fill="x")
        self.rt.tr(ttk.Label(box), "cmdpost.treasure.squad").pack(side="left")
        self._squad_var = tk.IntVar(master=self.rt.root, value=TREASURE_SQUADS[0])
        for squad in TREASURE_SQUADS:
            ttk.Radiobutton(box, text=str(squad), value=squad,
                            variable=self._squad_var).pack(side="left", padx=4)
        self._scan_btn = self.rt.tr(ttk.Button(box, width=16, command=self._scan),
                                      "cmdpost.scan")
        self._scan_btn.pack(side="right")
        ttk.Label(body, textvariable=self._info_var, foreground=DIM).pack(
            anchor="w", pady=(6, 4))
        self._scroll = self._list(body)

    # -- what is remembered between sessions --------------------------------
    def config(self) -> dict:
        """The digging squad, as it is stored in the profile."""
        return {"squad": _int(self._squad_var.get(), TREASURE_SQUADS[0])}

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        squad = raw.get("squad")
        self._squad_var.set(squad if squad in TREASURE_SQUADS else TREASURE_SQUADS[0])

    def persist_vars(self) -> list:
        return [self._squad_var]

    def _scan(self) -> None:
        """Scan the map for `f2 = 21` chests — the other half of «is there one?».

        Asking the server (the «Обновить» path) only ever answers about this
        alliance's own detect event. A chest is also an ordinary map point: it is
        handed to whoever pans over it, and its point update is re-sent the moment
        someone finishes the dig — which is the moment the row has to flip from
        «копают» to «раскопано». Both sources feed the same list.
        """
        self._scan_toggle(TREASURE_SCAN_SCRIPT, self.rt.profiles.treasures_json())

    # -- reading the game ---------------------------------------------------
    def fetch(self):
        """Ask, read back, park, and return `(treasures_num, daily, targets)`.

        The ids to ask for are the ones the client tracks a daily count for; a client
        that has just started tracks none, and asking for nothing would be never looking
        at all — so the finder's known ids stand in, exactly as `tools/find_treasures.py`
        does it.
        """
        import time
        import find_treasures
        import lua_actions
        import tool_config
        ev = self.evaluator()
        num, daily = self._read_state(ev)
        ids = sorted(daily) or list(find_treasures.KNOWN_ACTIVITY_IDS)
        ev.run(lua_actions.treasure_refresh_request(ids), marker=MARKER, settle=1.5)
        time.sleep(2.5)
        num, daily = self._read_state(ev)
        home = _int(tool_config.default_server())
        ev.run(lua_actions.park_treasures(home), marker=MARKER, settle=1.5)
        targets = []
        for line in ev.run(lua_actions.treasure_queue_dump(),
                           marker=MARKER, settle=1.2) or ():
            if " TQ " not in line:
                continue
            fields = _fields(line, " TQ ")
            targets.append({
                "i": _int(fields.get("i")), "pid": fields.get("pid"),
                "uuid": fields.get("uuid"), "server": _int(fields.get("srv")),
                "dug": fields.get("dug") == "1",
                "x": _int(fields.get("x")), "y": _int(fields.get("y")),
                "cross": bool(home) and _int(fields.get("srv")) != home,
            })
        targets += self._scanned_targets({str(t["uuid"]) for t in targets}, home)
        return num, daily, targets

    def _scanned_targets(self, known: set, home: int) -> list:
        """Chests the map scan saw that the server's own list did not carry.

        A treasure the alliance's detect event did not place — another alliance's, or
        one this client was never told about — only exists on the map, so this is the
        only way it reaches the list. The dug/digging split comes off the point's
        finisher field, the same one the recorded live treasure proved it with.

        No checkpoint (a scan never ran) is simply no extra rows.
        """
        import lastwar_proto as proto
        try:
            found = proto.load_fresh_treasures(self.rt.profiles.treasures_json())
        except Exception:              # noqa: BLE001 — no file, or a half-written one
            return []
        out = []
        for t in found:
            if t.uuid is None or str(t.uuid) in known or t.expired:
                continue
            out.append({
                "i": 0, "pid": t.point_id, "uuid": str(t.uuid),
                "server": t.server_id or 0, "dug": t.dug,
                "x": t.x or 0, "y": t.y or 0,
                "cross": bool(home) and (t.server_id or 0) != home,
            })
        return out

    @staticmethod
    def _read_state(ev):
        """`(treasures_num, {activityId: taken_today})` off the treasure manager."""
        import lua_actions
        num, daily = 0, {}
        for line in ev.run(lua_actions.treasure_state(),
                           marker=MARKER, settle=1.5) or ():
            if "treasures_num=" in line:
                num = _int(line.split("treasures_num=", 1)[1].split()[0])
            elif "treasure_daily " in line:
                key, _sep, value = line.split("treasure_daily ", 1)[1].partition("=")
                if key.strip().isdigit():
                    daily[int(key.strip())] = _int(value.split()[0] if value else 0)
        return num, daily

    def render(self, data) -> None:
        num, daily, targets = data
        self._status("")
        self._info("cmdpost.treasure.info", n=num,
                   daily=", ".join("%d: %d" % kv for kv in sorted(daily.items()))
                   or self.rt.t("cmdpost.treasure.no_daily"))
        self._clear_list()
        if not targets:
            self._empty("cmdpost.treasure.empty")
            return
        for target in targets:
            self._row(target).pack(fill="x", pady=1)

    def _row(self, target):
        import coords as coords_fmt
        frame = ttk.Frame(self._scroll)
        ttk.Label(frame, text=TREASURE_GLYPH, font=ui_font(size=14)).pack(
            side="left", padx=(0, 6))
        ttk.Label(frame, width=22, text=coords_fmt.fmt(
            target["x"], target["y"], target["server"])).pack(side="left", padx=(0, 8))
        state = ttk.Label(frame, width=16, font=ui_font(weight="bold"),
                          text=self.rt.t("cmdpost.treasure.dug" if target["dug"]
                                           else "cmdpost.treasure.digging"))
        state.configure(foreground=READY_COLOR if target["dug"] else WAIT_COLOR)
        state.pack(side="left", padx=(0, 8))
        ttk.Label(frame, text=_short(target["uuid"]), foreground=DIM).pack(
            side="left", padx=(0, 8))
        if target["dug"]:
            self.rt.tr(ttk.Button(frame, width=12,
                                    command=lambda t=target: self._claim(t)),
                         "cmdpost.treasure.claim").pack(side="right", padx=(4, 0))
        else:
            self.rt.tr(ttk.Button(frame, width=12,
                                    command=lambda t=target: self._dig(t)),
                         "cmdpost.treasure.dig").pack(side="right", padx=(4, 0))
        self.rt.tr(ttk.Button(frame, width=10,
                                command=lambda t=target: self._jump(t)),
                     "cmdpost.jump").pack(side="right")
        return frame

    # -- actions ------------------------------------------------------------
    def _jump(self, target) -> None:
        if target["x"] or target["y"]:
            self.rt.game.jump(target["x"], target["y"], target["server"] or None)

    def _dig(self, target) -> None:
        """March the chosen squad onto the tile — the dig half of the treasure.

        A march rides a *formation*, and a cold one silently no-ops, so the squad slot
        is resolved to its formation uuid the way every other march in the repo does
        (`rally_join.formation_by_squad`, falling back to any warm formation).
        """
        squad = self._squad_var.get()

        def work():
            ok, armed = False, True
            try:
                import lua_actions
                import rally_join
                ev = self.evaluator()
                formation = (rally_join.formation_by_squad(ev.run, squad)
                             or rally_join.pick_formation(ev.run))
                if not formation:
                    armed = False       # no warm squad: say which one, not "failed"
                else:
                    lines = ev.run(lua_actions.dig_treasure_march(
                        target["pid"], target["uuid"], target["server"], formation,
                        cross=target["cross"]), marker=MARKER, settle=1.6)
                    ok = any("dig_treasure_armed" in ln for ln in (lines or []))
            except Exception:          # noqa: BLE001
                ok = False
            if not armed:
                self._log("cmdpost.treasure.log_no_squad", squad=squad)
            else:
                self._log("cmdpost.treasure.log_dig" if ok
                          else "cmdpost.treasure.log_failed",
                          uuid=_short(target["uuid"]))
            self.after(self.refresh)

        threading.Thread(target=work, daemon=True).start()

    def _claim(self, target) -> None:
        """Take an already-dug treasure — `detect.event.claim.treasure {uuid, server}`."""
        def work():
            ok = False
            try:
                import lua_actions
                ev = self.evaluator()
                lines = ev.run(lua_actions.claim_treasure(target["uuid"],
                                                          target["server"]),
                               marker=MARKER, settle=1.5)
                ok = any("claim_treasure_sent" in ln for ln in (lines or []))
            except Exception:          # noqa: BLE001
                ok = False
            self._log("cmdpost.treasure.log_claim" if ok
                      else "cmdpost.treasure.log_failed", uuid=_short(target["uuid"]))
            self.after(self.refresh)

        threading.Thread(target=work, daemon=True).start()


# ---------------------------------------------------------------------------
class CommandPostTab(PanelTab):
    """The tab itself: a notebook of the three pages above.

    Each page loads lazily — the first time it is *shown*, not when the tab is built —
    so opening the tab costs one page's read and the two the operator never looks at
    cost nothing. The tab is EAGER all the same: the ghost page carries a standing
    order, and a standing order has to be running whether or not anybody looks at it.
    """

    ID = "command_post"
    TITLE_KEY = "tab.command_post"
    ORDER = 320
    PREFERRED_SIZE = "900x700"
    LOCALE_NS = ("cmdpost", "ghost")
    NEEDS = frozenset({"daemon", "children"})
    EAGER = True
    # `ghost_autoloot` was a flat key of the panel's, because the checkbox's var was;
    # the rest of the tab was already one nested block. Neither is renamed here — §5
    # rule 3 forbids it in the wave that moves them.
    LEGACY_KEYS = {"pages": "command_post", "ghost_autoloot": "ghost_autoloot"}

    def build(self) -> None:
        # Until the panel has actually shown this tab, a page change is Tk's own doing
        # (adding the first inner tab selects it) and must not start a game read — a
        # panel nobody opened this tab on would poll the client at start-up.
        self._shown = False
        nb = ttk.Notebook(self.parent)
        nb.pack(fill="both", expand=True)
        self._nb = nb
        self._pages = {}
        # The same three pages by name, for the profile block: a saved setting has to
        # find its page again, and a Tk widget path is not a name that survives a restart.
        self._by_key = {}
        for key, cls in (("ghost", GhostReconPane),
                         ("shared", SharedMissionsPane),
                         ("treasure", TreasuresPane)):
            frame = ttk.Frame(nb)
            nb.add(frame, text=self.rt.t("cmdpost.tab." + key))
            page = cls(self.rt, self, frame)
            self._pages[str(frame)] = page
            self._by_key[key] = page
        self.rt.i18n.hook(self._retranslate, key="cmdpost-tab-labels")
        nb.bind("<<NotebookTabChanged>>", self._on_page_changed)

    # -- lifecycle ----------------------------------------------------------
    def ensure_loaded(self) -> None:
        """Start the standing order this profile asked for, and load the page on top.

        Called at boot (EAGER) and again the first time the tab is shown; both are
        idempotent. The ghost watcher must not wait for a click — the event runs one day
        a week and the five robberies are the whole of it.
        """
        self.ghost.order.ensure_started()
        self._shown = True
        page = self._current()
        if page is not None:
            page.ensure_loaded()

    @property
    def ghost(self):
        """The «Операция Призрак» page — the one carrying the standing order."""
        return self._by_key["ghost"]

    def _on_page_changed(self, _event=None) -> None:
        """An inner page was selected — load it, once the tab has really been opened."""
        if not self._shown:
            return
        page = self._current()
        if page is not None:
            page.ensure_loaded()

    def _current(self):
        try:
            return self._pages.get(str(self._nb.select()))
        except Exception:              # noqa: BLE001 — no page selected yet
            return None

    def _retranslate(self) -> None:
        """Repaint the inner tab labels when the language changes."""
        for index, key in enumerate(("ghost", "shared", "treasure")):
            try:
                self._nb.tab(index, text=self.rt.t("cmdpost.tab." + key))
            except Exception:          # pragma: no cover - the notebook may be gone
                pass

    def shutdown(self) -> None:
        """Stop anything a page left running (the listener, the scans, the order)."""
        for page in self._pages.values():
            stop = getattr(page, "shutdown", None)
            if stop is not None:
                stop()
        self.rt.tick.disarm("cmdpost_ghost_reread")

    def panic(self) -> None:
        """«Стоп всё»: every child and every watcher this tab holds, boxes unticked."""
        self.ghost.autoloot_var.set(False)
        listen = getattr(self._by_key["shared"], "_listen_var", None)
        if listen is not None:
            listen.set(False)
        self.shutdown()

    def on_profile_switch(self) -> None:
        """A listener captures for one client and robs through one daemon, so it cannot
        carry over. Only a page whose box is still ticked comes back up."""
        self.restart_children()

    def on_language_change(self) -> None:
        self._retranslate()

    # -- what is remembered between sessions --------------------------------
    def config(self) -> dict:
        """Every page's own settings, plus the standing order's switch.

        `pages` is the block the profile already had under «command_post»; the ghost
        switch was a flat key beside it («ghost_autoloot») because its variable used to
        live on the panel. Both keep their spelling.
        """
        pages = {}
        for key, page in self._by_key.items():
            read = getattr(page, "config", None)
            if read is not None:
                pages[key] = read()
        return {"pages": pages,
                "ghost_autoloot": bool(self.ghost.autoloot_var.get())}

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        pages = raw.get("pages")
        pages = pages if isinstance(pages, dict) else {}
        for key, page in self._by_key.items():
            apply = getattr(page, "apply_config", None)
            if apply is not None:
                apply(pages.get(key))
        self.ghost.autoloot_var.set(bool(raw.get("ghost_autoloot", False)))

    def persist_vars(self) -> list:
        """Every control on the tab a change of has to be written to the profile."""
        out = [self.ghost.autoloot_var]
        for page in self._by_key.values():
            read = getattr(page, "persist_vars", None)
            if read is not None:
                out.extend(read())
        return out

    def restart_children(self) -> None:
        """The profile switched: re-point a running listener at the new client.

        A listener captures for one client and robs through one daemon, so it cannot
        simply carry over. Only a page whose box is still ticked comes back up.
        """
        for page in self._pages.values():
            restart = getattr(page, "restart", None)
            if restart is not None:
                restart()

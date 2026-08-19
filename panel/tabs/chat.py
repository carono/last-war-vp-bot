"""The «Чат» tab: the game's chat, read live and answered from the panel.

The chat stream is not on the sniffable socket — broadcast and DM ride a TLS
websocket — so it is read off the game's own Lua VM by a child process
(`tools/chat_reader.py`) that hooks `ChatMessage:onParseServerData`. The chat window
does not have to be open in the game for it to work.

What the tab is: a notebook of the chat types, a per-character SQLite history
(`panel/chat_history.py`) paged in a screenful at a time, a DM pane split into a
contact list and one open conversation, an emoji / sticker picker over the sprites
`tools/chat_assets.py` extracts, and a box to answer in.

TWO THINGS COST REAL RESOURCES, and both are why it is worth being able to switch
this tab off in the profile: the reader child, and the store. Neither is opened until
:meth:`ensure_loaded`, and a profile that does not list this tab never gets either.

Chat is also where coordinates actually ARRIVE — a rally target, a treasure, a base to
hit — so a coordinate in a message is a link that walks the camera there, drawn by the
same `panel/widgets.py` helpers the log uses.
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

# The runtime FIRST: importing `panel.runtime` is what puts the repo's tools/lib on
# sys.path, and the three bare-name modules below live there. Load-bearing rather than
# stylistic — `python -m panel.tabs.chat` reaches this file before anything else does.
from .. import chat_history as chathistmod                      # noqa: E402
from .. import widgets                                          # noqa: E402
from ..runtime import players                                   # noqa: E402
from ..runtime.paths import TOOLS, repo_rel                     # noqa: E402
from .base import PanelTab                                      # noqa: E402

import chat_assets                                              # noqa: E402
import chat_share       # self_profile -> the player's uid, read live  # noqa: E402
import coords                                                   # noqa: E402

try:
    from PIL import (Image as _PILImage, ImageTk as _PILImageTk,
                     ImageDraw as _PILImageDraw)
    _PIL_OK = True
except Exception:       # noqa: BLE001 — inline pictures are optional, chat is not
    _PIL_OK = False

#: A photo in a message is written as this token by the reader child.
_PHOTO_TOK = re.compile(r"\[photo:(\d+)\]")

# The chat sub-tabs, in order. `system` is on the list: the bucket was always carried,
# so those messages were counted and shown nowhere.
CHAT_TABS: tuple = ("world", "alliance", "national", "dm", "other", "system")

#: This tab's receiver in `panel/runtime/intake.py` (#1549) — what the reader child hands
#: over, and what the pump takes. The flow strip in the bottom bar is drawn from it.
INTAKE_CHAT = "chat.messages"

# Lazy-load: chat history lives in the per-profile SQLite store; only the newest
# CHAT_PAGE of a tab is read into memory and rendered at startup, and a scroll to the
# top pages the next CHAT_PAGE in from the store. CHAT_MSGS_MAX caps the in-memory
# (rendered) list so a marathon live session cannot grow it without bound — overflow is
# dropped from the front but stays in the store, reachable again by scrolling up.
CHAT_PAGE = 100
CHAT_MSGS_MAX = 2000

# Inline pictures — one Tk image per distinct (file, size): every sender's avatar and
# every photo posted. Kept as an LRU of this many, because they are live Tk objects and
# world chat walks past a new sender every few seconds; what falls out is history far
# above the viewport, which redraws its picture if it is scrolled back to.
CHAT_IMG_CACHE_MAX = 1500


class ChatTab(PanelTab):
    """The chat views, the DM pane, the picker, the reader child and the store."""

    ID = "chat"
    TITLE_KEY = "tab.chat"
    ORDER = 50
    #: Still being written: hidden unless «Разработка» is on (#1273). The mark
    #: comes off when this tab's abilities are proven live and said so in
    #: `docs/farming.md` (`PanelTab.IN_DEVELOPMENT`).
    IN_DEVELOPMENT = True
    PREFERRED_SIZE = "1000x760"
    LOCALE_NS = ("chat",)
    NEEDS = frozenset({"daemon", "children"})
    LEGACY_KEYS = {"chat_monitor": "chat_monitor"}

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        self._chat_var = tk.BooleanVar(master=rt.root, value=False)
        self._chat_q: "queue.Queue[dict]" = queue.Queue()
        self._chat_proc = None
        # In-memory chat messages keyed by chat_type. `system` has a tab of its own
        # now — it used to be counted here and shown nowhere.
        self._chat_msgs: dict = {t: [] for t in CHAT_TABS}
        # Unread marks: how many messages have arrived in a tab nobody is looking
        # at. Cleared when that tab is selected.
        self._chat_unread: dict = {t: 0 for t in CHAT_TABS}
        # Text-view widgets per chat type (populated by _build_chat_tab). Named
        # _chat_trees for historical reasons; they are tk.Text now, not Treeviews.
        self._chat_trees: dict = {}
        # Count of lines already rendered into each view (for incremental appends)
        self._chat_tree_rows: dict = {}
        # Lazy-load: `_chat_msgs` holds only the records currently in memory (the
        # newest page at startup); `_chat_has_more` is True while the SQLite store
        # still holds OLDER messages for that tab than the oldest one in memory. A
        # scroll to the top (or the load-more header) pages the next chunk in from
        # the store. `_chat_store` is the ChatHistoryStore of the CURRENT CHARACTER
        # (`_chat_uid`), not the account: one account can hold several characters and
        # their chats live in separate files. It is re-pointed when the chat monitor
        # starts (the uid is read live from the game then).
        self._chat_has_more: dict = {t: False for t in CHAT_TABS}
        self._chat_store = None
        self._chat_uid = ""            # current character's uid; "" until resolved
        self._chat_resolving = False   # guards against overlapping uid resolves
        # DM contact list. The DM tab is split: a contact list (one peer per DM
        # conversation, read from the store) beside a conversation view that shows
        # ONE peer at a time. `_dm_active_room`/`_dm_active_peer` is the open
        # conversation; `_dm_unread` counts messages that arrived for a contact while
        # it was not the open one; `_dm_contacts_dirty` asks for a sidebar repaint.
        self._dm_active_room = ""
        self._dm_active_peer = ""
        self._dm_unread: dict = {}
        self._dm_contacts_dirty = False
        self._dm_list = None           # the contact-list textbox (built in _build_dm_tab)
        self._chat_entry = None        # the message-send Entry (for emoji insertion)
        self._emoji_win = None         # the open emoji/sticker picker, if any
        # Cache of inline sprite images keyed by (path, height) -- also keeps the
        # PhotoImage refs alive (tk.Text does not hold a Python reference). Bounded
        # at CHAT_IMG_CACHE_MAX: a night of chat walks past thousands of distinct
        # avatars and photos, and every one of them is a live Tk image until it is
        # dropped (see `_chat_image`).
        self._chat_img_cache: dict = {}
        self._photo_seq = 0            # how many photos have been drawn (diagnostics)
        # Tk image name -> (uid, pic_ver, path) for the click that opens a chat photo
        # full-size. Keyed by the image, so it is bounded by the cache above.
        self._photo_meta: dict = {}
        self._loaded = False

    # -- lifecycle ------------------------------------------------------------
    def ensure_loaded(self) -> None:
        """Open the store and draw the history — and start the reader if it was on.

        NOTHING above happens for a profile that does not list this tab: no child
        process, no SQLite file, no image cache. That is the whole point of being able
        to switch it off.
        """
        if self._loaded:
            return
        self._loaded = True
        self._load_chat_history()
        if self._chat_var.get():
            self._start_chat()

    def on_show(self) -> None:
        self.ensure_loaded()

    def on_profile_switch(self) -> None:
        """A different account is a different chat: bounce the reader, drop what is on
        screen and re-open the store under the new character."""
        self._stop_chat()
        self._clear_chat()
    # -- the phone ------------------------------------------------------------
    #
    # READING ONLY. Sending is `tools/chat_send.py` — a tool the tab spawns, not a DSL
    # scenario — and the rule for this whole port is that a press goes through a
    # scenario or does not go at all. Reading is the half that is useful away from the
    # machine anyway: what the alliance is saying, and whether somebody wrote to you.
    #
    # It costs no game read at all: the messages are in this character's own SQLite
    # history, which the reader child fills whether or not anybody is looking.
    WEB_SCREEN = True

    #: How many messages a phone is handed per chat type. A screenful and a bit — the
    #: window pages further back, and a phone that wants the archive wants the window.
    WEB_MESSAGES = 30

    def web_view(self) -> "dict | None":
        import time as _time

        cards = []
        for chat_type in CHAT_TABS:
            rows = self._web_messages(chat_type)
            if not rows and chat_type not in ("world", "alliance", "dm"):
                continue                       # a quiet corner is not worth a card
            cards.append({"title": f"chat.tab.{chat_type}", "items": rows,
                          "empty": "chat.empty", "flow": self._web_flow()})
        return {"cards": cards, "now": _time.time(),
                "actions": []}

    def _web_messages(self, chat_type: str) -> list:
        """The newest messages of one type, oldest first — as the window shows them."""
        rows = list(self._chat_msgs.get(chat_type) or ())[-self.WEB_MESSAGES:]
        if not rows and self._chat_store is not None:
            try:
                rows = self._chat_store.recent(chat_type, self.WEB_MESSAGES)
            except Exception:                  # noqa: BLE001 — a closed store is empty
                rows = []
        out = []
        for row in rows:
            text = str(row.get("msg") or "").strip()
            if not text:
                continue                       # a sticker or a photo: the window's job
            out.append({"text": str(row.get("sender_name") or "?"),
                        "note": text,
                        "until": None})
        return out

        if self._chat_store is not None:
            self._chat_store.close()
            self._chat_store = None
        self._chat_uid = ""
        if self._loaded:
            self._load_chat_history()
        if self._chat_var.get():
            self._start_chat()

    def panic(self) -> None:
        self._was_watching = bool(self._chat_var.get())
        self._chat_var.set(False)
        self._stop_chat()

    def resume(self) -> None:
        """«Включить обратно»: the chat monitor comes back if it was running."""
        if getattr(self, "_was_watching", False):
            self._was_watching = False
            self._chat_var.set(True)

    def shutdown(self) -> None:
        self._stop_chat()
        if self._chat_store is not None:
            self._chat_store.close()
            self._chat_store = None
        self.rt.tick.disarm("chat")

    # -- persistence ----------------------------------------------------------
    def config(self) -> dict:
        return {"chat_monitor": bool(self._chat_var.get())}

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._chat_var.set(bool(raw.get("chat_monitor", False)))

    def persist_vars(self) -> list:
        return [self._chat_var]

    def build(self) -> None:
        """Build the Chat tab: monitor toggle, sub-tabs per chat type, and a box to answer in."""
        ctrl = ttk.Frame(self.parent, padding=(8, 6, 8, 4))
        ctrl.pack(fill="x")
        self.tr(ttk.Checkbutton(ctrl, variable=self._chat_var, command=self._toggle_chat),
                 "chat.monitor").pack(side="left")
        self.tr(ttk.Label(ctrl, foreground="#888", wraplength=500, justify="left"),
                 "chat.hint").pack(side="left", padx=(10, 0))

        sub_nb = ttk.Notebook(self.parent)
        sub_nb.pack(fill="both", expand=True, padx=4, pady=(0, 2))
        self._chat_nb = sub_nb
        self._chat_frames: dict = {}

        for type_key in CHAT_TABS:
            frame = ttk.Frame(sub_nb)
            sub_nb.add(frame, text=self.t(f"chat.tab.{type_key}"))
            self._chat_frames[type_key] = frame
            # The DM tab is a contact list beside the conversation; every other tab
            # is just the message view.
            tree = (self._build_dm_tab(frame) if type_key == "dm"
                    else self._make_chat_tree(frame))
            self._chat_trees[type_key] = tree
            self._chat_tree_rows[type_key] = 0
        # One hook for all of them: the labels carry an unread count, so they are
        # rewritten together and by the same code that draws the marks.
        self.rt.i18n.hook(self._paint_chat_tabs)
        # A DM that arrived while another tab was open used to be silent. Selecting a
        # tab is what marks it read.
        sub_nb.bind("<<NotebookTabChanged>>", self._on_chat_tab_changed)

        # -- the box to answer in ------------------------------------------------
        #
        # chat_send.py, tools/lib/chat_share.py and actions/send_chat_message.md all
        # existed and the tab had no input at all, so answering a mate or sharing a
        # coordinate meant leaving the panel. The target is the room of the last
        # message in the tab that is open — and it is SHOWN, so it is never a guess:
        # a message sent to the wrong room cannot be unsent.
        send = ttk.Frame(self.parent, padding=(6, 2, 6, 2))
        send.pack(fill="x")
        self._chat_room_var = tk.StringVar(value="—")
        self.tr(ttk.Label(send), "chat.to").pack(side="left")
        ttk.Label(send, textvariable=self._chat_room_var, foreground="#888",
                  width=26).pack(side="left", padx=(4, 6))
        # The emoji / sticker picker: a game emoji goes inline into the text as a
        # {e:<id>} token (chat_send resolves it), a sticker is sent as its own
        # message (the game does not let a sticker ride alongside text).
        ttk.Button(send, text="😊", width=32, command=self._open_emoji_picker).pack(
            side="left", padx=(0, 4))
        self._chat_msg_var = tk.StringVar()
        entry = ttk.Entry(send, textvariable=self._chat_msg_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _e: self._chat_send_text())
        self._chat_entry = entry
        self.tr(ttk.Button(send, command=self._chat_send_text),
                 "chat.send").pack(side="left", padx=(4, 0))
        # The coordinate written in the box beside it, shared as a map pin — not as
        # text. A pin is tappable in the game; "600,400" is not.
        self.tr(ttk.Button(send, command=self._chat_send_coords),
                 "chat.send_coords").pack(side="left", padx=(4, 0))

        bot = ttk.Frame(self.parent, padding=(6, 2, 6, 4))
        bot.pack(fill="x")
        self.tr(ttk.Button(bot, command=self._clear_chat),
                 "chat.clear").pack(side="left")
        self._chat_count_var = tk.StringVar(value=self.t("chat.count", n=0))
        ttk.Label(bot, textvariable=self._chat_count_var, foreground="#888").pack(
            side="right", padx=8)
        # IS THE READER STILL TALKING TO US (#1549). The chat window has looked exactly
        # the same when the reader had exited as when the alliance simply had nothing to
        # say, and «чат молчит» is the most common way a dead child shows itself. The
        # same strip every fed grid in the panel has, out of the same module.
        self._flow_var = tk.StringVar(value="")
        self._flow_label = ttk.Label(bot, textvariable=self._flow_var)
        self._flow_label.pack(side="left", padx=(12, 0))
        self._refresh_flow()
        self.rt.i18n.hook(self._retranslate_chat_bottom)

        self._pump_chat()

    def _retranslate_chat_bottom(self) -> None:
        """Re-apply translatable text in the chat bottom bar after a language change."""
        total = sum(len(v) for v in self._chat_msgs.values())
        self._chat_count_var.set(self.t("chat.count", n=total))

    # -- which tab is open, and what has arrived in the others ---------------
    def _active_chat_type(self) -> str:
        nb = getattr(self, "_chat_nb", None)
        if nb is None:
            return CHAT_TABS[0]
        try:
            current = nb.select()
        except tk.TclError:
            return CHAT_TABS[0]
        for key, frame in self._chat_frames.items():
            if str(frame) == str(current):
                return key
        return CHAT_TABS[0]

    def _on_chat_tab_changed(self, _event=None) -> None:
        """A tab was selected: it is read now, and it is the send target."""
        active = self._active_chat_type()
        self._chat_unread[active] = 0
        if active == "dm":
            self._refresh_dm_contacts()     # show the freshest ordering on open
        self._paint_chat_tabs()
        self._update_chat_target()

    def _paint_chat_tabs(self) -> None:
        """Tab labels, each carrying its unread count."""
        nb = getattr(self, "_chat_nb", None)
        if nb is None:
            return
        for key, frame in self._chat_frames.items():
            unread = self._chat_unread.get(key, 0)
            label = self.t(f"chat.tab.{key}")
            if unread:
                label = f"{label} ({unread})"
            try:
                nb.tab(frame, text=label)
            except tk.TclError:
                pass

    def _chat_room(self, chat_type: str) -> str:
        """The room to answer in.

        For a DM that is the open conversation's room (a reply must go to the peer
        whose thread is on screen, not to whoever spoke last across all DMs). For any
        other tab it is the room of that tab's last message.
        """
        if chat_type == "dm":
            return self._dm_active_room
        for record in reversed(self._chat_msgs.get(chat_type, [])):
            room = str(record.get("room_id") or "").strip()
            if room:
                return room
        return ""

    def _update_chat_target(self) -> None:
        room = self._chat_room(self._active_chat_type())
        try:
            self._chat_room_var.set(room or "—")
        except tk.TclError:
            pass

    # -- sending -------------------------------------------------------------
    def _chat_send(self, args: list, what: str) -> None:
        """Run tools/chat_send.py with ``args``, streaming its output into the log.

        A child, like the monitors: the send walks the Lua VM several times and must
        not sit on the Tk thread. It does not claim the busy flag — a chat message is
        not a game action competing for the camera, and making a reply wait behind a
        collect run would be its own kind of wrong.
        """
        room = self._chat_room(self._active_chat_type())
        if not room:
            self.say("chat", "chat.no_room")
            return
        cmd = [self.rt.children.python(), "-u", os.path.join(TOOLS, "chat_send.py"),
               "--room", room] + args
        self.say("chat", "chat.sending", room=room, what=what)
        proc = self.rt.children.spawn_raw(cmd, "chat")
        if proc is None:
            return
        threading.Thread(target=self._chat_send_reader, args=(proc,),
                         daemon=True).start()

    def _chat_send_reader(self, proc) -> None:
        try:
            for raw in proc.stdout:
                line = raw.rstrip()
                if line:
                    self.rt.put(f"[chat] {line}")
        except Exception:
            pass

    def _chat_send_text(self) -> None:
        text = self._chat_msg_var.get().strip()
        if not text:
            return
        self._chat_msg_var.set("")
        self._chat_send(["--text", text], text[:40])

    def _chat_send_coords(self) -> None:
        """Share the coordinate written in the message box as a map pin.

        It used to be read from the Main tab's X/Y/server fields; that block is gone
        (#1183), so the box the message is typed into is the source — through the same
        tolerant parser the log's clickable links use, so anything a coordinate is
        written as elsewhere in the panel (`#2305 X:568 Y:371`, `@[568,371]`,
        `(568,371)`) can simply be pasted in and shared.
        """
        found = coords.parse(self._chat_msg_var.get())
        if not found:
            self.say("chat", "chat.no_coords")
            return
        _s, _e, x, y, srv = found[0]
        args = ["--coords", f"{x},{y}"]
        if srv is not None:
            args += ["--coord-server", str(srv)]
        # The box held the coordinate, not a message — clear it like a send does, or
        # the next «Отправить» would post the pin's text alongside the pin.
        self._chat_msg_var.set("")
        self._chat_send(args, coords.fmt(x, y, srv))

    # -- emoji / sticker picker ---------------------------------------------
    def _open_emoji_picker(self) -> None:
        """A popup of the game's emoji (insert inline) and stickers (send one).

        Both grids are drawn from the sprites `tools/chat_assets.py` already extracts
        — no game call needed to open the picker. An emoji click drops a `{e:<id>}`
        token into the message box; a sticker click sends that sticker as its own
        message (the game does not allow a sticker beside text).
        """
        old = getattr(self, "_emoji_win", None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass
        emojis = chat_assets.emoji_catalogue()
        stickers = chat_assets.sticker_catalogue()

        # rt.root, not `self`: a PanelTab is not a widget and Tk wants a window path
        # for both the master and the transient owner (#1235).
        top = tk.Toplevel(self.rt.root)
        self._emoji_win = top
        top.title(self.t("chat.picker.title"))
        top.transient(self.rt.root)
        ttk.Label(top, text=self.t("chat.picker.emoji"), anchor="w",
                 foreground="#8a8a8a").pack(fill="x", padx=8, pady=(8, 0))
        em_box = ScrolledText(top, wrap="char", state="disabled", cursor="arrow",
                            borderwidth=0, highlightthickness=0, padx=4, pady=4)
        em_box.pack(fill="both", expand=True, padx=8, pady=(2, 4))
        self._fill_picker(em_box, emojis, "emoji", 24)
        ttk.Label(top, text=self.t("chat.picker.sticker"), anchor="w",
                 foreground="#8a8a8a").pack(fill="x", padx=8, pady=(4, 0))
        st_box = ScrolledText(top, wrap="char", state="disabled", cursor="arrow",
                            height=4, borderwidth=0, highlightthickness=0, padx=4, pady=4)
        st_box.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        self._fill_picker(st_box, stickers, "sticker", 44)

        top.geometry("380x460")
        top.bind("<Escape>", lambda _e: top.destroy())
        try:
            top.update_idletasks()
            x = self.parent.winfo_rootx() + 60
            y = self.parent.winfo_rooty() + 80
            top.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

    def _fill_picker(self, box: "tk.Text", items: list, kind: str, px: int) -> None:
        """Draw one grid of clickable sprites into ``box`` (fresh widget, no stale tags)."""
        box.configure(state="normal")
        box.delete("1.0", "end")
        drawn = 0
        for idx, item in enumerate(items):
            img = self._chat_image(item["path"], px)
            if img is None:
                continue
            tag = f"{kind}{idx}"
            pos = box.index("end -1c")
            box.image_create("end", image=img)
            box.insert("end", " ")
            box.tag_add(tag, pos, f"{pos} +1c")
            if kind == "emoji":
                box.tag_bind(tag, "<Button-1>", lambda _e, it=item: self._pick_emoji(it))
            else:
                box.tag_bind(tag, "<Button-1>", lambda _e, it=item: self._pick_sticker(it))
            box.tag_bind(tag, "<Enter>", lambda _e, b=box: b.configure(cursor="hand2"))
            box.tag_bind(tag, "<Leave>", lambda _e, b=box: b.configure(cursor="arrow"))
            drawn += 1
        if drawn == 0:
            box.insert("end", self.t("chat.picker.empty"), ("token",))
        box.configure(state="disabled")

    def _pick_emoji(self, item: dict) -> None:
        """Insert an emoji token at the cursor; the picker stays open for more."""
        token = "{e:%s}" % item.get("id", "")
        entry = getattr(self, "_chat_entry", None)
        try:
            entry.insert("insert", token)          # at the caret
            entry.focus_set()
        except (tk.TclError, AttributeError):
            self._chat_msg_var.set(self._chat_msg_var.get() + token)

    def _pick_sticker(self, item: dict) -> None:
        """Send one sticker as its own message, then close the picker."""
        sid = str(item.get("id", ""))
        if sid:
            self._chat_send(["--sticker", sid], f"sticker {sid}")
        win = getattr(self, "_emoji_win", None)
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass

    def _build_dm_tab(self, parent: ttk.Frame) -> "tk.Text":
        """The DM tab: a contact list on the left, one conversation on the right.

        Returns the conversation Text view (which becomes ``_chat_trees['dm']`` so the
        generic lazy-load machinery drives it), while the contact list is its own
        read-only textbox drawn from the store. A contact = one DM peer; clicking it
        opens that peer's conversation and nothing else.
        """
        left = ttk.Frame(parent, width=210)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)          # keep the fixed sidebar width
        self.tr(ttk.Label(left, foreground="#8a8a8a"),
                 "chat.contacts").pack(anchor="w", padx=6, pady=(4, 2))
        lst = ScrolledText(left, wrap="none", state="disabled", cursor="arrow",
                         font=("Segoe UI", 9), borderwidth=0, highlightthickness=0,
                         padx=4, pady=2)
        lst.tag_configure("dmname", foreground="#d8d8d8")
        lst.tag_configure("dmlast", foreground="#8a8a8a")
        lst.tag_configure("time", foreground="#6f6f6f")
        lst.tag_configure("dmunread", foreground="#66bb6a")
        lst.tag_configure("dmactive", background="#2a3a52")
        lst.pack(fill="both", expand=True, padx=(2, 0), pady=(0, 4))
        self._dm_list = lst

        right = ttk.Frame(parent)
        right.pack(side="left", fill="both", expand=True)
        self._dm_header_var = tk.StringVar(value=self.t("chat.dm.pick"))
        ttk.Label(right, textvariable=self._dm_header_var, anchor="w",
                 foreground="#c8c8c8").pack(fill="x", padx=6, pady=(4, 0))
        return self._make_chat_tree(right)

    def _refresh_dm_contacts(self) -> None:
        """Repaint the contact sidebar from the store, newest conversation on top."""
        lst = self._dm_list
        if lst is None:
            return
        # Drop the previous rows' per-contact tags (and their click bindings): the
        # idx->contact mapping changes on every repaint, so a stale binding would
        # open the wrong peer. Style tags (dmname/…) are kept.
        for tag in lst.tag_names():
            if tag[:2] == "dm" and tag[2:].isdigit():
                lst.tag_delete(tag)
        lst.configure(state="normal")
        lst.delete("1.0", "end")
        contacts: list = []
        if self._chat_store is not None:
            try:
                contacts = self._chat_store.dm_contacts(self._chat_uid)
            except Exception:       # noqa: BLE001
                contacts = []
        if not contacts:
            lst.insert("end", self.t("chat.contacts.empty"), ("dmlast",))
            lst.configure(state="disabled")
            return
        for idx, contact in enumerate(contacts):
            self._render_contact_row(lst, idx, contact)
        lst.configure(state="disabled")

    def _render_contact_row(self, lst: "tk.Text", idx: int, contact: dict) -> None:
        """One contact: avatar + name + time on the first line, last message below."""
        tag = f"dm{idx}"
        start = lst.index("end -1c")
        img = self._chat_avatar({"sender_uid": contact.get("peer_uid", ""),
                                 "head_pic_ver": contact.get("head_pic_ver", "")})
        if img is not None:
            lst.image_create("end", image=img)
        lst.insert("end", " ")
        lst.insert("end", (contact.get("name") or "")[:16], ("dmname",))
        t_str = self._dm_contact_time(contact.get("last_ts", 0))
        if t_str:
            lst.insert("end", "  " + t_str, ("time",))
        unread = self._dm_unread.get(contact.get("room"), 0)
        if unread:
            lst.insert("end", f"  ●{unread}", ("dmunread",))
        lst.insert("end", "\n")
        prefix = (self.t("chat.you") + " ") if contact.get("last_mine") else ""
        preview = (prefix + (contact.get("last_text") or "")).replace("\n", " ")[:26]
        lst.insert("end", "    " + preview + "\n", ("dmlast",))
        end = lst.index("end -1c")
        lst.tag_add(tag, start, end)
        if contact.get("room") and contact.get("room") == self._dm_active_room:
            lst.tag_add("dmactive", start, end)
        lst.tag_bind(tag, "<Button-1>", lambda _e, c=contact: self._open_dm(c))
        lst.tag_bind(tag, "<Enter>", lambda _e: lst.configure(cursor="hand2"))
        lst.tag_bind(tag, "<Leave>", lambda _e: lst.configure(cursor="arrow"))

    @staticmethod
    def _dm_contact_time(ts) -> str:
        """A compact last-message stamp: HH:MM today, DD.MM on an earlier day."""
        from datetime import datetime as _dt
        if not ts:
            return ""
        try:
            when = _dt.fromtimestamp(ts)
        except (OSError, ValueError, OverflowError):
            return ""
        now = _dt.now()
        return when.strftime("%H:%M") if when.date() == now.date() else when.strftime("%d.%m")

    def _open_dm(self, contact: dict) -> None:
        """Show one DM peer's conversation in the DM tab, filtered to their room."""
        room = contact.get("room") or ""
        if not room:
            return
        self._dm_active_room = room
        self._dm_active_peer = contact.get("peer_uid") or ""
        self._dm_unread[room] = 0
        try:
            self._dm_header_var.set(contact.get("name") or room)
        except (tk.TclError, AttributeError):
            pass
        msgs: list = []
        self._chat_has_more["dm"] = False
        if self._chat_store is not None:
            msgs = self._chat_store.recent_room(room, CHAT_PAGE)
            if msgs:
                self._chat_has_more["dm"] = self._chat_store.has_older_room(
                    room, msgs[0].get("ts", 0))
        self._chat_msgs["dm"] = msgs
        self._chat_tree_rows["dm"] = 0
        self._rebuild_chat_view("dm")
        self._refresh_dm_contacts()      # re-highlight the open contact, clear its dot
        self._update_chat_target()

    def _bind_photo_links(self, widget) -> None:
        """Install the chat-photo handlers on a Text widget, once — see above."""
        widget.tag_bind("photolink", "<Button-1>",
                        lambda ev, w=widget: self._on_photo_link_click(w, ev))
        widget.tag_bind("photolink", "<Enter>",
                        lambda ev, w=widget: w.configure(cursor="hand2"))
        widget.tag_bind("photolink", "<Leave>",
                        lambda ev, w=widget: w.configure(cursor="arrow"))

    def _on_photo_link_click(self, widget, event) -> None:
        """Open the photo under the pointer full-size — which one is read off the
        embedded image, not off a tag that had to be kept alive to remember it."""
        try:
            here = widget.index(f"@{event.x},{event.y}")
            found = widget.dump(here, f"{here} +1c", image=True)
        except tk.TclError:
            return
        meta = self._photo_meta.get(found[0][1]) if found else None
        if meta is not None:
            self._open_photo(*meta)

    def _make_chat_tree(self, parent: ttk.Frame) -> "tk.Text":
        """Build a read-only Text view for one chat type, with a scrollbar.

        A Text widget (not a Treeview) is used so emoji / sticker sprites can be
        drawn inline with the message text via ``image_create``.
        """
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        txt = ScrolledText(frame, wrap="word", state="disabled", cursor="arrow",
                      font=("Segoe UI", 10), spacing1=1, spacing3=3,
                      borderwidth=0, highlightthickness=0, padx=6, pady=4)
        txt.tag_configure("time", foreground="#8a8a8a")
        txt.tag_configure("alliance", foreground="#5c9dff")
        txt.tag_configure("nick", foreground="#c8c8c8")
        txt.tag_configure("mine", foreground="#66bb6a")
        txt.tag_configure("token", foreground="#a586e0")
        # Same look the log gives a coordinate, so a clickable one reads as clickable
        # here too (bright blue, on the dark textbox).
        txt.tag_configure("coordlink", foreground="#5cf", underline=True)
        # Both link kinds are bound ONCE per view, for the same reason the header
        # below is: a handler laid down per rendered item stacks up for as long as
        # the panel is open (see `_bind_coord_links`).
        widgets.bind_coord_links(txt, self.rt.game.jump)
        self._bind_photo_links(txt)
        # The "↑ older messages" affordance drawn atop a partially-loaded tab.
        txt.tag_configure("loadmore", foreground="#5c9dff", underline=True,
                          justify="center")
        # Clicking the header pages in older history. Bound once here (not per
        # rebuild) so the handler cannot stack up; the tab is resolved at click time.
        txt.tag_bind("loadmore", "<Button-1>",
                     lambda _e, v=txt: self._chat_click_load_more(v))
        txt.tag_bind("loadmore", "<Enter>", lambda _e, v=txt: v.configure(cursor="hand2"))
        txt.tag_bind("loadmore", "<Leave>", lambda _e, v=txt: v.configure(cursor="arrow"))
        # ScrolledText carries its own scrollbars, so no ttk.Scrollbar is wired here.
        txt.pack(fill="both", expand=True)
        # Paging in older history: a scroll to the very top loads the previous
        # CHAT_PAGE. Bind on the inner tk.Text (ScrolledText proxies to `_textbox`);
        # add="+" so the widget's own scrolling is untouched. Wheel/keys all route
        # through one deferred check of the top fraction.
        inner = getattr(txt, "_textbox", txt)
        for seq in ("<MouseWheel>", "<Button-4>", "<Prior>", "<Up>", "<Home>"):
            inner.bind(seq, lambda _e, v=txt: v.after(40, lambda: self._on_chat_scroll(v)),
                       add="+")
        return txt

    def _chat_image(self, path: str, height: int):
        """Load (and cache) an inline sprite scaled to ``height`` px, or None.

        The cache is an LRU bounded at CHAT_IMG_CACHE_MAX. It used to be unbounded,
        and it holds a live Tk image per distinct (file, size) — one per sender's
        avatar and one per photo — so a night in world chat quietly turned into
        thousands of them. What falls out is what has not been drawn for longest,
        i.e. history far above the viewport; the newest page always keeps its
        pictures.
        """
        key = (path, height)
        img = self._chat_img_cache.get(key)
        if img is not None:
            self._chat_img_cache[key] = self._chat_img_cache.pop(key)   # touch (LRU)
            return img
        try:
            if _PIL_OK:
                im = _PILImage.open(path).convert("RGBA")
                w, h = im.size
                if h and h != height:
                    w = max(1, round(w * height / h))
                    im = im.resize((w, height), _PILImage.LANCZOS)
                img = _PILImageTk.PhotoImage(im)
            else:
                img = tk.PhotoImage(file=path)   # PNG, no scaling
        except Exception:       # noqa: BLE001
            return None
        self._chat_img_cache[key] = img
        self._trim_chat_images()
        return img

    def _trim_chat_images(self) -> None:
        """Drop the least recently drawn images once the cache is over its cap.

        The placeholder avatar is never evicted — it is the fallback every sender
        without a cached picture shares, so dropping it only means drawing it again.
        """
        cache = self._chat_img_cache
        while len(cache) > CHAT_IMG_CACHE_MAX:
            key = next(iter(cache))
            if key[0] == "__avatar_placeholder__":
                cache[key] = cache.pop(key)      # keep it: move to the young end
                continue
            self._photo_meta.pop(str(cache.pop(key)), None)

    _AVATAR_PX = 20

    def _chat_avatar(self, record: dict):
        """The avatar image for a message: the sender's cached JPG, else a placeholder.

        Returns a Tk image (never None when PIL is available); only if the image
        machinery is missing entirely does it return None, and the caller draws a
        text glyph instead.
        """
        uid = record.get("sender_uid") or ""
        ver = record.get("head_pic_ver") or ""
        path = chat_assets.avatar_path(uid, ver) if uid and ver else None
        if path:
            img = self._chat_image(path, self._AVATAR_PX)
            if img is not None:
                return img
        return self._chat_avatar_placeholder()

    def _chat_avatar_placeholder(self):
        """A cached neutral head-and-shoulders silhouette, sized like a real avatar."""
        key = ("__avatar_placeholder__", self._AVATAR_PX)
        img = self._chat_img_cache.get(key)
        if img is not None:
            return img
        px = self._AVATAR_PX
        try:
            if not _PIL_OK:
                return None
            im = _PILImage.new("RGBA", (px, px), (0, 0, 0, 0))
            d = _PILImageDraw.Draw(im)
            d.ellipse((0, 0, px - 1, px - 1), fill=(74, 78, 86, 255))        # disc
            head = (px * 0.32, px * 0.16, px * 0.68, px * 0.52)
            body = (px * 0.18, px * 0.56, px * 0.82, px * 1.04)
            d.ellipse(head, fill=(176, 180, 188, 255))
            d.ellipse(body, fill=(176, 180, 188, 255))
            img = _PILImageTk.PhotoImage(im)
        except Exception:       # noqa: BLE001
            return None
        self._chat_img_cache[key] = img
        return img

    @staticmethod
    def _chat_clear_view(view: "tk.Text") -> None:
        view.configure(state="normal")
        view.delete("1.0", "end")
        view.configure(state="disabled")

    def _insert_chat_text(self, view: "tk.Text", text: str) -> None:
        """Write chat text, turning coordinates into the same links the log makes.

        Chat is where coordinates actually ARRIVE — a rally target, a treasure, a base
        to hit — and it was the one place that inserted them as dead text while the
        log made them clickable.
        """
        pos = 0
        for (s, e, _x, _y, _srv) in coords.parse(text):
            if s > pos:
                view.insert("end", text[pos:s])
            widgets.insert_coord_link(view, text[s:e])
            pos = e
        if pos < len(text):
            view.insert("end", text[pos:])

    def _render_msg_line(self, view: "tk.Text", record: dict) -> None:
        """Append one chat message as a line, with sprites drawn inline."""
        from datetime import datetime as _dt
        ts = record.get("ts", 0)
        t_str = _dt.fromtimestamp(ts).strftime("%H:%M:%S") if ts else ""
        alliance = (record.get("alliance") or "")[:12]
        nick = (record.get("sender_name") or "")[:30]
        nick_tag = "mine" if record.get("is_mine") else "nick"
        view.configure(state="normal")
        view.insert("end", (t_str + " ") if t_str else "", ("time",))
        # Sender avatar, drawn inline before the nick. It resolves to the JPG the
        # client already cached under ChatPhotos (keyed by uid+headPicVer); a
        # built-in head with no cached file falls back to a neutral placeholder.
        av_img = self._chat_avatar(record)
        if av_img is not None:
            view.image_create("end", image=av_img)
            view.insert("end", " ")
        else:
            view.insert("end", "👤 ", ("token",))    # PIL/Tk image unavailable
        if alliance:
            view.insert("end", f"[{alliance}] ", ("alliance",))
        view.insert("end", nick + ": ", (nick_tag,))
        uid = record.get("sender_uid") or ""
        for kind, val in chat_assets.segments((record.get("msg") or "")[:300]):
            if kind == "text":
                self._insert_chat_text(view, val)
            elif kind == "token":
                # A photo token resolves to a JPG the client already cached on disk
                # (keyed by uid+picVer) -> render it; else a friendly placeholder.
                m = _PHOTO_TOK.match(val)
                path = chat_assets.photo_path(uid, m.group(1)) if m else None
                if path:
                    img = self._chat_image(path, 110)
                    if img is not None:
                        # Tag the image so a click opens it full-size (like the game).
                        # ONE shared tag, bound once per view (`_bind_photo_links`):
                        # a tag per photo left three callbacks behind on every chat
                        # rebuild, and the DM tab rebuilds its whole window whenever
                        # a message arrives. What was clicked is resolved from the
                        # image itself, which is cached and therefore bounded.
                        self._photo_seq += 1
                        pos = view.index("end -1c")
                        view.image_create(pos, image=img)
                        view.tag_add("photolink", pos, f"{pos} +1c")
                        self._photo_meta[str(img)] = (uid, m.group(1), path)
                        continue
                view.insert("end", self.t("chat.photo") if m else val, ("token",))
            elif kind == "image":
                # stickers are bigger objects than inline emoji
                height = 56 if (os.sep + "sticker") in val else 18
                img = self._chat_image(val, height)
                if img is not None:
                    view.image_create("end", image=img)
                else:
                    view.insert("end", "[img]", ("token",))
        view.insert("end", "\n")
        view.configure(state="disabled")

    def _open_photo(self, uid: str, pic_ver: str, fallback: str) -> None:
        """Open a chat photo full-size in a popup, like tapping it in the game."""
        path = chat_assets.photo_path(uid, pic_ver, big=True) or fallback
        if not path or not os.path.isfile(path):
            return
        sw, sh = self.parent.winfo_screenwidth(), self.parent.winfo_screenheight()
        max_w, max_h = int(sw * 0.85), int(sh * 0.85)
        try:
            if _PIL_OK:
                im = _PILImage.open(path).convert("RGBA")
                w, h = im.size
                # Fit within the screen; allow modest upscaling of small thumbnails.
                scale = min(max_w / w, max_h / h, 4.0)
                if abs(scale - 1.0) > 0.01:
                    im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                                   _PILImage.LANCZOS)
                photo = _PILImageTk.PhotoImage(im)
            else:
                photo = tk.PhotoImage(file=path)
        except Exception as exc:       # noqa: BLE001
            self.say("chat", "log.chat.photo_failed", error=exc)
            return
        top = tk.Toplevel(self.rt.root)      # a PanelTab is not a widget (#1235)
        top.title(self.t("tab.chat"))
        top.configure(bg="#000000")
        lbl = tk.Label(top, image=photo, bg="#000000", cursor="hand2")
        lbl.image = photo              # keep a reference alive
        lbl.pack()
        top.bind("<Button-1>", lambda e: top.destroy())
        top.bind("<Escape>", lambda e: top.destroy())
        top.update_idletasks()
        x = max(0, (sw - top.winfo_width()) // 2)
        y = max(0, (sh - top.winfo_height()) // 2)
        top.geometry(f"+{x}+{y}")
        top.transient(self.rt.root)
        top.focus_set()

    @staticmethod
    def _met_in_chat(met: dict, record: dict) -> None:
        """Whoever said this, as a row for the register of players (#1371).

        A chat line already carries a uid, a nickname, the speaker's alliance tag and
        their server — the panel decoded all four to draw the message. Nothing is asked
        of the game for this; a message that came in is a player we have seen.

        Our own messages are skipped: the register is of OTHER people, and a row for
        the account itself would sort into every list it is not about.
        """
        uid = str(record.get("sender_uid") or "").strip()
        if not uid or record.get("is_mine"):
            return
        server = str(record.get("server_id") or "").strip()
        met[uid] = {"uid": uid,
                    "name": (record.get("sender_name") or "").strip() or None,
                    "alliance_abbr": (record.get("alliance") or "").strip() or None,
                    "server_id": int(server) if server.isdigit() else None,
                    "head": (record.get("head_pic") or "").strip() or None,
                    "seen_at": int(record.get("ts") or time.time())}

    def _file_met(self, met: dict) -> None:
        """Hand a pump's worth of speakers to the register, OFF the Tk thread.

        A merge that changes anything rewrites the whole register, and this runs on the
        event loop every open profile's window shares (`docs/panel-tabs.md`).
        """
        rows = list(met.values())

        def work() -> None:
            try:
                self.rt.players.sighted(rows, source=players.SRC_CHAT)
            except Exception as exc:                                    # noqa: BLE001
                self.rt.dbg("chat").warning("players.sighted failed: %s", exc)

        threading.Thread(target=work, daemon=True).start()

    def _refresh_flow(self) -> None:
        """Rewrite the reader's own flow strip (#1549) — same module, same six states."""
        if getattr(self, "_flow_label", None) is None:
            return
        from ..runtime import flow

        said = flow.line(flow.badge(self.rt, INTAKE_CHAT))
        self._flow_var.set(self.t(said["key"], **said["fmt"]))
        try:
            self._flow_label.configure(foreground=said["colour"])
        except tk.TclError:
            pass

    def _web_flow(self) -> dict:
        """The same badge for the phone — data, never words (#1549)."""
        from ..runtime import flow

        badge = flow.badge(self.rt, INTAKE_CHAT)
        said = flow.line(badge)
        return {"key": said["key"], "fmt": said["fmt"], "colour": said["colour"],
                "state": badge.get("state")}

    def _pump_chat(self) -> None:
        """Drain the chat queue and refresh treeviews — scheduled every 1 s."""
        changed: set = set()
        rebuild: set = set()          # types whose whole window must be redrawn
        met: dict = {}                # whoever spoke, for the register (#1371)
        try:
            while True:
                record = self._chat_q.get_nowait()
                self.take(INTAKE_CHAT).kept()
                self._met_in_chat(met, record)
                chat_type = record.get("chat_type", "other")
                if chat_type not in self._chat_msgs:
                    chat_type = "other"
                # Persist first: the SQLite store is the history of record, so a
                # message is durable the moment it arrives (idempotent on identity).
                if self._chat_store is not None:
                    self._chat_store.append(record)
                # A DM does NOT go into one shared stream: it belongs to a contact.
                # The sidebar always updates; the conversation view only grows when
                # the message is for the peer currently open.
                if chat_type == "dm":
                    self._dm_contacts_dirty = True
                    room = str(record.get("room_id") or "")
                    if room and room == self._dm_active_room:
                        if self._dm_append(record):
                            rebuild.add("dm")
                        changed.add("dm")
                    elif not record.get("is_mine"):
                        self._dm_unread[room] = self._dm_unread.get(room, 0) + 1
                    if not record.get("is_mine") and "dm" != self._active_chat_type():
                        self._chat_unread["dm"] = self._chat_unread.get("dm", 0) + 1
                    continue
                msgs = self._chat_msgs[chat_type]
                # Order by the message's own serverTime (record["ts"]). The live
                # stream is already monotonic; only history re-parsed on scroll-up
                # arrives "from the past" -- resort and rebuild that tree then, so
                # old messages land in their proper place, not at the bottom. A plain
                # append just grows the bottom — no rebuild, only the new tail draws.
                out_of_order = bool(msgs) and record.get("ts", 0) < msgs[-1].get("ts", 0)
                msgs.append(record)
                if out_of_order:
                    msgs.sort(key=lambda r: r.get("ts", 0))
                    rebuild.add(chat_type)
                if len(msgs) > CHAT_MSGS_MAX:
                    # Bound the rendered list: drop the oldest overflow from memory.
                    # It is still in the store, so mark the tab as having more to page
                    # back in, and redraw so the load-more header appears.
                    del msgs[:len(msgs) - CHAT_MSGS_MAX]
                    self._chat_has_more[chat_type] = True
                    rebuild.add(chat_type)
                changed.add(chat_type)
                # Unread only counts somebody else's message in a tab nobody is
                # looking at: my own echo back is not news, and neither is a message
                # in the tab that is open.
                if not record.get("is_mine") and chat_type != self._active_chat_type():
                    self._chat_unread[chat_type] = self._chat_unread.get(chat_type, 0) + 1
        except queue.Empty:
            pass

        if met:
            self._file_met(met)

        if self._dm_contacts_dirty:
            self._dm_contacts_dirty = False
            self._refresh_dm_contacts()

        for chat_type in changed:
            if chat_type in rebuild:
                self._rebuild_chat_view(chat_type)
            else:
                self._update_chat_tree(chat_type)
        if changed:
            # A DM that arrives while another tab is open used to be silent.
            self._paint_chat_tabs()
            if self._active_chat_type() in changed:
                self._update_chat_target()

        # The count reflects the whole stored history, not just the loaded window.
        # `total()` is the running tally, not a fresh COUNT(*): this line runs once
        # a second for as long as the panel is open.
        total = (self._chat_store.total() if self._chat_store is not None
                 else sum(len(v) for v in self._chat_msgs.values()))
        self._chat_count_var.set(self.t("chat.count", n=total))
        # …and the flow strip on the same second (#1549): «идут ли данные ПРЯМО СЕЙЧАС»
        # is a question only a moving strip can answer.
        self._refresh_flow()
        self.rt.tick.arm("chat", 1000, self._pump_chat)

    def _dm_append(self, record: dict) -> bool:
        """Append a live DM to the OPEN conversation. True if a full rebuild is needed.

        Same ordering/cap rules as the generic append, but scoped to the DM tab's
        single-conversation window.
        """
        msgs = self._chat_msgs["dm"]
        need_rebuild = False
        if msgs and record.get("ts", 0) < msgs[-1].get("ts", 0):
            msgs.append(record)
            msgs.sort(key=lambda r: r.get("ts", 0))
            need_rebuild = True
        else:
            msgs.append(record)
        if len(msgs) > CHAT_MSGS_MAX:
            del msgs[:len(msgs) - CHAT_MSGS_MAX]
            self._chat_has_more["dm"] = True
            need_rebuild = True
        return need_rebuild

    def _update_chat_tree(self, chat_type: str) -> None:
        """Append records not yet rendered into the view, and autoscroll if at the bottom.

        Only the tail beyond ``_chat_tree_rows`` is drawn (an incremental append for
        the live stream). The view is kept pinned to the newest message ONLY when the
        reader is already there — a live message must not yank someone reading older
        history back down to the bottom.
        """
        view = self._chat_trees.get(chat_type)
        if view is None:
            return
        msgs = self._chat_msgs.get(chat_type, [])
        start = self._chat_tree_rows.get(chat_type, 0)
        if start >= len(msgs):
            return
        at_bottom = self._chat_view_at_bottom(view)
        for record in msgs[start:]:
            self._render_msg_line(view, record)
        self._chat_tree_rows[chat_type] = len(msgs)
        if at_bottom:
            view.see("end")

    @staticmethod
    def _chat_view_at_bottom(view: "tk.Text") -> bool:
        """True if the view is scrolled to (or very near) its bottom edge."""
        try:
            return float(view.yview()[1]) >= 0.999
        except (tk.TclError, ValueError, IndexError):
            return True

    def _chat_type_of_view(self, view) -> str | None:
        for key, v in self._chat_trees.items():
            if v is view:
                return key
        return None

    def _rebuild_chat_view(self, chat_type: str, keep_index: int | None = None) -> None:
        """Redraw a tab's whole in-memory window from scratch: the load-more header
        (when the store holds older messages than are in memory) followed by every
        loaded record.

        ``keep_index`` is the absolute index in ``_chat_msgs`` of the record to hold
        under the viewport after the redraw — used when paging in older messages so
        the reader stays on the line they were looking at instead of jumping.
        """
        view = self._chat_trees.get(chat_type)
        if view is None:
            return
        msgs = self._chat_msgs.get(chat_type, [])
        self._chat_clear_view(view)
        view.configure(state="normal")
        if self._chat_has_more.get(chat_type):
            view.insert("end", self.t("chat.load_more") + "\n", ("loadmore",))
        keep_mark = None
        for i, record in enumerate(msgs):
            if keep_index is not None and i == keep_index:
                keep_mark = view.index("end -1c")
            self._render_msg_line(view, record)
        view.configure(state="disabled")
        self._chat_tree_rows[chat_type] = len(msgs)
        if keep_mark is not None:
            view.see(keep_mark)
        else:
            view.see("end")

    def _chat_load_older(self, chat_type: str) -> None:
        """Page the previous CHAT_PAGE of history in from the store (top-anchored).

        The DM tab pages ONE conversation (its open room); every other tab pages its
        whole chat_type bucket.
        """
        if not self._chat_has_more.get(chat_type) or self._chat_store is None:
            return
        msgs = self._chat_msgs.get(chat_type, [])
        oldest_ts = msgs[0].get("ts", 0) if msgs else float("inf")
        if chat_type == "dm":
            room = self._dm_active_room
            if not room:
                return
            older = self._chat_store.older_room(room, oldest_ts, CHAT_PAGE)
            has_more = (lambda ts: self._chat_store.has_older_room(room, ts))
        else:
            older = self._chat_store.older(chat_type, oldest_ts, CHAT_PAGE)
            has_more = (lambda ts: self._chat_store.has_older(chat_type, ts))
        if not older:
            self._chat_has_more[chat_type] = False
            self._rebuild_chat_view(chat_type)
            return
        # Prepend the chunk; the record that WAS first is now at index len(older),
        # so hold it under the viewport — the new page appears above where the
        # reader already was.
        msgs[:0] = older
        self._chat_has_more[chat_type] = has_more(older[0].get("ts", 0))
        self._rebuild_chat_view(chat_type, keep_index=len(older))

    def _on_chat_scroll(self, view) -> None:
        """A scroll settled: if it reached the top and the store holds more, page it in."""
        try:
            top = float(view.yview()[0])
        except (tk.TclError, ValueError, IndexError):
            return
        if top > 0.001:
            return
        chat_type = self._chat_type_of_view(view)
        if chat_type and self._chat_has_more.get(chat_type):
            self._chat_load_older(chat_type)

    def _chat_click_load_more(self, view) -> None:
        """The '↑ show earlier messages' header was clicked."""
        chat_type = self._chat_type_of_view(view)
        if chat_type:
            self._chat_load_older(chat_type)

    def _toggle_chat(self) -> None:
        if self._chat_var.get():
            self._start_chat()
        else:
            self._stop_chat()

    def _start_chat(self) -> None:
        if self._chat_proc is not None:
            return
        out = self.rt.profiles.chat_log()
        try:
            os.makedirs(os.path.dirname(out), exist_ok=True)
        except Exception:
            pass
        rel = repo_rel(out)
        self.say("chat", "log.chat.starting", path=rel)
        self.say("chat", "log.chat.needs_daemon")
        # stderr is dropped, not folded in: chat_reader's stdout is a JSONL stream and
        # a traceback interleaved into it would be parsed as a message.
        mon = self.rt.children.spawn("chat",
                          [self.rt.children.python(), "-u", os.path.join(TOOLS, "chat_reader.py"),
                           "--seconds", "0", "--out", out],
                          on_line=self._on_chat_line, on_exit=self._on_chat_exit,
                          capture_stderr=False)
        if not mon.start():
            self._chat_var.set(False)
            return
        self._chat_proc = mon
        # The monitor means the game is alive: read the current character's uid now
        # and (re)open its history file, so captured messages land in the right
        # character's store — not whatever was open (or nothing) before.
        self._reopen_chat_store()
        self.say("chat", "log.chat.started", pid=mon.pid)

    def _on_chat_line(self, line: str) -> bool:
        """One JSONL record from the reader into the queue the Tk pump drains."""
        line = line.strip()
        if line:
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    # ONE MESSAGE REACHED THE PANEL'S DOOR (#1549). Counted here rather
                    # than in the pump, because the two answer different questions: this
                    # is «the reader is talking to us» and the pump is «we did something
                    # with it», and the gap between them is what a flow strip is for.
                    self.take(INTAKE_CHAT).seen()
                    self._chat_q.put(record)
            except json.JSONDecodeError:
                pass
        return False                    # never logged: it is data, not prose

    def _on_chat_exit(self) -> None:
        self.say("chat", "log.chat.ended")
        self._chat_proc = None
        self._chat_var.set(False)

    # chat_log.jsonl is written by chat_reader.py itself (`--out`), so the panel
    # does NOT append here: two processes appending to one file interleaved
    # their buffers, duplicating every record and corrupting utf-8 mid-line.

    def _stop_chat(self) -> None:
        mon, self._chat_proc = self._chat_proc, None
        if mon is not None:
            self.say("chat", "log.chat.stopped")
            mon.stop()

    def _clear_chat(self) -> None:
        """Remove all in-memory chat messages and clear all views.

        Only the on-screen state is cleared; the SQLite store is untouched, so the
        history is still there after a restart or profile switch. The tabs are left
        able to page it back in (has_more), rather than looking permanently empty.
        """
        for chat_type in list(self._chat_msgs):
            self._chat_msgs[chat_type].clear()
            view = self._chat_trees.get(chat_type)
            if view is not None:
                self._chat_clear_view(view)
            self._chat_tree_rows[chat_type] = 0
            if chat_type == "dm":
                # Close the open conversation; the contact list stays (it is the store).
                self._chat_has_more["dm"] = False
                continue
            self._chat_has_more[chat_type] = bool(
                self._chat_store and self._chat_store.count(chat_type))
            if self._chat_has_more[chat_type]:
                self._rebuild_chat_view(chat_type)      # draw the load-more header
        self._dm_active_room = ""
        self._dm_active_peer = ""
        if getattr(self, "_dm_header_var", None) is not None:
            self._dm_header_var.set(self.t("chat.dm.pick"))
        self._refresh_dm_contacts()
        self._chat_count_var.set(self.t("chat.count", n=0))

    def _load_chat_history(self) -> None:
        """Point the chat store at the CURRENT CHARACTER and render its newest page.

        Called on startup and on profile switch. The store is per character, not per
        profile, so the character's uid has to be read from the game first — a daemon
        round trip that must not sit on the Tk thread. Resolve it off-thread, then
        open the matching file back on the Tk thread.
        """
        self._reopen_chat_store()

    def _resolve_char_uid(self) -> str:
        """The logged-in character's uid, read live from the game (or "" if unknown).

        Empty when the game is not alive / not logged in or the daemon is not up —
        the caller then shows no history until the chat monitor starts and the uid
        can be read.
        """
        try:
            return str(chat_share.self_profile(self.rt.game.client).get("uid") or "")
        except Exception:       # noqa: BLE001 -- daemon down / game not alive
            return ""

    def _reopen_chat_store(self) -> None:
        """Resolve the current character's uid off-thread, then (re)open its store."""
        if self._chat_resolving:
            return
        self._chat_resolving = True

        def work() -> None:
            uid = self._resolve_char_uid()
            self.post(lambda: self._open_chat_store(uid))

        threading.Thread(target=work, daemon=True).start()

    def _open_chat_store(self, char_uid: str) -> None:
        """Open the SQLite store for ``char_uid`` and render the newest page per tab.

        Clears the current in-memory state first. An empty uid means the character is
        not known yet (game not alive): the tabs are simply left empty and no store is
        opened — persistence begins once the monitor starts and the uid resolves.
        """
        self._chat_resolving = False
        # Clear current state and drop the previous character's store.
        for chat_type in list(self._chat_msgs):
            self._chat_msgs[chat_type].clear()
            view = self._chat_trees.get(chat_type)
            if view is not None:
                self._chat_clear_view(view)
            self._chat_tree_rows[chat_type] = 0
            self._chat_has_more[chat_type] = False
        # The DM tab starts with no conversation open — the contact list is the entry
        # point, and a conversation loads only when a contact is clicked.
        self._dm_active_room = ""
        self._dm_active_peer = ""
        self._dm_unread = {}
        if getattr(self, "_dm_header_var", None) is not None:
            self._dm_header_var.set(self.t("chat.dm.pick"))
        if self._chat_store is not None:
            self._chat_store.close()
            self._chat_store = None
        self._chat_uid = char_uid or ""
        self._chat_count_var.set(self.t("chat.count", n=0))
        if not char_uid:
            self._refresh_dm_contacts()      # empties the sidebar too
            return

        try:
            store = chathistmod.ChatHistoryStore(self.rt.profiles.chat_db(char_uid))
        except Exception as exc:        # noqa: BLE001 -- a bad store must not kill startup
            self.say("chat", "log.error", error=exc)
            return
        self._chat_store = store

        total = 0
        for chat_type in CHAT_TABS:
            total += store.count(chat_type)
            # DMs are shown per contact, not as one stream — the sidebar handles them.
            if chat_type == "dm":
                continue
            recs = store.recent(chat_type, CHAT_PAGE)
            if not recs:
                continue
            self._chat_msgs[chat_type] = recs
            self._chat_has_more[chat_type] = store.has_older(
                chat_type, recs[0].get("ts", 0))
            self._chat_tree_rows[chat_type] = 0
            self._rebuild_chat_view(chat_type)

        self._refresh_dm_contacts()
        self._chat_count_var.set(self.t("chat.count", n=total))
        if total:
            self.say("chat", "log.chat.history", n=total)


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(ChatTab))

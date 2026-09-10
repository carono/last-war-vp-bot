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
from ..runtime import statevar

try:
    from PIL import (Image as _PILImage, ImageTk as _PILImageTk,
                     ImageDraw as _PILImageDraw)
    _PIL_OK = True
except Exception:       # noqa: BLE001 — inline pictures are optional, chat is not
    _PIL_OK = False

def _coord_parts(text: str):
    """The coordinate marks for one piece of chat prose, or ``None`` for none of them.

    The marking lives in `panel/web/coordlinks.py` because `tools/lib/coords.py` is the
    one parser this repository has and a second one written in JavaScript would be a
    second answer to «is this a place». Imported lazily and guarded: this tab is a Tk
    tab first, and a window that never serves a page must not pay for the web package.
    """
    try:
        from ..web import coordlinks
    except Exception:                       # noqa: BLE001 — a link, never the message
        return None
    try:
        return coordlinks.parts(text)
    except Exception:                       # noqa: BLE001
        return None


#: A photo in a message is written as this token by the reader child.
_PHOTO_TOK = re.compile(r"\[photo:(\d+)\]")

# The game writes its own rich text into chat — `<color=#fd5454>…</color>` around
# an alliance tag or a place name in a system announcement. Tk shows it as the tags
# it is; a browser would eat `<color=…>` as an unknown element and swallow the words
# inside it. Stripped to the words, so the phone reads the sentence and never markup.
_RICH_TAG = re.compile(r"</?(?:color|size|b|i|u)(?:=[^>]*)?>", re.IGNORECASE)

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
    #: THE EAR MUST BE UP WITHOUT ANYBODY LOOKING (#2064). The monitor is a switch a
    #: person leaves ON, and what it starts is a reader listening for messages that will
    #: not wait for somebody to click the tab: left lazy, a restart quietly stopped
    #: recording until the tab (or the phone's chat screen) was next opened, and a gap
    #: in a chat history looks exactly like a quiet hour. This is the case the flag was
    #: written for — and it costs a profile that has the tab off precisely nothing.
    EAGER = True
    PREFERRED_SIZE = "1000x760"
    LOCALE_NS = ("chat",)
    NEEDS = frozenset({"daemon", "children"})
    LEGACY_KEYS = {"chat_monitor": "chat_monitor"}

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        self._chat_var = statevar.boolean(rt.root, False)
        self._chat_q: "queue.Queue[dict]" = queue.Queue()
        self._chat_proc = None
        # THE EAR IS KEPT UP (#2418). The reader is a child process that dies with the
        # game it listens to — a client restart, a failed hook, a machine asleep — and a
        # dead ear used to switch the monitor OFF and file nothing until somebody
        # noticed. Nobody does: a chat that stopped growing looks exactly like a quiet
        # one. So the switch says what the PERSON wants and the child is brought back
        # while that is «on», with a widening gap so a client that is down is not
        # hammered.
        self._chat_wanted = False
        self._chat_retry = 0.0
        self._chat_retry_timer = None
        # THE ROOMS ARE THE CLIENT'S, NOT A TABLE IN THE CODE (#2418). The person's own
        # report: «не вижу все контакты, там есть другие группы, кастомные, их нету». A
        # player's own group is a room like any other and the client holds it by name —
        # the panel simply never asked, so its messages were tipped into «Другие» beside
        # the cross-server and season channels and the group's name was nowhere.
        # `room id -> {"name": str, "msgs": int}`, read on the LOOK and on a press.
        self._rooms: dict = {}
        self._rooms_read = 0.0
        self._rooms_busy = False
        # Rooms an arriving message revealed and the register was asked about, so a
        # room the client will not name costs one read and not one per message.
        self._rooms_asked: set = set()
        # `room|seq` -> (translation, language). The game's own answer, kept so a
        # reader can put the original back and read the translation again without a
        # second round trip (#2418).
        self._translated: dict = {}
        # AUTO-TRANSLATION (#2418): «пусть на все новые сообщения, которые не на моём
        # языке, сразу переводить». There is NO language on a message — measured, see
        # `actions/translate_chat_batch.md` — so what this can honestly do is translate
        # everything the GAME offers to translate, which is what the person chose when
        # told the finding. Off unless somebody switches it on, because it spends the
        # one game link: `_tr_queue` is what has arrived and not been asked about yet,
        # `_tr_at` is the earliest the next batch may go, and `_tr_busy` is a batch in
        # flight. Nothing here is a clock — the arrival of a message is the signal, and
        # the flush rides the queue's own pump.
        self._tr_auto = False
        self._tr_queue: dict = {}
        self._tr_at = 0.0
        self._tr_busy = False
        #: How many messages one batch asks about. One batch costs one three-second wait
        #: whether it carries one message or twenty, so the cap is about how much of a
        #: burst is worth catching up on rather than about the cost of a message.
        self._tr_done = 0
        # …and unread per ROOM, because a chip is a room now and not a kind.
        self._room_unread: dict = {}
        # uid -> the link its face is served on, or "". The lookup walks a few thousand
        # md5 sums, and the list draws sixty of them (`_face_for`).
        self._faces: dict = {}
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
        # Guards the backlog read against a second press while the first is still
        # in the game: it is one round trip, and two of them race for one link.
        self._backlog_busy = False
        # What a backlog read brought back before the store could be opened. The store
        # is keyed by the CHARACTER's uid and the uid is a game read taken off the Tk
        # thread, so a press from a phone — which reaches this tab before anybody has
        # looked at it — can finish first. Held here, folded in by `_open_chat_store`.
        self._backlog_pending: list = []
        # THE ROOMS THE SERVER HAS SAID ARE FINISHED (#2064). The game remembers this
        # per room itself (`GetIsChatHistoryEnd`), and this is the panel's copy of that
        # answer, so a thumb that keeps travelling upwards past the end asks nobody.
        self._history_end: set = set()
        # One deep read at a time, per room: the ask is a game round trip and a scroll
        # can fire several times before the first has answered.
        self._deep_busy: set = set()
        # HOW MANY ASKS IN A ROW BROUGHT NOTHING, per room. The game does not always
        # set its own end flag — measured live on the world room, which kept answering
        # «nothing» with `GetIsChatHistoryEnd()` still unset — so silence is read as the
        # end too, but only the SECOND one in a row: a single empty answer is also what
        # a slow reply inside the recipe's wait looks like, and one of those must not
        # close the history for the rest of the session.
        self._deep_empty: dict = {}
        # HOW MANY THAT ROOM'S LIST HELD at the end of the last ask. `READ_CHAT` brings
        # home the NEWEST `limit` of each room, and the fetched messages arrive at the
        # OLD end — so a fixed limit stops carrying them the moment the client holds
        # more than that, and the ask goes on succeeding while the store gains nothing.
        # Measured: `got: 100, filed: 0`, three times running.
        self._deep_hold: dict = {}

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
        # THE QUEUE IS DRAINED WITHOUT A WINDOW (#2418). The pump was armed in `build()`
        # — the method that DRAWS — so on the live panel, which has no window at all,
        # nothing ever took a message off the reader's queue: the ear heard, the child
        # wrote its own file, and the panel filed nothing and showed nothing. It belongs
        # with the state rather than with the drawing, exactly like the reader it
        # empties (`docs/panel-tabs.md`, the `LAZY` contract).
        self._pump_chat()
        self._read_rooms()
        if self._chat_var.get():
            self._start_chat()

    def on_show(self) -> None:
        self.ensure_loaded()

    def on_profile_switch(self) -> None:
        """A different account is a different chat: bounce the reader, drop what is on
        screen and re-open the store under the new character.

        THE TAIL OF THIS METHOD HAD BEEN LOST since #1221: the lines that close the
        store, forget the character and start the reader again had drifted below a
        `return` at the end of the web view's message helper, where they were
        unreachable. So a
        profile switch stopped the reader and cleared the widgets and then went on
        paging the PREVIOUS account's history out of a store that was never closed.
        """
        self._stop_chat()
        self._clear_chat()
        if self._chat_store is not None:
            self._chat_store.close()
            self._chat_store = None
        if self._read_store is not None:
            self._read_store.close()
            self._read_store = None
            self._read_store_uid = ""
        self._chat_uid = ""
        if self._loaded:
            self._load_chat_history()
        if self._chat_var.get():
            self._start_chat()
    # -- the phone ------------------------------------------------------------
    #
    # Reading AND answering. It was the reading alone while sending was a tool the tab
    # spawned — a press travels only when the ability is a scenario — and
    # `actions/send_chat_message.md` is that scenario now, so the box to answer in
    # travels too: a message and a map pin, into the room the card is showing.
    #
    # THE ROOM COMES FROM WHAT IS ON SCREEN, never from «wherever the window happens
    # to be looking»: a channel card answers its own channel, and a private message
    # answers the ROW it came from, because the window's open thread belongs to whoever
    # is at the machine. Outgoing chat cannot be unsent, so this is the one mistake
    # this tab must not make.
    #
    # It costs no game read at all: the messages are in this character's own SQLite
    # history, which the reader child fills whether or not anybody is looking.
    WEB_SCREEN = True

    #: How many messages a phone is handed per chat type. A screenful and a bit — the
    #: window pages further back, and a phone that wants the archive wants the window.
    WEB_MESSAGES = 30

    def web_view(self) -> "dict | None":
        import time as _time

        # THE CHAT SCREEN CARRIES NO MESSAGE CARDS AT ALL (#2418). They were the
        # fallback list for a front-end that does not draw a conversation — five cards
        # of thirty messages, marked `drawn` so the one front-end there is throws every
        # one of them away (`ScreenView.tsx`: `cards.filter(c => !(map && c.drawn))`).
        # The chat page re-asks `/api/screen` every couple of seconds, so that fallback
        # was 26.6 KB of a 35.2 KB reading built, serialised and discarded 24 times a
        # minute on a phone. The conversation itself has travelled on
        # `/api/screen/data?kind=page` since #2064 and is what the screen actually
        # shows; the send box, the picker and the room list are the ChatView's own.
        cards: list = []
        # THE PICKER IS NOT A PAIR OF GRIDS UNDER THE CHAT ANY MORE (#2418). The person:
        # «эмодзи и стикеры сделаны огромными таблицами под чатом, сделай дополнительные
        # кнопки, и в модалке сделай нужный выбор». Two hundred sprites laid out below
        # the conversation also made the screen a many-card one, which is what put a
        # PAGER over the chat — «убери пагинацию чатов». So they travel on their own
        # reading (`web_data(kind="picker")`), drawn in the one modal this panel has,
        # and the chat screen is left with no cards to page at all.
        # THE CHAT IS DRAWN, NOT LISTED (#2064). A conversation is not a card of rows:
        # it reads oldest-at-the-top with the box at the bottom, it opens on the newest
        # message, and scrolling up brings in older ones — «в игре именно такой
        # механизм». So the screen says what it is and the front-end draws it, through
        # the same door the world map goes through (#2018), and the messages travel on
        # `/api/screen/data` rather than on the screen's own poll.
        #
        # WHETHER THE EAR IS OPEN travels too (#2064). Nothing is written down while
        # the reader child is stopped, so a phone reading a chat with the monitor off is
        # reading a history that has quietly stopped growing — and until now the only
        # switch was the window's tick.
        return {"cards": cards, "now": _time.time(), "map": {"kind": "chat"},
                "listening": bool(self._chat_var.get()),
                # HOW OLD THE READING IS (#2418). A chat nobody has written into for an
                # hour and a chat whose ear has been down since Tuesday look identical —
                # the newest message is old in both. So the age travels and the phone
                # says it; stale is visibly stale rather than quietly wrong.
                "silent": self._chat_silence(),
                "waiting": bool(self._chat_wanted and self._chat_proc is None),
                "rooms": self._web_rooms(),
                # WHETHER ARRIVING MESSAGES ARE TRANSLATED AT ONCE (#2418), and how many
                # this run has done — the price of the switch, said where it is thrown.
                "autotr": bool(self._tr_auto),
                "autotr_done": int(self._tr_done),
                "actions": [{"id": "autotr",
                             "label": ("chat.autotr.off" if self._tr_auto
                                       else "chat.autotr.on")},
                            {"id": "history", "label": "chat.history.load"},
                            {"id": "rooms", "label": "chat.rooms.reload"}]}

    def _chat_silence(self) -> "float | None":
        """Seconds since the newest message this profile has filed, or ``None``.

        Judged on the GAME's clock, because the messages are stamped with the server's
        own time and the machine's is the one that lies (`tools/lib/game_clock.py`).
        """
        import game_clock

        newest = 0.0
        for chat_type in CHAT_TABS:
            rows = self._chat_msgs.get(chat_type) or ()
            if rows:
                try:
                    newest = max(newest, float(rows[-1].get("ts") or 0.0))
                except Exception:              # noqa: BLE001 — a bad stamp is no stamp
                    pass
        if not newest:
            return None
        try:
            now = game_clock.now_ms() / 1000.0
        except Exception:                      # noqa: BLE001 — no game, no judgement
            return None
        return max(0.0, now - newest)

    @staticmethod
    def _age_of(ts: float) -> "float | None":
        """Seconds since one message was said, on the GAME's clock, or ``None``.

        THE AGE OVER A CONVERSATION IS THAT CONVERSATION'S (#2418). `_chat_silence` is
        the age of the newest message in ANY room — the right answer to «is the ear
        alive» and the wrong one over an open room: measured live, «Мировой» whose last
        message was 14 minutes old was drawn «10 с назад» because a busy season group
        had just spoken. A stale conversation looking fresh is the exact reading this
        line exists to prevent, so a page carries the age of what is ON it.
        """
        import game_clock

        try:
            said = float(ts or 0.0)
        except Exception:                      # noqa: BLE001 — a bad stamp is no stamp
            return None
        if not said:
            return None
        try:
            now = game_clock.now_ms() / 1000.0
        except Exception:                      # noqa: BLE001 — no game, no judgement
            return None
        return max(0.0, now - said)

    def _web_picker(self) -> dict:
        """The sprites for the modal: the emoji to write with, the stickers to send.

        IT NAMES NO ROOM, AND THAT IS THE POINT (#2418). It used to be two grids on the
        screen whose taps carried a channel of the PICKER's own — defaulting to the
        world — so an emoji tapped while a private conversation was open was posted to
        the world chat, where everybody read it. The picker hands back pictures and
        nothing else now: the room is the one the conversation is in, decided where the
        send is made and nowhere else.

        Asked for when somebody opens the picker, so a chat nobody is decorating costs
        nothing.
        """
        import chat_assets

        try:
            catalogue = chat_assets.emoji_catalogue()
            grid = chat_assets.sticker_catalogue()
        except Exception:                 # noqa: BLE001 — nothing extracted is an empty picker
            catalogue, grid = [], []
        emoji, stickers = [], []
        for item in catalogue:
            link = chat_assets.sprite_link(item.get("path"))
            if link:
                emoji.append({"id": str(item.get("id") or ""), "icon": link,
                              "token": "{e:%s}" % item.get("id")})
        for item in grid:
            link = chat_assets.sprite_link(item.get("path"))
            if link:
                stickers.append({"id": str(item.get("id") or ""),
                                 "name": str(item.get("name") or ""), "icon": link})
        return {"emoji": emoji, "stickers": stickers}

    def web_press(self, action: str, args: dict) -> dict:
        """Answer into one card's room — the window's sends, and nothing else.

        All three play `send_chat_message`. THE PICKER TRAVELS TOO since #1976: the
        sprites are served over the panel's own port (`/api/chatsprite`), an emoji opens
        the send box with its token in it, and a sticker goes as its own message because
        the game does not allow one beside text.
        """
        args = args or {}
        if action == "listen":
            # THE EAR ITSELF, from the phone (#2064). Catching the pushes is what keeps
            # the history growing, and the only switch for it was the window's tick — so
            # a phone could sit reading a chat that had stopped recording hours ago, with
            # nothing on the page saying so. This is not a press at the game: it starts
            # (or stops) this profile's own reader child, exactly as the tick does, on
            # the thread the tick lives on.
            want = bool(args.get("on"))
            self.post(lambda: self._set_listening(want))
            return {"ok": True}
        if action == "history":
            # The same press the window's «Загрузить историю» is: one read of what the
            # client already holds, folded into the same store.
            return {"ok": self._load_backlog()}
        if action == "older":
            # THE ONE PLACE THE CHAT TALKS TO THE SERVER (#2064). A person's thumb has
            # travelled past everything this profile has on disk and past everything the
            # client is holding, and the words they are looking for are on the server.
            return self._ask_server_for_older(str(args.get("room") or "").strip(),
                                              str(args.get("type") or ""))
        if action == "autotr":
            # THE SWITCH, and it is a switch rather than a press at the game (#2418):
            # what it decides is whether an ARRIVING message is queued. Off by default —
            # a batch holds the game for about four seconds, and this is the one link.
            self._tr_auto = not self._tr_auto
            if not self._tr_auto:
                self._tr_queue.clear()
            # …AND WRITTEN DOWN, the same road the ear's switch takes (#2064): a knob
            # moved from the phone reaches the state directly, so nothing else would
            # save it, and a switch a restart forgets is a switch nobody trusts.
            self.rt.settings.changed()
            return {"ok": True, "on": self._tr_auto}
        if action == "translate":
            # THE GAME'S OWN TRANSLATOR (#2418) — «в чате есть функция перевода, изучи
            # её, сделай эту возможность». Nothing leaves this machine for an outside
            # service: the client has the button and the answer comes back ON the
            # message. One press, one message, and the original is never overwritten —
            # the phone keeps both and shows whichever the reader asked for.
            return self._translate(str(args.get("room") or "").strip(),
                                   str(args.get("seq") or "").strip())
        chat_type = str(args.get("type") or "")
        if action == "rooms":
            # ASKED FOR, NEVER TIMED. The client's own list, re-read because somebody
            # pressed — a group joined five minutes ago appears on the next press and
            # not on a clock nobody asked for.
            return {"ok": self._read_rooms(force=True)}
        if action not in ("send", "coords", "sticker") or chat_type not in CHAT_TABS:
            return {"error": "unknown"}
        # THE ROOM IS SAID OUTRIGHT OR NOTHING IS SENT (#2418). A private message went
        # to the WORLD chat once — an emoji tapped in the old picker carried the
        # picker's own channel, which defaulted to the world — and everybody read it.
        # There is no falling back to «the last room of that kind» any more, and least
        # of all to the world: the most expensive mistake this panel can make must never
        # be anybody's default. A press that cannot name its room is refused and says so.
        room = str(args.get("room") or "").strip()
        if not room:
            return {"ok": False, "reason": "chat.no_room"}
        if room not in self._known_rooms(chat_type) and room not in self._rooms:
            return {"error": "unknown"}
        # …AND THE ROOM AND THE KIND MUST AGREE. A DM room reaching this with `world` on
        # it is the shape the leak had, so it is refused rather than reconciled: one of
        # the two is wrong and there is no way to tell which.
        if chathistmod.classify_room(room) != chat_type:
            return {"ok": False, "reason": "chat.no_room"}
        if action == "sticker":
            # A STICKER IS ITS OWN MESSAGE — the game allows no text beside it, which is
            # why the window's grid sends on the click instead of writing into the box.
            sticker = str(args.get("id") or "").strip()
            if not sticker:
                return {"error": "unknown"}
            return {"ok": self._chat_send({"sticker": sticker},
                                          f"sticker {sticker}", room=room)}
        typed = str(args.get("text") or "").strip()
        if not typed:
            return {"ok": False, "reason": "chat.nothing_typed"}
        if action == "send":
            return {"ok": self._chat_send({"text": typed}, typed[:40], room=room)}
        found = coords.parse(typed)
        if not found:
            return {"ok": False, "reason": "chat.no_coords"}
        _s, _e, x, y, srv = found[0]
        payload = {"coords": f"{x},{y}"}
        if srv is not None:
            payload["server"] = str(srv)
        return {"ok": self._chat_send(payload, coords.fmt(x, y, srv), room=room)}

    #: How many messages one scroll-up brings in. A screenful and a bit, so the reader
    #: never sees the end of what was fetched.
    WEB_PAGE = 40

    def web_data(self, kind: str, args: dict) -> "dict | None":
        """The chat itself — a page of it, read from the STORE and never from the game.

        THIS IS WHERE THE «read once, then LISTEN» RULE IS KEPT for scrolling. Paging
        upwards asks this profile's own SQLite history and nothing else: no round trip,
        no question to the server, nothing that a person scrolling fast could turn into
        a poll. The game is asked exactly once, by «Загрузить историю», when a person
        presses it.

        **What happens at the bottom of the store is deliberate:** the client itself
        holds only the newest few dozen messages per room, and `READ_CHAT` has already
        taken those, so once the store runs out there is nothing left to read without
        `ChatRoomRequestHistoryMsg` — a REQUEST TO THE SERVER. That request exists now,
        it was asked for and agreed («опрос сервера при прокрутке тоже сделай»), and it
        is NOT made here: this page only says whether it would still be worth making
        (`server`, `deep_room`), and the ask itself is a press — `_ask_server_for_older`,
        one scroll, one request, never a clock.

        Answered on an HTTP worker thread, so nothing here touches a widget.
        """
        args = args or {}
        if kind == "picker":
            return self._web_picker()
        if kind == "contacts":
            store = self._store_for_reading()
            if store is None:
                return {"contacts": []}
            try:
                contacts = store.dm_contacts(self._chat_uid)
            except Exception:                  # noqa: BLE001 — a closed store is empty
                return {"contacts": []}
            out = []
            for c in contacts:
                room = str(c.get("room") or "")
                out.append({"room": room,
                            "who": str(c.get("name") or c.get("peer_uid") or "?"),
                            "uid": str(c.get("peer_uid") or ""),
                            "text": str(c.get("last_text") or ""),
                            "ts": float(c.get("last_ts") or 0.0),
                            "when": self._web_when(float(c.get("last_ts") or 0.0)),
                            "mine": bool(c.get("last_mine")),
                            "unread": int(self._dm_unread.get(room, 0))})
            return {"contacts": out}
        if kind != "page":
            return None
        chat_type = str(args.get("type") or "world")
        room = str(args.get("room") or "").strip()
        limit = max(1, min(200, int(args.get("limit") or self.WEB_PAGE)))
        before = args.get("before")
        store = self._store_for_reading()
        if store is None:
            return {"rows": [], "more": False, "room": room, "type": chat_type}
        try:
            if room:
                rows = (store.older_room(room, float(before), limit) if before
                        else store.recent_room(room, limit))
                more = bool(rows) and store.has_older_room(room, rows[0].get("ts", 0))
            else:
                rows = (store.older(chat_type, float(before), limit) if before
                        else store.recent(chat_type, limit))
                more = bool(rows) and store.has_older(chat_type, rows[0].get("ts", 0))
        except Exception:                      # noqa: BLE001 — a bad page is an empty one
            return {"rows": [], "more": False, "room": room, "type": chat_type}
        if room:
            # SOMEBODY IS READING IT, so it is not unread any more. The window clears
            # its own marks by opening a tab; the phone's chip is a room, and this is
            # the moment it was opened.
            self._room_unread.pop(room, None)
        # WHICH ROOM a deeper read would name, and whether it is still worth naming.
        # Resolved from what was just served rather than from the drawn tab: this
        # answers on an HTTP thread, and the tab may never have been looked at.
        asked = room or (str(rows[-1].get("room_id") or "").strip() if rows else "")
        return {"rows": [self._web_row(r) for r in rows], "more": more,
                "room": room, "type": chat_type,
                # HOW OLD THIS CONVERSATION IS (#2418) — see `_age_of`. The screen's
                # own `silent` answers for the EAR; this answers for what is on screen.
                "age": self._age_of(rows[-1].get("ts")) if rows else None,
                "server": bool(asked) and asked not in self._history_end,
                "deep_room": asked}

    #: A store opened for READING alone, off the Tk thread. Kept apart from
    #: `_chat_store` — that one belongs to the drawn tab and is closed with it.
    _read_store = None
    _read_store_uid = ""

    def _store_for_reading(self):
        """The history to page through, opened without asking the game anything.

        A phone opening the chat on a freshly started panel must see the messages that
        are already on disk. `_chat_store` is opened by the drawn tab, and resolving
        WHICH character it belongs to costs a game round trip — which is exactly what a
        page of history must not cost. So the character last read (`chat_uid`, kept in
        this tab's own saved block) names the file, and it is opened read-only here on
        the HTTP thread. No widget, no game, no round trip.
        """
        if self._chat_store is not None:
            return self._chat_store
        uid = str(self._chat_uid or "") or self._only_history_on_disk()
        if not uid:
            return None
        if self._read_store is not None and self._read_store_uid == uid:
            return self._read_store
        try:
            self._read_store = chathistmod.ChatHistoryStore(
                self.rt.profiles.chat_db(uid))
            self._read_store_uid = uid
        except Exception:                      # noqa: BLE001 — no store is an empty page
            self._read_store = None
        return self._read_store

    def _only_history_on_disk(self) -> str:
        """The character a lone history file belongs to, when there is exactly one.

        A phone opening this screen on a freshly started panel has no `chat_uid` yet:
        the tab remembers it once it has read the game, and until somebody opens the tab
        nothing has. A profile that has ever collected chat holds a
        `chat_history_<uid>.db` beside its log, and when there is exactly ONE of them
        the character is not a guess — it is the only answer the disk has.

        TWO OR MORE IS NOT ANSWERED HERE. A person who has played several characters on
        one account would be shown whichever file sorted first, and a chat drawn under
        the wrong character's name is worse than an empty page. Then the screen stays
        empty until the tab has asked the game who is logged in.
        """
        import glob

        try:
            found = glob.glob(os.path.join(self.rt.profiles.dir(), "chat_history_*.db"))
        except Exception:                      # noqa: BLE001 — no directory, no history
            return ""
        if len(found) != 1:
            return ""
        stem = os.path.basename(found[0])
        return stem[len("chat_history_"):-len(".db")]

    def _web_when(self, ts: float) -> str:
        """A short «when» for a contact row — the time today, the date before that."""
        import game_clock

        if not ts:
            return ""
        stamp = time.localtime(ts)
        today = time.localtime(game_clock.now_ms() / 1000.0)
        if (stamp.tm_year, stamp.tm_yday) == (today.tm_year, today.tm_yday):
            return time.strftime("%H:%M", stamp)
        return time.strftime("%d.%m.%Y", stamp)

    def _web_row(self, record: dict) -> dict:
        """One message as the phone draws it — a bubble, with its own time on it.

        THE TIME IS THE GAME'S, and getting that wrong is a mistake this repository has
        made before: a stamp in the game's milliseconds compared against the machine's
        seconds put readings hours out. `record["ts"]` is the message's own `serverTime`
        — already the game's clock — and the only thing judged against «now» is which
        DAY it belongs to, so that «сегодня» means the game's today and not the phone's.
        `tools/lib/game_clock.py` is what answers for now, and when it has never been
        synced the label simply carries the full date instead of guessing.
        """
        import game_clock

        ts = float(record.get("ts") or 0.0)
        stamp = time.localtime(ts) if ts else None
        now_ms = game_clock.now_ms()
        today = time.localtime(now_ms / 1000.0)
        when = time.strftime("%H:%M", stamp) if stamp else ""
        day = ""
        if stamp:
            same = (stamp.tm_year, stamp.tm_yday) == (today.tm_year, today.tm_yday)
            yesterday = (stamp.tm_year, stamp.tm_yday) == (today.tm_year,
                                                           today.tm_yday - 1)
            if not same:
                # «Вчера» only when the game's own clock has actually been read; an
                # un-synced clock names the date outright rather than guessing a
                # relation to a «now» nobody has measured.
                day = ("chat.day.yesterday" if (yesterday and game_clock.synced())
                       else time.strftime("%d.%m.%Y", stamp))
        parts, photo = self._web_parts(record)
        room = str(record.get("room_id") or "")
        return {"id": "%s|%s|%s" % (room, record.get("seq_id") or "",
                                    record.get("sender_uid") or ""),
                # The message's own sequence id, on its own: a press that asks the game
                # to translate this row names the room and the seq, and picking them out
                # of the id above would be the front-end knowing how one is built.
                "seq": str(record.get("seq_id") or ""),
                # WHETHER THE GAME OFFERS TO TRANSLATE IT (#2418). Its own answer where
                # the recorder carried one — a coordinate share and a system post are
                # refused by the client itself, and an offer the game will not honour is
                # a button that can only disappoint. A row filed before the recorder
                # carried it falls back to «a plain message, and not my own».
                "tr": self._can_translate(record),
                "ts": ts, "when": when, "day": day,
                "who": str(record.get("sender_name") or "?"),
                "uid": str(record.get("sender_uid") or ""),
                # THE FACE TRAVELS WITH THE MESSAGE (#2418). Only the file's NAME goes
                # to the phone, on the same route every other face on this panel uses;
                # somebody who never uploaded a photo has none, and the bubble draws an
                # initial rather than borrowing anybody else's picture.
                "face": self._face_for(record.get("sender_uid")),
                "alliance": str(record.get("alliance") or ""),
                "mine": bool(record.get("is_mine")),
                "room": room, "parts": parts, "photo": photo,
                # WHAT IT ANSWERS (#2418). The quote the game shows above a reply, plus
                # the ID OF THE MESSAGE IT NAMES — the same id this row is keyed by, so
                # the front-end can walk to it without knowing how one is built.
                # WHAT THE GAME ALREADY ANSWERED FOR THIS ROW (#2418). Sent only
                # while auto-translation is on: that is the mode in which a translation
                # is meant to be READ instead of the original, and a reader who tapped
                # one by hand has it on the phone already. The original travels
                # untouched beside it, so the same tap puts it back.
                "trtext": (self._translated.get(f"{room}|{record.get('seq_id')}",
                                                ("", ""))[0]
                           if self._tr_auto else ""),
                "reply": self._web_reply(record, room)}

    @staticmethod
    def _can_translate(record: dict) -> bool:
        """Does the GAME offer a translation for this message?

        `isShowTranslateBtn()` is the client's own answer and the recorder carries it,
        measured live: a coordinate share (`post = 13`) answers false, an ordinary
        message answers true. Rows filed before the recorder carried it have to be
        judged here, and the honest guess is the one the post already makes — a plain
        message, and never one of my own, which the game does not offer either.
        """
        if record.get("is_mine"):
            return False
        if "can_translate" in record:
            return bool(record.get("can_translate"))
        return str(record.get("post") or "0") in ("0", "0.0", "")

    @staticmethod
    def _web_reply(record: dict, room: str) -> "dict | None":
        """The quote above a reply — who was answered, what they said, and which row."""
        reply = record.get("reply")
        if not isinstance(reply, dict) or not reply.get("seq_id"):
            return None
        return {"id": "%s|%s|%s" % (room, reply.get("seq_id") or "",
                                    reply.get("uid") or ""),
                "who": str(reply.get("name") or ""),
                "text": str(reply.get("text") or "")}

    def _web_parts(self, record: dict) -> tuple:
        """Split one message into what the phone draws: text, sprites, and a photograph.

        The same split the window's `tk.Text` gets (`chat_assets.segments`), so an emoji
        and a sticker are the picture they are on both front-ends rather than a
        `[e:E006]` on one of them. A PHOTOGRAPH is not a segment: it is the message, and
        it is carried beside the text with the pair that names it, so a tap can ask for
        the full-size copy.
        """
        import chat_assets

        text = _RICH_TAG.sub("", str(record.get("msg") or ""))
        photo = None
        m = _PHOTO_TOK.search(text)
        if m:
            uid = str(record.get("sender_uid") or "")
            small = chat_assets.photo_link(uid, m.group(1))
            if small:
                photo = {"small": small,
                         "big": chat_assets.photo_link(uid, m.group(1), big=True)}
            else:
                # A PHOTOGRAPH THAT CANNOT EVEN BE NAMED IS SAID, NOT SWALLOWED (#2418).
                # The token was stripped whatever happened, so a message that is only a
                # picture came out as an EMPTY bubble — «изображения не грузятся» with
                # nothing on screen to explain it. This branch is now only the pair that
                # is not a pair (a sender uid or a `[photo:N]` number that is not
                # digits); everything else gets a link, and the panel FETCHES the
                # picture off the game's own CDN the first time somebody looks at it
                # (`chat_assets.photo_fetch`). It had to: the client downloads a chat
                # photograph only while its own chat window is drawing the message, and
                # the panel never opens it — measured live, `ChatPhotos` did not exist
                # on this machine at all. A picture the CDN does not know is a 404 on
                # the route, and the phone draws the same sentence.
                photo = {"small": "", "big": "", "missing": True}
            text = (text[:m.start()] + text[m.end():]).strip()
        parts = []
        for kind, value in chat_assets.segments(text):
            if kind == "image":
                link = chat_assets.sprite_link(value)
                if link:
                    parts.append({"t": "img", "v": link})
                    continue
                kind = "token"
            if kind in ("text", "token") and str(value):
                if parts and parts[-1]["t"] == "text":
                    parts[-1]["v"] += str(value)
                else:
                    parts.append({"t": "text", "v": str(value)})
        # A COORDINATE IN A MESSAGE IS A LINK, on the phone as in the window (#1982).
        # Chat is where places actually arrive — a rally target, a treasure, a base to
        # hit — so the same marker the rest of the web panel uses runs over the words
        # here, and the browser draws what it is handed rather than parsing anything
        # itself. `tools/lib/coords.py` stays the one parser in this repository.
        for part in parts:
            if part["t"] != "text":
                continue
            marks = _coord_parts(part["v"])
            if marks is not None:
                part["parts"] = marks
        return parts, photo

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
        # The character whose history this is, remembered (#2064). Not game data — it is
        # WHICH FILE to open, and remembering it is what lets a fresh panel show the
        # messages it already has without asking the game who is logged in. The game
        # remains the authority: the next read overwrites it.
        return {"chat_monitor": bool(self._chat_var.get()),
                "chat_autotr": bool(self._tr_auto),
                "chat_uid": str(self._chat_uid or "")}

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self._chat_var.set(bool(raw.get("chat_monitor", False)))
        # Off unless it was switched on: it spends the game link, so a profile that has
        # never been asked gets nothing (#2418).
        self._tr_auto = bool(raw.get("chat_autotr", False))
        self._chat_uid = str(raw.get("chat_uid") or "")

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
        self._chat_room_var = statevar.string(None, "—")
        self.tr(ttk.Label(send), "chat.to").pack(side="left")
        ttk.Label(send, textvariable=self._chat_room_var, foreground="#888",
                  width=26).pack(side="left", padx=(4, 6))
        # The emoji / sticker picker: a game emoji goes inline into the text as a
        # {e:<id>} token (chat_send resolves it), a sticker is sent as its own
        # message (the game does not let a sticker ride alongside text).
        ttk.Button(send, text="😊", width=32, command=self._open_emoji_picker).pack(
            side="left", padx=(0, 4))
        self._chat_msg_var = statevar.string(None)
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
        # THE HISTORY IS LOADED, not only listened for (#2064). One press, one round
        # trip to the client's own per-room copy — never a clock.
        self.tr(ttk.Button(bot, command=self._load_backlog),
                 "chat.history.load").pack(side="left")
        self.tr(ttk.Button(bot, command=self._clear_chat),
                 "chat.clear").pack(side="left", padx=(4, 0))
        self._chat_count_var = statevar.string(None, self.t("chat.count", n=0))
        ttk.Label(bot, textvariable=self._chat_count_var, foreground="#888").pack(
            side="right", padx=8)
        # IS THE READER STILL TALKING TO US (#1549). The chat window has looked exactly
        # the same when the reader had exited as when the alliance simply had nothing to
        # say, and «чат молчит» is the most common way a dead child shows itself. The
        # same strip every fed grid in the panel has, out of the same module.
        self._flow_var = statevar.string(None, "")
        self._flow_label = ttk.Label(bot, textvariable=self._flow_var)
        self._flow_label.pack(side="left", padx=(12, 0))
        self._refresh_flow()
        self.rt.i18n.hook(self._retranslate_chat_bottom)

        self._pump_chat()      # idempotent: `ensure_loaded` has usually armed it already

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

    # -- the rooms the client is in ------------------------------------------
    #
    # ONE READ, ON THE LOOK. `read_chat_rooms` asks the CLIENT what it holds — no
    # question reaches the server — and it is played when the tab is first needed and
    # when somebody presses «Обновить». Never on a clock: a chip that appeared a minute
    # late is a chip, and a poll is a robbery that did not happen.

    #: A room read that is younger than this is not made again — a person tapping
    #: between screens must not turn the look into a beat. Seconds.
    ROOMS_FRESH = 60.0

    #: What a room id says about itself when the client gave it no name of its own.
    #: Prefix, longest first — `alliance_friend_` must beat `alliance_`.
    ROOM_KEYS = (
        ("alliance_friend_", "chat.room.alliance_friend"),
        ("country_", "chat.tab.world"),
        ("custom_lang_", "chat.tab.national"),
        ("crossbattle_", "chat.room.crossbattle"),
        ("season_faction_war", "chat.room.season_war"),
        ("custom_season_", "chat.room.season"),
        ("custom_group_", "chat.room.group"),
        ("alliance_", "chat.tab.alliance"),
    )

    def _read_rooms(self, force: bool = False) -> bool:
        """Ask the client for its rooms, off the Tk thread. False when it was too soon."""
        if self._rooms_busy:
            return False
        if not force and (time.time() - self._rooms_read) < self.ROOMS_FRESH:
            return False
        self._rooms_busy = True

        def work() -> None:
            found: dict = {}
            try:
                outcome = self.rt.play_now("read_chat_rooms", {},
                                           human=True, tag="chat")
                got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
                found = self._parse_rooms(str(got.get("rooms") or ""))
            except Exception as exc:            # noqa: BLE001 — a failed read, not a dead tab
                self.post(lambda: self.say("chat", "log.error", error=exc))
            self.post(lambda: self._absorb_rooms(found))

        threading.Thread(target=work, daemon=True).start()
        return True

    @staticmethod
    def _parse_rooms(raw: str) -> dict:
        """`<id>\t<name in hex>\t<messages>`, `;;` between rooms — as the recipe leaves it.

        The name is hex because a group is named by a person and may hold any byte; a
        line that will not decode keeps the room and loses the name, which is the way
        round that shows a chip rather than hiding one.
        """
        out: dict = {}
        for line in raw.replace("\r", "").replace("\n", ";;").split(";;"):
            bits = line.split("\t")
            room = bits[0].strip() if bits else ""
            if not room:
                continue
            name = ""
            if len(bits) > 1 and bits[1].strip():
                try:
                    name = bytes.fromhex(bits[1].strip()).decode("utf-8", "replace")
                except ValueError:              # noqa: PERF203 — a mangled name, not a lost room
                    name = ""
            def _num(at: int) -> float:
                if len(bits) <= at:
                    return 0.0
                try:
                    return float(bits[at].strip() or 0)
                except ValueError:
                    return 0.0
            # `isPin` is the client's own flag and the ONLY one there is: measured, not
            # guessed — it is on all 69 rooms, and `pinTime` / `isTop` / `topTime` /
            # `stick` / `sortWeight` are on none of them. So there is no order BETWEEN
            # pinned rooms to read, and they are sorted by their last message like the
            # rest of the list.
            out[room] = {"name": name, "msgs": int(_num(2)),
                         "pin": bool(_num(3)), "last": _num(4) / 1000.0}
        return out

    def _absorb_rooms(self, found: dict) -> None:
        """Put the read away, on the Tk thread. An empty answer changes nothing.

        THE FLAG IS CLEARED HERE, WHATEVER CAME BACK. A read made while the link was
        not up yet — the boot does exactly that — answers with nothing, and leaving the
        flag standing meant no look and no press could ever ask again.
        """
        self._rooms_busy = False
        if not found:
            return                              # …and `_rooms_read` stays old, so the
        # A ROOM THE EAR HEARD IS NOT DROPPED BY A READ THAT MISSED IT (#2418). The
        # client's answer wins wherever it has one — it carries the name, the pin and
        # the client's own stamp — but a room only this panel has heard from keeps its
        # entry, so a chip cannot disappear the moment the register is refreshed.
        merged = dict(self._rooms)
        merged.update(found)
        for room, info in found.items():
            was = float((self._rooms.get(room) or {}).get("last") or 0.0)
            if was > float(info.get("last") or 0.0):
                merged[room] = dict(info, last=was)
        self._rooms = merged                    # next look asks again rather than
        self._rooms_read = time.time()          # trusting an answer nobody gave.

    def _room_heard(self, room: str, ts: float) -> None:
        """One message names its room: move that room's stamp, on the Tk thread.

        A room the register has never seen is a room the CLIENT can name and this panel
        cannot — a custom group is named by the person who made it — so the arrival that
        revealed it asks for the register once. On the arrival, never on a clock, and
        only for a room that is new: `_read_rooms` is already one-at-a-time, and a room
        the client will not name is asked about exactly once per panel.
        """
        if not room:
            return
        info = self._rooms.get(room)
        if info is None:
            self._rooms[room] = {"name": "", "msgs": 0, "pin": False, "last": ts}
            if room not in self._rooms_asked:
                self._rooms_asked.add(room)
                self._read_rooms(force=True)
            return
        if ts > float(info.get("last") or 0.0):
            info["last"] = ts

    def _room_label(self, room: str) -> tuple:
        """`(key, label)` for a chip — a locale key, or the group's own name.

        A name the CLIENT gave the room wins, and only a custom group ever has one: it
        is the whole point of this read. Everything else is named by what its id says,
        so no room is drawn as a raw `custom_group_<uuid>`.
        """
        info = self._rooms.get(room) or {}
        name = str(info.get("name") or "").strip()
        if name and room.startswith("custom_group_"):
            return "", name
        for prefix, key in self.ROOM_KEYS:
            if room.startswith(prefix):
                if prefix == "alliance_" and room.endswith("_Notice"):
                    return "chat.room.notice", ""
                return key, ""
        return "chat.tab.other", ""

    #: The order the list is drawn in, and it is the person's own (#2418): «сначала
    #: общие группы, мир, альянс, национальный и т.д., потом кастомные группы, потом
    #: лички с игроками». A section is data — the front-end draws whatever comes.
    ROOM_SECTIONS = ("pin", "channel", "group", "people")

    #: Which section a room belongs to. A custom group is the player's own; a private
    #: thread is a person; everything else is a channel the game gave everybody.
    def _room_section(self, room: str) -> str:
        # PINNED IS A SECTION, NOT A KIND. The person pinned it in the game and the
        # client says so (`isPin`), so it goes to the top whatever sort of room it is.
        if (self._rooms.get(room) or {}).get("pin"):
            return "pin"
        if room.endswith("_v2"):
            return "people"
        if room.startswith("custom_group_"):
            return "group"
        return "channel"

    def _face_for(self, uid: str) -> str:
        """This player's face as a link, cached — `""` for somebody with no picture.

        Cached because the lookup walks a few thousand md5 sums (`player_faces`) and a
        list of sixty conversations would otherwise do it sixty times per draw.
        """
        uid = str(uid or "").strip()
        if not uid:
            return ""
        if uid in self._faces:
            return self._faces[uid]
        from ..runtime import player_card

        try:
            link = player_card.face_link(uid)
        except Exception:                       # noqa: BLE001 — a picture, never the page
            link = ""
        self._faces[uid] = link
        return link

    def _web_rooms(self) -> list:
        """The whole list, in the order the person asked for it (#2418).

        Channels first — the ones the game gives everybody — then the player's own
        custom groups, then the private conversations, each with the face of whoever is
        on the other end. A row carries its section and the front-end groups by it, so
        the order is decided HERE and never guessed from an id in JavaScript.

        THERE IS NO PICTURE FOR A GROUP, and that is measured rather than assumed: a
        custom group's room data carries a name, a category and its members, and no icon
        of any kind (#2418, probed live). So a group draws its initial, exactly as an
        account with no photograph does — never somebody else's art.
        """
        rows = []
        for room in sorted(self._rooms):
            if room.endswith("_v2"):
                continue                        # a private thread is drawn below
            kind = chathistmod.classify_room(room)
            key, label = self._room_label(room)
            rows.append({"type": kind, "room": room, "key": key, "label": label,
                         "section": self._room_section(room), "face": "",
                         "ts": float((self._rooms.get(room) or {}).get("last") or 0.0),
                         "unread": int(self._room_unread.get(room, 0))})
        if not rows:
            # NOTHING READ YET — a panel whose client is down still draws the channels
            # it has history for, rather than an empty list that looks broken.
            for kind in CHAT_TABS:
                if kind in ("dm", "system"):
                    continue
                room = self._chat_room(kind)
                rows.append({"type": kind, "room": room, "key": f"chat.tab.{kind}",
                             "label": "", "section": "channel", "face": "",
                             "unread": int(self._chat_unread.get(kind, 0))})
        rows.append({"type": "system", "room": "", "key": "chat.tab.system", "label": "",
                     "section": "channel", "face": "",
                     "unread": int(self._chat_unread.get("system", 0))})
        rows.extend(self._web_people())
        # THE ORDER THE PERSON ASKED FOR (#2418): pinned, channels, groups, people —
        # and inside a section, whatever that section sorts by. Pinned rooms and private
        # conversations go by their last message («чаты игроков сортируем по последнему
        # сообщению»); a channel keeps the steady order it is read in, because a strip
        # of channels that reshuffles itself under a thumb is worse than a stale one.
        order = self.ROOM_SECTIONS
        rows.sort(key=lambda r: (order.index(r.get("section") or "channel"),
                                 -float(r.get("ts") or 0.0)
                                 if r.get("section") in ("pin", "people") else 0))
        return rows

    #: How many private conversations the phone is handed. Sixty of them is a list
    #: nobody scrolls; the newest are the ones somebody is actually talking in, and the
    #: front-end folds all but a handful away.
    WEB_CONTACTS = 60

    def _web_people(self) -> list:
        """The private conversations, newest first, each with the peer's own face."""
        store = self._store_for_reading()
        if store is None:
            return []
        try:
            contacts = store.dm_contacts(self._chat_uid)[:self.WEB_CONTACTS]
        except Exception:                       # noqa: BLE001 — a closed store is empty
            return []
        out = []
        for c in contacts:
            room = str(c.get("room") or "")
            uid = str(c.get("peer_uid") or "")
            if not room:
                continue
            out.append({"type": "dm", "room": room, "key": "",
                        "section": self._room_section(room),
                        "label": str(c.get("name") or uid or "?"),
                        "face": self._face_for(uid),
                        "text": str(c.get("last_text") or ""),
                        "ts": float(c.get("last_ts") or 0.0),
                        "unread": int(self._dm_unread.get(room, 0))})
        return out

    def _known_rooms(self, chat_type: str) -> set:
        """Every room this tab has actually SEEN a message of `chat_type` in.

        A press names its room, so this is what stops it naming any other: a phone that
        could post an arbitrary room id would be a way to write into a channel the
        panel never opened.
        """
        rooms = set()
        for record in self._chat_msgs.get(chat_type, ()):
            room = str(record.get("room_id") or "").strip()
            if room:
                rooms.add(room)
        if self._chat_store is not None and not rooms:
            try:
                for record in self._chat_store.recent(chat_type, self.WEB_MESSAGES):
                    room = str(record.get("room_id") or "").strip()
                    if room:
                        rooms.add(room)
            except Exception:                  # noqa: BLE001 — a closed store is empty
                pass
        return rooms

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
        # The line is `build()`'s, and the pump now runs without one (#2418): a window
        # that was never drawn has no variable to write, and a bare attribute here is an
        # `AttributeError` on the tick that drains the reader.
        var = getattr(self, "_chat_room_var", None)
        if var is None:
            return
        room = self._chat_room(self._active_chat_type())
        try:
            var.set(room or "—")
        except tk.TclError:
            pass

    # -- sending -------------------------------------------------------------
    def _chat_send(self, args: dict, what: str, room: str = "") -> bool:
        """Play `send_chat_message` with `args`, into the room the tab is answering in.

        It used to spawn `tools/chat_send.py`, which is why the phone had this tab's
        reading and no box to answer in: a press travels only when the ability is a
        scenario (`CLAUDE.md`). The ability is one now — `CHAT_SEND` in the DSL — so
        both front-ends press the same recipe and neither assembles a line of Lua.

        A press, therefore at `claims.HUMAN`: a reply that waited out a collect run
        would be a reply nobody sends from the panel. Nothing here sits on the Tk
        thread — the lane below takes it on a thread of its own and answers at once.

        AND IT IS QUEUED RATHER THAN ATTEMPTED (#2594). It used to be one
        `play_async(..., human=True)` from this line, which answered `False` when
        something else was driving the client — and by then the box had already been
        cleared, so **the message ceased to exist**: eight of them in the 55 hours
        measured on this account's log. `rt.chat_out` is the fix and the whole of it:
        the message is handed to the chat's own lane, which keeps asking for up to
        `chat_outbox.HOLD_SEC` and says in the log which end it reached. `True` here
        therefore means «accepted», not «gone» — and that is the honest word, because
        this thread cannot know whether the client is free this second.
        """
        room = room or self._chat_room(self._active_chat_type())
        if not room:
            # A send with nowhere to go is REFUSED, never redirected (#2418).
            self.say("chat", "chat.no_room")
            return False
        self.say("chat", "chat.sending", room=room, what=what)
        return bool(self.rt.chat_out.send(dict(args), what, room))

    def _chat_send_text(self) -> None:
        text = self._chat_msg_var.get().strip()
        if not text:
            return
        self._chat_msg_var.set("")
        self._chat_send({"text": text}, text[:40])

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
        args = {"coords": f"{x},{y}"}
        if srv is not None:
            args["server"] = str(srv)
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
            self._chat_send({"sticker": sid}, f"sticker {sid}")
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
        self._dm_header_var = statevar.string(None, self.t("chat.dm.pick"))
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

    def _pump_chat(self) -> None:
        """Drain the chat queue and refresh treeviews — scheduled every 1 s."""
        changed: set = set()
        rebuild: set = set()          # types whose whole window must be redrawn
        met: dict = {}                # whoever spoke, for the register (#1371)
        try:
            while True:
                record = self._chat_q.get_nowait()
                # A BACKLOG record is not the reader talking. It travels the same queue
                # so that it is persisted, ordered, rendered and routed by exactly one
                # piece of code — but the flow strip answers «идут ли данные ПРЯМО
                # СЕЙЧАС», and a press that seeds three hundred old messages would paint
                # it green over a reader that has been dead for an hour (#1549, #2064).
                backlog = bool(record.pop("_backlog", False))
                if not backlog:
                    self.take(INTAKE_CHAT).kept()
                self._met_in_chat(met, record)
                if not backlog:
                    # THE ARRIVAL IS THE SIGNAL (#2418): auto-translation is fed here
                    # and nowhere else, so nothing asks the game on a clock. A backlog
                    # read is a person pressing «Загрузить историю» — three hundred old
                    # messages are not «new messages» and must not be queued.
                    self._tr_take(record)
                chat_type = record.get("chat_type", "other")
                if chat_type not in self._chat_msgs:
                    chat_type = "other"
                # THE ROOM LIST FOLLOWS THE EAR (#2418). It was read once, when the
                # screen was first looked at, and never again while the panel ran: every
                # stamp on the left-hand list was measured 96 minutes stale on a live
                # panel whose newest message was 57 seconds old, so the sections that
                # sort by their last message («лички по последнему сообщению», pinned)
                # were sorted by an hour-old answer, and a room that started talking
                # after that read had no chip at all until somebody pressed «Обновить
                # комнаты». A message names its own room, so the arrival is the signal —
                # no clock, and no question to the game for a stamp it already sent.
                if not backlog:
                    self._room_heard(str(record.get("room_id") or "").strip(),
                                     float(record.get("ts") or 0.0))
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
                    elif not backlog and not record.get("is_mine"):
                        self._dm_unread[room] = self._dm_unread.get(room, 0) + 1
                    if (not backlog and not record.get("is_mine")
                            and "dm" != self._active_chat_type()):
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
                if (not backlog and not record.get("is_mine")
                        and chat_type != self._active_chat_type()):
                    self._chat_unread[chat_type] = self._chat_unread.get(chat_type, 0) + 1
                # …and per ROOM, because a chip on the phone is a room now (#2418): two
                # custom groups are two chips, and one of them being loud says nothing
                # about the other.
                room = str(record.get("room_id") or "").strip()
                if room and not backlog and not record.get("is_mine"):
                    self._room_unread[room] = self._room_unread.get(room, 0) + 1
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
        self._set_chat_count(total)
        # …and the flow strip on the same second (#1549): «идут ли данные ПРЯМО СЕЙЧАС»
        # is a question only a moving strip can answer.
        self._refresh_flow()
        # …and one batch of translations goes out if one is due (#2418). It rides this
        # pump rather than a clock of its own: the queue is only ever filled by an
        # arrival, so an idle chat asks the game nothing at all.
        self._tr_flush()
        self.rt.tick.arm("chat", 1000, self._pump_chat)

    #: How many messages of EACH ROOM the backlog read asks the client for. The client
    #: holds about forty per room it has been sitting in; asking for more costs nothing
    #: and gets whatever is there.
    BACKLOG_LIMIT = 40

    def _load_backlog(self) -> bool:
        """Play `read_chat_history` and fold what the client holds into this store.

        THE HISTORY WAS NEVER LOADED, only listened for (#2064): the reader child hears
        what ARRIVES, so a freshly switched-on chat tab was empty until somebody spoke,
        and everything said before the panel started existed only in the client. The
        client keeps its own per-room copy, and this reads THAT — one round trip, on a
        press, never on a clock.

        The records go into the same queue the reader's do, so they are persisted,
        de-duplicated, ordered by their own `serverTime` and routed to their tabs by
        exactly one piece of code. They are marked `_backlog` on the way in, because
        history is neither «the reader is talking» nor unread news.

        Off the Tk thread — a scenario is a game round trip, and it must not sit on the
        thread that draws. `human=True`: somebody is at a button.
        """
        if self._backlog_busy:
            return False
        self._backlog_busy = True
        self.say("chat", "log.chat.backlog_reading")

        def work() -> None:
            # THE UID IS RESOLVED HERE, on the thread that is already off Tk (#2064).
            # The store is keyed by the character, and reading which character this is
            # costs a game round trip — doing it in a second thread afterwards is how
            # the first fix still filed nothing: the backlog came back, the store was
            # not open yet, and the open that would have taken it never finished.
            uid = self._resolve_char_uid()
            records: list = []
            try:
                outcome = self.rt.play_now("read_chat_history",
                                           {"limit": self.BACKLOG_LIMIT},
                                           human=True, tag="chat")
                got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
                raw = got.get("chat") or "[]"
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, list):
                    records = [r for r in parsed if isinstance(r, dict)]
            except Exception as exc:            # noqa: BLE001 — a failed read, not a dead tab
                self.post(lambda: self.say("chat", "log.error", error=exc))
            self.post(lambda: self._absorb_backlog(records, uid))

        threading.Thread(target=work, daemon=True).start()
        return True

    #: How many messages of EACH room the deep read carries home. Bigger than the
    #: backlog's forty on purpose: the whole point of asking the server is what lies
    #: BELOW the forty the client was holding, and `READ_CHAT` answers with the newest
    #: `limit` of every room — anything smaller would fetch the slice and then throw it
    #: away unread.
    DEEP_LIMIT = 400

    #: …and how big it may ever grow. Beyond this the drain costs more than the slice
    #: is worth, and a person who has read that far back has the messages on file
    #: already — every earlier ask filed them.
    DEEP_CEILING = 3000

    def _deep_room(self, room: str, chat_type: str, store) -> str:
        """Which room a deeper read may name — and never one the store has not seen.

        A press names its room, exactly as sending does, so this is what stops a phone
        naming a room the panel never opened. A channel needs no name at all: it is the
        room its newest message is in.
        """
        if room:
            try:
                return room if store.recent_room(room, 1) else ""
            except Exception:                  # noqa: BLE001 — an unreadable store
                return ""
        try:
            rows = store.recent(chat_type, 1)
        except Exception:                      # noqa: BLE001 — a closed store is empty
            return ""
        return str(rows[-1].get("room_id") or "").strip() if rows else ""

    #: How many messages may hold a translation at once. A reader taps a few of them;
    #: keeping every one of a night's chat would be a second copy of the history in
    #: memory for no one to read.
    TRANSLATED_MAX = 200

    #: How many messages one auto-translate batch names.
    TR_BATCH = 20

    #: The shortest gap between two batches, in seconds.
    #:
    #: THIS IS THE PRICE OF THE FEATURE AND IT IS DELIBERATE (#2418). A batch is one
    #: call, one three-second wait and one reading — near enough four seconds during
    #: which nothing else may touch the game. Measured on this account: 1.5 messages a
    #: minute over a quiet hour, 8.2 over the busiest hour, 22.4 in the busiest ten
    #: minutes. Translating each message as it lands would spend half the link on a busy
    #: hour and more than all of it on a busy ten minutes; batching every 20 s spends
    #: three batches a minute — about 12 s of every 60, whatever the chat is doing.
    TR_GAP = 20.0

    #: THE SHORTEST MESSAGE WORTH A TRANSLATION, in characters (#2705). The person's
    #: words: «Условие для автоперевода, не переводить (отображать оригинал в панели)
    #: сообщения короче 5 символов».
    #:
    #: It is a cure for a kind of noise rather than a saving: «ок», «+1», «)))» and a
    #: single sticker come back from the game's translator as themselves or as something
    #: worse, and a row that says «translated» over an unchanged «ок» is a reader being
    #: told a translation happened. A batch is twenty messages and one four-second hold
    #: of the game link either way, so what this actually buys is a chat with fewer
    #: pointless rows in it — and, on a busy alliance evening, fewer batches.
    #:
    #: ONE PLACE. Nothing else in this file may spell a length out: the gate is
    #: :meth:`_tr_short` and this is the number it reads.
    TR_MIN_CHARS = 5

    @staticmethod
    def _tr_length(record: dict) -> int:
        """How long the message is TO A READER — the count :data:`TR_MIN_CHARS` judges.

        Not `len(msg)`, because a message is not its markup. What a person sees is what
        is counted, so each of these is ONE character however many bytes it is written
        with: an emoji (`[e:E006]`), a sticker, a photograph (`[photo:3]`). Colour and
        size tags are not characters at all and come out entirely. What is left is
        stripped of the whitespace round it and counted in CHARACTERS, which is what the
        person asked for — punctuation and emoji included, since «)))» and a single
        smiley are exactly the rows this exists to leave alone.

        The split is `chat_assets.segments`, the very one both front-ends draw the
        message with (`_web_parts`), so the count cannot disagree with what is on screen.

        A TOKEN COUNTS AS ONE WHETHER OR NOT THIS MACHINE HAS THE PICTURE. `segments`
        answers `image` for a token it can resolve to a sprite and `token` for one it
        cannot — a machine that has never extracted the game's assets gets `token` for
        every emoji there is. Both are ONE thing the sender put in the message, so both
        count as one; anything else would make «is this worth translating» depend on
        whether a sprite had been unpacked.
        """
        import chat_assets

        text = _RICH_TAG.sub("", str(record.get("msg") or ""))
        # U+FFFC OBJECT REPLACEMENT CHARACTER — «something is drawn here», one of it.
        text = _PHOTO_TOK.sub("\ufffc", text)
        seen = []
        for kind, value in chat_assets.segments(text):
            seen.append(str(value) if kind == "text" else "\ufffc")
        return len("".join(seen).strip())

    @classmethod
    def _tr_short(cls, record: dict) -> bool:
        """Is this message too short to be worth translating? (#2705)

        A separate method and not an `if` inside the gate, because the phone asks the
        same question: a row the auto-translator will never touch must not sit there
        looking as though its translation failed. A CLASSMETHOD, for the reason
        `_can_translate` beside it is a `staticmethod`: the question is about a message
        and a number, never about a particular tab, and it is asked of the class in the
        test that pins the number.
        """
        return cls._tr_length(record) < cls.TR_MIN_CHARS

    def _tr_take(self, record: dict) -> None:
        """A message has arrived: queue it for translation if the switch is on.

        Never my own — the person said so outright, and the game does not offer to
        translate one either. Never one already translated: the answers are kept
        (`_translated`), so a message that has been through this costs nothing again.
        AND NEVER A SHORT ONE (#2705): it is dropped here, before the queue, so it is
        never asked for, never counted and never reported — the original simply stands,
        which is what the person asked for and what a reader would expect of «ок».

        THE HAND-DRIVEN TAP IS UNTOUCHED. The rule is about the AUTOMATIC translator;
        somebody who deliberately taps «перевести» on a two-word message is asking, and
        an ask is answered (`_translate`).
        """
        if not self._tr_auto or record.get("is_mine"):
            return
        if not self._can_translate(record) or self._tr_short(record):
            return
        room = str(record.get("room_id") or "").strip()
        seq = str(record.get("seq_id") or "").strip()
        if not room or not seq or f"{room}|{seq}" in self._translated:
            return
        waiting = self._tr_queue.setdefault(room, [])
        if seq not in waiting:
            waiting.append(seq)

    def _tr_flush(self) -> None:
        """Send one batch, if one is due. Called by the queue's own pump, never a clock.

        The work goes to a thread of its own: a batch holds the game for about four
        seconds and this is the tick that draws.
        """
        import threading
        import time as _time

        if self._tr_busy or not self._tr_queue or not self._tr_auto:
            return
        now = _time.monotonic()
        if now < self._tr_at:
            return
        room = max(self._tr_queue, key=lambda k: len(self._tr_queue[k]))
        seqs = self._tr_queue[room][:self.TR_BATCH]
        rest = self._tr_queue[room][self.TR_BATCH:]
        if rest:
            self._tr_queue[room] = rest
        else:
            self._tr_queue.pop(room, None)
        if not seqs:
            return
        self._tr_busy = True
        self._tr_at = now + self.TR_GAP
        threading.Thread(target=self._tr_batch, args=(room, list(seqs)),
                         daemon=True, name="chat-autotr").start()

    def _tr_batch(self, room: str, seqs: list) -> None:
        """One round trip: ask the game for all of these, file what came back."""
        try:
            outcome = self.rt.play_now("translate_chat_batch",
                                       {"room": room, "seqs": ",".join(seqs)},
                                       human=False, tag="chat")
            got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
            lang = str(got.get("tr_lang") or "")
            done = str(got.get("tr_done") or "")
            if done and done != "none":
                for pair in done.split(","):
                    seq, _, raw = pair.partition("=")
                    if not seq or not raw:
                        continue
                    try:
                        text = bytes.fromhex(raw).decode("utf-8", "replace")
                    except ValueError:         # noqa: PERF203 — a mangled pair, not a crash
                        continue
                    if text:
                        self._translated[f"{room}|{seq}"] = (text, lang)
                        self._tr_done += 1
                while len(self._translated) > self.TRANSLATED_MAX:
                    self._translated.pop(next(iter(self._translated)))
        except Exception as exc:               # noqa: BLE001 — a failed batch, not a dead tab
            self.post(lambda: self.say("chat", "log.error", error=exc))
        finally:
            self._tr_busy = False

    def _translate(self, room: str, seq: str) -> dict:
        """Ask the GAME to translate one message, and hand back what it answered.

        The client's own button, measured live (`actions/translate_chat_message.md`):
        `Ctrl:OnChatTranslate(message)` and the answer lands on the message itself —
        `translateState = 2`, `getTranslationMsg()`, and the language is the player's
        own chat setting rather than anything this panel picks. No outside service is
        touched, which is the whole point of using the game's.

        Answered on the HTTP worker thread — the round trip must not sit on the thread
        that draws — and the translation is remembered here so the phone can put the
        original back without asking the game a second time.
        """
        if not room or not seq:
            return {"error": "unknown"}
        if room not in self._rooms and not self._known_rooms(
                chathistmod.classify_room(room)):
            return {"error": "unknown"}
        key = f"{room}|{seq}"
        held = self._translated.get(key)
        if held:
            return {"ok": True, "text": held[0], "lang": held[1]}
        try:
            outcome = self.rt.play_now("translate_chat_message",
                                       {"room": room, "seq": seq},
                                       human=True, tag="chat")
        except Exception as exc:               # noqa: BLE001 — a failed press, not a dead tab
            self.post(lambda: self.say("chat", "log.error", error=exc))
            return {"ok": False, "reason": "chat.translate.failed"}
        got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
        raw = str(got.get("tr_text") or "")
        try:
            text = bytes.fromhex(raw).decode("utf-8", "replace") if raw else ""
        except ValueError:                     # noqa: PERF203 — a mangled answer, not a crash
            text = ""
        if not text:
            return {"ok": False, "reason": "chat.translate.failed"}
        lang = str(got.get("tr_lang") or "")
        self._translated[key] = (text, lang)
        while len(self._translated) > self.TRANSLATED_MAX:
            self._translated.pop(next(iter(self._translated)))
        return {"ok": True, "text": text, "lang": lang}

    def _ask_server_for_older(self, room: str, chat_type: str) -> dict:
        """Ask the SERVER for the slice above what the store and the client both hold.

        THE ONE PLACE IN THE CHAT THAT TALKS TO THE SERVER (#2064), and every rule the
        person set for it is kept here rather than in the front-end:

        * **The store first, always.** This is reached only when paging the database has
          said `more: false` — the phone asks for it, it never offers itself.
        * **A person's scroll, never a clock.** It is a press, and nothing arms it.
        * **One scroll, one request.** `_deep_busy` holds the room for the length of the
          round trip, so a thumb that fires the handler three times asks once.
        * **Never twice for the same slice.** The cursor belongs to the CLIENT — the
          request means «what lies before the oldest I hold» — so a second ask fetches
          the slice before the first.
        * **«There is no more» is remembered.** The game keeps that per room and the
          recipe reads it back; `_history_end` is the panel's copy, and the page stops
          offering the reading once it stands.

        Answered on the HTTP worker thread — a game round trip must not sit on the
        thread that draws — and it BLOCKS that one worker for the length of the ask, so
        the phone can page the moment the answer says how many arrived.
        """
        if chat_type not in CHAT_TABS:
            return {"error": "unknown"}
        store = self._store_for_reading()
        if store is None:
            return {"ok": False, "reason": "chat.no_room"}
        room = self._deep_room(room, chat_type, store)
        if not room:
            return {"ok": False, "reason": "chat.no_room"}
        if room in self._history_end:
            return {"ok": False, "reason": "chat.history_end", "end": True, "got": 0}
        if room in self._deep_busy:
            return {"ok": False, "reason": "chat.deep_busy"}
        self._deep_busy.add(room)
        self.say("chat", "log.chat.deep_asking")
        records: list = []
        ended = False
        try:
            # The limit follows the room's own list: everything it holds, and room for
            # what this ask is about to add. Capped, because it is also the size of the
            # drain — a room somebody has paged all afternoon must not turn one press
            # into a minute of reading.
            limit = min(self.DEEP_CEILING,
                        max(self.DEEP_LIMIT, self._deep_hold.get(room, 0) + 200))
            outcome = self.rt.play_now("fetch_chat_history",
                                       {"room": room, "limit": limit},
                                       human=True, tag="chat")
            got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
            ended = str(got.get("history_end") or "0") in ("1", "1.0")
            # WHAT THE SERVER SENT FOR THIS ROOM, counted by the CLIENT's own per-room
            # list rather than by rows landing in the store. Measured the hard way: the
            # store grows by whatever arrived in ANY room while the ask was in flight,
            # so a single word said in the alliance channel read as «the world chat gave
            # us something» and the end could never be reached.
            held_after = self._as_int(got.get("held_after"))
            gained = held_after - self._as_int(got.get("held_before"))
            if held_after > 0:
                self._deep_hold[room] = held_after
            raw = got.get("chat") or "[]"
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list):
                records = [r for r in parsed if isinstance(r, dict)]
        except Exception as exc:                # noqa: BLE001 — a failed ask, not a dead tab
            self.say("chat", "log.error", error=exc)
            return {"ok": False, "reason": "chat.deep_failed"}
        finally:
            self._deep_busy.discard(room)
        before = self._store_count(store)
        for record in records:
            try:
                store.append(record)
            except Exception:                  # noqa: BLE001 — a lost row, not a dead panel
                pass
        added = max(0, self._store_count(store) - before)
        if gained > 0:
            self._deep_empty.pop(room, None)
        else:
            self._deep_empty[room] = self._deep_empty.get(room, 0) + 1
        # THE END IS REMEMBERED PER ROOM, and it is reached two ways: the game's own
        # flag, or two asks in a row that brought nothing. Either way the page stops
        # offering the reading and no further scroll can spend a round trip on it.
        if ended or self._deep_empty.get(room, 0) >= 2:
            self._history_end.add(room)
            ended = True
        # The DRAWN tab, if anybody is looking at one: the same records through the same
        # door the backlog uses, so the window shows what the phone just fetched.
        if self._chat_trees and records:
            self.post(lambda: self._file_backlog(list(records)))
        self.say("chat", "log.chat.deep_done", n=added)
        # `end` is what the front-end stops on — and it is the REMEMBERED end, not
        # «this one ask was empty»: the first empty answer leaves the button in place,
        # so a person can ask again rather than be told the history has finished
        # because one reply was slow.
        return {"ok": True, "got": max(0, gained), "filed": added,
                "end": bool(ended), "room": room}

    @staticmethod
    def _as_int(value) -> int:
        """A scenario variable as a whole number — 0 when it is anything else."""
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _store_count(store) -> int:
        """How many rows the store holds, or 0 when it cannot say."""
        try:
            return int(store.count())
        except Exception:                      # noqa: BLE001 — an unreadable store
            return 0

    def _absorb_backlog(self, records: list, uid: str = "") -> None:
        """Put what was read where it is durable — on the Tk thread, and say how many.

        THE STORE FIRST, the view second, and that order is the whole lesson of the
        first live run (#2064): the press answered «278 messages of 278 held in 7 rooms»
        and the store still had nought rows in it. A press off a phone reaches this tab
        before anybody has LOOKED at it, and until somebody does there is no view, no
        `build()` and therefore no pump — so records handed to the queue sat in it for
        ever. Persisting here needs neither.
        """
        self._backlog_busy = False
        if not records:
            self.say("chat", "log.chat.backlog_none")
            return
        if self._chat_store is None and uid:
            # The character is known — the read resolved it on its own thread — so the
            # store is opened here, before anything is filed into it.
            #
            # DIRECTLY, and never through `_open_chat_store`: that one resets the whole
            # tab as well, and half of what it touches is made in `build()`. On a tab
            # nobody has looked at there are no widgets, so it raised inside a posted
            # callback and took the backlog with it in complete silence — the third
            # version of one bug (#2064), and every version of it looked like success
            # in the log.
            try:
                self._chat_store = chathistmod.ChatHistoryStore(
                    self.rt.profiles.chat_db(uid))
                self._chat_uid = uid
            except Exception as exc:      # noqa: BLE001 — a bad store, not a dead tab
                self.say("chat", "log.error", error=exc)
        if self._chat_store is None:
            # Not «no store», but «no character»: the game could not say who is logged
            # in. Held rather than dropped — a press that says 279 and keeps none of
            # them is the worse of the two failures, because it looks like it worked —
            # and filed by `_open_chat_store` as soon as one is known.
            self._backlog_pending = list(records)
            self.say("chat", "log.chat.backlog_held", n=len(records))
            self.ensure_loaded()
            return
        self._file_backlog(records)

    def _set_chat_count(self, n: int) -> None:
        """The «N messages» line, when there is one to write it on.

        `build()` runs when somebody first LOOKS at a tab, and this tab is now reached
        without that — a press off the phone, and the store opening behind it. A bare
        `self._chat_count_var` there is an `AttributeError` inside a posted callback,
        which is silent (#2064).
        """
        var = getattr(self, "_chat_count_var", None)
        if var is not None:
            var.set(self.t("chat.count", n=n))

    def _file_backlog(self, records: list) -> None:
        """Write the read messages into this character's store, and draw them if drawn.

        `append` is idempotent on the message's own identity, so a second press — or the
        pump seeing the same record again — adds nothing.
        """
        if self._chat_store is None:
            return
        for record in records:
            self._chat_store.append(record)
        # The views exist only once somebody has looked at the tab. A record queued for
        # a pump that is not running would wait for ever, and it does not need to: a
        # view built later pages the same messages back OUT of the store.
        if self._chat_trees:
            for record in records:
                record["_backlog"] = True
                self._chat_q.put(record)
        self.say("chat", "log.chat.backlog", n=len(records))

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

    def _set_listening(self, on: bool) -> None:
        """Move the monitor to ``on`` and do what moving it does — on the Tk thread.

        The window's checkbox and the phone's switch are ONE state with two views: this
        is what both of them move, so neither can start a second reader or leave the
        other showing the opposite of what is running.
        """
        if bool(self._chat_var.get()) == on:
            return
        self._chat_var.set(on)
        self._toggle_chat()
        # …AND WRITTEN DOWN. A tick moved at the machine is saved by the binder's own
        # trace over `persist_vars`; a switch moved from the phone reaches the variable
        # by a different road, and a monitor left on that a restart forgets is exactly
        # the silence this switch exists to end. `changed()` is a no-op while a profile
        # is being applied, so it cannot write a half-loaded block back.
        self.rt.settings.changed()

    def _toggle_chat(self) -> None:
        if self._chat_var.get():
            self._start_chat()
        else:
            self._stop_chat()

    #: How long the panel waits before bringing a dead reader back, and the ceiling
    #: that wait grows to. Seconds. The first gap is short because the ordinary death
    #: is a client that is restarting; the ceiling is what a client that is OFF costs.
    CHAT_RETRY_FIRST = 15.0
    CHAT_RETRY_MAX = 300.0

    def _start_chat(self) -> None:
        self._chat_wanted = True
        self._cancel_chat_retry()
        if self._chat_proc is not None:
            return
        out = self.rt.profiles.chat_log()
        try:
            os.makedirs(os.path.dirname(out), exist_ok=True)
        except Exception:
            pass
        rel = repo_rel(out)
        self.say("chat", "log.chat.starting", path=rel)
        self.say("chat", "log.chat.needs_link")
        # stderr is dropped, not folded in: chat_reader's stdout is a JSONL stream and
        # a traceback interleaved into it would be parsed as a message.
        mon = self.rt.children.spawn("chat",
                          [self.rt.children.python(), "-u", os.path.join(TOOLS, "chat_reader.py"),
                           "--seconds", "0", "--out", out],
                          on_line=self._on_chat_line, on_exit=self._on_chat_exit,
                          capture_stderr=False)
        if not mon.start():
            # A child that will not start is the same case as one that died: at the
            # boot it usually means the client is not up yet, and switching the monitor
            # off for that reason is how the ear stayed down for three days (#2418).
            self._schedule_chat_retry()
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
                    # A message proves the ear is working, so the next death starts
                    # from the short gap again rather than from the ceiling.
                    self._chat_retry = 0.0
                    self._chat_q.put(record)
            except json.JSONDecodeError:
                pass
        return False                    # never logged: it is data, not prose

    def _on_chat_exit(self) -> None:
        self.say("chat", "log.chat.ended")
        self._chat_proc = None
        if self._chat_wanted and bool(self._chat_var.get()):
            self._schedule_chat_retry()
            return
        self._chat_var.set(False)

    def _schedule_chat_retry(self) -> None:
        """Bring the reader back after a widening gap, while the switch says «on»."""
        self._cancel_chat_retry()
        gap = self._chat_retry or self.CHAT_RETRY_FIRST
        self._chat_retry = min(gap * 2.0, self.CHAT_RETRY_MAX)
        self.say("chat", "log.chat.retry", sec=int(gap))
        timer = threading.Timer(gap, lambda: self.post(self._chat_retry_now))
        timer.daemon = True
        self._chat_retry_timer = timer
        timer.start()

    def _cancel_chat_retry(self) -> None:
        timer, self._chat_retry_timer = self._chat_retry_timer, None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:               # noqa: BLE001 — a timer, never the panel
                pass

    def _chat_retry_now(self) -> None:
        """The gap has passed: start again if the switch is still on."""
        self._chat_retry_timer = None
        if self._chat_wanted and bool(self._chat_var.get()) and self._chat_proc is None:
            self._start_chat()

    # chat_log.jsonl is written by chat_reader.py itself (`--out`), so the panel
    # does NOT append here: two processes appending to one file interleaved
    # their buffers, duplicating every record and corrupting utf-8 mid-line.

    def _stop_chat(self) -> None:
        self._chat_wanted = False
        self._cancel_chat_retry()
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
        self._set_chat_count(0)

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
        self._set_chat_count(0)
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
        self._set_chat_count(total)
        if total:
            self.say("chat", "log.chat.history", n=total)
        # A backlog that came back before the store was open — file it now.
        pending, self._backlog_pending = self._backlog_pending, []
        if pending:
            self._file_backlog(pending)


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(ChatTab))

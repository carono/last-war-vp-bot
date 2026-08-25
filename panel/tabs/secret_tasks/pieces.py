"""«Обмен кусочками» — the second tab of «Мобильный отряд», as a page here (#1975).

WHAT THE GAME'S OWN SCREEN IS. Beside the secret tasks the game keeps a board where
alliancemates swap the pieces a treasure map is made of. A dig spends ONE OF EACH of the
set's seven pieces, so the number of digs left is the SMALLEST of the seven counts — an
eighth copy of one piece is worth nothing until it becomes a copy of the scarcest one.
Everything on this page serves that one number.

WHAT IS HERE, AND WHAT IS NOT. The ability is a scenario and this page only plays it
(`CLAUDE.md`): `actions/exchange_treasure_pieces.md` takes the offers worth taking and
keeps one of ours standing, `actions/read_piece_exchange.md` is the reading the table
draws, `actions/withdraw_piece_offer.md` is the one press a person wants by hand. No Lua
is assembled here, no gate is held here, and the verdict column is the SCENARIO's verdict
read back — not a second copy of the rule written in Tk.

THE RULE IS THE OPERATOR'S, not this module's (#1975): «только добор минимума» — take an
offer only when what it PAYS is the scarcest piece we hold and what it ASKS FOR is at
least `gap` above that floor. The two knobs the page carries are `gap` (how much spare a
piece needs before it may be traded away) and how many trades one run may make; both
travel to the scenario as ARGS, and to the four-hourly errand through
`Schedule.register_args`, so the button and the timer can never disagree about the rule.

THE ROWS ARE THE GAME'S, ALWAYS. Nothing here is marked done by a press: the table is
replaced whole by every read, so an offer that has gone is an offer somebody took. A
press starts a trade and then re-reads — the shape `CLAUDE.md` calls ordinary and wanted.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ...widgets import NumericEntry

#: The errand this page's button plays, and the timer's name — one word for both.
ERRAND = "exchange_treasure_pieces"

#: Which splinter set the board is about. 4 is the dig-treasure one the current event
#: runs; 1 is the dispatch-treasure set, 2 the season synthesis, 3 the cooking one. It is
#: not a knob on the page: a person cannot usefully choose a set they hold no pieces of,
#: and the scenario answers «nothing to trade» in one round trip for any of them.
DEFAULT_SET = 4


def parse_board(text: str) -> dict:
    """Turn the reading `read_piece_exchange.md` hands back into a dictionary.

    One string, because that is what a scenario variable is. The shape is
    ``set=4 | digs=12 | have=id:n,… | mine=need>pay | offers=uuid;name;give;get;verdict|…``
    and every part of it is optional — a reading that failed leaves the page saying what
    it last knew rather than raising into the Tk callback that asked for it.
    """
    out = {"set": DEFAULT_SET, "digs": None, "have": [], "mine": None, "offers": []}
    for chunk in str(text or "").split("|"):
        chunk = chunk.strip()
        if chunk.startswith("set="):
            out["set"] = _int(chunk[4:], DEFAULT_SET)
        elif chunk.startswith("digs="):
            out["digs"] = _int(chunk[5:], None)
        elif chunk.startswith("have="):
            for pair in chunk[5:].split(","):
                if ":" in pair:
                    piece, _, count = pair.partition(":")
                    out["have"].append((piece.strip(), _int(count, 0)))
        elif chunk.startswith("mine="):
            body = chunk[5:].strip()
            out["mine"] = None if body in ("", "-") else body
        elif chunk.startswith("offers="):
            chunk = chunk[7:]
            if chunk.strip():
                out["offers"].append(_offer(chunk))
        elif chunk.count(";") >= 4:
            # `offers=` is followed by more records separated by the same `|`, so
            # everything after it that still looks like a record belongs to it.
            out["offers"].append(_offer(chunk))
    return out


def _offer(raw: str) -> dict:
    parts = (raw.split(";") + ["", "", "", "", ""])[:5]
    return {"uuid": parts[0].strip(), "name": parts[1].strip(),
            "give": parts[2].strip(), "get": parts[3].strip(),
            "take": parts[4].strip() == "1"}


def _int(raw, default):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


class PiecesPage:
    """The board as one page: the seven counts, the offers, and the two presses."""

    CONFIG_KEY = "pieces"

    def __init__(self, tab) -> None:
        self.tab = tab
        self.rt = tab.rt
        root = tab.rt.root
        #: How much spare a piece must have over the floor before it may be traded away.
        self.gap_var = tk.StringVar(master=root, value="1")
        #: How many trades ONE run may make. Ours, not the game's: no daily cap on
        #: exchanges was found anywhere in the client (#1975), so the ceiling that stops
        #: a board filled overnight from emptying our spare pieces has to be here.
        self.limit_var = tk.StringVar(master=root, value="3")
        #: Whether the errand keeps an offer of ours standing. A standing offer holds
        #: back one copy of the piece it pays with (measured live: the count drops while
        #: it is up and returns on withdrawal), but the recipe always pays with the piece
        #: we hold MOST of, so the held copy is never the one deciding how many digs are
        #: left. On by default; this box is for the person who would rather not.
        self.offer_var = tk.BooleanVar(master=root, value=True)
        #: The last reading, as `parse_board` returns it. Drawn by the window, handed to
        #: the phone, and never edited by either.
        self.board = {"set": DEFAULT_SET, "digs": None, "have": [], "mine": None,
                      "offers": []}
        self.busy = False
        self._tree = None
        self._summary = tk.StringVar(master=root, value="")
        self._mine = tk.StringVar(master=root, value="")
        self._registered = False

    # -- wiring -----------------------------------------------------------------
    def register(self) -> None:
        """Let the four-hourly errand read the page's knobs LIVE. Idempotent.

        Without this the timer would carry whatever `args` block its row was written
        with, and the two would drift apart the first time somebody moved `gap` — the
        button trading on one rule and the errand on another, with nothing on screen to
        say which had just run.
        """
        if self._registered:
            return
        schedule = getattr(self.rt, "schedule", None)
        if schedule is None:                     # a tab opened on its own
            return
        schedule.register_args(ERRAND, self.args)
        self._registered = True

    def args(self) -> dict:
        """The scenario's ARGS as the page has them right now."""
        return {"kind": self.board.get("set") or DEFAULT_SET,
                "accept": 1,
                "offer": 1 if self.offer_var.get() else 0,
                "gap": max(0, _int(self.gap_var.get(), 1)),
                "limit": max(0, _int(self.limit_var.get(), 3))}

    # -- the window --------------------------------------------------------------
    def build(self, book):
        """Draw the page into the tab's notebook and hand the frame back."""
        tab = self.tab
        frame = ttk.Frame(book, padding=6)

        head = ttk.Frame(frame)
        head.pack(fill="x")
        ttk.Label(head, textvariable=self._summary).pack(anchor="w")
        ttk.Label(head, textvariable=self._mine, foreground="#888").pack(anchor="w")
        tab.tr(ttk.Label(frame, foreground="#888", wraplength=720, justify="left"),
               "pieces.hint").pack(fill="x", anchor="w", pady=(2, 6))

        bar = ttk.Frame(frame)
        bar.pack(fill="x")
        tab.tr(ttk.Label(bar), "pieces.gap").pack(side="left")
        NumericEntry(bar, textvariable=self.gap_var, width=4).pack(side="left",
                                                                  padx=(2, 12))
        tab.tr(ttk.Label(bar), "pieces.limit").pack(side="left")
        NumericEntry(bar, textvariable=self.limit_var, width=4).pack(side="left",
                                                                    padx=(2, 12))
        tab.tr(ttk.Checkbutton(bar, variable=self.offer_var), "pieces.offer").pack(
            side="left")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(6, 4))
        tab.tr(ttk.Button(buttons, command=self.refresh), "pieces.refresh").pack(
            side="left")
        tab.tr(ttk.Button(buttons, command=self.trade), "pieces.trade").pack(
            side="left", padx=(6, 0))
        tab.tr(ttk.Button(buttons, command=self.withdraw), "pieces.withdraw").pack(
            side="left", padx=(6, 0))

        columns = ("player", "give", "get", "verdict")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=8)
        for name, width in zip(columns, (200, 110, 110, 160)):
            tree.column(name, width=width, anchor="w")
        tree.pack(fill="both", expand=True)
        self._tree = tree
        self.retranslate()
        return frame

    def retranslate(self) -> None:
        """Redraw every word this page owns in whatever language is on now."""
        tree = self._tree
        if tree is not None:
            for name in ("player", "give", "get", "verdict"):
                try:
                    tree.heading(name, text=self.tab.t("pieces.col.%s" % name))
                except tk.TclError:              # the page was closed mid-retranslate
                    return
        self.repaint()

    # -- what the reading turned into -------------------------------------------
    def repaint(self) -> None:
        """Draw `self.board`. Called after every read and after a language change."""
        board = self.board
        digs = board.get("digs")
        have = ", ".join("%s: %d" % (piece, count) for piece, count in board["have"])
        self._summary.set(self.tab.t(
            "pieces.summary",
            digs=("—" if digs is None or digs < 0 else str(digs)),
            have=have or "—"))
        mine = board.get("mine")
        self._mine.set(self.tab.t("pieces.mine", offer=mine) if mine
                       else self.tab.t("pieces.mine.none"))
        tree = self._tree
        if tree is None:
            return
        try:
            tree.delete(*tree.get_children())
            for offer in board["offers"]:
                tree.insert("", "end", values=(
                    offer["name"] or "—", offer["give"], offer["get"],
                    self.tab.t("pieces.verdict.take" if offer["take"]
                               else "pieces.verdict.pass")))
        except tk.TclError:                      # the tab was closed while this ran
            pass

    # -- the three presses --------------------------------------------------------
    def refresh(self) -> None:
        """Ask the game for the board — a read, and the only thing this page does alone."""
        self._play("read_piece_exchange", {"kind": self.board.get("set") or DEFAULT_SET,
                                           "gap": max(0, _int(self.gap_var.get(), 1))},
                   "pieces.log.read", read_back=False)

    def trade(self) -> None:
        """Play the ability, then re-read — the ordinary «press and look again»."""
        self._play(ERRAND, self.args(), "pieces.log.trade")

    def withdraw(self) -> None:
        """Take our own offer off the board, then re-read."""
        self._play("withdraw_piece_offer",
                   {"kind": self.board.get("set") or DEFAULT_SET},
                   "pieces.log.withdraw")

    def _play(self, name: str, args: dict, log_key: str, read_back: bool = True) -> bool:
        """One scenario, its reading taken off the run, and the page repainted.

        `read_back` is what tells the two kinds apart: the READ hands its board back on
        its own variables, while a press has changed the board and has to ask again.
        Both land in the same place, so the table can never show the state from before
        the press that was just made.
        """
        if self.busy:
            return False
        rt = self.rt
        self.busy = True
        rt.say("secret", log_key)

        def landed(outcome=None) -> None:
            got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
            if got.get("board"):
                self.board = parse_board(got.get("board"))
                self.repaint()

        def done(_outcome=None) -> None:
            self.busy = False
            if read_back:
                self.tab.after(self.refresh)

        started = rt.play_async(name, args, tag="secret", human=True,
                                on_result=landed, on_done=done)
        if not started:
            self.busy = False
            rt.say("secret", "pieces.log.busy")
        return bool(started)

    # -- settings ------------------------------------------------------------------
    def config(self) -> dict:
        return {"gap": self.gap_var.get(), "limit": self.limit_var.get(),
                "offer": bool(self.offer_var.get())}

    def apply_config(self, raw) -> None:
        raw = raw if isinstance(raw, dict) else {}
        self.gap_var.set(str(raw.get("gap") or "1"))
        self.limit_var.set(str(raw.get("limit") or "3"))
        self.offer_var.set(bool(raw.get("offer", True)))

    def persist_vars(self) -> list:
        return [self.gap_var, self.limit_var, self.offer_var]

    # -- the phone -------------------------------------------------------------------
    def web_card(self) -> dict:
        """The same page as one card — the counts, the offers and the same three presses.

        Every press here plays a scenario and nothing else, which is what makes it
        allowed out of the house (`CLAUDE.md`): unlike the robbery on the ★ page, this
        ability spawns no tool of its own.
        """
        board = self.board
        digs = board.get("digs")
        rows = [{"label": "pieces.digs",
                 "value": ("—" if digs is None or digs < 0 else str(digs))},
                {"label": "pieces.mine.label",
                 "value": board.get("mine") or self.tab.t("pieces.mine.none")},
                {"label": "pieces.gap", "value": self.gap_var.get()},
                {"label": "pieces.limit", "value": self.limit_var.get()}]
        rows += [{"label": "pieces.piece", "value": "%s: %d" % (piece, count)}
                 for piece, count in board["have"]]
        items = [{"text": offer["name"] or "—",
                  "facts": [{"label": "pieces.col.give", "value": offer["give"]},
                            {"label": "pieces.col.get", "value": offer["get"]}],
                  "pill": ("pieces.verdict.take" if offer["take"]
                           else "pieces.verdict.pass")}
                 for offer in board["offers"]]
        return {"title": "secrettasks.page.pieces", "rows": rows, "items": items,
                "empty": "pieces.empty",
                "actions": [{"id": "pieces_refresh", "label": "pieces.refresh"},
                            {"id": "pieces_trade", "label": "pieces.trade"},
                            {"id": "pieces_withdraw", "label": "pieces.withdraw"},
                            {"id": "pieces_offer",
                             "label": ("pieces.offer.off" if self.offer_var.get()
                                       else "pieces.offer.on")}]}

    def web_press(self, action: str) -> "dict | None":
        """One of the card's four buttons, or `None` when it is not ours."""
        if action == "pieces_refresh":
            return {"ok": self._play("read_piece_exchange",
                                     {"kind": self.board.get("set") or DEFAULT_SET,
                                      "gap": max(0, _int(self.gap_var.get(), 1))},
                                     "pieces.log.read", read_back=False)}
        if action == "pieces_trade":
            return {"ok": self._play(ERRAND, self.args(), "pieces.log.trade")}
        if action == "pieces_withdraw":
            return {"ok": self._play("withdraw_piece_offer",
                                     {"kind": self.board.get("set") or DEFAULT_SET},
                                     "pieces.log.withdraw")}
        if action == "pieces_offer":
            # The box, not a press on the game: the phone gets the same switch the
            # window has, and the errand reads it live through `register_args`.
            self.offer_var.set(not self.offer_var.get())
            return {"ok": True}
        return None

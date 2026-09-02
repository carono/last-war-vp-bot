"""The «Скрытые Сокровища» tab: the week's compasses, the digs in hand, the goal.

WHAT THE PAGE IS FOR. The event pays a random handful of COMPASSES for every treasure map
dug on the tab beside the explorer chests, and a week's worth of them unlocks ten reward
steps — the last at 6000, which is the week's whole point. Two numbers decide everything a
person wants to know: how far off the goal the account is, and how many digs the map
fragments in the bag still allow. Both are on the card, in words, with the digs the
distance is still worth beside them.

NOTHING HERE DRIVES THE GAME. The ability is one scenario
(`actions/dig_hidden_treasures.md`) and the reading is another
(`actions/read_hidden_treasures.md`); this page plays them and draws what came back
(`CLAUDE.md`, «Everything is a scenario — the panel only plays them»). The gates — the
week being over, the goal already earned, an empty bag of fragments — are inside the
scenario, not here.

IT READS ONCE AND THEN HOLDS WHAT IT READ. There is no clock on this page: the board is
asked for when somebody first opens the tab and when somebody presses «Обновить», and the
card says how old the reading is so a stale one is visibly stale (`CLAUDE.md`, «Read once,
then LISTEN»). Nothing about this event arrives by itself — there is no push behind it —
and a page that asked every ten seconds would be a background poll of the game, which is
exactly what that rule forbids.

THE SCORE LAGS ON PURPOSE, and the card says so rather than hiding it: the compasses a dig
pays do not reach the client's own count until it is restarted (measured live,
`docs/research/hidden-treasures.md`). So a reading taken right after a run shows the old
score, and the honest thing is to show WHEN it was read.
"""
from __future__ import annotations

import time
from tkinter import ttk

from .base import PanelTab

#: The scenario that reads the board, and the one that does the work.
READ_ACTION = "read_hidden_treasures"
DIG_ACTION = "dig_hidden_treasures"

#: What one dig is worth on average, in compasses — the event's own reward table
#: (150/180/240 six times in ten, 350/450/600 three, 600/700/900 one). It is only used to
#: turn «how far to the goal» into «how many digs», and a person may move it behind the
#: gear.
DEFAULT_PAY = 320


def parse_board(line: str) -> dict:
    """`key=value key=value …` — the one string the reading scenario hands back.

    Anything unreadable comes back as an empty dict rather than a half-filled one: a
    board with a score and no goal would draw «750 из 0», which is worse than «нечего
    показать».
    """
    out: dict = {}
    for chunk in str(line or "").split():
        key, _, value = chunk.partition("=")
        if not key or not _:
            continue
        try:
            out[key] = int(float(value))
        except (TypeError, ValueError):
            out[key] = value
    return out if "score" in out and "goal" in out else {}


class HiddenTreasuresTab(PanelTab):
    ID = "hidden_treasures"
    TITLE_KEY = "tab.hidden_treasures"
    ORDER = 315
    LOCALE_NS = ("hidden",)
    NEEDS = ("daemon", "actions")
    WEB_SCREEN = True
    #: Proven on a live account down to the last press — the dig, the claim and the
    #: reading — but not yet driven end to end for a whole week, so it stays behind
    #: «Разработка» until `docs/farming.md` says it works.
    IN_DEVELOPMENT = True

    def __init__(self, rt, parent) -> None:
        super().__init__(rt, parent)
        #: The last board that came back, and when — `{}` while nothing has been read.
        self._board: dict = {}
        self._read_at: float = 0.0
        #: The knobs, all three of them the scenario's own arguments.
        self._goal = 0          # 0 = whatever the game's own cap says
        self._cap = 0           # 0 = as many digs as the plan asks for
        self._pay = DEFAULT_PAY
        self._busy = False
        self._line = None

    # -- the block ----------------------------------------------------------
    def restore(self, raw: dict) -> None:
        """The saved knobs — applied to the STATE, which exists before the drawing."""
        super().restore(raw)
        block = dict(raw or {})
        self._goal = self._whole(block.get("goal"), 0)
        self._cap = self._whole(block.get("cap"), 0)
        self._pay = max(1, self._whole(block.get("pay"), DEFAULT_PAY))

    @staticmethod
    def _whole(value, fallback: int) -> int:
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return fallback

    # -- drawing ------------------------------------------------------------
    def build(self) -> None:
        frame = self.tr(ttk.LabelFrame(self.parent, padding=8), "hidden.card")
        frame.pack(fill="x", padx=8, pady=8)
        self._line = self.tr(ttk.Label(frame, justify="left"), "hidden.empty")
        self._line.pack(anchor="w")
        bar = ttk.Frame(frame)
        bar.pack(anchor="w", pady=(8, 0))
        self.tr(ttk.Button(bar, command=self.refresh), "hidden.refresh").pack(side="left")
        self.tr(ttk.Button(bar, command=self.dig), "hidden.dig").pack(side="left",
                                                                     padx=(6, 0))
        self.tr(ttk.Label(frame, foreground="#888", wraplength=620, justify="left"),
                "hidden.hint").pack(anchor="w", pady=(8, 0))

    def on_show(self) -> None:
        """The first look asks the game once. Every look after that draws what it has."""
        if not self._board:
            self.refresh()
        self._repaint()

    def _repaint(self) -> None:
        if self._line is None:
            return
        board = self._board
        if not board:
            self.rt.tr(self._line, "hidden.empty")
            return
        self._line.configure(text=self.t("hidden.line",
                                         score=board.get("score", 0),
                                         goal=self.goal(),
                                         digs=board.get("digs", 0),
                                         left=self.digs_left(),
                                         ready=board.get("ready", 0)))

    # -- what the numbers mean ----------------------------------------------
    def goal(self) -> int:
        """The goal being played to: the person's own, or the game's cap."""
        cap = int(self._board.get("goal") or 0)
        if self._goal > 0 and (cap <= 0 or self._goal < cap):
            return self._goal
        return cap

    def digs_left(self) -> int:
        """How many digs the distance to the goal is still worth, at the average pay.

        Never «how many are possible» — that is `digs` and it is drawn beside this one.
        A goal already earned answers 0, which is the whole point of the number.
        """
        short = self.goal() - int(self._board.get("score") or 0)
        if short <= 0:
            return 0
        return -(-short // max(1, self._pay))

    def week_ends(self) -> float:
        """When the week's board closes, on THIS machine's clock, or 0 if unknown.

        The game's own stamp is in server seconds and the panel draws countdowns off its
        own clock, so the two are bridged by the difference the reading itself carried.
        """
        closes = int(self._board.get("closes") or 0)
        now = int(self._board.get("now") or 0)
        if closes <= 0 or now <= 0 or self._read_at <= 0:
            return 0.0
        return self._read_at + (closes - now)

    def age(self) -> int:
        """Seconds since the board was read — what makes a stale reading visibly stale."""
        return 0 if self._read_at <= 0 else max(0, int(time.time() - self._read_at))

    # -- the two presses ----------------------------------------------------
    #
    # Both go through `rt.play_async`, which takes the game claim, runs the scenario on a
    # worker and hands the Outcome back on the Tk thread — so nothing here waits on the
    # thread that draws every open profile, and the readings the scenario left in
    # `ctx.vars` arrive where they can be drawn (`docs/panel-tabs.md`).

    def refresh(self) -> None:
        """Ask the game for the board. Only ever on a press or a first look."""
        if self._busy:
            return
        self._busy = True
        if not self.rt.play_async(READ_ACTION, {}, tag=self.ID, human=True,
                                  on_result=self._board_landed,
                                  on_done=self._free):
            self._busy = False

    def dig(self) -> None:
        """Play the ability, then re-read — the reading is what the page draws."""
        self._start(self.args())

    def claim(self) -> None:
        """Take the steps the week has already earned and dig nothing.

        The same ability with a goal that is already passed: it plans nothing, claims
        everything and says why in the log.
        """
        self._start(dict(self.args(), goal=1))

    def _start(self, args: dict) -> None:
        if self._busy:
            return
        self._busy = True
        if not self.rt.play_async(DIG_ACTION, args, tag=self.ID, human=True,
                                  on_done=self._dug):
            self._busy = False

    def _free(self) -> None:
        self._busy = False

    def _dug(self) -> None:
        """The run is over — free the page and read the board it left behind."""
        self._busy = False
        self.refresh()

    def _board_landed(self, outcome) -> None:
        """The reading, on the Tk thread. A run that did not happen changes nothing.

        A failed read is NOT written down as an empty board: «no daemon» and «the game
        says the week is over» are different answers, and the second one is the only one
        worth drawing.
        """
        ctx = getattr(outcome, "ctx", None)
        raw = (getattr(ctx, "vars", {}) or {}).get("board")
        if not getattr(outcome, "ok", False) or not isinstance(raw, str):
            return
        board = parse_board(raw)
        if not board:
            return
        self._board = board
        self._read_at = time.time()
        self._repaint()

    def args(self) -> dict:
        """What the ability is told — the three knobs and nothing else."""
        return {"goal": self._goal, "cap": self._cap, "pay": self._pay}

    # -- the knobs ----------------------------------------------------------
    def set_knob(self, key: str, value) -> None:
        """One setter, whoever pressed — the window, the phone, or a gear elsewhere."""
        whole = self._whole(value, 0)
        if key == "goal":
            self._goal = whole
        elif key == "cap":
            self._cap = whole
        elif key == "pay":
            self._pay = max(1, whole or DEFAULT_PAY)
        else:
            return
        self.remember({key: getattr(self, "_" + key)})
        self.rt.settings.changed()
        self.rt.post(self._repaint)

    def _fields(self) -> list:
        return [{"key": "goal", "label": "hidden.opt.goal", "hint": "hidden.opt.goal.hint",
                 "kind": "number", "value": self._goal, "min": 0, "max": 100000},
                {"key": "cap", "label": "hidden.opt.cap", "hint": "hidden.opt.cap.hint",
                 "kind": "number", "value": self._cap, "min": 0, "max": 100},
                {"key": "pay", "label": "hidden.opt.pay", "hint": "hidden.opt.pay.hint",
                 "kind": "number", "value": self._pay, "min": 1, "max": 5000}]

    # -- the phone -----------------------------------------------------------
    def web_view(self) -> "dict | None":
        """One card, drawn as the card an errand is, with the week's facts in words."""
        board = self._board
        item = {"text": self.t("hidden.score", score=board.get("score", 0),
                               goal=self.goal()) if board else self.t("hidden.unread"),
                "detail": self.t("hidden.age", minutes=self.age() // 60) if board else "",
                "pill": ("hidden.pill.open" if board.get("open")
                         else "hidden.pill.closed") if board else "hidden.pill.unread",
                "facts": [{"label": "hidden.fact.digs",
                           "value": str(board.get("digs", 0))},
                          {"label": "hidden.fact.left", "value": str(self.digs_left())},
                          {"label": "hidden.fact.ready",
                           "value": str(board.get("ready", 0))},
                          {"label": "hidden.fact.next",
                           "value": str(board.get("next", 0))}],
                "options": self._fields(),
                "options_title": "hidden.options",
                "actions": [{"id": "dig", "label": "hidden.dig"},
                            {"id": "claim", "label": "hidden.claim"}]}
        ends = self.week_ends()
        if ends > 0:
            item["until"] = ends
        card = {"title": "hidden.card", "layout": "cards", "items": [item],
                "note": "hidden.hint", "empty": "hidden.empty"}
        return {"cards": [card], "now": time.time(),
                "actions": [{"id": "refresh", "label": "hidden.refresh"}]}

    def web_press(self, action: str, args: dict) -> dict:
        args = args or {}
        if action == "refresh":
            self.refresh()
            return {"ok": True}
        if action == "dig":
            self.dig()
            return {"ok": True}
        if action == "claim":
            # The rewards on their own: the ability with nothing to dig still takes every
            # step the week has earned, which is what this press asks for.
            self.claim()
            return {"ok": True}
        if action == "set":
            key = str(args.get("key") or "")
            if key not in ("goal", "cap", "pay"):
                return {"ok": False, "reason": "hidden.unknown_knob"}
            self.set_knob(key, args.get("value"))
            return {"ok": True}
        return {"error": "unknown"}

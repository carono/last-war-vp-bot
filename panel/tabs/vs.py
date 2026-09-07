"""The «VS» tab: the duel week as six cards, one per day (#2617).

The person asked for it in these words: «Сделай отдельную вкладку VS, там будут такие
же карточки как в таймерах, первая карточка, понедельник, можно сразу 6 карточек
сделать по дням недели».

**It is not a second plan.** The week — what scores on each day, the ceilings each
action spends against, the details, the picks and the sets a day is played from — is
:mod:`panel.tabs.vs_duel`, and this tab IS that one: the same class, the same variables,
the same profile block, drawn under a name a person recognises. What it changes is the
SHAPE the phone sees it in: the week used to be six cards of bare switches, and it is
six cards of the kind «Таймеры» draws now — the picture, the name on one line, the day's
own switch in the corner and everything else behind the gear, which opens in the one
modal this front-end has (`panel/web/app/src/ui/Modal.tsx`, CLAUDE.md).

The window's half is inherited unchanged: the day grid the tab has always drawn. New
work goes into the web (CLAUDE.md, #1976), and there is no control here the window would
otherwise lose.

Nothing on this tab presses anything at the game beyond the one read it inherits —
«Записать дуэль», which is `actions/collect_vs_duel.md` and nothing else.
"""
from __future__ import annotations

from .vs_duel import DAYS, VsDuelTab, _Choice, walk_items


class VsTab(VsDuelTab):
    """The duel plan, drawn as a card per day of the week."""

    ID = "vs"
    TITLE_KEY = "tab.vs"
    ORDER = 330
    #: It replaces the tab it inherits from, which never left development mode, so it
    #: arrives switched ON like every new ability (CLAUDE.md, #2390). Nothing here
    #: spends anything: the plan is a set of choices, and the one press is a read.
    IN_DEVELOPMENT = False
    DEFAULT_ENABLED = True
    #: Its own key for the title, and the week's words are the ones it inherits.
    LOCALE_NS = ("vsduel", "vs")

    def __init__(self, rt, parent) -> None:
        """…and the week is LOADED here, which is not a nicety on this front-end.

        A block is applied by `restore`, and the panel that actually runs — the headless
        one behind the web (`panel/headless.py`) — calls it only for a block that is not
        empty. A profile that has never saved this tab therefore never had `apply_config`
        called at all, and the variables kept what `__init__` gave them: the day switch
        on and every action off. The window hides that by loading the week when it draws
        it; the phone has no drawing, so it read «0 / 4» over a plan the panel would have
        played in full. So the sets are put into the variables the moment the tab exists.

        The old block is where it looks first. «Дуэль VS» never left development mode, so
        most profiles have none — but one that DOES had a week typed into it, and a
        rename of the page is not a reason to hand somebody an empty one. From this tab's
        first save on, `restore` brings its own block and this seeding is overwritten.
        """
        super().__init__(rt, parent)
        try:
            old = self.rt.settings.tab_config("vs_duel")
        except Exception:                # noqa: BLE001 — a profile, never the panel
            old = {}
        self.apply_config(old if isinstance(old, dict) else {})

    # -- the phone's copy ------------------------------------------------------
    def web_view(self) -> "dict | None":
        """The week as cards, the last read, and the sets.

        Every card is a DAY: its switch on the card itself (the one thing a day is
        about), how much of it is ticked and which set it is played from on the line of
        facts, and the day's actions, ceilings, details and picks behind the gear. The
        knobs are the very fields the inherited screen sent — they travel back through
        the same `set` press, so nothing about what a knob MEANS lives here.
        """
        self._paint_collected()
        cards = [{"title": "vs.week", "layout": "cards",
                  "items": [self._web_day_item(day) for day, _items in DAYS]},
                 {"title": "vsduel.collect",
                  "rows": [{"label": "vsduel.collect.last",
                            "value": self._collected.get()}]},
                 self._web_sets_card()]
        return {"cards": cards,
                "actions": [{"id": "collect", "label": "vsduel.collect"}]}

    def _web_day_item(self, day: str) -> dict:
        """One day, as the card an errand is drawn as."""
        fields = self._web_day_card(day)["fields"]
        # The first field IS the day's own switch (`_web_day_card`), and it belongs on
        # the card rather than behind its gear (#2068): a row's one switch is the thing
        # the row is about.
        toggle, knobs = fields[0], fields[1:]
        return {"label": f"vsduel.day.{day}", "shape": "cover",
                "toggle": toggle,
                "options": knobs, "options_title": f"vsduel.day.{day}",
                "facts": [{"label": "vs.day.actions", "value": self._day_count(day)},
                          {"label": "vs.day.set",
                           # The set's name is DATA — the operator may have typed it.
                           "value": self._store.name(self._day_set[day].get(),
                                                     self.t)}]}

    def _day_count(self, day: str) -> str:
        """«3 / 6» — how much of the day is ticked, out of what it holds.

        A pick is not counted: one of its options is always chosen, so it is not
        something a person switches on or off.
        """
        on = total = 0
        for item in walk_items(dict(DAYS)[day]):
            if isinstance(item, _Choice):
                continue
            var = self._flags.get(f"{day}.{item.key}")
            if var is None:
                continue
            total += 1
            try:
                on += 1 if var.get() else 0
            except Exception:            # noqa: BLE001 — a half-built window
                pass
        return f"{on} / {total}"


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(VsTab))

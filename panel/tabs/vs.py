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

#: WHAT IS ACTUALLY WIRED, and nothing else is drawn (#2617). The person's words:
#: «делаем функциональный первый день, скрой все параметры, что еще не реализованы».
#: A tick over an ability nobody has written reads as «the bot will do this on Monday»,
#: and the bot will not. So a day draws the knobs named here and no others, and a day
#: with none of them says it is still being written instead of showing dead boxes.
#:
#: The names are `<day>.<action>`, exactly as the plan spells them.
READY: frozenset = frozenset({"mon.drone_chips", "mon.drone_level"})

#: …and which scenario each of those knobs RUNS, for the button beside it. The panel
#: holds no opinion about what the ability is: it plays the recipe and reports what came
#: back (CLAUDE.md). A ready knob with no recipe here simply has no button.
RUNS: dict = {"mon.drone_chips": "open_drone_chips",
              "mon.drone_level": "upgrade_drone"}


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
        """One day, as the card an errand is drawn as — with only what is wired on it."""
        fields = self._web_day_card(day)["fields"]
        # The first field IS the day's own switch (`_web_day_card`), and it belongs on
        # the card rather than behind its gear (#2068): a row's one switch is the thing
        # the row is about.
        toggle = fields[0]
        ready = [f for f in fields[1:] if self._plain_key(f.get("key")) in READY]
        item = {"label": f"vsduel.day.{day}", "shape": "cover", "toggle": toggle,
                "facts": [{"label": "vs.day.set",
                           # The set's name is DATA — the operator may have typed it.
                           "value": self._store.name(self._day_set[day].get(),
                                                     self.t)}]}
        if ready:
            item["options"] = ready
            item["options_title"] = f"vsduel.day.{day}"
            item["facts"].insert(0, {"label": "vs.day.actions",
                                     "value": self._day_count(day)})
        else:
            # A DAY NOBODY HAS WIRED SAYS SO, in one word, rather than offering knobs
            # that decide nothing.
            item["pill"] = "vs.day.soon"
        # ONE BUTTON PER WIRED KNOB, in the plan's own order, each saying WHAT it runs
        # (#2617): «Открыть чипы дрона» and «Повышать дрон» are two abilities on one
        # day, and a single «Выполнить» could only ever be one of them.
        acts = [{"id": "run", "args": {"key": name}, "label": label}
                for name, label in ((f"{day}.{action.key}", action.label)
                                    for action in self._day_actions(day))
                if name in READY and name in RUNS]
        if acts:
            item["actions"] = acts
        return item

    @staticmethod
    def _plain_key(key) -> str:
        """`plan.mon.drone_chips` -> `mon.drone_chips`; a ceiling keeps its own name."""
        text = str(key or "")
        return text[len("plan."):] if text.startswith("plan.") else text

    def _day_actions(self, day: str) -> list:
        """The day's actions in the order the plan lists them, its own picks left out."""
        return [item for item in walk_items(dict(DAYS)[day])
                if not isinstance(item, _Choice)]

    def web_press(self, action, args) -> dict:
        """The week's own presses, plus «run this one now» (#2617).

        The button plays the recipe the knob names and nothing else: no gate of the
        ability lives here, and the panel does not decide what «opening the chip chests»
        is (CLAUDE.md). A day switched off is not a refusal either — the person pressed
        it themselves, and a press is not the schedule.
        """
        if action != "run":
            return super().web_press(action, args)
        name = str((args or {}).get("key") or "")
        recipe = RUNS.get(name) if name in READY else None
        if recipe is None:
            return {"error": "unknown"}
        return {"ok": self.rt.play_async(recipe, tag="vs", human=True)}

    def _day_count(self, day: str) -> str:
        """«1 / 1» — how much of the day is ticked, out of what the panel can DO.

        A pick is not counted: one of its options is always chosen, so it is not
        something a person switches on or off. Neither is a box no scenario is behind
        (:data:`READY`) — the card would otherwise say «1 / 4» about a day on which the
        other three do nothing at all.
        """
        on = total = 0
        for item in self._day_actions(day):
            if f"{day}.{item.key}" not in READY:
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

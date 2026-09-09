"""The ARGUMENTS a built-in errand carries, as knobs instead of raw JSON (#2017).

WHY IT EXISTS. Five errands in the shipped catalogue are steered by their row's
`args` — how many warzones a star lap walks, which weekdays the radar duel scores on,
whether the radar claims or hoards, how many rounds of «Прорыв обороны» to play. Every
one of those is a decision a person makes about their own week, and until now the only
way to make it was to open the row's editor in the WINDOW and type JSON into a text
box. On a phone there was no way at all — the editor is not there, and the gear on
«Таймеры» showed the errand's other knobs while the ones that decide what it DOES were
invisible.

WHY IT IS IN THE RUNTIME AND NOT ON THE TIMERS TAB. The catalogue belongs to the
schedule, not to the page that draws it: a profile may have «Таймеры» switched off and
still run every errand in the list, and its phone still gets the timers screen
(`panel/web/api.py`). A knob registered by the tab would vanish with the tab, which is
exactly the fault #2010 found in the ghost robbery.

WHAT IT IS NOT. Not a second home for the values — the same rule as every other knob
here (`panel/runtime/errand_options.py`). The value lives in the errand's own row and
nowhere else; this only says which arguments are worth typing, what kind of control
each is and what bounds it has, and the write goes through the ONE setter that respects
a drawn «Таймеры» tab (`Schedule.set_timer_arg`).

WHAT IS DELIBERATELY NOT HERE. The steps and the title of a row: they are the
operator's text, and a phone that can rewrite a scenario by accident is not a remote
control (`panel/tabs/timers.py::web_edit` says the same thing at length). An errand
whose arguments are handed over LIVE by the page that owns them — the piece exchange —
is not here either: its rules are already knobs of the owning tab, and a copy here
would be a second answer to one question.
"""
from __future__ import annotations

from . import errand_options as errandopts

#: The weekdays a switch can name, 1 = Monday … 7 = Sunday. One locale key each rather
#: than a formatted number: «Дуэль: 3» is not a sentence anybody reads.
DAY_KEYS = tuple("errand.arg.day.%d" % day for day in range(1, 8))


def _flag(key: str, label_key: str, *, hint_key: str = "", default: int = 0) -> dict:
    """An argument the recipe reads as 0/1 — drawn as a switch, stored as a number.

    The recipes take numbers because the DSL has no booleans; a person should not have
    to know that, so the box is a box and the conversion happens on the way in.

    `default` is what the switch SHOWS while the row has never been written — and it
    must be the recipe's own `ARGS` value, or the two disagree: the errand would run
    with the recipe's default while the page drew the opposite. It is `0` only because
    most of the older knobs are opt-in; a knob whose recipe declares `ARGS x = 1` says
    `default=1` here (#2390, #2395).
    """
    return {"key": key, "label": label_key, "kind": errandopts.SWITCH,
            "hint": hint_key, "cast": "flag", "default": int(default)}


def _num(key: str, label_key: str, *, low: int, high: int,
         hint_key: str = "") -> dict:
    return {"key": key, "label": label_key, "kind": errandopts.NUMBER,
            "low": low, "high": high, "hint": hint_key, "cast": "int"}


def _choice(key: str, label_key: str, choices, *, hint_key: str = "") -> dict:
    """One argument out of a short list — `choices` is `((value, locale key), …)`."""
    return {"key": key, "label": label_key, "kind": errandopts.CHOICE,
            "choices": tuple(choices), "hint": hint_key, "cast": "int"}


def _days(key: str, *, hint_key: str = "") -> dict:
    """A LIST of weekdays, drawn as seven switches and stored as `[1, 3, 5, 6]`.

    Seven boxes rather than a text field for the reason the whole of #2017 exists: a
    comma-separated list typed on a phone is a value nobody can check before it is
    saved, and the one that matters here decides which days the radar spends squads on.
    """
    return {"key": key, "kind": "days", "hint": hint_key}


#: Which arguments of which shipped errand are worth a control, in the order they are
#: drawn. An errand that is not here keeps its arguments in the row editor, which is
#: the right answer for anything a person edits once a year.
SPEC: dict = {
    "do_radar_tasks": (
        _flag("claim", "errand.arg.radar.claim", hint_key="errand.arg.radar.claim.hint"),
        _flag("help", "errand.arg.radar.help"),
        _num("duel_day", "errand.arg.radar.duel_day", low=0, high=7,
             hint_key="errand.arg.radar.duel_day.hint"),
        _num("keep_free", "errand.arg.radar.keep_free", low=0, high=50),
    ),
    "radar_full_cycle": (
        _days("duel_days", hint_key="errand.arg.radar.duel_days.hint"),
        _choice("force", "errand.arg.radar.force",
                ((0, "errand.arg.radar.force.day"),
                 (1, "errand.arg.radar.force.spend"),
                 (2, "errand.arg.radar.force.hoard"))),
        _num("keep_free", "errand.arg.radar.keep_free", low=0, high=50),
        _flag("help", "errand.arg.radar.help"),
        _flag("march", "errand.arg.radar.march"),
    ),
    "do_radar_marches": (
        _flag("place", "errand.arg.radar.place"),
        _flag("forget", "errand.arg.radar.forget"),
    ),
    "sweep_star_servers": (
        _num("count", "errand.arg.star.count", low=1, high=20,
             hint_key="errand.arg.star.count.hint"),
    ),
    # THE DAY'S SECRET TASKS (#2022). Every one of these knobs existed already — on
    # «Командный пункт», a tab `IN_DEVELOPMENT` and therefore off in the live profile.
    # So the errand that spends the day's marches ran with a rule nobody could see, and
    # «отправлять отряды» silently unticked the game's «только UR» filter and sent the
    # cheap tasks with the UR ones. The filter is now a knob of its own, on by default,
    # and the recipe VERIFIES it rather than trusting that it was set.
    "secret_tasks_day": (
        _flag("only_ur", "errand.arg.secret.only_ur",
              hint_key="errand.arg.secret.only_ur.hint"),
        _num("keep", "errand.arg.secret.keep", low=0, high=20,
             hint_key="errand.arg.secret.keep.hint"),
        _flag("mega", "errand.arg.secret.mega"),
        _flag("use_diamonds", "errand.arg.secret.use_diamonds"),
        _num("diamond_cap", "errand.arg.secret.diamond_cap", low=0, high=100000,
             hint_key="errand.arg.secret.diamond_cap.hint"),
        _flag("dispatch", "errand.arg.secret.dispatch",
              hint_key="errand.arg.secret.dispatch.hint"),
    ),
    # THE TRADE TRUCKS (#2023). The errand spends a five-a-day allowance and the person's
    # Trade Contracts, and until now every one of those decisions was an `ARGS` line only
    # the row editor could reach — which on a phone is nowhere. «По одному за раз» is the
    # one the operator asked for by name: it sends the best truck standing and comes back
    # when it lands, so the fleet leaves under the first, strongest escort.
    # HEALING THE WOUNDED (#2085). The person asked to be able to say «по сколько
    # лечить»: the hospital takes ONE job at a time, so sending every wounded soldier in
    # the base starts a treatment that nothing else can interrupt, while a portion is as
    # much as they want to wait for — and the watch the run arms sends the next one the
    # moment the queue frees. Zero keeps the old behaviour, «all of them».
    "heal_units": (
        _num("portion", "errand.arg.heal.portion", low=0, high=1000000,
             hint_key="errand.arg.heal.portion.hint"),
        _flag("help", "errand.arg.heal.help", hint_key="errand.arg.heal.help.hint"),
        _flag("watch", "errand.arg.heal.watch", hint_key="errand.arg.heal.watch.hint"),
        _flag("chests", "errand.arg.heal.chests",
              hint_key="errand.arg.heal.chests.hint"),
    ),
    # THE ALERT TOWER (#2084). The errand claims what the training march finished,
    # pays the tasks that ask for something out of the bag, and spends the day's one
    # start. Each of those is a decision about somebody's own account — the handover
    # spends items — so all three are switches rather than a rule written into the
    # recipe, and they are drawn on «Вышка оповещения» as well as here.
    # THE WEEK'S CEREMONY (#2584). One knob, and it is cosmetic on purpose: the chest
    # counts LIKES and not faces, so which of the five ceremony reactions goes out is
    # the person's taste and nothing else. Everything that could be a rule here is the
    # server's own flag instead — a star already liked, a chest already claimed — and
    # a rule this recipe kept would be a second copy of the server's answer.
    "work_alliance_star": (
        _num("emoji", "errand.arg.alliance_star.emoji", low=1, high=5,
             hint_key="errand.arg.alliance_star.emoji.hint"),
    ),
    "work_alert_tower": (
        _flag("give_goods", "alerttower.give_goods",
              hint_key="alerttower.give_goods.hint"),
        _flag("start_run", "alerttower.start_run",
              hint_key="alerttower.start_run.hint"),
        _flag("take_box", "alerttower.take_box",
              hint_key="alerttower.take_box.hint"),
    ),
    # WHAT THE SHOP GIVES FOR NOTHING (#2395). Four claims, and each is a decision
    # about somebody's own account rather than a rule: the daily free gift of the
    # week-card page, the daily reward of the week and month cards already bought, the
    # levels an event battle pass has earned and not paid out, and the three claims that
    # are open only some days — the decoration shop's free spin, the recharge page's free
    # reward and the golloes camp's daily one. None of them spends a thing — the errand
    # never buys, and the only «attempt» it uses is one the game calls free — so all
    # seven default to on, and all are drawn on «Магазин» as well as here.
    "collect_shop_freebies": (
        _flag("free_gift", "shop.free_gift",
              hint_key="shop.free_gift.hint", default=1),
        _flag("card_daily", "shop.card_daily",
              hint_key="shop.card_daily.hint", default=1),
        _flag("month_card", "shop.month_card",
              hint_key="shop.month_card.hint", default=1),
        _flag("battle_pass", "shop.battle_pass",
              hint_key="shop.battle_pass.hint", default=1),
        _flag("decoration_free", "shop.decoration_free",
              hint_key="shop.decoration_free.hint", default=1),
        _flag("recharge_free", "shop.recharge_free",
              hint_key="shop.recharge_free.hint", default=1),
        _flag("golloes_free", "shop.golloes_free",
              hint_key="shop.golloes_free.hint", default=1),
    ),
    # THE GLITTERING MARKET, the free half (#2636). Three claims and a ceiling, and not
    # one of them can spend anything: the daily free reward (100 diamonds on the day the
    # event was read), the shop rows the GAME prices at zero, and the progress chests the
    # account has already earned. `cap` is only how many free rows one run asks for at
    # once — the quota is the event's, and what is left is taken next time.
    "collect_glittering_market": (
        _flag("free_reward", "market.free_reward",
              hint_key="market.free_reward.hint", default=1),
        _flag("free_goods", "market.free_goods",
              hint_key="market.free_goods.hint", default=1),
        _flag("boxes", "market.boxes",
              hint_key="market.boxes.hint", default=1),
        _num("cap", "market.cap", low=1, high=200,
             hint_key="market.cap.hint"),
    ),
    # …AND THE HALF THAT SPENDS (#2636). The row of the shop to buy, how many of it, and
    # the most coins one run may spend. A coin is bought with diamonds in the game's own
    # pack window and does not come back, so the errand is off, the price is said before
    # anything is sent, and `product = 0` means «nothing chosen» — the recipe stops
    # rather than guessing which of two dozen rows was meant.
    "buy_glitter_market_goods": (
        _num("product", "market.product", low=0, high=999999,
             hint_key="market.product.hint"),
        _num("count", "market.count", low=1, high=500,
             hint_key="market.count.hint"),
        _num("budget", "market.budget", low=0, high=1000000,
             hint_key="market.budget.hint"),
    ),
    # THE AUTOBUY OF THE SHOPS (#2666). The ORDER it spends in is not here on purpose:
    # it is a list of rows with a place each, and it is edited where the rows are drawn
    # («Магазин» → the gear on a good). What IS here is what a person decides about the
    # SPENDING itself, which is exactly the question somebody looking at «Таймеры» has:
    # how many diamonds one run may spend — 0 means «not one», which is the default and
    # the person's own rule about an irreversible spend — and how many purchases one run
    # may make at all.
    "autobuy_shop_goods": (
        _num("diamond_cap", "shop.opt.diamond_cap", low=0, high=100000,
             hint_key="shop.opt.diamond_cap.hint"),
        _num("cap", "shop.opt.cap", low=1, high=200,
             hint_key="shop.opt.cap.hint"),
    ),
    # THE HIDDEN TREASURES (#2597). The three knobs were a page of their own until the
    # person asked for it to go — «"Скрытые Сокровища" убираем отдельную вкладку,
    # настройки переносим в карточку в таймерах». They are the recipe's own `ARGS`, so
    # the row holds them and the gear edits the row: the week's goal (0 = the game's own
    # cap), the digs one run may make (0 = as many as the plan asks for), and what one
    # dig pays on average — which decides only how many digs the distance is planned as.
    "dig_hidden_treasures": (
        _num("goal", "hidden.opt.goal", low=0, high=100000,
             hint_key="hidden.opt.goal.hint"),
        _num("cap", "hidden.opt.cap", low=0, high=100,
             hint_key="hidden.opt.cap.hint"),
        _num("pay", "hidden.opt.pay", low=1, high=5000,
             hint_key="hidden.opt.pay.hint"),
    ),
    "send_trucks": (
        _flag("collect", "errand.arg.trucks.collect",
              hint_key="errand.arg.trucks.collect.hint"),
        _flag("one_at_a_time", "errand.arg.trucks.one_at_a_time",
              hint_key="errand.arg.trucks.one_at_a_time.hint"),
        _choice("target", "errand.arg.trucks.target",
                ((10, "errand.arg.trucks.target.sleigh"),
                 (5, "errand.arg.trucks.target.ur")),
                hint_key="errand.arg.trucks.target.hint"),
        _flag("refresh", "errand.arg.trucks.refresh"),
        _flag("dispatch", "errand.arg.trucks.dispatch"),
        _flag("use_diamonds", "errand.arg.trucks.use_diamonds"),
        _num("diamond_cap", "errand.arg.trucks.diamond_cap", low=0, high=100000,
             hint_key="errand.arg.trucks.diamond_cap.hint"),
    ),
    # ROBBING SOMEBODY ELSE'S TRUCK (#2591). Every one of these decides whether troops
    # come home: the rarity worth taking, the level below which a load is not worth a
    # fight, and how much weaker than us an escort has to be before the run will touch it.
    "rob_trucks": (
        _choice("quality", "errand.arg.rob.quality",
                ((10, "errand.arg.rob.quality.sleigh"),
                 (5, "errand.arg.rob.quality.ur"),
                 (0, "errand.arg.rob.quality.any")),
                hint_key="errand.arg.rob.quality.hint"),
        _num("min_level", "errand.arg.rob.min_level", low=1, high=99,
             hint_key="errand.arg.rob.min_level.hint"),
        _num("margin", "errand.arg.rob.margin", low=0, high=90,
             hint_key="errand.arg.rob.margin.hint"),
        _num("squad", "errand.arg.rob.squad", low=1, high=4,
             hint_key="errand.arg.rob.squad.hint"),
        _num("rotations", "errand.arg.rob.rotations", low=1, high=60,
             hint_key="errand.arg.rob.rotations.hint"),
        _num("pause_min", "errand.arg.rob.pause_min", low=1, high=240,
             hint_key="errand.arg.rob.pause_min.hint"),
    ),
    "play_frontline_breakthrough": (
        _num("rounds", "errand.arg.frontline.rounds", low=1, high=20),
    ),
}


def _as_int(value, low=None, high=None, fallback=0) -> int:
    """A number off a front-end, held inside its bounds. A blank is the fallback.

    Never `int(value)` on its own: the box may hold anything a thumb produced, and an
    errand's argument silently becoming 0 is «claim nothing» or «walk no warzones».
    """
    raw = str(value if value is not None else "").strip()
    try:
        number = int(float(raw))
    except (TypeError, ValueError):
        return fallback
    if low is not None:
        number = max(low, number)
    if high is not None:
        number = min(high, number)
    return number


def options_for(schedule, errand: str) -> tuple:
    """The knobs of one errand's arguments, or `()` for an errand with none.

    Each one reads the row as it is NOW rather than a value captured at registration:
    the row can be rewritten from the editor, from the phone, or by a profile switch,
    and a knob showing what it said an hour ago is the second answer this whole module
    exists to avoid.
    """
    built: list = []
    for spec in SPEC.get(errand, ()):
        if spec.get("kind") == "days":
            built.extend(_day_options(schedule, errand, spec))
            continue
        built.append(_one_option(schedule, errand, spec))
    return tuple(built)


def _one_option(schedule, errand: str, spec: dict):
    key = spec["key"]
    kind = spec["kind"]
    low, high = spec.get("low"), spec.get("high")

    fallback = int(spec.get("default") or 0)

    def read(_k=key, _kind=kind, _d=fallback):
        value = schedule.timer_arg(errand, _k, _d)
        if _kind == errandopts.SWITCH:
            return bool(_as_int(value, fallback=_d))
        return "" if value is None else value

    def write(value, _k=key, _kind=kind, _low=low, _high=high):
        if _kind == errandopts.SWITCH:
            schedule.set_timer_arg(errand, _k, 1 if value else 0)
            return
        current = _as_int(schedule.timer_arg(errand, _k), fallback=0)
        schedule.set_timer_arg(errand, _k,
                               _as_int(value, _low, _high, fallback=current))

    return errandopts.Option(
        key, spec["label"], kind, get=read, set=write,
        low=low, high=high, hint_key=spec.get("hint") or "",
        options=[{"value": value, "text_key": text_key}
                 for value, text_key in spec.get("choices", ())])


def _day_options(schedule, errand: str, spec: dict) -> list:
    """Seven switches over one list-valued argument."""
    key = spec["key"]

    def days() -> list:
        raw = schedule.timer_arg(errand, key)
        if isinstance(raw, (list, tuple)):
            return [_as_int(d) for d in raw]
        return []

    def write(on, day: int) -> None:
        chosen = {d for d in days() if 1 <= d <= 7}
        chosen.add(day) if on else chosen.discard(day)
        schedule.set_timer_arg(errand, key, sorted(chosen))

    return [errandopts.Option(
        "%s_%d" % (key, day), DAY_KEYS[day - 1], errandopts.SWITCH,
        hint_key=(spec.get("hint") or "") if day == 1 else "",
        get=(lambda d=day: d in days()),
        set=(lambda on, d=day: write(on, d)))
        for day in range(1, 8)]


def register(schedule) -> None:
    """Declare every shipped errand's arguments on that errand's own row.

    Called once, by the schedule that owns the catalogue, so the knobs are there for a
    profile with no «Таймеры» tab and for a tab nobody has opened alike.
    """
    for errand in SPEC:
        options = options_for(schedule, errand)
        if options:
            schedule.options.register(errand, options)

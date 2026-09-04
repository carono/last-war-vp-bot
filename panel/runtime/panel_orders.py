"""The standing orders that belong to NO tab — registered by the schedule (#2408).

WHY IT EXISTS. `panel/runtime/errand_options.py` already knows what a standing order is:
a watcher with a switch of its own, drawn among the triggers because that is what it is
to a person. Every one of them so far has been a TAB's — «Автолут ★» belongs to
«Секретки» — and the registry collects them from the tabs it is handed
(`Schedule._register_knobs`).

The reward-popup ear belongs to nobody. It lives inside the client
(`tools/lib/lua_actions.py::reward_watch_install`), it is put back by every recipe that
earns something, and the page that draws its book (`panel/tabs/rewards.py`) is
`IN_DEVELOPMENT` and therefore absent from the live profile. So the ability worked
perfectly and appeared nowhere: the person's own words, «мы поставили триггер на авто
закрытие сообщений о подарках, к слову работает отлично, но я не вижу в триггерах её
карточку».

Registering it from a tab would have repeated the fault #2010 found in the ghost robbery
— an order reachable only on a page the profile has switched off — so it is registered
HERE, beside `errand_args.register`, for the same reason that one is: the catalogue
belongs to the schedule, and a profile that draws no tabs at all still runs its errands
and still gets the timers screen on its phone.

WHERE THE VALUE LIVES. The wish is this profile's own setting (`reward_popups`), read and
written through `panel/runtime/opt_value.py` like every other knob; the client is TOLD
about it by a scenario (`actions/set_reward_popups.md`) and never by Python assembling
Lua. Nothing is stored twice.
"""
from __future__ import annotations

from . import errand_options as errandopts, opt_value

#: The order's name — its id on both front-ends, and the key of the profile setting the
#: switch moves. One word for one thing, so the row and the value cannot drift apart.
REWARD_ORDER = "reward_popups"

#: The recipe that carries the wish to the client.
REWARD_SCENARIO = "set_reward_popups"


def register(schedule) -> None:
    """Declare the orders that are in no catalogue. Called once, from `Schedule`."""
    rt = schedule.rt
    schedule.options.register_order(errandopts.Order(
        name=REWARD_ORDER,
        label_key="order.reward_popups",
        hint_key="order.reward_popups.hint",
        get=lambda: bool(opt_value.get(rt, REWARD_ORDER, True)),
        set=lambda on: _switch(rt, bool(on)),
        state=lambda: _state(rt),
    ))
    # …and the wish put back into a client that has been restarted since it was made.
    # EVENT-DRIVEN and never a clock (`CLAUDE.md`): the book already hears every drain
    # the panel writes, and a drain is proof that the ear is in — so the one moment a
    # muted ear can be noticed is the one moment it says something.
    try:
        rt.rewards.watch(lambda rows: _reassert(rt, rows))
    except Exception:                    # noqa: BLE001 — an order, never the panel
        pass


def _switch(rt, on: bool) -> None:
    """Move the wish, and tell the client. On the Tk thread, like every other setter."""
    opt_value.set(rt, REWARD_ORDER, on)
    _tell(rt, on)


def _tell(rt, on: bool) -> None:
    """Play the one recipe that carries the wish. A client that is away hears it at the
    next collect instead, which is what :func:`_reassert` is for."""
    try:
        rt.play_async(REWARD_SCENARIO, {"on": 1 if on else 0}, tag="order")
    except Exception:                    # noqa: BLE001 — a press, never the panel
        pass


def _reassert(rt, rows) -> None:
    """A drain arrived while the switch is OFF — the client has forgotten the wish."""
    if not rows:
        return
    try:
        if opt_value.get(rt, REWARD_ORDER, True):
            return
    except Exception:                    # noqa: BLE001 — a reading, never the panel
        return
    _tell(rt, False)


def _state(rt) -> str:
    """What the order is DOING, in this panel's own words — never a key (`CLAUDE.md`).

    Off the book that is already in memory, so the row costs the game nothing: how many
    popups were closed, and how many windows the ear saw and would not touch.
    """
    try:
        tally = rt.rewards.tally()
    except Exception:                    # noqa: BLE001 — a reading, never the panel
        return ""
    return rt.t("order.reward_popups.state",
                closed=int(tally.get("closed", 0)),
                unknown=int(tally.get("unknown", 0)))

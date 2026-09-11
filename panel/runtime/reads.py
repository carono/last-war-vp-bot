"""Live readings more than one tab needs.

Most game reads belong to the tab that shows them. This one does not: the resource
balance is the front page's «Ресурсы базы» card AND the raw material of the daily tally
the «Статистика» tab keeps, so it cannot live in either without the other importing a
tab.

ONE READING, ONE DOOR (#1990). Everything here is served out of
:class:`~panel.runtime.resources.BaseResources` — the profile's cache, filled by playing
`actions/read_base_resources.md`. There is no Lua in this file any more and there is no
second trip to the game: a page open on the phone and the tracker listening for balance
pushes read the same rows, at most one play of the scenario every half minute.

WHAT USED TO BE HERE, AND WHY IT NEVER WORKED. A hand-written chunk that asked
`DataCenter.ResourceManager` for `GetFood()`, then the field `food`, then
`R.resource.food` — «best-effort», every branch wrapped. None of the three exists in this
client: `ResourceManager` carries nothing but name/icon/building lookups, so every read
fell through its `pcall` and the function returned `{}` on every call it ever made. The
tally it fed was therefore empty for as long as it has existed, and nothing anywhere said
so — which is precisely what a `pcall` around a guess costs (the same lesson as
`docs/research/inventory.md`). The balance actually lives on `LuaEntry.Resource`, and it
answers by resource TYPE; the scenario asks it that way.
"""
from __future__ import annotations

#: The game's resource type -> the tracker's own key (`panel/resource_stats.py`).
#:
#: NOT the client's field names, which are the engine's originals and no longer say what
#: the game shows: the field spelled `wood` is drawn as «Золотые монеты» and the one
#: spelled `money` as «Еда». The types are what the client itself labels
#: (`ResourceManager:GetResourceNameByType`), read live on 2026-08-26 and written up in
#: `docs/research/base-resources.md`.
TRACKER_KEY = {
    14: "food",       # «Еда» — the bread the base grows
    1: "metal",       # «Металл»
    2: "gold",        # «Золотые монеты»
    23: "oil",        # «Нефть»
}


#: How an ITEM the base's lines pay is spelled in the tally (#2744). The four resources
#: above have a key of their own because the panel has always had one; an item is named
#: by the GAME's own id, because there is no panel word for «Запчасти дрона» and there
#: must not be one (`CLAUDE.md`, «Not one word of the panel is written in the panel»).
ITEM_PREFIX = "item:"


def item_key(item_id) -> str:
    """The tally's key for one of the base's item payments."""
    return ITEM_PREFIX + str(item_id)


def item_labels(rt) -> dict:
    """`{key: {"name", "icon"}}` for the items the last reading saw — the GAME's words.

    A LOOK at what is already in memory, never a read: the names and the pictures come
    off the same reading that carries the counts, so nothing here asks the game anything.
    """
    out: dict = {}
    try:
        rows = (rt.resources.cached() or {}).get("items") or []
    except Exception:                    # noqa: BLE001 — no reading, no labels
        return {}
    for row in rows:
        try:
            out[item_key(row.get("id"))] = {"name": str(row.get("name") or ""),
                                            "icon": str(row.get("icon") or "")}
        except Exception:                # noqa: BLE001 — a label, never the tally
            continue
    return out


def resource_balance(rt, cached: bool = False) -> dict:
    """The current balance in the tracker's own keys, off the profile's cached reading.

    ``rt`` is the :class:`~panel.runtime.host.PanelRuntime`. Returns ``{}`` when nothing
    has been read yet — no client, no game, a profile that is switched off — and the
    caller then records no gain rather than a false one.

    THE READING MAY BE UP TO :data:`~panel.runtime.resources.TTL_SEC` OLD, and that is
    deliberate. A tally built by differencing successive balances loses nothing to a
    stale one: two pushes inside the same half minute are counted as a single step of
    the same size, and the day's total is what it would have been. Reading the game on
    every push instead — which a busy account emits several times a minute — would spend
    a fifth of a second of the exclusive game link each time, for a number the tally does
    not need that promptly.

    ``cached=True`` is a LOOK at what the last reading left and books nothing — for a
    caller that has just been TOLD a fresh reading landed (#2743,
    `panel/runtime/resource_book.py`) and would otherwise ask the door for what it has.
    """
    try:
        source = rt.resources.cached if cached else rt.resources.state
        # ONE CALL, both halves: `state` is a door that books a refresh, so asking it
        # twice for one diff would be one press paying for two.
        data = source() or {}
    except Exception:                    # noqa: BLE001 — a bad read is not a gain
        return {}
    rows = data.get("rows") or []
    out: dict = {}
    for row in rows:
        key = TRACKER_KEY.get(row.get("type"))
        if key is not None:
            try:
                out[key] = int(row.get("count") or 0)
            except (TypeError, ValueError):
                pass
    # …AND THE ITEMS THE BASE'S LINES PAY (#2744). The person's words: «Ещё с базы мы
    # собираем компоненты дрона, шестерёнки и медали для обезьяны». They are not resource
    # types — a drone part is a resource ITEM and a chest is a bag stack — so the reading
    # carries them apart and they are counted here exactly as the four are: a balance to
    # be diffed, and never a number the panel works out for itself.
    for row in (data.get("items") or []):
        try:
            out[item_key(int(row.get("id")))] = int(row.get("count") or 0)
        except (TypeError, ValueError):
            continue
    return out


#: THE VARIABLE `actions/collect_base_resources.md` LEAVES ITS OWN SIZE IN (#2747).
#: Read off the game BEFORE the sweep presses anything — `GetBuildingCurrStorage` summed
#: by what each production line pays — so the panel knows exactly how much of the balance
#: movement that follows is the harvest's and how much came from somewhere else.
HARVEST_VAR = "harvest_pending"

#: How that variable is spelled: `type=amount` for a resource, `i<id>=amount` for an
#: item, « #|# » between them. The scenario's own words; nothing here is derived.
HARVEST_SEP = "#|#"


def parse_harvest(raw) -> dict:
    """`{tracker key: amount}` from what the harvest said it was about to collect.

    A record this panel has no key for — a season resource, a type the tally does not
    track — is dropped rather than invented: the budget it would arm is a budget for a
    column nobody counts.
    """
    out: dict = {}
    for record in str(raw or "").split(HARVEST_SEP):
        record = record.strip()
        if not record or "=" not in record:
            continue
        name, _, amount = record.partition("=")
        name = name.strip()
        try:
            value = int(float(amount.strip()))
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        if name.startswith("i"):
            try:
                key = item_key(int(name[1:]))
            except (TypeError, ValueError):
                continue
        else:
            try:
                key = TRACKER_KEY.get(int(name))
            except (TypeError, ValueError):
                continue
            if key is None:
                continue
        out[key] = out.get(key, 0) + value
    return out


def pending_balance(rt) -> dict:
    """`{tracker key: amount}` standing uncollected, off the LAST reading — a LOOK.

    The fallback budget for a harvest the panel did not play: a thumb on the green
    bubbles sends the same frame and leaves no variable anywhere, so the only statement
    of size available is whatever the last reading happened to say. It is never fresher
    than that reading and therefore only ever UNDERSTATES, which is the right way for
    this number to be wrong: a harvest priced short is a number somebody can question,
    a card three times over is one nobody can.
    """
    try:
        data = rt.resources.cached() or {}
    except Exception:                    # noqa: BLE001 — no reading, no budget
        return {}
    out: dict = {}
    for row in (data.get("rows") or []):
        key = TRACKER_KEY.get(row.get("type"))
        if key is None:
            continue
        try:
            value = int(row.get("pending") or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            out[key] = value
    for row in (data.get("items") or []):
        try:
            value = int(row.get("pending") or 0)
            key = item_key(int(row.get("id")))
        except (TypeError, ValueError):
            continue
        if value > 0:
            out[key] = value
    return out

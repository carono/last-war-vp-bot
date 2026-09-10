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
        rows = (source() or {}).get("rows") or []
    except Exception:                    # noqa: BLE001 — a bad read is not a gain
        return {}
    out: dict = {}
    for row in rows:
        key = TRACKER_KEY.get(row.get("type"))
        if key is not None:
            try:
                out[key] = int(row.get("count") or 0)
            except (TypeError, ValueError):
                pass
    return out

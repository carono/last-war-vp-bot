"""Live readings more than one tab needs.

Most game reads belong to the tab that shows them. These do not: the resource balance
is drawn by the «Профиль» tab AND tallied by the resource tracker, so it cannot live in
either without the other importing a tab.

BEST-EFFORT is the rule here. The exact accessors are not confirmed against a live
client, so each is wrapped and a field that cannot be read is left OUT rather than
guessed at — a missing number is an empty cell, a guessed one is a wrong tally.
"""
from __future__ import annotations

# gold=money, oil=petroleum on the wire (docs/research/city-protocol.md); the panel's
# own keys are the left-hand ones.
_RESOURCE_FIELDS = (("food", "food"), ("wood", "wood"), ("metal", "metal"),
                    ("oil", "petroleum"), ("gold", "money"))

_BALANCE_CHUNK = (
    'local R = DataCenter.ResourceManager or DataCenter.ResourceItemDataManager '
    'local function bal(field) '
    'if not R then return nil end '
    'local ok, v = pcall(function() return R["Get"..field:sub(1,1):upper()..field:sub(2)](R) end) '
    'if ok and type(v)=="number" then return v end '
    'ok, v = pcall(function() return R[field] end) if ok and type(v)=="number" then return v end '
    'ok, v = pcall(function() return R.resource[field] end) '
    'if ok and type(v)=="number" then return v end return nil end '
    'local out = {} '
    'for _, p in ipairs({' +
    ",".join('{"%s","%s"}' % pair for pair in _RESOURCE_FIELDS) +
    '}) do '
    'local n = bal(p[2]) if n ~= nil then out[#out+1] = p[1].."="..tostring(math.floor(n)) end end '
    'CS.UnityEngine.Debug.LogError("RB "..table.concat(out, " "))'
)


def resource_balance(game) -> dict:
    """The current balance off the live game, in the panel's own keys.

    ``game`` is the :class:`~panel.runtime.daemon.GameLink`. Returns ``{}`` when nothing
    is readable — no daemon, no game, or a manager that is not loaded yet — and the
    caller then records no gain rather than a false one.
    """
    if not game.up():
        return {}
    try:
        lines = game.evaluator().run(_BALANCE_CHUNK, marker="RB", settle=0.6)
    except Exception:                    # noqa: BLE001 — a bad read is not a gain
        return {}
    out: dict = {}
    for line in lines or []:
        if "RB " not in line:
            continue
        for token in line.split("RB ", 1)[1].split():
            if "=" in token:
                key, _, value = token.partition("=")
                try:
                    out[key] = int(value)
                except ValueError:
                    pass
    return out

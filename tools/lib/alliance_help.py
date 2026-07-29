r"""Answer the alliance's pending help requests — the reusable core.

One press of the in-game "Помочь всем" is one ``al.help.all`` message that answers
*every* pending request at once; the engine side (and why
``AllianceHelpDataManager:OnHelpAll`` is the reply applier rather than the press) is
written up in ``lua_actions.alliance_help_all`` and docs/research/alliance-help.md.

This module is the Python side of that press, shared by everything that wants to help
without a recipe run: the live auto-helper (``tools/alliance_help_monitor.py``) and the
panel checkbox behind it. No Lua is written here — every chunk comes from
``lua_actions`` (``alliance_help_send`` for the press, ``alliance_help_pending`` /
``alliance_help_red_point`` for the two readings), so the DSL
(`TAP help_ally_all xall`) and the auto-helper stay the same message gated the same way.

Everything runs through any evaluator exposing ``.run(chunk, marker, settle)`` — the warm
daemon client or a local ``LuaEval`` (see ``tools/lib/lua_client.py``).

Two gates, because one of them is blind
---------------------------------------

The obvious gate is the *list*: ``GetAllianceHelpList()`` entries that are not mine. For
a request the client already knows about that is right. For something woken by
``push.al.help.new`` it is **not enough**, and the reason is in the push handler itself
(``Net.Msgs.Alliance.PushAlHelpNewMessage.HandleMessage``, constants dumped live)::

    senderId | LuaEntry | Player | DataCenter | AllianceHelpDataManager | SetHelpNum |
    GetHelpNum | EventManager | Broadcast | EventId | UpdateAllianceHelpNum |
    BuildManager | GetFunbuildByItemID | ... | AllianceMemberNeedHelp

No ``otherHelpInfoList``, no insert: the push **only bumps the red-point counter**
(``SetHelpNum(GetHelpNum() + 1)``) and broadcasts the "somebody needs help" event. The
list of other people's requests is filled in by the *reply* to ``al.help.all``
(``AlHelpAllMessage.HandleMessage`` → ``OnHelpAll(otherHelpInfoList)``) and by the help
window's own query. So a request that has just arrived is visible as a **number** and
invisible as a **list entry** — which is exactly what a live run showed: four
``push.al.help.new`` frames, and ``GetAllianceHelpList()`` non-self count stuck at 0 for
seconds afterwards.

Hence :func:`signals` reads both, and the press fires when *either* says somebody is
waiting. The red-point count is the arrival signal (it is what the push increments and
what the reply resets); the list is what survives from the last reply. Both being zero,
and staying zero for the whole retry window, is what "nobody to help" actually means.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game_buttons  # noqa: E402
import lua_actions  # noqa: E402

# A "run" is any `evaluator.run(chunk, marker=None, settle=1.4) -> list[str]`.
Run = Callable[..., list]
Log = Callable[[str], None]

MARKER = "HELP"
BUTTON = "help_ally_all"

# The two readings are taken apart rather than through the button's `count_lua` (which
# is their max): logging *which* of them saw the request is what made the blind gate
# visible in the first place, and it is the line to look at when this misbehaves again.

# How long to keep re-reading the gates before accepting "nobody is waiting".
# ~1.5s: the client applies the push within a frame or two of the packet we decoded,
# and every attempt after the first costs one cheap daemon read.
GATE_TRIES = 6
GATE_GAP = 0.25


def _button():
    btn = game_buttons.get(BUTTON)
    if btn is None:                     # catalogue renamed/removed — say which
        raise KeyError(f"no {BUTTON!r} entry in the button catalogue "
                       f"(known: {', '.join(game_buttons.names())})")
    return btn


def signals(run: Run, settle: float = 0.35) -> "tuple[int, int] | None":
    """``(helpable list entries, red-point count)`` — the two "somebody is waiting" reads.

    ``None`` means neither could be read at all (daemon down, game restarting, Lua
    error) — which is not the same as zero and must not be treated as one.
    """
    chunk = ('local ok,v=pcall(function() return %s end) '
             'local ok2,n=pcall(function() return %s end) '
             'CS.UnityEngine.Debug.LogError("%s list="..(ok and tostring(v) or "ERR")'
             '.." num="..(ok2 and tostring(n) or "ERR"))'
             % (lua_actions.alliance_help_pending(),
                lua_actions.alliance_help_red_point(), MARKER))
    try:
        lines = run(chunk, MARKER, settle)
    except (RuntimeError, OSError):
        return None
    for line in lines:
        if "list=" not in line:
            continue
        listed = _number(line, "list=")
        number = _number(line, "num=")
        if listed is None and number is None:
            return None                 # both errored — the VM is not answering
        return listed or 0, number or 0
    return None


def _number(line: str, key: str) -> "int | None":
    if key not in line:
        return None
    raw = line.split(key, 1)[1].split()[0]
    try:
        return int(float(raw))
    except ValueError:                  # "ERR" / "nil" — unreadable, not empty
        return None


def press(run: Run) -> "str | None":
    """Fire one ``al.help.all``. Returns the Lua error text, or None on success.

    Sends `lua_actions.alliance_help_send()` — the bare message — and **not** the button's
    own chunk, which wraps the same send in the list gate. With the list at zero and only
    the red point raised (the live case this module exists for) that wrapper turns the
    press into a no-op that still reports success. The decision is made above, in
    :func:`answer_pending`, where both signals are visible.
    """
    btn = _button()
    chunk = ('local ok,err=pcall(function() %s end) '
             'CS.UnityEngine.Debug.LogError("%s sent="..(ok and "ok" or ("ERR:"..tostring(err))))'
             % (lua_actions.alliance_help_send(), MARKER))
    try:
        lines = run(chunk, MARKER, btn.wait)
    except (RuntimeError, OSError) as exc:
        return str(exc)
    for line in lines:
        if "sent=ERR:" in line:
            return line.split("sent=ERR:", 1)[1].strip()
    return None


def answer_pending(run: Run, log: "Log | None" = None,
                   tries: int = GATE_TRIES, gap: float = GATE_GAP) -> int:
    """Help everyone who is waiting, once. Returns how many requests it fired for.

    The press is gated on somebody actually waiting — a quiet alliance costs no server
    round trip (`#1087`: a speculative network call is a rejection with a toast, not a
    no-op). Both gates are honoured: the list (what the last reply left) and the
    red-point count (what a brand-new push raises), because neither alone sees
    everything — see the module docstring.

    A zero read is retried for ``tries * gap`` seconds first: a caller woken by the
    ``push.al.help.new`` packet can get here before the client has processed it.

    Returns 0 when nothing was waiting, when the game VM could not be reached, or when
    the press itself errored — in every case with a line through ``log``.
    """
    say: Log = log or (lambda _m: None)
    for attempt in range(1, max(1, tries) + 1):
        state = signals(run)
        if state is None:
            say("game VM unreachable — no help sent")
            return 0
        listed, number = state
        waiting = max(listed, number)
        if waiting > 0:
            err = press(run)
            if err:
                say(f"al.help.all failed: {err}")
                return 0
            say(f"helped {waiting} request(s) (list={listed}, red point={number})")
            return waiting
        if attempt < tries:
            time.sleep(gap)
    say("nobody to help — no message sent")
    return 0

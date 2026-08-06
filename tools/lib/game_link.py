"""Is this client still TALKING to the game server? — the rule, in one place.

A Last War client that has lost its server session goes on looking healthy from the
inside: the window draws, every Lua getter answers (with yesterday's numbers), and every
send returns `true` while nothing arrives. **No reading inside the client can tell**, because
the client itself does not know — it is holding a socket the far end closed. The whole
story is docs/research/server-link-status.md.

The tell is the socket table, and the rule for reading it is small and easy to get wrong:

* a healthy client keeps **half-closed sockets** while it plays — six of them, the losers
  of the gateway race it runs while logging in — so «there is a CLOSE_WAIT» proves
  nothing on its own. An ESTABLISHED game socket is checked FIRST and wins;
* it keeps an ESTABLISHED **loopback pair to itself**, which survives the server hanging
  up. Counting one as proof is exactly the lie this rule exists to stop;
* the **game port moves between builds** (`:17935`, then `:10012`), so the only port rule
  that survives an update is «anything that is not 80 or 443»;
* `TIME_WAIT` is NOT a loss — it is what a clean reconnect leaves behind, and a client
  that reconnects every few hours would otherwise look broken for a minute afterwards.

WHY IT LIVES HERE AND NOT IN THE PANEL. It used to live only in
`panel/runtime/game_process.py`, which meant the only layer that could ask was the one
DRAWING the answer. Everything that SENDS — `script_engine`, every scenario, every
tool — had no way to ask and did not, so a recipe on a stranded client pressed its way
to the end, got `true` from every send, and failed with a believable wrong reason
(#1259 spent a day concluding «the server silently refuses this march» over a client the
panel had already declared dead in its own log). The panel imports the rule from here
now; the engine asks it before it drives anything.

This module answers in **ids, not words**: the panel wraps them in its own locale keys
(`panel/runtime/game_process.py`), and nothing here may grow a translator.
"""
from __future__ import annotations

#: The ports the client talks HTTP on all day. Everything else that is remote and not
#: loopback is a candidate for the game gateway — see the module docstring for why this
#: is a port EXCLUSION list and not the game port itself.
NON_GAME_PORTS = frozenset({80, 443})

#: The four things that can honestly be said about a client.
#:
#: * ``ONLINE``  — an ESTABLISHED connection to the game server. The only green one.
#: * ``LOST``    — the process is alive and its sockets say the server hung up. The state
#:                 that used to read as «running»: everything answers, nothing arrives.
#: * ``UNKNOWN`` — alive, and its sockets make no verdict: one still starting up, or a
#:                 machine that will not attribute a foreign process's sockets. NOT a
#:                 fault, and never to be treated as one.
#: * ``OFFLINE`` — no client process at all, whatever the reason.
ONLINE = "online"
LOST = "lost"
UNKNOWN = "unknown"
OFFLINE = "offline"

#: The TCP states a socket sits in once the far end has closed and this one has not.
#: `TIME_WAIT` is deliberately absent — see the module docstring.
HALF_CLOSED = frozenset({"CLOSE_WAIT", "CLOSING", "LAST_ACK",
                         "FIN_WAIT1", "FIN_WAIT2"})


def is_game_socket(c) -> bool:
    """Could this row of the socket table be the connection to the game server?"""
    if not c.raddr or c.raddr.port in NON_GAME_PORTS:
        return False
    ip = c.raddr.ip or ""
    return not (ip.startswith("127.") or ip in ("::1", "0.0.0.0", "::"))


def live_endpoint(sockets) -> "str | None":
    """The established game connection among sockets already read, if there is one."""
    for c in sockets:
        if c.status == "ESTABLISHED" and is_game_socket(c):
            return f"{c.raddr.ip}:{c.raddr.port}"
    return None


def classify(sockets) -> tuple:
    """``(state, endpoint, dead)`` for a client that IS running, from its own sockets.

    Established first — that is the only proof of a live account, and a pile of
    half-closed sockets means nothing beside a live one. Failing that, a half-closed
    game socket is proof of the opposite. With neither, the honest answer is
    :data:`UNKNOWN` and not a guess: a client 45 seconds into starting up has exactly
    those sockets, and so does a machine that will not attribute a foreign process's.
    """
    conn = live_endpoint(sockets)
    if conn:
        return ONLINE, conn, 0
    dead = sum(1 for c in sockets if c.status in HALF_CLOSED and is_game_socket(c))
    return (LOST if dead else UNKNOWN), None, dead


def sockets_of(pids) -> list:
    """Every TCP socket owned by ``pids``, walked fresh — no cache, no psutil for callers.

    For a caller that holds no shared reading of the machine (the script engine, a tool
    run from a shell). The panel has its own cached walk and passes the rows straight to
    :func:`classify`; one uncached walk per scenario run is cheap beside what a scenario
    then does, and being a walk behind is worse here than being slow.

    An empty list back means «could not be read», which :func:`classify` turns into
    ``UNKNOWN`` — never into a loss.
    """
    try:
        import psutil
    except Exception:                      # noqa: BLE001 — no psutil is «cannot tell»
        return []
    wanted = {int(p) for p in pids or ()}
    if not wanted:
        return []
    try:
        return [c for c in psutil.net_connections(kind="tcp") if c.pid in wanted]
    except Exception:                      # noqa: BLE001 — a refused socket table, ditto
        return []


def state_of(pids) -> str:
    """The link state of the given client pids: ONLINE / LOST / UNKNOWN / OFFLINE.

    ``OFFLINE`` when there are no pids at all — there is no client to have a link.
    """
    if not pids:
        return OFFLINE
    return classify(sockets_of(pids))[0]

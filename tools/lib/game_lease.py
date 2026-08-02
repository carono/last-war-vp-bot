"""The game lease: who may drive the client right now, across processes.

The warm daemon (tools/lua_daemon.py) already serialises individual `run` calls — the
hijack is not reentrant. This is the coarser thing above it: an *action* is many chunks
over seconds, and two actions must not interleave inside the game.

The panel used to hold that as a process-wide flag (`_claim_busy`). That stopped being
enough the moment a single tab could be launched as its own process
(docs/research/panel-tabs-refactor.md §7): two windows, two flags, one game. So the
holder is recorded HERE, in the one thing both windows already share — the daemon.

Four properties, each load-bearing:

  * **A lease excludes other leases, never a plain `run`.** The read-only tabs and the
    account poll drive the VM without claiming anything and always have; making them
    queue behind a recipe would freeze the dashboard for the length of every action,
    which is a behaviour change and not this mechanism's business.
  * **A lease expires.** `ttl` seconds without a renew and it is dropped, so a client
    that died mid-action cannot wedge the game until someone restarts the daemon.
  * **A `run` carrying a token that is not the live lease is refused.** That is the case
    where an action's lease expired and somebody else took it: the right answer is to
    stop, not to carry on driving the game beside its new owner.
  * **Re-acquiring a token you already hold returns it unchanged**, so a nested claim
    inside one owner cannot deadlock against itself.

Kept out of lua_daemon.py so it can be imported — and tested — without the il2cpp
dependencies `lua_eval` brings.
"""
from __future__ import annotations

import threading
import time
import uuid

# Longest an unrenewed lease survives. Generous on purpose: every `run` renews it, so
# this only ever fires for a holder that stopped talking — crashed, or killed.
DEFAULT_TTL = 120.0
MAX_TTL = 3600.0
MIN_TTL = 1.0


class Lease:
    """One holder at a time. Named by ``owner``, proved by an opaque token.

    ``owner`` is for the human — a refusal says who has it. The token is the capability:
    only the holder can renew or release, and only its `run`s are let through.
    """

    def __init__(self, on_expire=None, clock=time.monotonic):
        self._lock = threading.Lock()
        self._on_expire = on_expire
        self._clock = clock
        self._token: "str | None" = None
        self._owner = ""
        self._ttl = DEFAULT_TTL
        self._deadline = 0.0
        self._since = 0.0

    # -- internals: call with the lock held ---------------------------------
    def _reap(self, now: float) -> None:
        """Drop a lease nobody renewed inside its ttl."""
        if self._token is not None and now >= self._deadline:
            owner, held = self._owner, now - self._since
            self._token, self._owner = None, ""
            if self._on_expire is not None:
                self._on_expire(owner, held)

    def _snapshot(self, now: float) -> dict:
        if self._token is None:
            return {"held": False}
        return {"held": True, "owner": self._owner,
                "held_sec": round(now - self._since, 1),
                "expires_in": round(self._deadline - now, 1)}

    # -- the three ops ------------------------------------------------------
    def acquire(self, owner: str, ttl: float = DEFAULT_TTL, token=None) -> dict:
        """``{"ok": True, "token": …}`` or ``{"ok": False, "busy": owner, "held_sec": n}``."""
        now = self._clock()
        try:
            ttl = float(ttl or DEFAULT_TTL)
        except (TypeError, ValueError):
            ttl = DEFAULT_TTL
        ttl = max(MIN_TTL, min(ttl, MAX_TTL))
        with self._lock:
            self._reap(now)
            if self._token is not None:
                if token and token == self._token:
                    self._deadline = now + self._ttl
                    return {"ok": True, "token": self._token, "reentrant": True}
                return {"ok": False, "busy": self._owner,
                        "held_sec": round(now - self._since, 1)}
            self._token = uuid.uuid4().hex
            self._owner = str(owner or "?")
            self._ttl = ttl
            self._since = now
            self._deadline = now + ttl
            return {"ok": True, "token": self._token}

    def renew(self, token) -> dict:
        now = self._clock()
        with self._lock:
            self._reap(now)
            if not token or token != self._token:
                return {"ok": False, "error": "lease lost"}
            self._deadline = now + self._ttl
            return {"ok": True, "expires_in": round(self._ttl, 1)}

    def release(self, token) -> dict:
        now = self._clock()
        with self._lock:
            self._reap(now)
            if self._token is None:
                return {"ok": True, "note": "not held"}
            if token != self._token:
                return {"ok": False, "error": "not the holder"}
            self._token, self._owner = None, ""
            return {"ok": True}

    # -- the gate a `run` passes through ------------------------------------
    def check_run(self, token) -> "str | None":
        """``None`` to let the run through, else the reason it is refused.

        No token → always through: reads and polls never queue behind an action.
        The live token → through, and the lease is renewed by the act of running.
        Any other token → refused; that holder lost the lease.
        """
        if not token:
            return None
        now = self._clock()
        with self._lock:
            self._reap(now)
            if token == self._token:
                self._deadline = now + self._ttl
                return None
            return ("lease lost — it expired or was taken by "
                    + (self._owner or "nobody"))

    def state(self) -> dict:
        now = self._clock()
        with self._lock:
            self._reap(now)
            return self._snapshot(now)

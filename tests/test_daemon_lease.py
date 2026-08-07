"""The game lease (tools/lib/game_lease.py) and the daemon ops that expose it.

Two halves. The lease itself is pure state under a fake clock, so expiry is tested
without waiting for it. Then the protocol: a real `lua_daemon.Daemon` with its evaluator
stubbed out, served over a real socket to real `lua_client.DaemonClient`s — which is the
only way to check the thing the lease exists for, two *processes* against one game.

Nothing here needs the game, the il2cpp stack or Tk: `lua_daemon` imports `LuaEval`
lazily precisely so this file can import it.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lib"))

import game_lease  # noqa: E402
import lua_client  # noqa: E402
import lua_daemon  # noqa: E402

#: A pid no machine hands out — the pin of a daemon whose client has died.
#: Windows pids are multiples of four and well under this; asking about it
#: is «is my client still there», answered «no», with nothing else running
#: on this box able to accidentally be it.
_IMPOSSIBLE_PID = 0x7FFF_FFF0


class FakeClock:
    """A clock that only moves when the test says so."""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


# --------------------------------------------------------------------------
# the lease itself
# --------------------------------------------------------------------------

def test_one_holder_at_a_time():
    lease = game_lease.Lease(clock=FakeClock())
    first = lease.acquire("panel/rally", ttl=60)
    assert first["ok"] and first["token"], first

    second = lease.acquire("panel/timers", ttl=60)
    assert second["ok"] is False, second
    assert second["busy"] == "panel/rally", second

    assert lease.release(first["token"])["ok"] is True
    third = lease.acquire("panel/timers", ttl=60)
    assert third["ok"] and third["token"] != first["token"], third


def test_reacquiring_your_own_token_is_not_a_deadlock():
    """Auto-loot claims, then the tool it spawns claims again with the inherited token."""
    lease = game_lease.Lease(clock=FakeClock())
    tok = lease.acquire("panel/autoloot", ttl=60)["token"]
    again = lease.acquire("panel/autoloot", ttl=60, token=tok)
    assert again["ok"] and again["token"] == tok and again.get("reentrant"), again


def test_a_lease_expires_and_the_next_owner_can_take_it():
    clock = FakeClock()
    expired = []
    lease = game_lease.Lease(clock=clock, on_expire=lambda o, h: expired.append((o, h)))
    tok = lease.acquire("panel/rally", ttl=10)["token"]

    clock.advance(9)
    assert lease.acquire("panel/timers")["ok"] is False   # still held

    clock.advance(2)                                       # 11s > ttl
    taken = lease.acquire("panel/timers")
    assert taken["ok"], taken
    assert expired and expired[0][0] == "panel/rally", expired
    # …and the dead holder cannot renew its way back in
    assert lease.renew(tok)["ok"] is False


def test_renewing_keeps_it_alive():
    clock = FakeClock()
    lease = game_lease.Lease(clock=clock)
    tok = lease.acquire("panel/rally", ttl=10)["token"]
    for _ in range(5):
        clock.advance(8)
        assert lease.renew(tok)["ok"] is True
    assert lease.acquire("panel/timers")["ok"] is False    # never lapsed


def test_only_the_holder_may_release():
    lease = game_lease.Lease(clock=FakeClock())
    tok = lease.acquire("panel/rally")["token"]
    assert lease.release("not-the-token")["ok"] is False
    assert lease.state()["held"] is True
    assert lease.release(tok)["ok"] is True
    assert lease.state()["held"] is False
    assert lease.release(tok)["ok"] is True                # releasing twice is fine


def test_check_run_lets_unleased_calls_through_and_stops_stale_ones():
    clock = FakeClock()
    lease = game_lease.Lease(clock=clock)
    tok = lease.acquire("panel/rally", ttl=10)["token"]

    # A read with no token is never blocked — that is the whole point of the rule.
    assert lease.check_run(None) is None
    assert lease.check_run("") is None
    # The holder passes, and running renews.
    assert lease.check_run(tok) is None
    clock.advance(9)
    assert lease.check_run(tok) is None                    # renewed by the run above
    # Someone else's token is refused.
    other = game_lease.Lease(clock=clock).acquire("x")["token"]
    assert lease.check_run(other) is not None

    # And once it lapses, the ex-holder's own runs are refused too.
    clock.advance(30)
    refused = lease.check_run(tok)
    assert refused and "lease lost" in refused, refused


def test_ttl_is_bounded():
    lease = game_lease.Lease(clock=FakeClock())
    tok = lease.acquire("x", ttl=999999)["token"]
    assert lease.state()["expires_in"] <= game_lease.MAX_TTL
    lease.release(tok)
    lease.acquire("x", ttl=0)                              # 0/None -> the default
    assert lease.state()["expires_in"] >= game_lease.MIN_TTL


# --------------------------------------------------------------------------
# the protocol: two clients, one daemon
# --------------------------------------------------------------------------

class _FakeEval:
    """Stands in for the warm LuaEval: records chunks, returns one line each."""

    def __init__(self):
        self.chunks = []

    def run(self, chunk, marker=None, settle=1.2, early=False, sentinel=None):
        # `sentinel` (#1272) has to be here even though nothing in this file passes
        # one: `Daemon.run` forwards every keyword it was given, a stand-in that will
        # not take it raises TypeError, and the daemon's «stale handle?» recovery reads
        # that as a dead evaluator and builds a REAL one — so an offline test goes
        # looking for a game client and reports the link as gone (#1282).
        self.chunks.append(chunk)
        return [f"{marker or 'X'} ok"]

    def close(self):
        pass


class _Server:
    """The real daemon dispatch on a real socket, with the game stubbed out."""

    def __init__(self):
        self.daemon = lua_daemon.Daemon()
        self.daemon._ev = _FakeEval()          # so _ensure never imports lua_eval
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=lua_daemon._handle,
                             args=(conn, self.daemon), daemon=True).start()

    def client(self, token=""):
        return lua_client.DaemonClient("127.0.0.1", self.port, timeout=5.0, token=token)

    def close(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass


def test_two_clients_cannot_both_hold_the_game():
    srv = _Server()
    try:
        panel, standalone = srv.client(), srv.client()
        tok = panel.acquire("panel/main", ttl=60)
        assert tok, "the first claim should win"
        assert standalone.acquire("panel.tabs.rally", ttl=60) is None, \
            "a second window must not get the game while the first holds it"

        # The refusal says who has it, so the operator is not left guessing.
        assert standalone.lease_state().get("owner") == "panel/main"

        assert panel.release() is True
        assert standalone.acquire("panel.tabs.rally", ttl=60), \
            "released means the next window can take it"
    finally:
        srv.close()


def test_a_plain_read_is_never_blocked_by_a_lease():
    """The account poll and the read-only tabs must not queue behind a recipe."""
    srv = _Server()
    try:
        holder, reader = srv.client(), srv.client()
        assert holder.acquire("panel/rally", ttl=60)
        assert reader.token == ""
        assert reader.run("return 1", marker="R") == ["R ok"]
        assert holder.run("return 2", marker="H") == ["H ok"]
    finally:
        srv.close()


def test_a_run_on_a_lost_lease_is_refused_not_executed():
    srv = _Server()
    try:
        first = srv.client()
        stale = first.acquire("panel/rally", ttl=60)
        assert stale
        # Model the lease being lost: the daemon drops it and another owner takes it.
        srv.daemon.lease.release(stale)
        second = srv.client()
        assert second.acquire("panel.tabs.rally", ttl=60)

        before = len(srv.daemon._ev.chunks)
        try:
            first.run("TAP something", marker="A")
        except lua_client.LeaseLost as exc:
            assert "lease" in str(exc).lower(), exc
        else:
            raise AssertionError("a run on a lost lease must raise, not execute")
        assert len(srv.daemon._ev.chunks) == before, \
            "the refused chunk must never reach the game"
    finally:
        srv.close()


class _DeadClient:
    """The machine, once this daemon's client has died: nothing of ours is running.

    Stubbed rather than read, so the case is the same on a box with a live client as on
    one without — and so `_repin` cannot quietly re-aim this daemon at whatever else
    happens to be up while the test runs.
    """

    @staticmethod
    def alive(_pid):
        return False

    @staticmethod
    def session_pids(*_a, **_kw):
        return []


class _DeadStack:
    """`from lua_eval import LuaEval` on a client that is gone — the real failure.

    `SystemExit`, not an `Exception`, and the raw words of a Windows call: that is what
    `il2cpp_probe.module_base` does, and it is half of why this arrived at the panel as
    a stranger's message.
    """

    @staticmethod
    def LuaEval():                                  # noqa: N802 — the real name
        raise SystemExit("snapshot failed err=5")


def test_a_daemon_whose_client_is_gone_says_so_instead_of_err_5():
    """The third thing a failed run can mean, and the one nothing used to say (#1266).

    A daemon attached to a client that has died stays up, stays warm and goes on
    answering — with the raw words of a Windows call. `SystemExit: snapshot failed
    err=5` reads as a bug in the toolkit, so a whole evening of timers reported it and
    not one reader anywhere concluded «the client is gone»
    (docs/research/server-link-status.md §2.2).

    Note what is NOT stubbed: the daemon still drops its evaluator and rebuilds once
    before it gives up, exactly as it does live. The verdict is only reached after the
    cure it can apply by itself has failed.
    """
    srv = _Server()
    saved_pin = os.environ.get("LW_GAME_PID")
    saved_mods = {n: sys.modules.get(n) for n in ("lua_eval", "game_client")}
    # A pin naming a pid nothing can be: the daemon ASKS about its own client rather
    # than reading the error text and hoping.
    os.environ["LW_GAME_PID"] = str(_IMPOSSIBLE_PID)
    sys.modules["lua_eval"], sys.modules["game_client"] = _DeadStack, _DeadClient
    try:
        srv.daemon._ev = None                       # nothing warm left to answer with
        try:
            srv.client().run("return 1", marker="A")
        except lua_client.LeaseLost as exc:
            raise AssertionError(f"a dead client is not a lost lease: {exc}") from exc
        except lua_client.ClientGone as exc:
            said = str(exc).lower()
            assert "client" in said, exc
            assert "gone" in said or "not there" in said, exc
            assert "snapshot failed err=5" in said, \
                "the original failure must still be carried, for whoever debugs it"
        else:
            raise AssertionError("a run against a dead client must raise ClientGone")
    finally:
        if saved_pin is None:
            os.environ.pop("LW_GAME_PID", None)
        else:
            os.environ["LW_GAME_PID"] = saved_pin
        for name, mod in saved_mods.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        srv.close()


def test_an_older_daemon_is_understood_without_being_restarted():
    """…and the fix works on the daemon that is ALREADY RUNNING.

    A warm daemon outlives the panel by design and will go on running for days, so a
    cure that needed it restarted would be a cure for the next incident and not for
    this one. The flag is preferred; the sentence is recognised when there is no flag.
    """
    assert lua_client._client_gone({"client_gone": True, "error": "whatever"})
    assert lua_client._client_gone({"error": "SystemExit: snapshot failed err=5"})
    assert lua_client._client_gone({"error": "SystemExit: LastWar.exe not running"})
    assert lua_client._client_gone({"error": "GameAssembly.dll not found in pid 4242"})
    # …and a chunk that is simply wrong stays the author's problem.
    assert not lua_client._client_gone({"error": "LuaError: attempt to index a nil value"})
    assert not lua_client._client_gone({"error": "lease lost"})


def test_a_child_inherits_the_lease_through_the_token():
    """LW_GAME_LEASE is how the tool auto-loot spawns drives the game it already holds."""
    srv = _Server()
    try:
        parent = srv.client()
        tok = parent.acquire("panel/autoloot", ttl=60)
        child = srv.client(token=tok)               # what LW_GAME_LEASE gives it
        assert child.run("hero.dispatch.steal", marker="C") == ["C ok"]
        # …and it may re-claim without deadlocking against its parent's hold
        assert child.acquire("tools/steal_secret_task", ttl=60) == tok
    finally:
        srv.close()


def test_the_environment_carries_the_lease_to_later_clients():
    """A recipe builds its own evaluator mid-action — it must inherit, not run unleased.

    The panel publishes the token into `os.environ` while it holds the game, which is
    how it reaches both an evaluator constructed after the claim and every child. A
    client built while nothing is published must come out unleased.
    """
    import os
    saved = os.environ.get(lua_client.LEASE_ENV_VAR)
    try:
        os.environ.pop(lua_client.LEASE_ENV_VAR, None)
        assert lua_client.current_lease() == ""
        assert lua_client.DaemonClient("127.0.0.1", 1).token == ""

        os.environ[lua_client.LEASE_ENV_VAR] = "deadbeef"
        assert lua_client.current_lease() == "deadbeef"
        assert lua_client.DaemonClient("127.0.0.1", 1).token == "deadbeef"
        # …unless the caller says otherwise: a read opts out explicitly.
        assert lua_client.DaemonClient("127.0.0.1", 1, token="").token == ""
    finally:
        os.environ.pop(lua_client.LEASE_ENV_VAR, None)
        if saved is not None:
            os.environ[lua_client.LEASE_ENV_VAR] = saved


def test_ping_reports_the_lease():
    srv = _Server()
    try:
        c = srv.client()
        assert c.lease_state() == {"held": False}
        c.acquire("panel/rally", ttl=60)
        state = c.lease_state()
        assert state["held"] is True and state["owner"] == "panel/rally", state
    finally:
        srv.close()


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())

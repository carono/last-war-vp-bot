r"""The chat runs on its own thread, blocks nobody, and does not wait for the farm (#2594).

The person's rule, in their own words: «Чат должен всегда работать в отдельном потоке и
его действия ничего не должны блокировать и сам он не зависит от работы сценариев
панели».

WHAT WAS ACTUALLY WRONG, measured on this account's own `panel.log` over
2026-09-03..06 before the change:

  * **The chat took no game claim at all.** Its five readings went through
    `rt.actions.play(...)`, which is the one door that claims nothing — so every chat
    call interleaved into whatever run was holding the lease, and the two took it off
    each other. 1538 translation batches whose own work is one call, one 3-second wait
    and two reads: median 5 s, p90 11 s, **max 127 s**, and **16** runs that ended
    «lease lost — it expired or was taken by default/timer».
  * **It held what it did take across its own WAIT.** No chat recipe declared `SHARE`,
    so a 3-second wait for the game's translator was 3 seconds the farm could not have.
  * **A person's typed line was DROPPED when the client was busy** — eight «занят» in
    four minutes for one message, because a press refused by an equal-ranked holder gave
    up on the spot.
  * **And nothing at all ran while the light was amber.** 61 chat runs were turned away
    by #2446's gate, which is «чат не работает, пока фарм чинится» — the opposite of
    what was asked for.

So four promises are pinned here, one per cause. No Tk, no game, no daemon.

    C:\Python312\python.exe tests\test_panel_chat_thread.py
    python3 tests/test_panel_chat_thread.py
"""
from __future__ import annotations

TIER = "ui"        # `panel.runtime` imports Tk on the way in

import sys
import time
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "tools" / "lib"))
sys.path.insert(0, str(_REPO / "src"))

import profile_health  # noqa: E402

from lastwar_bot import script_engine  # noqa: E402
from panel.runtime import claims as claimsmod  # noqa: E402
from panel.runtime import gate as gatemod  # noqa: E402
from panel.runtime import power as powermod  # noqa: E402

#: Every ability the chat has, and the whole of what this file is about.
CHAT = ("read_chat_rooms", "read_chat_history", "fetch_chat_history",
        "send_chat_message", "translate_chat_batch", "translate_chat_message")

HOST = (_REPO / "panel" / "runtime" / "host.py").read_text(encoding="utf-8")
TAB = (_REPO / "panel" / "tabs" / "chat.py").read_text(encoding="utf-8")


class _Light:
    """`ProfileHealth` as the gate sees it — built through the real verdict."""

    def __init__(self, plumbing: str = profile_health.LANDING,
                 reason: str = profile_health.TRAFFIC) -> None:
        self.current = profile_health.verdict(
            running=True, plumbing=plumbing,
            server=(profile_health.ANSWERING if reason == profile_health.TRAFFIC
                    else profile_health.SILENT),
            maintenance=reason == profile_health.MAINTENANCE)
        self.read_at = time.time()


class _RT:
    """The three things the gate reads, and nothing else."""

    def __init__(self, plumbing: str = profile_health.LANDING,
                 reason: str = profile_health.TRAFFIC) -> None:
        self.game = types.SimpleNamespace(ready=lambda fresh=False: True,
                                          up=lambda fresh=False: True)
        self.health = _Light(plumbing, reason)
        self.power = powermod.Power()
        self.gate = gatemod.LinkGate(self)

    def say(self, tag: str, key: str, **fmt) -> None:
        pass

    def dbg(self, component: str = "panel"):
        return types.SimpleNamespace(info=lambda *a, **k: None,
                                     warning=lambda *a, **k: None,
                                     error=lambda *a, **k: None,
                                     debug=lambda *a, **k: None)


# --- 1. the recipes let go of the client between their own statements -------

def test_every_chat_recipe_declares_share():
    """`SHARE` on all six — the chat opens no window, so it holds nothing it is not using.

    The one that mattered most is `translate_chat_batch`: its `WAIT 3` is the game's own
    translator thinking, and 1538 of those in three days is over an hour of link that the
    farm was simply not allowed to have.
    """
    for name in CHAT:
        assert script_engine.resolve_action(name) is not None, name
        assert script_engine.action_shares(name) is True, \
            f"{name} does not declare SHARE — it would hold the client across its WAIT"


def test_no_chat_recipe_pretends_to_be_detached():
    """`SHARE` and `DETACH` are different declarations and the chat wants only one.

    A detached run answers its caller before it has done anything, which is wrong for a
    send: «отправил» has to mean the game confirmed it.
    """
    for name in CHAT:
        assert script_engine.action_detached(name) is False, name


# --- 2. amber does not silence the chat -------------------------------------

def test_the_chat_runs_while_the_server_is_silent_and_the_client_is_reachable():
    """THE DECISION, pinned: chat is an exception to #2446, on the recovery's terms.

    A silent server is exactly the state in which somebody most wants to read what the
    alliance is saying — and four of the six recipes answer perfectly there, because they
    read the copy the CLIENT is holding and ask the server nothing.
    """
    rt = _RT(profile_health.LANDING, reason=profile_health.NO_TRAFFIC)
    assert rt.gate.alive() is False, "the light must still be amber"
    assert rt.gate.blocks("collect_resources") != "", "the farm is still held"
    for name in CHAT:
        assert rt.gate.blocks(name) == "", name


def test_a_client_the_panel_cannot_reach_holds_the_chat_like_everything_else():
    """The narrow half of the exception. Nothing to read, nowhere to send: hold it.

    Without this the exception would be the very thing #2446 removed — runs that cannot
    succeed, filling the log and queueing ahead of the restart.
    """
    rt = _RT(profile_health.NOT_LANDING, reason=profile_health.NO_CONNECTION)
    for name in CHAT:
        assert rt.gate.blocks(name) != "", name


def test_a_switched_off_profile_is_not_playing_chat_either():
    """«Профиль выключен» means the account is not playing — the chat included."""
    rt = _RT()
    rt.power.set(False)
    for name in CHAT:
        assert rt.gate.blocks(name) == "action.held.off", name


def test_the_exception_names_exactly_the_chat_and_nothing_else():
    """A list an agent can audit, not an `if` per caller."""
    assert gatemod.CHAT_ACTIONS == frozenset(CHAT)
    assert not (gatemod.CHAT_ACTIONS & gatemod.RECOVERY_ACTIONS), \
        "a chat recipe is not a recovery scenario and must not be filed as one"


# --- 3. a press is not demoted, and is not dropped --------------------------

def test_a_person_s_press_keeps_its_rank_although_the_recipe_shares():
    """`SHARE` says how a run HOLDS the client, never how hard it is to get.

    Demoted to :data:`claims.SHARED` a press outranks nothing at all, so the first thing
    holding the client refuses it — which for a chat send means the line the person typed
    is gone.
    """
    assert "if shares and not detached and not human:" in HOST, \
        "a human press of a sharing scenario is being demoted to SHARED again"
    assert claimsmod.SHARED < claimsmod.BACKGROUND < claimsmod.HUMAN


def test_a_sharing_run_queues_behind_an_equal_instead_of_dying_on_the_spot():
    """Waiting costs nothing when the waiter holds nothing.

    The give-up branch is for a press that would only shuffle the order of two things
    that both have to happen. A sharing run is not that: it hangs its demand on the door
    and `claim_soon` answers with the same «занят» a few seconds later if it really
    cannot get in.
    """
    assert "if not held and not self.game.outranks(priority) and not shares:" in HOST


# --- 4. the chat's own readings take the claim ------------------------------

def test_the_chat_tab_plays_through_the_claimed_door():
    """`rt.play_now`, never `rt.actions.play` — the door that takes no claim at all.

    This is the one that produced the 127-second batch and the sixteen lost leases: an
    unclaimed run asking the daemon with whatever token the runtime happened to hold,
    while a timer held the lease it was using.
    """
    assert "rt.actions.play(" not in TAB, \
        "a chat reading is going through the unclaimed door again"
    assert TAB.count("rt.play_now(") == 5


def test_play_now_runs_where_it_was_called_and_hands_the_outcome_back():
    """The claimed call for a worker thread: same gate, same claim, no Tk round trip."""
    assert "def play_now(" in HOST
    assert "inline: bool = False" in HOST
    assert "deliver = (lambda call: call()) if inline else self._on_tk" in HOST
    assert "self._on_tk(" not in HOST.split("def play_async(")[1].split("def post(")[0], \
        "a callback inside play_async still goes to Tk unconditionally"
    assert "priority: int = claims.SHARED" in HOST, \
        "play_now must default to the level that steps aside for anybody"


def _run_standalone() -> int:
    tests = [obj for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())

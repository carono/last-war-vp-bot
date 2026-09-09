r"""Три статуса и ни одного четвёртого: один огонёк на профиль (#1911).

A person with four accounts open reads four tab labels and nothing else, so each tab
carries its profile's whole state in one colour — and there are exactly three of them:

* **red** — there is no client process;
* **amber** — there IS a client and no traffic from the game. Never a resting state: it
  is a diagnosis, and it says which of the two halves failed;
* **green** — the game SERVER answered.

The danger is entirely on one side: an amber that should have been green costs a second
glance, and a green that should have been amber is never looked at again — which is how
an account farms nothing all night while every indicator says it is fine
(`docs/research/server-link-status.md` §5). So this file is mostly a list of things that
must NOT be green, plus the one distinction the whole model turns on: a client that is
wedged (restart it) against wiring of ours that is broken (fix it, and never restart a
client for it).

The rule is `tools/lib/profile_health.py` and takes ids, so none of this needs a game, a
socket or a clock. The wording half needs `panel.runtime`, which drags Tk in.

    C:\Python312\python.exe tests\test_profile_health.py
"""
from __future__ import annotations

TIER = "ui"        # panel.runtime drags tkinter in — see tools/run_tests.py

import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import profile_health as ph                              # noqa: E402

from panel.runtime.health import ProfileHealth           # noqa: E402


class _Probe:
    """`panel.runtime.game_process.Probe` as far as the light is concerned."""

    def __init__(self, running: bool = True, text: str = "") -> None:
        self.running = running
        self.message = text or ("client is running" if running else "no client")


# -- the rule ----------------------------------------------------------------

def test_there_are_exactly_three_colours() -> None:
    """A fourth colour is a colour nobody reads — the whole point of #1911."""
    seen = set()
    for running in (True, False):
        for plumbing in (ph.LANDING, ph.NOT_LANDING, ph.PLUMBING_UNASKED):
            for server in (ph.ANSWERING, ph.SILENT, ph.SERVER_UNASKED):
                for responding in (True, False):
                    seen.add(ph.verdict(running=running, plumbing=plumbing,
                                        server=server, responding=responding).colour)
    assert seen == {ph.OK, ph.WARN, ph.BAD}, seen


def test_no_client_is_red_whatever_else_is_true() -> None:
    """Nothing else can be true or false about a process that is not there."""
    said = ph.verdict(running=False, plumbing=ph.LANDING, server=ph.ANSWERING)
    assert (said.colour, said.reason) == (ph.BAD, ph.NO_CLIENT)


def test_only_a_server_that_answered_is_green() -> None:
    """Green is a guarantee. A client that lands chunks proves nothing about the server:
    a stranded client accepts every send and nothing arrives."""
    landing = ph.verdict(running=True, plumbing=ph.LANDING, server=ph.SILENT)
    assert landing.colour == ph.WARN and landing.reason == ph.NO_TRAFFIC
    unasked = ph.verdict(running=True, plumbing=ph.LANDING, server=ph.SERVER_UNASKED)
    assert unasked.colour == ph.WARN, "an unasked question is not a green light"
    asked = ph.verdict(running=True, plumbing=ph.LANDING, server=ph.ANSWERING)
    assert (asked.colour, asked.reason) == (ph.OK, ph.TRAFFIC)


def test_a_wedged_client_and_a_bug_of_ours_are_told_apart() -> None:
    """THE DISTINCTION THE WHOLE MODEL RESTS ON. Both are amber and the cures are
    opposites: one is a client to restart, the other is our own code to fix."""
    hung = ph.verdict(running=True, plumbing=ph.NOT_LANDING, responding=False)
    assert (hung.colour, hung.reason) == (ph.WARN, ph.CLIENT_HUNG)
    ours = ph.verdict(running=True, plumbing=ph.NOT_LANDING, responding=True)
    assert (ours.colour, ours.reason) == (ph.WARN, ph.NO_CONNECTION)


def test_nothing_landing_outranks_a_server_that_answered_a_while_ago() -> None:
    """If we cannot drive the client, that is the fact worth showing — the server's last
    answer is about a moment that has passed."""
    said = ph.verdict(running=True, plumbing=ph.NOT_LANDING, server=ph.ANSWERING)
    assert said.reason in (ph.NO_CONNECTION, ph.CLIENT_HUNG)


def test_a_profile_nothing_has_read_is_red_and_keeps_the_reason() -> None:
    """Amber means «there is a client and no traffic», so it may not double as «I have
    not looked» — that is what a closed game looks like, and the first poll corrects it."""
    said = ph.unread("boom")
    assert (said.colour, said.reason, said.error) == (ph.BAD, ph.NO_CLIENT, "boom")


# -- the wording -------------------------------------------------------------

def test_every_reason_has_a_sentence_and_a_key() -> None:
    """A reason with no words is a light with no explanation."""
    light = ProfileHealth()
    for plumbing, server, responding in ((ph.LANDING, ph.ANSWERING, True),
                                         (ph.LANDING, ph.SILENT, True),
                                         (ph.NOT_LANDING, ph.SILENT, True),
                                         (ph.NOT_LANDING, ph.SILENT, False)):
        light.update(_Probe(True), plumbing=plumbing, server=server,
                     responding=responding)
        key = light.message().key
        assert key.startswith("health."), key
    light.update(_Probe(False))
    assert light.message().key == "health.no_client"


def test_the_tooltip_names_the_reading_that_decided_it() -> None:
    """Amber with no explanation leaves a person unable to tell what to fix."""
    light = ProfileHealth()
    light.update(_Probe(True), plumbing=ph.NOT_LANDING, server=ph.SILENT,
                 responding=True, error="attach failed")
    said = light.lines(lambda key, **fmt: key)
    assert any("health.tip.plumbing" in line for line in said), said
    assert any("health.tip.server" in line for line in said), said
    assert any("attach failed" in line for line in said), said


def test_the_phone_gets_the_same_verdict_the_window_draws() -> None:
    """One reading, two front-ends — never two answers waiting to disagree."""
    light = ProfileHealth()
    light.update(_Probe(True), plumbing=ph.LANDING, server=ph.ANSWERING)
    state = light.state(lambda key, **fmt: key)
    assert state["colour"] == light.colour == ph.OK
    assert state["reason"] == ph.TRAFFIC
    assert state["tip"] and isinstance(state["tip"], list)


def test_a_reading_that_blew_up_stops_claiming_anything() -> None:
    light = ProfileHealth()
    light.update(_Probe(True), plumbing=ph.LANDING, server=ph.ANSWERING)
    assert light.colour == ph.OK
    light.failed(RuntimeError("the poll raised"))
    assert light.colour == ph.BAD and "raised" in light.current.error


# --- the closed door (#1982) -----------------------------------------------
def test_the_maintenance_message_narrows_the_amber_it_would_have_been() -> None:
    """Amber either way — but «wait» rather than «find the fault»."""
    plain = ph.verdict(running=True, plumbing=ph.LANDING, server=ph.SILENT)
    shut = ph.verdict(running=True, plumbing=ph.LANDING, server=ph.SILENT,
                      maintenance=True)
    assert plain.colour == shut.colour == ph.WARN
    assert plain.reason == ph.NO_TRAFFIC
    assert shut.reason == ph.MAINTENANCE


def test_a_server_that_answers_is_playing_whatever_dialog_is_on_screen() -> None:
    """The expensive mistake is telling somebody their working account is closed."""
    said = ph.verdict(running=True, plumbing=ph.LANDING, server=ph.ANSWERING,
                      maintenance=True)
    assert said.colour == ph.OK and said.reason == ph.TRAFFIC


def test_no_client_at_all_outranks_the_dialog_it_cannot_be_showing() -> None:
    said = ph.verdict(running=False, maintenance=True)
    assert said.colour == ph.BAD and said.reason == ph.NO_CLIENT


def test_the_maintenance_light_has_words_on_both_front_ends() -> None:
    light = ProfileHealth()
    light.update(_Probe(True), plumbing=ph.LANDING, server=ph.SILENT, maintenance=True)
    assert light.state(lambda key, **fmt: key)["text"] == "health.maintenance"


def test_a_client_that_says_it_is_not_logged_in_is_named_as_such():
    """The amber a person cannot read off «нет связи» gets its own word (#2060).

    Same colour, different act: our plumbing is fixed, a client outside the game is
    knocked on. A person looking at the strip could not tell the two apart before.
    """
    said = ph.verdict(running=True, plumbing=ph.LANDING, server=ph.SILENT, in_game=False)
    assert said.colour == ph.WARN and said.reason == ph.NOT_IN_GAME


def test_only_the_clients_own_evidence_counts_never_a_failed_reading():
    """`None` is «nobody could ask» and stays the plain amber it always was."""
    unasked = ph.verdict(running=True, plumbing=ph.LANDING, server=ph.SILENT, in_game=None)
    assert unasked.reason == ph.NO_TRAFFIC
    playing = ph.verdict(running=True, plumbing=ph.LANDING, server=ph.SILENT, in_game=True)
    assert playing.reason == ph.NO_TRAFFIC


def test_being_outside_the_game_never_takes_a_green_light_away():
    """Same rule the maintenance narrowing has (#1982): the server answering wins."""
    said = ph.verdict(running=True, plumbing=ph.LANDING, server=ph.ANSWERING, in_game=False)
    assert said.colour == ph.OK and said.reason == ph.TRAFFIC


def test_the_green_light_says_how_old_its_answer_is() -> None:
    """«Показывай» — the person's answer to «зелёный живёт 5 минут» (#2061).

    Green means the game SERVER answered, and that answer has a five-minute shelf life
    (`recovery.PROBE_OK_HOLD_SEC`) — so a colour on its own is a statement about a moment
    presented as a statement about now. An answer four seconds old and one four minutes
    old paint the same dot; the age is the difference, and both front-ends draw it.

    Dropping green sooner was NOT asked for and is not done: the threshold stands and
    becomes honest instead.
    """
    light = ProfileHealth()
    light.update(_Probe(True), plumbing=ph.LANDING, server=ph.ANSWERING,
                 server_at=time.time() - 243)
    assert light.colour == ph.OK
    assert 240 <= light.server_age <= 246, light.server_age
    assert light.state(lambda key, **fmt: key)["server_age"] > 0
    # …and the window's tooltip says it in words, off the same vocabulary the phone uses.
    said = light.lines(lambda key, **fmt: key + (str(sorted(fmt.items())) if fmt else ""))
    assert any("web.ui.ago" in line for line in said), said


def test_a_light_that_never_had_an_answer_says_so_rather_than_guessing() -> None:
    """`-1` is «never answered», which is not «answered a long time ago»."""
    light = ProfileHealth()
    light.update(_Probe(True), plumbing=ph.LANDING, server=ph.SILENT)
    assert light.server_age == -1.0
    assert light.state(lambda key, **fmt: key)["server_age"] == -1.0


def test_a_kicked_client_is_never_green() -> None:
    """The one narrowing that OUTRANKS green (#2061), and why it has to.

    The person's words: «когда выкинуло из игры, состояние светится зеленым, только по
    доп сообщению можно понять, что был кик, состояние зеленым быть не может, т.к.
    трафика нет». A taken account goes on drawing, its getters answer out of what they
    last received and its sends return `true` while nothing arrives — so the server probe
    that answered a minute BEFORE the kick is still inside its shelf life, and the light
    stayed green while somebody else played the account.

    Maintenance and «not logged in» sit below green because there a green light means a
    client that is demonstrably talking. Here it means a stale reading.
    """
    said = ph.verdict(running=True, plumbing=ph.LANDING, server=ph.ANSWERING, kicked=True)
    assert said.colour == ph.WARN and said.reason == ph.KICKED


def test_the_kick_does_not_hide_a_client_we_cannot_drive_at_all() -> None:
    """It is a narrowing of what is BELOW it, never of the two faults above it."""
    hung = ph.verdict(running=True, plumbing=ph.NOT_LANDING, responding=False, kicked=True)
    assert hung.reason == ph.CLIENT_HUNG
    gone = ph.verdict(running=False, kicked=True)
    assert gone.colour == ph.BAD and gone.reason == ph.NO_CLIENT


def test_the_kick_light_has_words_on_both_front_ends() -> None:
    light = ProfileHealth()
    light.update(_Probe(True), plumbing=ph.LANDING, server=ph.ANSWERING, kicked=True)
    state = light.state(lambda key, **fmt: key)
    assert state["colour"] == ph.WARN and state["text"] == "health.kicked"


def test_the_shut_door_outranks_the_login_screen():
    """Both are true during maintenance; «the server is shut» is the one that helps."""
    said = ph.verdict(running=True, plumbing=ph.LANDING, server=ph.SILENT,
                      maintenance=True, in_game=False)
    assert said.reason == ph.MAINTENANCE


def test_a_client_we_cannot_drive_is_ours_whatever_it_last_said():
    """Nothing landing outranks it: that amber is our plumbing, and #1268 owns it."""
    said = ph.verdict(running=True, plumbing=ph.NOT_LANDING, server=ph.SILENT,
                      in_game=False)
    assert said.reason == ph.NO_CONNECTION



def test_a_missing_windows_session_is_its_own_red():
    """Red either way, and a DIFFERENT reason, because the act is a person's (#2677)."""
    plain = ph.verdict(running=False)
    gone = ph.verdict(running=False, session_missing=True)
    assert plain.colour == ph.BAD
    assert gone.colour == ph.BAD
    assert plain.reason == ph.NO_CLIENT
    assert gone.reason == ph.NO_SESSION


def test_a_running_client_is_never_narrowed_by_the_session_reading():
    """The narrowing belongs to «there is no client» and to nothing else."""
    made = ph.verdict(running=True, plumbing=ph.LANDING, server=ph.ANSWERING,
                      session_missing=True)
    assert made.reason == ph.TRAFFIC
    assert made.colour == ph.OK

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

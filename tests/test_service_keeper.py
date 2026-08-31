r"""The service OWNS the panels: what it starts, what it leaves alone, how it lets go.

    «Не, не пойдет, центр правды — это служба, если я её поднял,
      значит все уже должно работать»            — the person, 2026-08-26

Before that the machine had two things to bring up and the one that survived a reboot did
nothing on its own. `panel/service/keeper.py` is the other arrangement, and these are the
four things it must not get wrong — each of which would be discovered live, at a cost:

  * **a wanted profile with no panel is started**, and started ONCE — a supervisor that
    starts a second panel for a profile the first one already holds is a profile opened
    twice, which is a lock fight and two schedules on one account;
  * **a panel restarting ITSELF is not overtaken.** «⟳ Перезапустить панель» is how a code
    fix reaches a running panel (`CLAUDE.md`), and it shuts down before its replacement
    dials in. Inside that gap the keeper must do nothing;
  * **going down asks, never kills.** A killed panel leaves locks, children and a client
    nobody let go of — and it asks only the panels IT started: somebody who opened
    `panel.bat` to look at a window keeps their window;
  * **«nobody is signed in» is a state, not a failure**: it is said once, it backs off,
    and it never turns into a launch attempt per tick all night.

Runs anywhere: no Windows, no service, no game — the launcher is a stub.

    C:\Python312\python.exe tests\test_service_keeper.py
    python3 tests/test_service_keeper.py
"""
from __future__ import annotations

TIER = "offline"   # no SCM, no session, no display

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from panel.service import keeper as keepermod      # noqa: E402
from panel.service import session as sessionmod    # noqa: E402


class _Panel:
    """A connected panel, as much of one as the keeper ever touches."""

    def __init__(self, pid: int, profiles, closed: bool = False, at: float = 0.0) -> None:
        self.pid = pid
        self.profiles = list(profiles)
        self.closed = closed
        #: When it dialled in. The keeper picks THE panel by it, oldest first.
        self.at = float(at or pid)
        self.asked: list = []
        #: What a press on the profiles screen answers. Swapped by the tests that are
        #: about a panel turning an open down.
        self.answer = (200, {"ok": True})

    def ask(self, method, path, query, body, timeout=None):
        body = dict(body or {})
        self.asked.append((method, path, body))
        if path == "/api/panel" and body.get("action") == "quit":
            self.closed = True                # a panel that took the press goes away
            return 200, {"ok": True}
        if path == "/api/screen/press":
            status, payload = self.answer
            if status == 200 and payload.get("ok"):
                name = str((body.get("args") or {}).get("name") or "")
                if name and name not in self.profiles:
                    self.profiles.append(name)
            return status, dict(payload)
        return 200, {"ok": True}


class _Registry:
    def __init__(self, panels=()) -> None:
        self.panels = list(panels)

    def all(self) -> list:
        return list(self.panels)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _keeper(registry, *, answers=None, profiles=("solo",), clock=None):
    """A keeper whose launcher is a list of canned answers, and whose clock is ours."""
    said = list(answers or [{"ok": True, "pid": 4242, "session": 1, "how": "popen"}])
    calls: list = []

    def launcher(cmd, *, cwd="", session_id=-1, log=None):
        calls.append({"cmd": cmd, "cwd": cwd, "session": session_id})
        return said.pop(0) if said else {"ok": False, "why": "failed", "detail": "no more"}

    lines: list = []
    keep = keepermod.Keeper(registry, {"keep": {"profiles": list(profiles)}},
                            log=lines.append, launcher=launcher,
                            clock=clock or _Clock())
    return keep, calls, lines


# ---------------------------------------------------------------------------
def test_a_wanted_profile_with_no_panel_is_started_once():
    registry = _Registry()
    keep, calls, _ = _keeper(registry)
    keep.tick()
    assert len(calls) == 1, calls
    assert calls[0]["cmd"][1:3] == ["-m", "panel.headless"], calls[0]["cmd"]
    assert "--profile" in calls[0]["cmd"] and "solo" in calls[0]["cmd"]

    # The panel is up now: nothing more is started, ever, for that profile.
    registry.panels.append(_Panel(4242, ["solo"]))
    for _ in range(5):
        keep.tick()
    assert len(calls) == 1, "a second panel was started for a profile already served"


def test_a_panel_restarting_itself_is_not_overtaken():
    clock = _Clock()
    registry = _Registry([_Panel(1, ["solo"])])
    keep, calls, _ = _keeper(registry, clock=clock)
    keep.tick()
    assert not calls, "started a panel for a profile that has one"

    registry.panels.clear()                   # it went down to come back
    clock.now += keepermod.GRACE_SEC - 5
    keep.tick()
    assert not calls, "overtook a panel's own restart"

    clock.now += 10                           # …and it never came back
    keep.tick()
    assert len(calls) == 1, "a panel that really died was not replaced"


def test_a_panel_that_is_up_but_not_talking_is_not_started_over():
    """The register knows who is TALKING; the lock knows who exists (#1994).

    A panel whose link to the service has dropped — or which somebody started by hand, or
    which is still coming up — serves no profile as far as the register is concerned. Read
    as an empty account it got a second panel started on top of it every time the grace ran
    out, and the machine reached EIGHT panels on one profile: one log, one `config.json`
    and one client written over by eight schedules.
    """
    clock = _Clock()
    keep, calls, lines = _keeper(_Registry(), clock=clock)
    keep.held = lambda name: True             # the kernel says a panel process is on it
    for _ in range(4):
        keep.tick()
        clock.now += keepermod.CHECK_SEC
    assert not calls, f"started a panel on top of one that is already there: {calls}"
    said = [ln for ln in lines if "already holds" in ln]
    assert len(said) == 1, f"said it {len(said)} times: {said}"

    keep.held = lambda name: False            # …and when it really is gone, one is started
    keep.tick()
    assert len(calls) == 1, calls


def test_nobody_signed_in_is_said_once_and_backed_off():
    registry = _Registry()
    clock = _Clock()
    keep, calls, lines = _keeper(
        registry, answers=[{"ok": False, "why": "no_session"}] * 6, clock=clock)
    for _ in range(3):
        keep.tick()
        clock.now += 1                        # ticks come every CHECK_SEC, not per hour
    assert len(calls) == 1, f"tried again inside its own backoff: {len(calls)}"

    clock.now += keepermod.BACKOFF_SEC[0] + 1
    keep.tick()
    assert len(calls) == 2, "never tried again"
    said = [ln for ln in lines if "signed in" in ln]
    assert len(said) == 1, f"said it {len(said)} times: {said}"


def test_going_down_asks_its_own_panels_and_leaves_the_persons_alone():
    mine, theirs = _Panel(4242, ["solo"]), _Panel(777, ["solo"])
    registry = _Registry([mine, theirs])
    keep, _, lines = _keeper(registry)
    keep.own.add(4242)
    keep.stop(wait=0.5)
    assert mine.asked, "the panel the service started was not asked to quit"
    assert mine.asked[0][1] == "/api/panel" and mine.asked[0][2]["action"] == "quit"
    assert not theirs.asked, "a panel the PERSON started was shut down by the service"


def test_a_panel_that_will_not_go_is_left_alone_and_said():
    class _Stubborn(_Panel):
        def ask(self, *a, **k):
            return 200, {"ok": True}          # takes the press and stays up

    stuck = _Stubborn(4242, ["solo"])
    keep, _, lines = _keeper(_Registry([stuck]))
    keep.own.add(4242)
    keep.stop(wait=0.5)
    assert any("left alone" in ln for ln in lines), lines
    assert not stuck.closed, "the keeper killed a panel instead of leaving it"


def test_which_profiles_is_a_SETTING_and_falls_back_to_this_machines_own_answer():
    assert keepermod.settings({})["profiles"] == []
    assert keepermod.settings({"keep": {"profiles": ["a", " b "]}})["profiles"] == ["a", "b"]
    assert keepermod.settings({"keep": {"enabled": False}})["enabled"] is False
    assert keepermod.settings({"keep": {"session": "3"}})["session"] == 3
    assert keepermod.settings({"keep": {"session": "nonsense"}})["session"] == -1

    # Nothing configured: whatever THIS MACHINE WANTS FARMED — never a name written into
    # the code (`CLAUDE.md`).
    keep, calls, _ = _keeper(_Registry(), profiles=())
    assert keep.wanted() == keepermod.machine_profiles()


def test_what_the_machine_wants_is_a_WISH_and_not_what_a_panel_last_had_open():
    """The list the service supervises may not be rewritten by looking at something.

    `open_profiles` is a record every panel process rewrites on every open, close and
    switch. Reading it as «what this machine wants farmed» meant a panel started for ten
    minutes to look at two test accounts became the boot list — and then the service put
    those accounts back five seconds after every attempt to quit them, which is what
    «погасили, она подняла снова» was (#2068).

    The wish is `panel/profile.py::keep_or_last_open`, written only by a person. What is
    pinned here is that the keeper asks THAT and not the record — including the fallback,
    so a machine that has never decided goes on behaving exactly as it did.
    """
    from panel import profile as profilemod

    asked: list = []
    real_keep = profilemod.keep_or_last_open
    real_open = profilemod.ProfileManager.open_profiles

    def wish():
        asked.append("wish")
        return ["wanted"]

    def record(self):
        asked.append("record")
        return ["a-look-at-something"]

    profilemod.keep_or_last_open = wish
    profilemod.ProfileManager.open_profiles = record
    try:
        # `exists` filters the answer, so the name has to be one this machine really has;
        # what matters is WHICH question was asked, so the filter is stood aside.
        real_exists = profilemod.ProfileManager.exists
        profilemod.ProfileManager.exists = lambda self, name=None: True
        try:
            assert keepermod.machine_profiles() == ["wanted"], keepermod.machine_profiles()
        finally:
            profilemod.ProfileManager.exists = real_exists
        assert "record" not in asked, asked
    finally:
        profilemod.keep_or_last_open = real_keep
        profilemod.ProfileManager.open_profiles = real_open


def test_switched_off_it_is_the_door_it_used_to_be():
    keep, calls, lines = _keeper(_Registry())
    keep.settings["enabled"] = False
    keep.tick()
    keep.start()
    assert not calls, "supervised something with supervision switched off"
    assert keep.wanted() == []


def test_a_panel_that_is_up_is_ASKED_and_never_bypassed_with_a_second_process():
    """ONE PANEL PER MACHINE, and it holds every account (#2068).

    This is the bug that put an account out of reach. `launch(missing)` started a panel
    for exactly the profiles the live one lacked, so a machine wanting two accounts with
    a panel on one of them got a SECOND process — and on Windows both bound the same web
    port without either saying so, so the browser reached whichever the kernel picked and
    the other account read as «закрыт» while it was farming.
    """
    panel = _Panel(1, ["one"])
    keep, calls, lines = _keeper(_Registry([panel]), profiles=("one", "two"))
    keep.tick()

    assert not calls, f"started a second panel instead of asking the one that is up: {calls}"
    presses = [a for a in panel.asked if a[1] == "/api/screen/press"]
    assert len(presses) == 1, f"did not ask the panel to open it: {panel.asked}"
    assert presses[0][2]["action"] == "open"
    assert presses[0][2]["args"]["name"] == "two"
    assert panel.profiles == ["one", "two"]

    # …and now that it holds both, it is left alone for ever.
    for _ in range(5):
        keep.tick()
    assert len([a for a in panel.asked if a[1] == "/api/screen/press"]) == 1, panel.asked
    assert not calls


def test_two_panels_are_an_accident_and_the_keeper_undoes_it():
    """A second panel is damage, and mostly invisible damage — so it is fixed, not reported.

    The person cannot act on «у вас две панели» and should not have to: what they see is
    an account that is not there. The oldest connection is the machine's panel; the rest
    are asked to go, orderly, through the same press the window's ✕ runs.
    """
    first, stray = _Panel(1, ["one"], at=100.0), _Panel(2, ["two"], at=200.0)
    keep, calls, lines = _keeper(_Registry([first, stray]), profiles=("one", "two"))
    keep.tick()

    assert stray.closed, "the stray panel was left running"
    assert stray.asked[0][1] == "/api/panel" and stray.asked[0][2]["action"] == "quit"
    assert not first.closed, "put down the panel it was supposed to keep"
    assert not calls, "started a process while cleaning up two of them"
    assert any("TWO PANELS" in ln for ln in lines), lines

    # The profile the stray held is not lost: its lock goes with it, and the survivor is
    # asked to open it on a later tick.
    keep.held = lambda name: False
    keep.tick()
    presses = [a for a in first.asked if a[1] == "/api/screen/press"]
    assert [p[2]["args"]["name"] for p in presses] == ["two"], first.asked


def test_a_refusal_is_not_asked_again_every_five_seconds():
    """Some refusals stand until a person changes something (#2024) — say it, then wait.

    A profile with no Windows session and no daemon port of its own drives somebody
    else's client, and the panel turns the open down for it. A supervisor that asks
    anyway writes the same line all night and drowns the one that matters.
    """
    clock = _Clock()
    panel = _Panel(1, ["one"])
    panel.answer = (200, {"ok": False, "reason": "log.profile.open_shared_client"})
    keep, calls, lines = _keeper(_Registry([panel]), profiles=("one", "two"),
                                 clock=clock)
    for _ in range(6):
        keep.tick()
        clock.now += keepermod.CHECK_SEC
    presses = [a for a in panel.asked if a[1] == "/api/screen/press"]
    assert len(presses) == 1, f"asked {len(presses)} times inside its own quiet spell"
    assert any("would not open" in ln for ln in lines), lines
    assert not calls, "fell back to starting a second panel when refused"

    clock.now += keepermod.ASK_AGAIN_SEC
    keep.tick()
    assert len([a for a in panel.asked if a[1] == "/api/screen/press"]) == 2, "never asked again"


def test_the_screen_a_press_is_sent_to_is_asked_of_the_module_that_owns_it():
    # Never spelled twice (`CLAUDE.md`): both the web API and the service read it off
    # the module that declares the presses.
    from panel.runtime import profile_control as profilectl

    assert keepermod._profiles_screen() == profilectl.SCREEN


def test_the_command_it_starts_is_the_one_place_a_panel_is_spelled():
    cmd = sessionmod.panel_command(["one", "two"], python="py.exe")
    assert cmd[:3] == ["py.exe", "-m", "panel.headless"], cmd
    assert cmd.count("--profile") == 2 and cmd[-1] == "two", cmd
    # A window, never: the service's panel has no session of its own to draw in.
    assert "panel.__main__" not in " ".join(cmd)


def main() -> int:
    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
        except Exception as exc:              # noqa: BLE001 — a report, not a crash
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok   {name}")
    print("FAILED" if failed else "OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

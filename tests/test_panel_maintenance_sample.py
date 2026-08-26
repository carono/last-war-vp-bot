r"""THE FIRST REAL MAINTENANCE HAS TO LEAVE A RECORDING BEHIND (#1982).

WHAT THIS FILE IS FOR. Every word of the maintenance detector was inferred rather than
recorded. The state was watched once, from outside the client (#1549,
`docs/research/server-maintenance.md`), and the next window — 2026-08-26 — was missed by
twenty minutes: the game was back on the world map before anybody could read the client.
So what the panel knows about it comes out of the GAME'S OWN tables (the key inventory)
and its own window list (`UIServerMaintenanceTip`), and not one line of it has been seen
firing for real.

That is exactly the shape of thing that quietly never works. So the poll writes the raw
reading down the moment the state is recognised — into the profile's own git-ignored
directory, never the repository — and the next real outage turns the inference into a
sample somebody can read.

What is pinned here:

  * a sample is written when the door SHUTS and when the game announces it CLOSING;
  * it holds what the client actually answered, verbatim, plus what the light said;
  * nothing is written while the game is playing normally, or when the state has not
    changed — one file per episode, not one per poll;
  * a sample that cannot be written never breaks the poll;
  * and the sample lands under the PROFILE, so two accounts keep two records.

Needs no display, no game, no client:

    python3 tests/test_panel_maintenance_sample.py
"""
from __future__ import annotations

TIER = "pure"

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# The module under test draws nothing, but `panel.runtime` reaches the whole panel on
# the way in — so Tk is stubbed, exactly as `tests/test_panel_headless.py` stubs it, and
# what is imported afterwards is the real poll.
def _stub_tk() -> None:
    if "tkinter" in sys.modules:
        return

    class _W:
        def __init__(self, *a, **k) -> None:
            pass

        def __getattr__(self, _n):
            return lambda *a, **k: None

    def _module(name: str):
        mod = types.ModuleType(name)
        made: dict = {}

        def _make(attr: str):
            if attr not in made:
                made[attr] = type(attr, (_W,), {})
            return made[attr]

        mod.__getattr__ = _make
        return mod

    tk = _module("tkinter")
    tk.TclError = type("TclError", (Exception,), {})
    sys.modules["tkinter"] = tk
    for sub in ("ttk", "font", "messagebox", "simpledialog", "scrolledtext",
                "filedialog"):
        child = _module(f"tkinter.{sub}")
        sys.modules[f"tkinter.{sub}"] = child
        setattr(tk, sub, child)


_stub_tk()

from panel.runtime import status as statusmod        # noqa: E402


class _Health:
    colour = "warn"
    current = types.SimpleNamespace(reason="maintenance", plumbing="landing",
                                    server="silent")


class _Profiles:
    def __init__(self, root: str) -> None:
        self.root = root

    def dir(self, _name=None) -> str:
        return self.root


class _RT:
    """The runtime, reduced to what writing a sample and saying a line touches."""

    def __init__(self, root: str) -> None:
        self.profiles = _Profiles(root)
        self.health = _Health()
        self.said: list = []

    def say(self, _tag, key, **fmt) -> None:
        self.said.append((key, fmt))

    def dbg(self, _component="panel"):
        return types.SimpleNamespace(info=lambda *a, **k: None,
                                     error=lambda *a, **k: None,
                                     debug=lambda *a, **k: None,
                                     warning=lambda *a, **k: None)


def _poll(root: str):
    return statusmod.StatusPoll(_RT(root))


def _files(root: str) -> list:
    folder = Path(root) / "maintenance"
    return sorted(p.name for p in folder.glob("*.json")) if folder.exists() else []


SEEN = {"window": True, "login": True, "disconnect": False, "cross": False,
        "tip": "The server is under maintenance. Please wait a moment!",
        "raw": "maint=1 login=1 disc=0 cross=0 tip=The server is under maintenance."}


# --- the recording ----------------------------------------------------------
def test_the_closed_door_leaves_a_sample_with_the_raw_reading_in_it():
    with tempfile.TemporaryDirectory() as root:
        poll = _poll(root)
        poll._announce_maintenance("closed", None, SEEN)
        names = _files(root)
        assert len(names) == 1 and names[0].endswith("-closed.json"), names
        body = json.loads((Path(root) / "maintenance" / names[0]).read_text("utf-8"))
        assert body["state"] == "closed"
        assert body["reading"]["raw"] == SEEN["raw"], body["reading"]
        assert body["reading"]["window"] is True
        assert body["light"]["reason"] == "maintenance"


def test_the_countdown_is_recorded_too_because_it_carries_the_only_time():
    with tempfile.TemporaryDirectory() as root:
        poll = _poll(root)
        poll._announce_maintenance("closing", 900.0, {"tip": "in 15-min", "raw": "…"})
        names = _files(root)
        assert len(names) == 1 and names[0].endswith("-closing.json"), names
        body = json.loads((Path(root) / "maintenance" / names[0]).read_text("utf-8"))
        assert body["seconds"] == 900.0


def test_nothing_is_written_while_the_game_is_simply_playing():
    with tempfile.TemporaryDirectory() as root:
        poll = _poll(root)
        for _ in range(5):
            poll._announce_maintenance("", None, {"tip": "", "raw": "maint=0"})
        assert _files(root) == []


def test_one_file_per_EPISODE_and_not_one_per_poll():
    with tempfile.TemporaryDirectory() as root:
        poll = _poll(root)
        for _ in range(20):
            poll._announce_maintenance("closed", None, SEEN)
        assert len(_files(root)) == 1, _files(root)


def test_a_sample_that_cannot_be_written_never_breaks_the_poll():
    """A record is worth a lot and never worth the panel."""
    poll = _poll("/nowhere/that/exists/at/all")
    poll._announce_maintenance("closed", None, SEEN)      # must not raise
    assert ("log.game.maintenance", {}) in poll.rt.said


# --- what it says while it does it ------------------------------------------
def test_the_line_is_said_once_per_edge():
    with tempfile.TemporaryDirectory() as root:
        poll = _poll(root)
        for _ in range(3):
            poll._announce_maintenance("closed", None, SEEN)
        poll._announce_maintenance("", None, {"tip": "", "raw": ""})
        keys = [k for k, _ in poll.rt.said]
        assert keys == ["log.game.maintenance", "log.game.maintenance_over"], keys


def test_the_seasons_own_estimate_is_said_when_the_game_gives_one():
    """The ONE length the game ever names, and it is read out of its own sentence."""
    import game_maintenance as gm

    gm.forget()
    gm._phrases = {gm.SEASON_KEY: {"The season has ended, and the server is currently "
                                   "under maintenance.\n(Estimated time: 10-30 minutes)"}}
    gm._looked = True
    try:
        with tempfile.TemporaryDirectory() as root:
            poll = _poll(root)
            poll._announce_maintenance(
                "closed", None,
                {"tip": "The season has ended, and the server is currently under "
                        "maintenance. (Estimated time: 10-30 minutes)", "raw": "maint=0"})
            said = dict((k, f) for k, f in poll.rt.said)
            assert "log.game.maintenance_estimate" in said, poll.rt.said
            assert said["log.game.maintenance_estimate"] == {"low": 10, "high": 30}
    finally:
        gm.forget()


# --- «no client» is never something a READING invented -----------------------
def test_a_dialog_that_could_not_be_read_keeps_the_last_verdict():
    """The question that came back: can the new reading turn «unknown» into «no client»?

    It cannot. The dialog read answers ``None`` for every way of not knowing, and both
    judges keep whatever they last knew — a reading that fails can only ever ADD a
    reason and never take one away.
    """
    poll = _poll("/tmp")
    poll._maint_was, poll._maint_secs = "closed", None
    poll._kick_was = True
    assert poll._read_maintenance(None) == ("closed", None)
    assert poll._read_kicked(None) is True


def test_the_maintenance_verdict_touches_the_LIGHT_and_never_the_client():
    """It narrows amber. Whether a client exists is the process probe's answer alone."""
    source = (Path(__file__).resolve().parents[1]
              / "panel" / "runtime" / "status.py").read_text(encoding="utf-8")
    at = source.index("health = rt.health.update(")
    call = source[at:source.index(")", source.index("maintenance=", at))]
    assert "running=" not in call, call
    assert "maintenance=maint ==" in call, call


def test_the_verdict_is_written_down_every_poll():
    """A light nobody records cannot be dated afterwards — which is how this got asked.

    The window has printed its `systems:` line for a year; the windowless panel printed
    nothing, so «панель говорила, что клиента нет» could be neither confirmed nor denied.
    """
    source = (Path(__file__).resolve().parents[1]
              / "panel" / "runtime" / "status.py").read_text(encoding="utf-8")
    assert "_note_verdict(health, found)" in source, "the verdict is not recorded"
    at = source.index("def _note_verdict")
    body = source[at:source.index("\n    def ", at + 10)]
    for wanted in ("light=%s", "client=%s", "pid=%s", "session=%s"):
        assert wanted in body, wanted


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

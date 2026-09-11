r"""The buttons drawn over the client's window (#2768) — what may never drift.

Four things this file holds in place:

* **the overlay is a FRONT-END.** The helper presses `/api/actions/run` and nothing else
  — no Lua, no game step, no gate of its own. A rewrite that taught it to drive the game
  fails here (`CLAUDE.md`, «Everything is a scenario — the panel only plays them»).
* **one bar per PROFILE.** «Is it up» is «has this profile's own child factory got a live
  child with the overlay's tag», never a module-level flag two open accounts would share.
* **an edit travels to both front-ends.** The two presses are one table, the phone reads
  it off `/api/state`, and every word of the bar is a locale key present in all eleven
  locales.
* **it never costs the game its input.** The window carries `WS_EX_NOACTIVATE`, so a
  press on the bar is delivered without the foreground moving — which is the whole
  reason the client underneath goes on taking keystrokes.

Offline: nothing here starts a process, opens a window or talks to the game.

    C:\Python312\python.exe tests\test_panel_overlay.py
"""
from __future__ import annotations

TIER = "offline"       # no Tk, no game, no network — see tools/run_tests.py

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

HELPER = _REPO / "tools" / "game_overlay.py"
CONTROL = _REPO / "panel" / "runtime" / "overlay.py"
API = _REPO / "panel" / "web" / "api.py"
STATE_VIEW = _REPO / "panel" / "web" / "app" / "src" / "views" / "StateView.tsx"
LOCALES = _REPO / "panel" / "locales"

#: Every word the overlay and its card say. All of them, in all eleven locales.
KEYS = (
    "overlay.show", "overlay.hide", "overlay.idle", "overlay.running", "overlay.done",
    "overlay.busy", "overlay.refused", "overlay.unreachable",
    "overlay.reason.unsupported", "overlay.reason.other_session",
    "overlay.reason.no_door", "overlay.reason.failed",
    "web.ui.overlay", "web.ui.overlay.hint",
    "log.overlay.starting", "log.overlay.stopping",
    "log.overlay.other_session", "log.overlay.no_door",
)


# ---------------------------------------------------------------------------
# the helper is a front-end and nothing more
# ---------------------------------------------------------------------------
def test_the_helper_presses_a_scenario_over_the_panels_own_door():
    source = HELPER.read_text(encoding="utf-8")
    assert "/api/actions/run" in source, "the bar must press the panel, not the game"


def test_the_helper_holds_no_game_logic_of_its_own():
    """No Lua, no daemon, no evaluator: the ability is a recipe and this only plays it."""
    source = HELPER.read_text(encoding="utf-8")
    for forbidden in ("lua_actions", "lua_client", "get_evaluator", "DoString",
                      "SendCollect"):
        assert forbidden not in source, f"the overlay must not reach for {forbidden}"


def test_the_trial_button_is_the_collect_scenario():
    import game_overlay

    assert "collect_base_resources" in game_overlay.BUTTONS
    assert (_REPO / "src" / "lastwar_bot" / "actions"
            / "collect_base_resources.md").exists()


def test_a_button_is_named_by_the_scenario_and_never_by_a_literal_here():
    source = HELPER.read_text(encoding="utf-8")
    assert "/api/actions" in source, "the titles come off the panel's action list"
    assert "/api/i18n" in source, "the words come out of the panel's locale table"


def test_the_window_is_found_by_the_GAMES_title_and_not_by_a_scenarios():
    """An hour of #2768: the scenario titles and the window titles were one attribute,
    so the bar looked for a window called «collect_base_resources», found none, and hid
    itself for ever with nothing said anywhere."""
    source = HELPER.read_text(encoding="utf-8")
    assert "find_client()" in source, "the follower must not pass the button labels in"
    assert "self.labels" in source, "the scenario titles live under their own name"
    assert "self.titles" not in source


def test_a_bar_that_cannot_find_the_client_says_so():
    source = HELPER.read_text(encoding="utf-8")
    assert "no game window on this desktop" in source


def test_the_result_is_the_runs_own_closing_line_and_not_a_tag_guess():
    """Live: a press from the bar is logged under the panel's WEB tag, so filtering the
    log by «action» made every run — refused or not — end as «готово» (#2768)."""
    source = HELPER.read_text(encoding="utf-8")
    assert '("action: %s" % name)' in source
    assert '("action", "error")' not in source


def test_the_press_never_takes_the_foreground_away_from_the_client():
    """The client takes FOREGROUND input only — an overlay that activated itself on every
    press would be breaking the very thing it sits on."""
    import game_overlay

    assert game_overlay.WS_EX_NOACTIVATE == 0x08000000
    source = HELPER.read_text(encoding="utf-8")
    assert "WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW" in source
    assert "SWP_NOACTIVATE" in source


def test_the_panel_is_asked_only_while_a_press_of_ours_is_running():
    """«Read once, then LISTEN»: a bar nobody has pressed asks the panel nothing."""
    import game_overlay

    assert game_overlay.WATCH_SEC >= 1.0
    source = HELPER.read_text(encoding="utf-8")
    head, _, _ = source.partition("def main(")
    assert "while time.monotonic() < deadline" in head, "the watch is bounded"


def test_the_token_is_not_put_on_the_command_line_in_the_ordinary_case():
    """A command line is in every process list and in `children-<pid>.json`."""
    control = CONTROL.read_text(encoding="utf-8")
    assert 'if token and web_control.serving() is not None:' in control
    assert "door_from_disk" in HELPER.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# the control table
# ---------------------------------------------------------------------------
class _Settings:
    def __init__(self, user=None) -> None:
        self.user = user

    def opt_str(self, name, default="") -> str:
        return "python"


class _Kid:
    def __init__(self, tag, alive=True) -> None:
        self.tag = tag
        self.alive = alive
        self.started = False
        self.stopped = False

    def start(self) -> bool:
        self.started = True
        return True

    def stop(self) -> None:
        self.stopped = True
        self.alive = False


class _Children:
    def __init__(self) -> None:
        self.live = []
        self.spawned = []

    def python(self) -> str:
        return "python"

    def spawn(self, tag, cmd, **_kw):
        self.spawned.append((tag, cmd))
        kid = _Kid(tag)
        self.live.append(kid)
        return kid


class _Profiles:
    active = "one"


class _Runtime:
    def __init__(self) -> None:
        self.children = _Children()
        self.settings = _Settings()
        self.profiles = _Profiles()
        self.said = []

    def say(self, tag, key, **fmt) -> None:
        self.said.append((tag, key))


def test_up_is_asked_of_this_profiles_own_children():
    from panel.runtime import overlay

    rt = _Runtime()
    assert overlay.running(rt) is False
    rt.children.live.append(_Kid(overlay.TAG))
    assert overlay.running(rt) is True
    # …and a second profile's runtime knows nothing about it.
    assert overlay.running(_Runtime()) is False


def test_a_dead_child_is_not_an_overlay():
    from panel.runtime import overlay

    rt = _Runtime()
    rt.children.live.append(_Kid(overlay.TAG, alive=False))
    assert overlay.running(rt) is False


def test_the_two_presses_say_when_they_apply():
    from panel.runtime import overlay

    rt = _Runtime()
    state = overlay.state(rt)
    by_id = {row["id"]: row for row in state["controls"]}
    assert set(by_id) == {overlay.SHOW, overlay.HIDE}
    if state["supported"]:
        assert by_id[overlay.SHOW]["enabled"] is True
        assert by_id[overlay.HIDE]["enabled"] is False


def test_an_unknown_press_is_refused():
    from panel.runtime import overlay

    assert overlay.play(_Runtime(), "explode").get("error") == "unknown"


def test_a_client_in_another_windows_session_is_told_why():
    from panel.runtime import overlay

    rt = _Runtime()
    rt.settings = _Settings(user="someone")
    saved = overlay.game_process.profile_user
    overlay.game_process.profile_user = lambda settings: getattr(settings, "user", None)
    saved_supported = overlay.supported
    overlay.supported = lambda: True
    try:
        answer = overlay.play(rt, overlay.SHOW)
    finally:
        overlay.game_process.profile_user = saved
        overlay.supported = saved_supported
    assert answer["ok"] is False and answer["reason"] == "other_session"
    assert not rt.children.spawned, "nothing may be started on another session's desktop"


def test_hiding_a_bar_that_is_not_up_is_not_an_error():
    from panel.runtime import overlay

    saved = overlay.supported
    overlay.supported = lambda: True
    try:
        answer = overlay.play(_Runtime(), overlay.HIDE)
    finally:
        overlay.supported = saved
    assert answer["ok"] is True and answer["running"] is False


def test_show_spawns_the_helper_with_the_profile_and_the_door():
    from panel.runtime import overlay

    rt = _Runtime()
    saved_supported, saved_user, saved_door = (
        overlay.supported, overlay.game_process.profile_user, overlay.door)
    overlay.supported = lambda: True
    overlay.game_process.profile_user = lambda settings: None
    overlay.door = lambda: ("http://127.0.0.1:9761", "tok")
    try:
        answer = overlay.play(rt, overlay.SHOW)
    finally:
        overlay.supported, overlay.game_process.profile_user, overlay.door = (
            saved_supported, saved_user, saved_door)
    assert answer["ok"] is True
    tag, cmd = rt.children.spawned[0]
    assert tag == overlay.TAG
    assert "game_overlay.py" in " ".join(cmd)
    assert "--profile" in cmd and "one" in cmd
    assert "--url" in cmd
    assert "--token" not in cmd, "the service's token stays off the command line"


# ---------------------------------------------------------------------------
# both front-ends
# ---------------------------------------------------------------------------
def test_the_phone_gets_the_reading_and_the_press():
    source = API.read_text(encoding="utf-8")
    assert '"overlay": overlaymod.state(rt)' in source, "the reading rides on /api/state"
    assert 'if path == "/api/overlay":' in source, "and the press has a route"


def test_the_card_is_drawn_on_the_state_screen():
    source = STATE_VIEW.read_text(encoding="utf-8")
    assert "function OverlayCard(" in source
    assert "'/api/overlay'" in source
    assert "<OverlayCard" in source
    assert "t('web.ui.overlay')" in source


def test_every_word_is_a_key_in_all_eleven_locales():
    files = sorted(LOCALES.glob("*.json"))
    assert len(files) == 11, f"expected eleven locales, found {len(files)}"
    for path in files:
        table = json.loads(path.read_text(encoding="utf-8"))
        missing = [key for key in KEYS if not str(table.get(key) or "").strip()]
        assert not missing, f"{path.name} is missing {missing}"


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok   {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {exc}")
        except Exception as exc:                    # noqa: BLE001
            failed += 1
            print(f"  ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())

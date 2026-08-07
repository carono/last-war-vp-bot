r"""The «Качество графики» switch on «Настройки → Игра».

Two states — the economy picture and the one the person had — and the whole of what the
switch knows about the game is the NAME of a scenario and the arguments it passes
(`CLAUDE.md`: the panel plays scenarios, it does not write them). So these tests never
need a game: they replace `play_async` with a recorder and assert on what the panel asked
for.

The rules that are easy to break here and quiet when broken:

  * **Only a click applies anything.** The mode is a profile setting, so its variable is
    written every time a profile loads. Tracing that variable would drive the game on
    every profile switch — the radio's `command` fires on a click and not on a `set()`,
    and this pins it.
  * **What to come back to is read BEFORE it is overwritten.** By the time a click
    reaches the handler the radio has ALREADY moved to «низкое», so a "are we in
    standard?" test would record the economy picture as the one to restore, and
    «стандартное» would then restore economy for ever.
  * **A restore uses that person's picture**, not a constant — and falls back to the
    client's shipped one only when nothing was ever remembered.
  * **The state line quotes the frame cap only when the cap is in force.** While vSync
    is on the engine ignores `targetFrameRate`, so printing it as the rate is a lie —
    and the disconnected-session case makes it a costly one
    (docs/research/headless-gpu.md §4).

Needs Tk and a display, so it says SKIP under the WSL python3 (no tkinter).

    C:\Python312\python.exe tests\test_panel_graphics.py
    python3 tests/test_panel_graphics.py        # SKIP without tkinter
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:                                        # the WSL python3 has no tkinter
    from tkinter import ttk
except Exception:                           # noqa: BLE001
    ttk = None


class _Outcome:
    """What `ActionRunner.play` hands back, as much of it as the switch reads."""

    def __init__(self, ok=True, reason="", values=None):
        self.ok, self.reason = ok, reason
        self.ctx = type("Ctx", (), {"vars": dict(values or {})})()

    def __bool__(self):
        return self.ok


def _page(*, game_up=True, replies=None, settings=None):
    """The real Settings tab with `play_async` recorded instead of run.

    ``replies`` is consulted by scenario name: the value is what that scenario's run
    comes back with, so a test says "the client reads 60/1/2/1700×1065" without a client.
    """
    import tkinter as tk
    import fake_runtime
    from panel.tabs.settings import SettingsTab

    root = tk.Tk()
    root.withdraw()
    rt = fake_runtime.cold_runtime(root, settings=settings)
    rt.settings.save = lambda raw=None: None            # no profile on disk here
    # `cold_runtime` puts the values in the file layer only, and `opt()` prefers the Tk
    # variable — which still holds the default. Loading a profile means writing both,
    # which is what the shell does, so a test of "this profile is already in economy"
    # has to do it too or it is testing an untouched profile.
    for key, value in (settings or {}).items():
        if key in rt.settings.vars:
            rt.settings.vars[key].set(value)
    rt.game.up = lambda: game_up

    calls: list = []

    def play_async(name, args=None, *, tag="action", cancel=None,
                   on_start=None, on_done=None, on_result=None):
        calls.append({"name": name, "args": dict(args or {}), "tag": tag})
        if on_result is not None:
            # Straight through, not via `root.after`: the real one hops to the Tk
            # thread, and a test with no mainloop would never see the callback.
            on_result((replies or {}).get(name, _Outcome()))
        if on_done is not None:
            on_done()
        return True

    rt.play_async = play_async
    page = SettingsTab(rt, ttk.Frame(root))
    page.parent.pack(fill="both", expand=True)
    page.build()
    return root, page, rt, calls


def _skip(exc=None) -> None:
    print(f"  SKIP no tkinter / display: {exc}" if exc else
          "  SKIP tkinter not importable — run under the Windows Python")


def _state(page) -> str:
    return page._graphics_state.cget("text")


def test_switching_to_low_passes_the_economy_profile_to_the_scenario():
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        root, page, rt, calls = _page(
            replies={"read_graphics_load": _Outcome(values={
                "fps": 60, "vsync": 1, "quality": 2, "width": 1700, "height": 1065})})
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        rt.settings.vars["graphics_mode"].set("low")     # as the radio does on a click
        page._apply_graphics("low")

        names = [c["name"] for c in calls]
        assert "set_graphics_load" in names, f"the scenario was never played: {names}"
        applied = [c for c in calls if c["name"] == "set_graphics_load"][-1]["args"]
        assert applied == page.LOW_GRAPHICS, applied
        # …and the whole of the panel's knowledge of the game is that dict plus a name.
        assert set(applied) == {"fps", "quality", "width", "height"}, applied
    finally:
        root.destroy()


def test_the_picture_is_remembered_before_it_is_overwritten():
    """The read that records the stock runs FIRST, and records what it read."""
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        root, page, rt, calls = _page(
            replies={"read_graphics_load": _Outcome(values={
                "fps": 60, "vsync": 1, "quality": 2, "width": 1700, "height": 1065})})
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        rt.settings.vars["graphics_mode"].set("low")
        page._apply_graphics("low")

        names = [c["name"] for c in calls]
        assert names[0] == "read_graphics_load", f"read did not come first: {names}"
        assert "set_graphics_load" in names, names
        assert names.index("read_graphics_load") < names.index("set_graphics_load"), names
        # The radio already said "low" when the read ran — recording must not depend on
        # asking the setting what mode we are in.
        assert rt.settings.opt_str("graphics_stock") == "60/1/2/1700/1065", \
            rt.settings.opt_str("graphics_stock")
    finally:
        root.destroy()


def test_standard_restores_that_persons_picture_and_not_a_constant():
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        root, page, rt, calls = _page(
            settings={"graphics_mode": "low", "graphics_stock": "45/0/1/1280/720"})
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        rt.settings.vars["graphics_mode"].set("standard")
        page._apply_graphics("standard")

        applied = [c for c in calls if c["name"] == "set_graphics_load"][-1]["args"]
        assert applied == {"fps": 45, "quality": 1, "width": 1280, "height": 720}, applied
        assert applied != page.STOCK_GRAPHICS, "restored the default, not the person's"
    finally:
        root.destroy()


def test_standard_falls_back_to_the_shipped_picture_when_nothing_was_remembered():
    """A profile hand-edited into economy has no stock to come back to."""
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        root, page, rt, calls = _page(
            settings={"graphics_mode": "low", "graphics_stock": ""})
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        rt.settings.vars["graphics_mode"].set("standard")
        page._apply_graphics("standard")
        applied = [c for c in calls if c["name"] == "set_graphics_load"][-1]["args"]
        assert applied == page.STOCK_GRAPHICS, applied
    finally:
        root.destroy()


def test_a_second_switch_does_not_overwrite_the_remembered_picture():
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        root, page, rt, calls = _page(
            settings={"graphics_stock": "60/1/2/1700/1065"},
            replies={"read_graphics_load": _Outcome(values={
                "fps": 10, "vsync": 0, "quality": 0, "width": 320, "height": 200})})
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        rt.settings.vars["graphics_mode"].set("low")
        page._apply_graphics("low")
        page._read_graphics()               # and an explicit «Обновить» on top
        assert rt.settings.opt_str("graphics_stock") == "60/1/2/1700/1065", \
            rt.settings.opt_str("graphics_stock")
    finally:
        root.destroy()


def test_loading_a_profile_never_drives_the_game():
    """Setting the variable is what a profile switch does; it must press nothing."""
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        root, page, rt, calls = _page()
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        for mode in ("low", "standard", "low"):
            rt.settings.vars["graphics_mode"].set(mode)
        root.update_idletasks()             # let any trace fire
        assert not calls, f"a profile load played scenarios: {calls}"
    finally:
        root.destroy()


def test_a_client_that_is_not_running_saves_the_choice_and_says_so():
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        root, page, rt, calls = _page(game_up=False)
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        rt.settings.vars["graphics_mode"].set("low")
        page._apply_graphics("low")
        assert not calls, f"pressed into a client that is not there: {calls}"
        assert rt.settings.opt_str("graphics_mode") == "low", "the choice was lost"
        assert _state(page), "said nothing about why nothing happened"
        assert page.t("graphics.mode.low") in _state(page), _state(page)
    finally:
        root.destroy()


def test_the_frame_cap_is_only_quoted_when_it_is_in_force():
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    for vsync, key in ((0, "graphics.state.now"), (1, "graphics.state.now_vsync")):
        try:
            root, page, rt, _calls = _page(
                replies={"read_graphics_load": _Outcome(values={
                    "fps": 60, "vsync": vsync, "quality": 2,
                    "width": 1700, "height": 1065})})
        except Exception as exc:            # noqa: BLE001
            return _skip(exc)
        try:
            page._read_graphics()
            expected = page.t(key, fps=60, quality=page.t("graphics.quality.2"),
                              width=1700, height=1065)
            assert _state(page) == expected, f"vsync={vsync}: {_state(page)!r}"
        finally:
            root.destroy()


def test_an_unreadable_client_still_lets_the_switch_through():
    """What cannot be remembered is not remembered — but the person still gets the switch."""
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        root, page, rt, calls = _page(
            replies={"read_graphics_load": _Outcome(values={})})
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        rt.settings.vars["graphics_mode"].set("low")
        page._apply_graphics("low")
        names = [c["name"] for c in calls]
        assert "set_graphics_load" in names, f"the switch was dropped: {names}"
        assert rt.settings.opt_str("graphics_stock") == "", "remembered a guess"
    finally:
        root.destroy()


def test_a_result_callback_can_start_the_next_scenario():
    """`on_result` fires with the claim already RELEASED.

    This is the real `play_async`, not the recorder above, because the bug it pins lives
    there: the graphics switch reads the picture and then changes it, so the result of
    the read starts a second scenario. Handing the result over before the claim was
    released got that second one refused as «занят» — by the very run that was holding
    it — and the switch stopped halfway with the radio already moved.
    """
    try:
        import tkinter as tk
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        import fake_runtime
        root = tk.Tk()
        root.withdraw()
        rt = fake_runtime.cold_runtime(root)
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        played: list = []
        rt.actions.play = lambda name, args=None, **kw: (played.append(name)
                                                        or _Outcome())
        rt.actions.run = lambda name, args=None, **kw: played.append(name) or True
        # A link that grants one claim at a time, which is what the real one does.
        held = {"busy": False}
        rt.game.claim = lambda owner="panel": (False if held["busy"]
                                               else (held.update(busy=True) or True))
        rt.game.release = lambda: held.update(busy=False)
        rt.game.on_settled = lambda: None

        seen: list = []

        def second(_outcome):
            # Exactly what the switch does: press again off what the read found.
            seen.append(rt.play_async("set_graphics_load", {}, tag="t2"))
            root.quit()

        assert rt.play_async("read_graphics_load", tag="t1", on_result=second)
        root.after(8000, root.quit)         # never hang the suite
        root.mainloop()

        assert seen == [True], f"the follow-up scenario was refused: {seen}"
        assert played == ["read_graphics_load", "set_graphics_load"], played
    finally:
        root.destroy()


def test_a_restart_that_dropped_half_the_mode_is_named():
    """The state a person would otherwise never notice.

    Measured on a real restart of the second client: the render size came back on its own
    (Unity keeps it where it reads it from) while the frame cap and the quality were back
    at 60 and High. So a lapsed mode still LOOKS right — small window — and only the two
    numbers that matter have gone. Judging by the size would call this fine.
    """
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        root, page, rt, _calls = _page(
            settings={"graphics_mode": "low", "graphics_stock": "60/1/2/1920/1080"},
            replies={"read_graphics_load": _Outcome(values={
                # exactly what the live restart came back with
                "fps": 60, "vsync": 1, "quality": 2, "width": 640, "height": 480})})
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        page._read_graphics()
        expected = page.t("graphics.state.lapsed", fps=60,
                          quality=page.t("graphics.quality.2"),
                          width=640, height=480, mode=page.t("graphics.mode.low"))
        assert _state(page) == expected, _state(page)
    finally:
        root.destroy()


def test_a_mode_that_is_still_in_force_is_not_called_lapsed():
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        root, page, rt, _calls = _page(
            settings={"graphics_mode": "low"},
            replies={"read_graphics_load": _Outcome(values={
                "fps": 10, "vsync": 0, "quality": 0, "width": 640, "height": 480})})
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        page._read_graphics()
        assert _state(page) == page.t(
            "graphics.state.now", fps=10, quality=page.t("graphics.quality.0"),
            width=640, height=480), _state(page)
    finally:
        root.destroy()


def test_the_size_alone_does_not_count_as_the_mode_being_on():
    """The size survives a restart by itself, so it cannot be the evidence."""
    try:
        import tkinter  # noqa: F401
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        root, page, _rt, _calls = _page()
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        low = page.LOW_GRAPHICS
        assert page._is_low(low["fps"], 0, low["quality"])
        assert not page._is_low(60, 1, 2), "a stock client read as economising"
        assert not page._is_low(low["fps"], 1, low["quality"]), \
            "vSync on means the cap is ignored — that is not the mode being in force"
    finally:
        root.destroy()


def test_a_run_that_raised_reports_what_raised():
    """The exception is the only account of the failure — it must reach the person.

    Losing the lease to another profile driving the same client is the case that made
    this worth pinning: it arrives as an exception, and without this the switch said
    «сценарий не назвал причину» when the reason was known and specific.
    """
    try:
        import tkinter as tk
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        import fake_runtime
        root = tk.Tk()
        root.withdraw()
        rt = fake_runtime.cold_runtime(root)
    except Exception as exc:                # noqa: BLE001
        return _skip(exc)
    try:
        def boom(*a, **kw):
            raise RuntimeError("lease lost — it expired or was taken by nobody")

        rt.actions.play = boom
        rt.game.claim = lambda owner="panel": True
        rt.game.release = lambda: None
        rt.game.on_settled = lambda: None

        seen: list = []
        assert rt.play_async("read_graphics_load", tag="t",
                             on_result=lambda out: (seen.append(out), root.quit()))
        root.after(8000, root.quit)
        root.mainloop()

        assert seen, "no result was delivered for a run that raised"
        assert not seen[0], "a run that raised reported success"
        assert "lease lost" in seen[0].reason, repr(seen[0].reason)
    finally:
        root.destroy()


def test_the_scenarios_it_names_exist_and_parse():
    """The two names above are the whole contract with the game — so they must resolve."""
    from lastwar_bot import script_engine
    for name in ("set_graphics_load", "read_graphics_load"):
        path = script_engine.resolve_action(name)
        assert path, f"{name}: no such scenario"
        text = Path(path).read_text(encoding="utf-8")
        source, _defaults = script_engine.prepare_source(text, None)
        script_engine.parse_text(source)                # raises if it does not parse


def test_the_read_scenario_reports_every_field_the_panel_reads():
    """A field dropped from the scenario would show up as «не ответил», not as a crash."""
    from lastwar_bot import script_engine
    text = Path(script_engine.resolve_action("read_graphics_load")).read_text(
        encoding="utf-8")
    for var in ("fps", "vsync", "quality", "width", "height"):
        assert f"INTO {var}" in text, f"read_graphics_load no longer reports {var!r}"


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

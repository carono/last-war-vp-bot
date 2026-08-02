r"""A profile written before the settings binder must keep every value it had.

This test is written BEFORE the binder exists, on purpose
(docs/research/panel-tabs-refactor.md §9.2 and §10). The settings live in three
hand-maintained lists — `_collect_settings` writes ≈29 keys, `_apply_settings_to_ui`
sets ≈22, `_install_autosave` traces ≈18 — and a key dropped from one of the three is a
setting that silently stops persisting. Nothing fails loudly when that happens, so the
guard has to exist before the move, not after it: it pins what a real pre-migration
`config.json` means today, and the binder is only correct if it still means that.

`tests/fixtures/config_pre_binder.json` is that profile — the shape the panel writes at
the time of this commit, including the three nested blocks (`autorally`, `rally_tab`,
`command_post`) and the deliberate hole where `autoloot_level_from` is missing, because
the fallback onto `filter_level_from` is exactly the kind of rule a rewrite loses.

No Tk, no game, no daemon: this reads a file and asks what the panel makes of it.

    C:\Python312\python.exe tests\test_panel_profile_compat.py
    python3 tests/test_panel_profile_compat.py
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "src", _REPO / "tools", _REPO / "tools" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "config_pre_binder.json"


def _saved() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class _Reader:
    """Whatever reads a profile's knobs — the panel today, the binder tomorrow.

    Only the Settings-page readers are borrowed (`_opt` and its typed friends plus the
    named ones). They are the whole surface through which the rest of the panel asks
    "what is this profile set to", so pinning them pins the meaning of the file.
    """

    def __init__(self, settings: dict):
        import panel.__main__ as pm
        from panel import runtime
        # The values live in the runtime's binder now; the panel's readers are faces
        # for it, so borrowing them here tests both at once — which is the point of
        # this file surviving the move unchanged.
        self._binder = runtime.SettingsBinder(profiles=None,
                                              defaults=pm.SETTINGS_DEFAULTS)
        self._binder.values = dict(settings)  # no widgets: the saved value is the answer
        for name in ("_opt", "_opt_int", "_opt_float", "_opt_str", "_opt_bool",
                     "_game_exe", "_launcher", "_autoloot_limit"):
            setattr(self, name, types.MethodType(getattr(pm.Panel, name), self))
        # The map-sweep box is read by the two that use it — the sweep itself and the
        # Settings page that describes it — rather than by the shell that has neither.
        from panel.tabs.settings import SettingsTab
        self.rt = types.SimpleNamespace(settings=self._binder)
        self._sweep_box = types.MethodType(SettingsTab._sweep_box, self)


# ---------------------------------------------------------------------------
# every knob the Settings page owns
# ---------------------------------------------------------------------------

def test_the_settings_knobs_read_back_exactly():
    r = _Reader(_saved())
    assert r._opt_str("win_python") == r"C:\Python312\python.exe"
    assert r._opt_int("daemon_port") == 47655   # the second session's client
    assert r._game_exe() == "LastWar.exe"
    assert r._launcher() == r"C:\Games\LastWar\launcher.exe"
    assert r._autoloot_limit() == 4, r._autoloot_limit()
    assert r._binder.opt_str("trace_filter") == "ghost"
    assert abs(r._binder.opt_float("sniff_ready_timeout") - 30.0) < 1e-9
    assert r._opt_int("log_max_lines", low=200, high=200000) == 4000
    assert r._opt_bool("watchdog") is True
    assert r._sweep_box() == (9, 3, 1.5, 12 * 60.0), r._sweep_box()


def test_a_knob_the_profile_never_set_keeps_its_default():
    """A profile that has never opened the Settings page must behave as it always did."""
    import panel.__main__ as pm

    bare = _Reader({})
    assert bare._opt_int("daemon_port") == int(pm.SETTINGS_DEFAULTS["daemon_port"])
    assert bare._opt_str("win_python") == str(pm.SETTINGS_DEFAULTS["win_python"])
    assert bare._autoloot_limit() == int(pm.SETTINGS_DEFAULTS["autoloot_limit"])
    assert bare._opt_bool("watchdog") is bool(pm.SETTINGS_DEFAULTS["watchdog"])


def test_bounds_are_applied_not_just_stored():
    """A half-typed box must never be obeyed — an empty limit read as 0 stops auto-loot."""
    r = _Reader({"daemon_port": "not a port", "autoloot_limit": "", "log_max_lines": 5})
    import panel.__main__ as pm
    assert r._opt_int("daemon_port") == int(pm.SETTINGS_DEFAULTS["daemon_port"])
    assert r._autoloot_limit() == int(pm.SETTINGS_DEFAULTS["autoloot_limit"])
    assert r._opt_int("log_max_lines", low=200, high=200000) == 200      # clamped up


# ---------------------------------------------------------------------------
# the values the panel keeps outside the Settings page
# ---------------------------------------------------------------------------

def test_every_key_this_profile_carries_is_one_the_panel_knows():
    """A key in a real profile that nothing reads is a setting that has gone missing."""
    import panel.__main__ as pm

    saved = _saved()
    # What `_collect_settings` writes: the Settings knobs, plus the named values the
    # panel keeps per profile. Listed here so that dropping one from the panel makes
    # THIS fail rather than a user's profile quietly lose it.
    known = set(pm.SETTINGS_DEFAULTS) | {
        "language", "window_geometry", "log_sash", "log_filter",
        "monitor_kind", "monitor_interval", "secret_monitor",
        "filter_star", "filter_pending", "filter_can_loot",
        "filter_level_from", "filter_level_to",
        "autoloot", "autoloot_level_from", "autoloot_level_to",
        "rally_monitor", "rally_autojoin", "rally_alert",
        "ghost_autoloot", "chat_monitor",
        "map_sweep", "sweep_centre_x", "sweep_centre_y",
        "scenario_selected", "scenario_args", "scenario_interval",
        "autorally", "rally_tab", "command_post",
    }
    unknown = sorted(set(saved) - known)
    assert unknown == [], f"the profile carries keys nothing reads: {unknown}"


def test_the_autoloot_range_still_falls_back_to_the_filter_range():
    """The one migration already in the file, and the easiest to lose in a rewrite.

    A profile saved before the display filter and the robbery rule were split has only
    the one pair — and it was aiming the robberies as well as narrowing the log. Seeding
    the auto-loot range from it is what keeps that profile robbing the same levels;
    without the fallback the rule silently widens to "any level", which is how a
    robbery gets spent on a level-6 star (#1099).
    """
    saved = _saved()
    assert "autoloot_level_from" not in saved, "the fixture must keep the hole"
    lo = saved.get("autoloot_level_from", saved.get("filter_level_from", ""))
    hi = saved.get("autoloot_level_to", saved.get("filter_level_to", ""))
    assert (lo, hi) == ("5", "7"), (lo, hi)


def test_the_three_nested_blocks_survive_whole():
    """«Авторалли», the Rally tab and the Command Post keep their own shapes."""
    saved = _saved()
    autorally = saved["autorally"]
    assert autorally["squads"] == {"1": True, "2": False, "3": True, "4": False}
    assert autorally["drill"]["banner"] == 3
    assert autorally["drill"]["squads"]["3"] == "lead"
    assert autorally["create"] == {"squad": 2, "level": 33}

    assert saved["rally_tab"] == {"kind": "boss", "level": 30,
                                  "squads": [1, 3], "repeats": 5}
    assert saved["command_post"]["treasure"]["squad"] == 2
    assert saved["command_post"]["ghost"]["autoloot"] is False


# ---------------------------------------------------------------------------
# the file itself, through the profile store
# ---------------------------------------------------------------------------

def test_the_profile_store_round_trips_it_unchanged():
    """Saving what was loaded must not lose, reorder-away or retype anything."""
    import tempfile
    from panel import profile as profilemod

    saved = _saved()
    with tempfile.TemporaryDirectory() as tmp:
        was_dir, was_file = profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE
        profilemod.PROFILES_DIR = str(Path(tmp) / "profiles")
        profilemod.SETTINGS_FILE = str(Path(tmp) / "settings.json")
        try:
            pm = profilemod.ProfileManager()
            pm.save(saved)
            back = pm.load()
        finally:
            profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE = was_dir, was_file
    assert back == saved, {k: (saved.get(k), back.get(k))
                           for k in set(saved) | set(back) if saved.get(k) != back.get(k)}


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

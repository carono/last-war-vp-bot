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

TIER = "ui"        # Tk and a display — see tools/run_tests.py

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
    assert r._opt_int("daemon_port") == 47655   # the second session's client
    assert r._autoloot_limit() == 4, r._autoloot_limit()
    assert r._binder.opt_str("trace_filter") == "ghost"
    assert abs(r._binder.opt_float("sniff_ready_timeout") - 30.0) < 1e-9
    assert r._opt_int("log_max_lines", low=200, high=200000) == 4000
    assert r._opt_bool("watchdog") is True
    # The step is no longer read from the profile (#1265): it belongs to the camera
    # height, and the pair is chosen on the «Секретки» coordinate bar. What this profile
    # SAID (3) is ignored; what comes back is the default level's step, and the three
    # knobs that really are the box's — radius, dwell, rest — still read back exactly.
    radius, step, dwell, rest = r._sweep_box()
    assert (radius, dwell, rest) == (9, 1.5, 12 * 60.0), r._sweep_box()
    import lua_actions
    assert step == lua_actions.zoom_level(lua_actions.DEFAULT_ZOOM_LEVEL)[1]


def test_a_knob_the_profile_never_set_keeps_its_default():
    """A profile that has never opened the Settings page must behave as it always did."""
    import panel.__main__ as pm

    bare = _Reader({})
    assert bare._opt_int("daemon_port") == int(pm.SETTINGS_DEFAULTS["daemon_port"])
    assert bare._opt_str("win_python") == str(pm.SETTINGS_DEFAULTS["win_python"])
    assert bare._autoloot_limit() == int(pm.SETTINGS_DEFAULTS["autoloot_limit"])
    assert bare._opt_bool("watchdog") is bool(pm.SETTINGS_DEFAULTS["watchdog"])


def test_the_paths_in_an_old_profile_are_the_one_thing_no_longer_obeyed():
    """The one deliberate break with «read back exactly», and why it is one (#1252).

    Where the game is installed, what its process is called and which Python runs the
    children have exactly ONE right answer per machine, and it is
    `tools/lib/game_paths.py`'s — an environment variable in front of an ordinary
    default. A path typed into a profile years ago cannot be told from a correct one by
    looking at it, and a real profile on the machine this was written on carried
    `C:\\Program Files\\LastWar\\LastWarLauncher.exe`: a folder the game has never
    installed itself into, so «Запустить игру» reported the ordinary «клиент не
    запущен» and there was nothing anywhere to say why.

    So the value is still in the file — an older panel opening this profile still reads
    it — and this panel answers from the machine and stops writing it back, which drops
    it on the next save.
    """
    import panel.__main__ as pm

    old = _Reader(_saved())
    assert old._binder.values["launcher"] == r"C:\Games\LastWar\launcher.exe"
    for key in pm.runtime.settings.MACHINE_KEYS:
        assert old._opt_str(key) == str(pm.SETTINGS_DEFAULTS[key]), key
    assert old._launcher() == str(pm.SETTINGS_DEFAULTS["launcher"])
    assert old._game_exe() == str(pm.SETTINGS_DEFAULTS["game_exe"])


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
        "filter_level_from", "filter_level_to",
        "autoloot", "autoloot_level_from", "autoloot_level_to",
        "rally_monitor", "rally_autojoin", "rally_alert",
        "ghost_autoloot", "chat_monitor",
        "map_sweep", "sweep_centre_x", "sweep_centre_y",
        # RETIRED, and still carried by profiles written before it was (#1265).
        # `sweep_step` was half of a pair — a step means nothing without the camera
        # height it was measured at — and both halves moved to the «Секретки»
        # coordinate bar as one control. Named here so an old profile does not read as
        # a setting the panel has lost, which is what this test is for.
        "sweep_step", "sweep_zoom",
        "scenario_selected", "scenario_args", "scenario_interval",
        "autorally", "rally_tab", "command_post",
    }
    unknown = sorted(set(saved) - known)
    assert unknown == [], f"the profile carries keys nothing reads: {unknown}"


def test_the_autoloot_minimum_still_falls_back_through_every_older_spelling():
    """The migration chain in the file, and the easiest to lose in a rewrite.

    The rule is ONE number now — «минимальный уровень», this level and everything above
    it (#1256) — and what it has to inherit is what the profile was actually ROBBING,
    not what it looked like it was: under the range it replaces the level taken was the
    TOP one, so the old «до» is the new minimum. Older still (before the display filter
    and the robbery rule were split, #1099) there is only the display pair, and it was
    aiming the robberies too — this fixture is exactly that profile, and without the
    fallback its rule would silently widen to «any level», which is how a robbery gets
    spent on a level-6 star.
    """
    saved = _saved()
    assert "autoloot_level_from" not in saved, "the fixture must keep the hole"
    low = (saved.get("autoloot_level_min") or saved.get("autoloot_level_to")
           or saved.get("autoloot_level_from") or saved.get("filter_level_to")
           or saved.get("filter_level_from") or "")
    assert low == "7", low


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


# ---------------------------------------------------------------------------
# a tab folded into another one (task #1240: "scenarios" became part of "develop")
# ---------------------------------------------------------------------------

def test_tab_list_migrates_a_folded_tab_id():
    """A profile that had the standalone «Сценарии» tab on must not lose it silently.

    `SettingsBinder.tab_list` is what `tabsreg.resolve()` is fed with, so a
    "scenarios" surviving unmapped in `tabs.enabled` would just be reported as an
    unknown id and dropped — the merged tab would look, to that profile, exactly
    like it was never asked for.
    """
    from panel import runtime

    binder = runtime.SettingsBinder(profiles=None, defaults={})
    binder.values = {"tabs": {"enabled": ["stats", "scenarios"],
                              "known": ["stats", "scenarios"],
                              "order": ["scenarios", "stats"]}}
    assert binder.tab_list("enabled") == ["stats", "develop"]
    assert binder.tab_list("known") == ["stats", "develop"]
    assert binder.tab_list("order") == ["develop", "stats"]

    # A profile that already has BOTH ids (someone turned "develop" on by hand too)
    # must not end up with it twice.
    binder.values = {"tabs": {"enabled": ["scenarios", "develop", "stats"]}}
    assert binder.tab_list("enabled") == ["develop", "stats"]

    # A profile untouched by the merge is unaffected.
    binder.values = {"tabs": {"enabled": ["stats", "heroes"]}}
    assert binder.tab_list("enabled") == ["stats", "heroes"]


def test_tab_config_falls_back_to_flat_legacy_keys_when_the_new_block_is_empty():
    """`develop`'s own block is autosaved as `{}` long before the merge (it was off by
    default and has never had settings of its own), and an empty dict must not shadow
    the flat `scenario_selected` / `scenario_args` / `scenario_interval` keys the old
    «Сценарии» tab dual-wrote (`docs/panel-tabs.md` §"Settings, and moving existing
    ones" — `LEGACY_KEYS` is read whenever the tab's own block has nothing in it)."""
    from panel import runtime

    legacy = {k: k for k in ("scenario_selected", "scenario_args", "scenario_interval")}
    binder = runtime.SettingsBinder(profiles=None, defaults={})
    binder.values = {
        "scenario_selected": "collect_trucks", "scenario_args": '{"n": 3}',
        "scenario_interval": "120",
        "tabs": {"config": {"develop": {}}},
    }
    assert binder.tab_config("develop", legacy) == {
        "scenario_selected": "collect_trucks", "scenario_args": '{"n": 3}',
        "scenario_interval": "120"}

    # Once the merged tab has actually been shown and saved its own block, THAT wins.
    binder.values["tabs"]["config"]["develop"] = {"scenario_selected": "heal_units"}
    assert binder.tab_config("develop", legacy) == {"scenario_selected": "heal_units"}


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

r"""The default profile is the base, every other one stores only its overrides (#1246).

Written after one profile here rebuilt NO tabs at all: its own ``tabs.enabled`` had
gone empty, and — before this — there was no shared base underneath a profile for it
to fall back to, so an empty list meant "every known tab explicitly switched off"
rather than "nothing of my own to say here". Three things had to change together,
and this file pins all three:

  * a profile's ``config.json`` exists on disk the moment its directory does, instead
    of appearing only after its first Settings save;
  * loading a profile layers its own file onto the DEFAULT profile's file — untouched
    settings (a fresh tab id among them) come from there, not from a copy every
    profile carries and can drift out of;
  * saving a profile keeps only what actually differs from the default profile, so a
    knob edited once in the default profile's own Settings page reaches every profile
    that never overrode it, on its next start.

`_deep_merge`/`_deep_diff` are meant to be exact inverses — ``merge(base,
diff(full, base)) == full`` for anything the panel could plausibly save — and the
subset case pinned here (a nested dict that has FEWER keys than the base's) is the
one that is not safe to diff as a partial patch; it is what silently reintroducing a
stale field from the base would look like if that guard were missing.

No Tk, no game, no daemon: this reads and writes JSON in a scratch directory.

    C:\Python312\python.exe tests\test_panel_profile_defaults.py
    python3 tests/test_panel_profile_defaults.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel import profile as profilemod          # noqa: E402


class _Profiles:
    """`profilemod` pointed at a scratch directory for the duration of a test."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self._saved = (profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE)
        profilemod.PROFILES_DIR = os.path.join(root, "profiles")
        profilemod.SETTINGS_FILE = os.path.join(root, "settings.json")
        return self

    def config_path(self, name: str) -> str:
        return os.path.join(profilemod.PROFILES_DIR, name, profilemod.CONFIG_FILE)

    def __exit__(self, *exc):
        profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE = self._saved
        self._tmp.cleanup()
        return False


# ---------------------------------------------------------------------------
# a profile's config.json exists the moment its directory does
# ---------------------------------------------------------------------------

def test_a_freshly_created_profile_has_a_config_file_right_away() -> None:
    with _Profiles() as env:
        mgr = profilemod.ProfileManager()
        mgr.create("alt")
        assert os.path.exists(env.config_path("alt")), "no config.json right after create()"
        assert json.loads(Path(env.config_path("alt")).read_text(encoding="utf-8")) == {}


def test_a_directory_with_no_config_is_not_a_profile_and_is_not_backfilled() -> None:
    """The reversal of #1246's backfill, and why it is not a regression (#1306).

    That rule wrote an empty `config.json` into every listed directory so no profile was
    left without a file to point at. It ran over «every directory in profiles/» — which
    is how the squads report's picture folder acquired a config and became an account
    with a share in another profile's daemon.

    A profile is a directory WITH a config now, so the invariant #1246 was maintaining
    is the definition instead of something defended against it. A directory without one
    is not promoted, not listed — and not silently dropped either: `strays()` is what
    the panel says out loud about it, because a real profile whose config was lost lands
    there too and would otherwise simply vanish.
    """
    with _Profiles() as env:
        os.makedirs(os.path.join(profilemod.PROFILES_DIR, "orphan"))
        assert not os.path.exists(env.config_path("orphan"))
        mgr = profilemod.ProfileManager()          # constructing a manager promotes nothing
        assert not os.path.exists(env.config_path("orphan")), (
            "the folder was promoted into an account")
        assert "orphan" not in mgr.list()
        assert not mgr.exists("orphan")
        assert "orphan" in mgr.strays(), "it was dropped without a word"


# ---------------------------------------------------------------------------
# the default profile is the base
# ---------------------------------------------------------------------------

def test_an_untouched_setting_comes_from_the_default_profile() -> None:
    with _Profiles() as env:
        mgr = profilemod.ProfileManager()
        mgr.save({"tabs": {"known": ["a", "b"], "enabled": ["a"]}}, name="default")
        mgr.create("second")
        assert mgr.load("second")["tabs"]["enabled"] == ["a"]

        # …and changing the default reaches "second" without touching it at all.
        mgr.save({"tabs": {"known": ["a", "b"], "enabled": ["a", "b"]}}, name="default")
        assert mgr.load("second")["tabs"]["enabled"] == ["a", "b"]


def test_a_profile_that_overrides_a_setting_keeps_overriding_it() -> None:
    with _Profiles() as env:
        mgr = profilemod.ProfileManager()
        mgr.save({"daemon_port": 47654}, name="default")
        mgr.save({"daemon_port": 47655}, name="alt")
        assert mgr.load("alt")["daemon_port"] == 47655
        mgr.save({"daemon_port": 47654}, name="default")     # the default moves again
        assert mgr.load("alt")["daemon_port"] == 47655, "the override still wins"


def test_saving_a_profile_keeps_only_what_differs_from_the_default() -> None:
    with _Profiles() as env:
        mgr = profilemod.ProfileManager()
        mgr.save({"daemon_port": 47654, "watchdog": True}, name="default")
        # "alt" saves the FULL effective config (as the panel always does — it loads,
        # then edits, then saves the same dict back) with one knob changed.
        full = dict(mgr.load("alt"))
        full["daemon_port"] = 47655
        mgr.save(full, name="alt")

        on_disk = json.loads(Path(env.config_path("alt")).read_text(encoding="utf-8"))
        assert on_disk == {"daemon_port": 47655}, on_disk


def test_the_default_profile_itself_is_stored_whole() -> None:
    """No base underneath the default — round-trips exactly, nothing diffed away."""
    with _Profiles() as env:
        mgr = profilemod.ProfileManager()
        saved = {"tabs": {"known": ["a"], "enabled": ["a"]}, "watchdog": True}
        mgr.save(saved, name="default")
        on_disk = json.loads(Path(env.config_path("default")).read_text(encoding="utf-8"))
        assert on_disk == saved


def test_a_profile_missing_before_the_default_exists_has_no_base_to_fall_back_to() -> None:
    """Deleting the default profile must not crash every other profile's load — it
    just means nobody defines the shared base any more."""
    with _Profiles() as env:
        mgr = profilemod.ProfileManager()
        mgr.save({"daemon_port": 47654}, name="default")
        mgr.create("alt")
        mgr.save({"watchdog": True}, name="alt")
        import shutil
        shutil.rmtree(os.path.join(profilemod.PROFILES_DIR, "default"))
        assert mgr.load("alt") == {"watchdog": True}


# ---------------------------------------------------------------------------
# _deep_merge / _deep_diff are exact inverses
# ---------------------------------------------------------------------------

def test_merge_and_diff_round_trip_a_plain_nested_override() -> None:
    base = {"rally": {"kind": "boss", "level": 30, "squads": [1, 2]}, "watchdog": False}
    full = {"rally": {"kind": "boss", "level": 35, "squads": [1, 2]}, "watchdog": False}
    diffed = profilemod._deep_diff(full, base)
    assert diffed == {"rally": {"level": 35}}, diffed
    assert profilemod._deep_merge(base, diffed) == full


def test_a_new_field_the_base_gains_later_reaches_an_old_override() -> None:
    """The whole point of the merge: a profile that only ever set `level` picks up a
    brand-new sibling field the default gains afterwards."""
    base_then = {"rally": {"kind": "boss", "level": 30}}
    full_then = {"rally": {"kind": "boss", "level": 35}}
    diffed = profilemod._deep_diff(full_then, base_then)

    base_now = {"rally": {"kind": "boss", "level": 30, "autojoin": True}}   # gained a field
    assert profilemod._deep_merge(base_now, diffed) == {
        "rally": {"kind": "boss", "level": 35, "autojoin": True}
    }


def test_a_profiles_dict_with_fewer_keys_than_the_base_is_not_silently_widened() -> None:
    """The subset case: an old profile's own block never had `extra`, the base has it.

    A careless partial diff would drop `sub` entirely (it looks like it matches the
    base on every key IT has) and merging would then resurrect `extra` from the base —
    a field this profile never carried appearing out of nowhere.
    """
    base = {"block": {"a": 1, "extra": "only-the-base-has-this"}}
    full = {"block": {"a": 1}}                      # note: no "extra" at all
    diffed = profilemod._deep_diff(full, base)
    merged = profilemod._deep_merge(base, diffed)
    assert merged == full, merged


def test_property_merge_after_diff_reconstructs_the_original() -> None:
    """A deterministic sweep over the shapes that matter: equal, differing, a new key
    on either side, and the subset case — every one must round-trip exactly."""
    cases = [
        ({}, {}),
        ({"a": 1}, {"a": 1}),
        ({"a": 1}, {"a": 2}),
        ({"a": {"x": 1}}, {"a": {"x": 1, "y": 2}}),
        ({"a": {"x": 1, "y": 2}}, {"a": {"x": 1}}),
        ({"a": None}, {"a": {"x": 1}}),
        ({"a": {"x": 1}}, {"a": None}),
        ({"a": [1, 2]}, {"a": [1, 2, 3]}),
        ({"a": {"b": {"c": 1, "d": 2}}}, {"a": {"b": {"c": 1}}}),
    ]
    for base, full in cases:
        diffed = profilemod._deep_diff(full, base)
        merged = profilemod._deep_merge(base, diffed)
        assert merged == full, (base, full, diffed, merged)


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
        except Exception as exc:                       # noqa: BLE001
            failed += 1
            print(f"  ERR  {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())

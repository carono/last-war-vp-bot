r"""The remote control is ONE setting for the window, and the old ones come across (#1313).

There has only ever been one web server per panel — it answers for every profile the
window has open — but its port, its token and its certificate lived on a tab, and
therefore in a profile's ``config.json``, one copy per account. A window with three
profiles open held three answers to a question with one subject and obeyed whichever of
them was switched on first.

So the block moved to the panel-wide ``profiles/settings.json``, and the thing that
matters to somebody who already had it working is the MIGRATION: nobody's port and
nobody's token may be lost by an update, or the next thing they see is a phone that no
longer signs in and no way to tell why. This file pins both halves — which profile's
answer wins, and that the retired tab id is swept out of the profiles so an older
setting cannot come back as «this profile names a tab that does not exist».

No game, no socket, no display: it reads and writes JSON in a scratch directory. The
`ui` tier all the same, because reaching `panel/runtime/` imports Tk on the way in.

    C:\Python312\python.exe tests\test_panel_web_setting.py
    python3 tests/test_panel_web_setting.py
"""
from __future__ import annotations

TIER = "ui"

import json
import os
import socket
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (_REPO, _REPO / "tools" / "lib", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from panel import profile as profilemod          # noqa: E402
from panel.runtime import web_control as webctl  # noqa: E402


class _Profiles:
    """`profilemod` pointed at a scratch directory for the duration of a test."""

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self._saved = (profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE)
        profilemod.PROFILES_DIR = os.path.join(root, "profiles")
        profilemod.SETTINGS_FILE = os.path.join(root, "settings.json")
        os.makedirs(profilemod.PROFILES_DIR, exist_ok=True)
        return self

    def write(self, name: str, config: dict) -> None:
        path = os.path.join(profilemod.PROFILES_DIR, name)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, profilemod.CONFIG_FILE), "w",
                  encoding="utf-8") as fh:
            json.dump(config, fh, ensure_ascii=False, indent=2)

    def read(self, name: str) -> dict:
        with open(os.path.join(profilemod.PROFILES_DIR, name,
                               profilemod.CONFIG_FILE), encoding="utf-8") as fh:
            return json.load(fh)

    def settings(self) -> dict:
        try:
            with open(profilemod.SETTINGS_FILE, encoding="utf-8") as fh:
                return json.load(fh)
        except OSError:
            return {}

    def __exit__(self, *exc):
        profilemod.PROFILES_DIR, profilemod.SETTINGS_FILE = self._saved
        self._tmp.cleanup()


def _tab_block(**web) -> dict:
    return {"tabs": {"enabled": ["timers", "web"], "known": ["timers", "web"],
                     "order": ["web", "timers"], "config": {"web": web,
                                                            "timers": {"n": 1}}}}


# ---------------------------------------------------------------------------
# the migration
# ---------------------------------------------------------------------------
def test_the_profile_that_had_it_switched_on_is_the_one_that_wins():
    """Its port and its token are what a phone is holding RIGHT NOW.

    A second profile that merely has a stale copy must not win by being read first —
    the person would come back to an address that answers 401.
    """
    with _Profiles() as store:
        store.write("default", _tab_block(enabled=False, port="9000", token="stale"))
        store.write("second", _tab_block(enabled=True, port="9761", token="live"))
        source = profilemod.migrate_web_settings()
        assert source == "second", source
        block = profilemod.web_settings()
        assert block["token"] == "live" and block["port"] == "9761", block
        assert block["enabled"] is True, block


def test_a_token_beats_no_token_when_nothing_is_switched_on():
    """A link that was set up and switched off still works when it is switched back on."""
    with _Profiles() as store:
        store.write("default", _tab_block(enabled=False, port="9000"))
        store.write("second", _tab_block(enabled=False, token="kept"))
        assert profilemod.migrate_web_settings() == "second"
        assert profilemod.web_settings()["token"] == "kept"


def test_the_default_profile_is_read_first_so_a_tie_goes_to_it():
    with _Profiles() as store:
        store.write("default", _tab_block(enabled=True, token="mine"))
        store.write("second", _tab_block(enabled=True, token="theirs"))
        assert profilemod.migrate_web_settings() == "default"
        assert profilemod.web_settings()["token"] == "mine"


def test_the_retired_tab_id_is_swept_out_of_every_profile():
    """Otherwise every start logs «this profile names a tab that does not exist».

    Once per profile, for ever, about a tab nobody removed by hand — and the settings
    block would sit there looking like the live answer to anybody who opened the file.
    """
    with _Profiles() as store:
        store.write("default", _tab_block(enabled=True, token="mine"))
        store.write("second", _tab_block(enabled=False))
        profilemod.migrate_web_settings()
        for name in ("default", "second"):
            tabs = store.read(name)["tabs"]
            assert "web" not in tabs["enabled"], name
            assert "web" not in tabs["known"], name
            assert "web" not in tabs["order"], name
            assert "web" not in tabs["config"], name
            # …and nothing else was touched on the way past.
            assert tabs["config"]["timers"] == {"n": 1}, name
            assert "timers" in tabs["enabled"], name


def test_it_runs_once_and_never_overwrites_what_is_there():
    """A profile that grows a stale block later must not take the panel's answer back."""
    with _Profiles() as store:
        store.write("default", _tab_block(enabled=True, token="first"))
        assert profilemod.migrate_web_settings() == "default"
        store.write("default", _tab_block(enabled=True, token="second"))
        assert profilemod.migrate_web_settings() is None
        assert profilemod.web_settings()["token"] == "first"


def test_a_fresh_install_records_that_there_was_nothing_to_bring_across():
    """The KEY is written even when the block is empty — or it would re-scan for ever."""
    with _Profiles() as store:
        store.write("default", {"tabs": {"enabled": ["timers"]}})
        assert profilemod.migrate_web_settings() is None
        assert profilemod.WEB_KEY in store.settings()
        assert profilemod.web_settings() == {}


# ---------------------------------------------------------------------------
# the setting itself
# ---------------------------------------------------------------------------
def test_an_unset_panel_is_off_on_this_machines_port_with_no_token():
    with _Profiles():
        values = webctl.settings()
        assert values["enabled"] is False
        assert values["token"] == ""
        assert int(values["port"]) == webctl.port_number(values)


def test_what_is_saved_is_what_comes_back_and_it_is_panel_wide():
    with _Profiles() as store:
        webctl.save({"enabled": True, "port": "9999", "token": "t0k"})
        assert webctl.settings()["port"] == "9999"
        assert webctl.settings()["enabled"] is True
        # In the panel-wide file, not in any profile's — that is the whole change.
        assert store.settings()[profilemod.WEB_KEY]["token"] == "t0k"


def test_a_new_token_is_saved_and_is_not_the_old_one():
    with _Profiles():
        webctl.save({"token": "old"})
        fresh = webctl.new_token()
        assert fresh and fresh != "old"
        assert webctl.settings()["token"] == fresh


def test_an_unreadable_port_falls_back_instead_of_raising():
    """A half-typed port is a knob somebody is in the middle of, not a crash."""
    with _Profiles():
        webctl.save({"port": "97 6x"})
        assert webctl.port_number() == webctl.port_number(webctl.defaults())


def test_switching_it_on_binds_and_switching_it_off_lets_go():
    """The whole of what the menu entry does, without the menu entry.

    Bound on `127.0.0.1` rather than on every interface: a test must not put a socket
    on the network of the machine it happens to be running on.
    """
    with _Profiles():
        port = _free_port()
        webctl.save({"enabled": True, "host": "127.0.0.1", "port": str(port),
                     "token": "t0k"})
        try:
            assert webctl.apply(_Runtime()) is True
            server = webctl.serving()
            assert server is not None and server.bound_port() == port
            # …and asking again changes nothing: one socket per window, idempotent.
            assert webctl.apply(_Runtime()) is True
            assert webctl.serving() is server
        finally:
            webctl.stop(_Runtime())
        assert webctl.serving() is None


def test_a_socket_that_cannot_be_bound_switches_the_setting_back_off():
    """So the dialog and the machine cannot disagree about whether it is running.

    A switch that stays ticked over a socket that never bound is the one state nobody
    can diagnose from a phone: the panel says «on» and nothing answers.

    An address this machine does not have, rather than a port somebody else is holding:
    Windows lets a second socket onto a taken port when both ask to reuse it, which
    `ThreadingHTTPServer` does by default — so «taken» is not a failure that can be
    staged portably, and «not mine to bind» is.
    """
    with _Profiles():
        webctl.save({"enabled": True, "host": "203.0.113.9",   # TEST-NET-3, RFC 5737
                     "port": str(_free_port()), "token": "t0k"})
        said = _Runtime()
        try:
            assert webctl.apply(said) is False
            assert webctl.settings()["enabled"] is False
            assert [key for _tag, key, _fmt in said.lines] == ["web.log.busy"], said.lines
        finally:
            webctl.stop()


class _Runtime:
    """As much of a runtime as starting the server needs — it attaches a log feed."""

    class _Profiles:
        active = "default"

        def panel_log(self) -> str:
            return os.path.join(tempfile.gettempdir(), "no-such-panel.log")

    class _Log:
        def tap(self, _take):
            return lambda: None

    def __init__(self) -> None:
        self.lines: list = []
        self.profiles = self._Profiles()
        self.log = self._Log()

    def say(self, tag: str, key: str, **fmt) -> None:
        self.lines.append((tag, key, fmt))


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


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

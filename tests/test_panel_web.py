r"""The panel seen from a phone: the JSON surface, the token, and the words (#1221).

Four things are pinned here, and each of them is something that has already gone wrong
in a remote control somebody wrote in a hurry:

* **every route answers what the panel holds** — and nothing here presses the game;
* **nothing is readable without the token** — bar the two routes that are deliberately
  open, and a path outside `static/` is not served at all;
* **the log is replayed BY NUMBER**, so a phone that was in a pocket for an hour gets
  what it missed once rather than the whole tail on every poll;
* **not one word of the page is written in the page** — every `data-i18n` key in the
  HTML and every `T('…')` in the JavaScript is in ALL ELEVEN locales, which the Python
  i18n test cannot see because it only walks `.py`.

Needs no display and no game: everything below is either a plain object or a socket on
a port the operating system picks.

    C:\Python312\python.exe tests\test_panel_web.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from panel import i18n as i18nmod          # noqa: E402
from panel import timers as timersmod      # noqa: E402
from panel.runtime.log import LogBus       # noqa: E402
from panel.web import api as apimod        # noqa: E402
from panel.web import server as webmod     # noqa: E402


# ---------------------------------------------------------------------------
# a runtime small enough to read, real where it matters
# ---------------------------------------------------------------------------
class _Profiles:
    def __init__(self, home: str) -> None:
        self.active = "test"
        self._home = home

    def panel_log(self) -> str:
        return os.path.join(self._home, "panel.log")

    def timers_json(self) -> str:
        return os.path.join(self._home, "timers.json")


class _Game:
    token = ""
    #: A PROPERTY on the real link, so it is one here too — a stand-in that made it a
    #: method hid `bool` not being callable until the tab was run against a real
    #: runtime, which is exactly the sort of thing a stand-in is supposed to catch.
    busy = False

    def __init__(self) -> None:
        self.claimed: list = []

    def up(self) -> bool:
        return False

    def claim(self, owner: str = "panel") -> bool:
        self.claimed.append(owner)
        return False                     # nothing in a test may drive a game


class _Activity:
    def current(self):
        return None


class _Settings:
    def __init__(self, values: dict | None = None) -> None:
        self.values = dict(values or {})
        self.defaults = {"game_exe": "nothing.exe", "rdp_session": False,
                         "rdp_user": ""}

    def opt(self, key: str):
        return self.values.get(key, self.defaults.get(key))

    def opt_str(self, key: str) -> str:
        return str(self.opt(key) or "")

    def opt_bool(self, key: str) -> bool:
        return bool(self.opt(key))


class _Timers:
    """The scheduler's queue, as far as the web is concerned."""

    def __init__(self) -> None:
        self.requested: list = []

    def pending(self) -> set:
        return set(self.requested)

    def running(self) -> bool:
        return False

    def request(self, timer) -> bool:
        self.requested.append(timer.name)
        return True


class _Schedule:
    def __init__(self, home: str) -> None:
        self.timer_catalogue = timersmod.Catalogue((
            timersmod.Timer(name="collect", scenario=("collect_base_resources",),
                            interval_sec=3600, enabled=True, title="Collect"),
            timersmod.Timer(name="upkeep", scenario=("donate_alliance_tech",),
                            interval_sec=1800, enabled=False, title="Upkeep"),
        ))
        self.store = timersmod.LastRunStore(os.path.join(home, "last_run.json"))
        self.timers = _Timers()

    def timer_config(self) -> dict:
        return self.timer_catalogue.default_config()


class _Tabs:
    def get(self, tab_id: str):
        return None


class _Actions:
    def resolve(self, name: str):
        return name if name == "collect_base_resources" else None


class _Runtime:
    """Everything `panel/web/api.py` asks for, and not one thing more."""

    root = None

    def __init__(self, home: str) -> None:
        self.profiles = _Profiles(home)
        self.i18n = type("_I18n", (), {"lang": "en"})()
        self.log = LogBus()
        self.game = _Game()
        self.activity = _Activity()
        self.settings = _Settings()
        self.schedule = _Schedule(home)
        self.tabs = _Tabs()
        self.actions = _Actions()
        self.played: list = []
        self.busy_next = False

    def t(self, key: str, **fmt) -> str:
        return i18nmod.load_locale("en").get(key, key).format(**fmt) if fmt else key

    def say(self, tag: str, key: str, **fmt) -> None:
        self.log.put(f"[{tag}] {key}")

    def daemon_port(self) -> int:
        return 47654

    def dbg(self, component: str = "panel"):
        import logging
        return logging.getLogger("test.web")

    def play_async(self, name, args=None, *, tag="action", **kw) -> bool:
        self.played.append(name)
        return not self.busy_next


def _api(home: str):
    rt = _Runtime(home)
    api = apimod.WebApi(rt)
    return rt, api


# ---------------------------------------------------------------------------
# the surface
# ---------------------------------------------------------------------------
def test_every_route_answers_off_the_runtime():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        for path in ("/api/state", "/api/timers", "/api/actions", "/api/i18n",
                     "/api/log"):
            status, payload = api.dispatch("GET", path, {}, {})
            assert status == 200, f"{path} answered {status}"
            assert isinstance(payload, dict), path
        status, _ = api.dispatch("GET", "/api/nothing", {}, {})
        assert status == 404
        # And the one thing the whole file is about: asking never pressed the game.
        assert rt.game.claimed == [], rt.game.claimed


def test_the_state_says_what_the_runtime_says():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        state = api.state()
        assert state["profile"] == "test"
        assert state["daemon"]["port"] == 47654
        assert state["daemon"]["up"] is False
        assert state["timers"]["on"] == 1, state["timers"]
        # The TITLE — see `test_the_front_page_names_the_errand_rather_than_its_id`.
        assert state["timers"]["next_name"] == "Collect"


def test_a_scenario_runs_through_play_async_and_a_busy_panel_says_so():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        assert api.run_action("no_such_scenario") == {"error": "unknown"}
        answer = api.run_action("collect_base_resources")
        assert answer["ok"] and rt.played == ["collect_base_resources"]
        rt.busy_next = True
        answer = api.run_action("collect_base_resources")
        assert answer["ok"] is False and answer["busy"] is True


def test_an_errand_is_queued_not_run_here():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        assert api.run_timer("nope") == {"error": "unknown"}
        assert api.run_timer("collect")["queued"] is True
        assert rt.schedule.timers.requested == ["collect"]


def test_a_switch_from_the_phone_lands_in_the_profiles_own_file():
    """With no Timers tab in this window the file IS the configuration."""
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        assert api.set_timer("upkeep", True)["ok"] is True
        saved = json.loads(Path(rt.profiles.timers_json()).read_text(encoding="utf-8"))
        rows = saved["timers"] if isinstance(saved, dict) else saved
        by_name = {row["name"]: row for row in rows}
        assert by_name["upkeep"]["enabled"] is True
        assert by_name["collect"]["enabled"] is True, "the other switch was not touched"


def test_the_timers_tabs_boxes_win_when_it_is_open():
    """A live Timers tab owns the switches — writing the file behind it would be undone."""
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        moved: list = []

        class _Tab:
            def set_enabled(self, name, on):
                moved.append((name, on))
                return True

        rt.tabs.get = lambda tab_id: _Tab() if tab_id == "timers" else None
        assert api.set_timer("upkeep", True)["ok"] is True
        assert moved == [("upkeep", True)]
        assert not os.path.exists(rt.profiles.timers_json()), (
            "the file was written behind a live tab's back")


# ---------------------------------------------------------------------------
# the log
# ---------------------------------------------------------------------------
def test_the_log_is_replayed_by_number_and_only_once():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        api.attach()
        rt.log.put("[panel] one")
        rt.log.put("[timer] ошибка two")
        first = api.log(0)
        assert [row["text"] for row in first["lines"]] == ["[panel] one",
                                                           "[timer] ошибка two"]
        assert first["lines"][1]["sev"] == "error", first["lines"][1]
        assert first["lines"][0]["tag"] == "panel"
        again = api.log(first["next"])
        assert again["lines"] == [], "a poll with nothing new re-sent the tail"
        rt.log.put("[panel] three")
        assert [row["text"] for row in api.log(again["next"])["lines"]] == \
            ["[panel] three"]
        api.detach()
        rt.log.put("[panel] four")
        assert api.log(0)["lines"] == [], "a stopped server is still collecting"


def test_a_phone_that_connects_late_is_handed_the_file():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        Path(rt.profiles.panel_log()).write_text(
            "2026-08-03 10:00:00 [panel] before the phone\n", encoding="utf-8")
        api.attach()
        try:
            assert any("before the phone" in row["text"] for row in api.log(0)["lines"])
        finally:
            api.detach()


# ---------------------------------------------------------------------------
# the door
# ---------------------------------------------------------------------------
class _Served:
    """A server on a port the OS picks, torn down whatever the test does."""

    def __init__(self, home: str, token: str = "s3cret") -> None:
        self.rt, self.api = _api(home)
        self.server = webmod.WebServer(self.rt, host="127.0.0.1", port=0,
                                       token=token, api=self.api)

    def __enter__(self):
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.bound_port()}"
        return self

    def __exit__(self, *exc):
        self.server.stop()
        return False

    def ask(self, path: str, token: str = "", cookie: str = "", data=None):
        """``(status, body)`` — an HTTP error is an answer here, not an exception."""
        request = urllib.request.Request(self.base + path)
        if token:
            request.add_header("X-Panel-Token", token)
        if cookie:
            request.add_header("Cookie", cookie)
        if data is not None:
            request.data = json.dumps(data).encode("utf-8")
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=5) as answer:
                return answer.status, answer.read(), dict(answer.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)


def test_nothing_of_the_profile_is_readable_without_the_token():
    with tempfile.TemporaryDirectory() as home, _Served(home) as served:
        for path in ("/api/state", "/api/timers", "/api/actions", "/api/log"):
            status, _body, _h = served.ask(path)
            assert status == 401, f"{path} answered {status} to a stranger"
        status, body, _h = served.ask("/api/state", token="s3cret")
        assert status == 200 and json.loads(body)["profile"] == "test"
        status, _body, _h = served.ask("/api/state", token="nearly-s3cret")
        assert status == 401


def test_the_token_travels_as_a_cookie_and_on_the_url():
    with tempfile.TemporaryDirectory() as home, _Served(home) as served:
        status, _body, _h = served.ask("/api/state",
                                       cookie=f"{webmod.COOKIE}=s3cret")
        assert status == 200
        status, _body, _h = served.ask("/api/state?token=s3cret")
        assert status == 200


def test_the_words_answer_without_a_token_so_the_login_box_has_any():
    """The locale table is eleven files this repository publishes; the profile is not."""
    with tempfile.TemporaryDirectory() as home, _Served(home) as served:
        status, body, _h = served.ask("/api/i18n")
        assert status == 200
        assert json.loads(body)["words"]["web.ui.login.enter"]
        status, body, _h = served.ask("/api/ping")
        assert status == 200 and json.loads(body)["authorised"] is False


def test_signing_in_sets_the_cookie_and_a_wrong_token_does_not():
    with tempfile.TemporaryDirectory() as home, _Served(home) as served:
        status, _body, headers = served.ask("/api/login", data={"token": "s3cret"})
        assert status == 200
        assert webmod.COOKIE in headers.get("Set-Cookie", "")
        status, _body, headers = served.ask("/api/login", data={"token": "wrong"})
        assert status == 403
        assert "Set-Cookie" not in headers


def test_the_page_is_served_and_nothing_above_it_is():
    with tempfile.TemporaryDirectory() as home, _Served(home) as served:
        status, body, _h = served.ask("/")
        assert status == 200 and b"<html" in body.lower()
        status, _body, _h = served.ask("/app.js")
        assert status == 200
        for escape in ("/../api.py", "/..%2fapi.py", "/static/../server.py"):
            status, _body, _h = served.ask(escape)
            assert status == 404, f"{escape} was served ({status})"


def test_a_command_reaches_the_runtime_over_the_wire():
    with tempfile.TemporaryDirectory() as home, _Served(home) as served:
        status, body, _h = served.ask("/api/actions/run", token="s3cret",
                                      data={"name": "collect_base_resources"})
        assert status == 200 and json.loads(body)["ok"] is True
        assert served.rt.played == ["collect_base_resources"]
        status, _body, _h = served.ask("/api/actions/run", token="s3cret",
                                       data={"name": "no_such_thing"})
        assert status == 404


def test_a_server_without_a_token_refuses_to_start():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        server = webmod.WebServer(rt, host="127.0.0.1", port=0, token="", api=api)
        try:
            server.start()
        except ValueError:
            return
        finally:
            server.stop()
        raise AssertionError("a server with no token started")


# ---------------------------------------------------------------------------
# the words of the page
# ---------------------------------------------------------------------------
_KEY_IN_JS = re.compile(r"""\bT\(\s*['"]([a-z0-9_.]+)['"]""")
_KEY_IN_HTML = re.compile(r"""data-i18n(?:-placeholder)?=["']([a-z0-9_.]+)["']""")


def _keys_the_page_asks_for() -> set:
    static = Path(apimod.static_dir())
    found: set = set()
    for path in sorted(static.glob("*.js")):
        found |= set(_KEY_IN_JS.findall(path.read_text(encoding="utf-8")))
    for path in sorted(static.glob("*.html")):
        found |= set(_KEY_IN_HTML.findall(path.read_text(encoding="utf-8")))
    return found


def test_the_page_asks_for_keys_and_never_writes_a_word_itself():
    asked = _keys_the_page_asks_for()
    assert len(asked) > 30, f"only {len(asked)} keys found — did the scan stop working?"
    shipped = {path.stem: json.loads(path.read_text(encoding="utf-8"))
               for path in sorted(Path(i18nmod.LOCALES_DIR).glob("*.json"))}
    assert len(shipped) >= 11, sorted(shipped)
    for lang, table in sorted(shipped.items()):
        missing = sorted(k for k in asked if k not in table)
        assert not missing, f"{lang}.json does not translate {missing[:8]}"


def test_the_pages_placeholders_match_the_english_ones():
    """`{span}` in one language and `{spann}` in another is a word that never appears."""
    asked = _keys_the_page_asks_for()
    english = json.loads((Path(i18nmod.LOCALES_DIR) / "en.json").read_text(
        encoding="utf-8"))
    holes = re.compile(r"\{([a-z_]+)\}")
    for path in sorted(Path(i18nmod.LOCALES_DIR).glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        for key in sorted(asked):
            want = set(holes.findall(english.get(key, "")))
            got = set(holes.findall(table.get(key, "")))
            assert want == got, f"{path.stem}.json[{key}]: {sorted(got)} ≠ {sorted(want)}"


# ---------------------------------------------------------------------------
# two accounts, one socket
# ---------------------------------------------------------------------------
#
# The window may hold two profiles open (#1206) and that is how this bot is actually
# run. A front-end that showed one of them and did not say which is the failure this
# whole section exists to prevent — it has happened at the machine already, one profile
# reading the other's client and looking perfectly healthy doing it.

class _Workspace:
    """The half of `panel/runtime/workspace.py` the web asks about."""

    def __init__(self, sessions) -> None:
        self._sessions = list(sessions)
        self.current = self._sessions[0]

    @property
    def sessions(self) -> list:
        return list(self._sessions)

    def close(self, name: str) -> None:
        self._sessions = [s for s in self._sessions if s.name != name]
        if self.current.name == name and self._sessions:
            self.current = self._sessions[0]


def _two_profiles(home: str):
    """Two runtimes in one workspace, wired the way `Workspace.open` wires them."""
    first, second = _Runtime(os.path.join(home, "a")), _Runtime(os.path.join(home, "b"))
    for rt, name in ((first, "main"), (second, "second")):
        os.makedirs(rt.profiles._home, exist_ok=True)
        rt.profiles.active = name
    sessions = [type("_S", (), {"name": "main", "rt": first})(),
                type("_S", (), {"name": "second", "rt": second})()]
    workspace = _Workspace(sessions)
    first.workspace = workspace
    second.workspace = workspace
    return first, second, workspace


def test_the_page_can_ask_which_accounts_are_open():
    with tempfile.TemporaryDirectory() as home:
        first, _second, _ws = _two_profiles(home)
        api = apimod.WebApi(first)
        answer = api.profiles()
        assert answer["profiles"] == ["main", "second"], answer
        assert answer["home"] == "main" and answer["showing"] == "main"


def test_every_route_answers_for_the_profile_it_was_asked_about():
    with tempfile.TemporaryDirectory() as home:
        first, second, _ws = _two_profiles(home)
        second.schedule.timer_catalogue = timersmod.Catalogue((
            timersmod.Timer(name="second_only", scenario=("heal_units",),
                            interval_sec=600, enabled=True, title="Second only"),))
        api = apimod.WebApi(first)
        assert api.state("second")["profile"] == "second"
        assert [t["name"] for t in api.timers("second")["timers"]] == ["second_only"]
        assert [t["name"] for t in api.timers()["timers"]] == ["collect", "upkeep"]


def test_a_press_lands_on_the_client_of_the_profile_it_named():
    """The whole point of naming one: the second account's button is not the first's."""
    with tempfile.TemporaryDirectory() as home:
        first, second, _ws = _two_profiles(home)
        api = apimod.WebApi(first)
        assert api.run_action("collect_base_resources", "second")["ok"] is True
        assert second.played == ["collect_base_resources"]
        assert first.played == [], "the press went to the wrong account"
        api.run_timer("collect")                      # unnamed = the server's own
        assert first.schedule.timers.requested == ["collect"]
        assert second.schedule.timers.requested == []


def test_each_profile_keeps_its_own_log_and_its_own_numbering():
    with tempfile.TemporaryDirectory() as home:
        first, second, _ws = _two_profiles(home)
        api = apimod.WebApi(first)
        api.attach()
        try:
            first.log.put("[panel] first says one")
            second.log.put("[panel] second says one")
            second.log.put("[panel] second says two")
            mine = api.log(0)
            theirs = api.log(0, "second")
            assert [r["text"] for r in mine["lines"]] == ["[panel] first says one"]
            assert len(theirs["lines"]) == 2, theirs
            # …and the sequence is per profile, so one does not skip the other's numbers
            assert mine["next"] == 1 and theirs["next"] == 2
        finally:
            api.detach()


def test_a_profile_opened_after_the_server_is_picked_up():
    with tempfile.TemporaryDirectory() as home:
        first, second, workspace = _two_profiles(home)
        workspace._sessions = workspace._sessions[:1]          # only «main» at start
        api = apimod.WebApi(first)
        api.attach()
        try:
            workspace._sessions.append(
                type("_S", (), {"name": "second", "rt": second})())
            api.log(0)                      # the phone's next ordinary poll
            second.log.put("[panel] opened later")
            assert any("opened later" in r["text"]
                       for r in api.log(0, "second")["lines"])
        finally:
            api.detach()


def test_a_profile_closed_at_the_machine_does_not_blank_the_phone():
    """The selector may name a profile that has just been closed — fall back, do not 404."""
    with tempfile.TemporaryDirectory() as home:
        first, _second, workspace = _two_profiles(home)
        api = apimod.WebApi(first)
        workspace.close("second")
        assert api.state("second")["profile"] == "main"
        assert api.profiles()["profiles"] == ["main"]


def test_a_runtime_with_no_workspace_answers_for_itself():
    """A tab launched on its own is the same code path with one session in it."""
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        assert api.profiles()["profiles"] == ["test"]
        assert api.state("nobody")["profile"] == "test"


def test_only_one_server_holds_the_window():
    """A second session's tab must not put a second address in front of the same pair."""
    with tempfile.TemporaryDirectory() as home:
        first, second, _ws = _two_profiles(home)
        one = webmod.WebServer(first, host="127.0.0.1", port=0, token="t1")
        one.start()
        try:
            assert webmod.serving_any() is one
            assert webmod.serving(one.bound_port()) is one
            assert one.owner == "main"
            # What the sibling's tab reads to decide it has nothing to start.
            assert webmod.serving_any().token == "t1"
        finally:
            one.stop()
        assert webmod.serving_any() is None, "the registry kept a stopped server"


# ---------------------------------------------------------------------------
# which port, and who decides it
# ---------------------------------------------------------------------------
def test_the_port_is_decided_by_the_resolver_and_not_spelled_here():
    """9761 lives in `tools/lib/game_paths.py` and nowhere else (`CLAUDE.md`).

    A literal in `panel/web/` would be the same number written twice, and the two would
    drift the first time somebody changed one — which is the exact history that made the
    resolver exist (a launcher path said one thing in the panel and another in a tool).
    """
    import game_paths

    saved = os.environ.pop("LW_WEB_PORT", None)
    try:
        assert webmod.default_port() == game_paths.DEFAULT_WEB_PORT == 9761
        os.environ["LW_WEB_PORT"] = "9999"
        assert webmod.default_port() == 9999, "LW_WEB_PORT is not read"
        for nonsense in ("0", "-1", "70000", "nine thousand"):
            os.environ["LW_WEB_PORT"] = nonsense
            assert webmod.default_port() == 9761, (
                f"{nonsense!r} was obeyed — a port nobody can reach is worse than "
                f"the default")
    finally:
        os.environ.pop("LW_WEB_PORT", None)
        if saved is not None:
            os.environ["LW_WEB_PORT"] = saved


def test_the_variable_is_written_down_where_a_person_would_look():
    """Every new variable goes into `.env.example` in the same change (`CLAUDE.md`)."""
    text = (_REPO / ".env.example").read_text(encoding="utf-8")
    assert "LW_WEB_PORT=" in text, ".env.example does not mention LW_WEB_PORT"


def test_a_profile_that_named_a_port_beats_the_machines_answer():
    """Three layers: the profile, then `LW_WEB_PORT`, then 9761. The top one wins."""
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        os.environ["LW_WEB_PORT"] = "9999"
        try:
            server = webmod.WebServer(rt, host="127.0.0.1", port=9123, token="t",
                                      api=api)
            assert server.port == 9123, "the profile's own port was ignored"
            assert webmod.WebServer(rt, host="127.0.0.1", token="t", api=api).port == 9999
        finally:
            os.environ.pop("LW_WEB_PORT", None)


# ---------------------------------------------------------------------------
# the phone it is actually held on
# ---------------------------------------------------------------------------
#
# The page was measured through real engines at 360x640 (Android, Chromium mobile) and
# 393x852 (iPhone 15, WebKit) — no horizontal overflow, no tap target under 44 px, no
# input under 16 px. That run needs Playwright and lives outside the repository
# (~/playwright-tests/shot-panel-web.js). What follows is the half a static reading can
# keep honest, so a later edit cannot quietly undo it.

def _css(with_comments: bool = False) -> str:
    """The stylesheet — by default WITHOUT its comments.

    The rules below read the text rather than a parsed tree, and the file explains the
    rules it is held to in prose. A comment saying «no `:hover` anywhere» is not a
    `:hover`, and the first version of this test failed on its own documentation.
    """
    css = (Path(apimod.static_dir()) / "style.css").read_text(encoding="utf-8")
    return css if with_comments else re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_the_page_is_told_it_is_on_a_phone():
    html = (Path(apimod.static_dir()) / "index.html").read_text(encoding="utf-8")
    meta = re.search(r'<meta name="viewport" content="([^"]+)"', html)
    assert meta, "no viewport meta — the phone renders it at 980 px and shrinks it"
    content = meta.group(1)
    assert "width=device-width" in content and "initial-scale=1" in content, content
    # The notch: without it the header sits under the status bar and the bottom bar
    # under the home indicator.
    assert "viewport-fit=cover" in content, content
    assert "env(safe-area-inset" in _css(), "the safe area is not kept clear"


def test_nothing_waits_for_a_cursor_that_is_not_there():
    """`:hover` on a phone is a state that never happens — the control looks dead."""
    assert ":hover" not in _css()


def test_every_control_is_at_least_a_finger_wide():
    """44 CSS px, and the audit that measured it found the switches at 26."""
    css = _css()
    heights = [int(n) for n in re.findall(r"min-height:\s*(\d+)px", css)]
    assert heights, "nothing declares a minimum height any more"
    assert min(heights) >= 44, f"a control is {min(heights)} px tall"
    assert re.search(r"button\s*\{[^}]*min-height:\s*(4[4-9]|[5-9]\d)px", css), (
        "the buttons no longer declare a thumb-sized minimum")


def test_no_input_is_small_enough_to_make_ios_zoom():
    """Under 16 px in a focused field and Safari zooms the page; the person pinches back."""
    css = _css()
    for rule in re.findall(r"input[^{]*\{[^}]*\}", css):
        for size in re.findall(r"font-size:\s*(\d+)px", rule):
            assert int(size) >= 16, f"an input is set to {size}px:\n{rule}"


def test_the_layout_is_mobile_first_and_not_a_squeezed_desktop():
    """Every media query WIDENS. A `max-width` one means the phone is the exception."""
    queries = re.findall(r"@media\s*\(([^)]+)\)", _css())
    assert queries, "there is no media query at all — that is fine, but say so here"
    for query in queries:
        assert "min-width" in query, f"@media ({query}) narrows instead of widening"


def test_nothing_is_wider_than_the_narrowest_phone():
    """A fixed width above 360 px is a page that scrolls sideways on an Android."""
    css = _css()
    wide = [int(n) for n in re.findall(r"[^-]width:\s*(\d{3,})px", css)
            if int(n) > 360]
    # `max-width` inside the desktop media query is allowed — it is a ceiling, not a size.
    allowed = {int(n) for n in re.findall(r"max-width:\s*(\d+)px", css)}
    assert not [n for n in wide if n not in allowed], f"fixed widths over 360: {wide}"


def test_the_front_page_names_the_errand_rather_than_its_id():
    """«ближайший: alliance_upkeep» is the file's key, not a thing anybody calls it."""
    with tempfile.TemporaryDirectory() as home:
        _rt, api = _api(home)
        assert api.state()["timers"]["next_name"] == "Collect", api.state()["timers"]


def test_the_running_scenario_is_named_so_the_page_can_mark_its_card():
    """The sentence is in whatever language the panel is set to; the name is not."""
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)

        class _Step:
            key, fmt = "activity.action", {"name": "collect_base_resources"}

        rt.activity.current = lambda: _Step()
        activity = api.state()["activity"]
        assert activity["name"] == "collect_base_resources", activity


def test_the_timers_tab_offers_the_hook_the_web_presses():
    """The two halves of «a switch from the phone» have to agree by name.

    `WebApi.set_timer` asks the live Timers tab for `set_enabled` and quietly writes the
    file when it is not there — which is correct for a profile without the tab and a
    silent no-op if the method is ever renamed.
    """
    from panel.tabs.timers import TimersTab

    assert callable(getattr(TimersTab, "set_enabled", None)), (
        "TimersTab.set_enabled is gone — the phone's switch now writes a file the "
        "tab's boxes will overwrite")


def test_the_tab_is_in_the_registry_and_names_the_same_key():
    from panel import tabs as tabsreg

    spec = tabsreg.BY_ID.get("web")
    assert spec is not None, "the «Веб» tab is not registered"
    assert spec.title_key == "tab.web"


def _main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for test in tests:
        started = time.time()
        try:
            test()
            print(f"  ok   {test.__name__}  ({time.time() - started:.2f}s)")
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

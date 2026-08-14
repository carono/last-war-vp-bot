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

Needs no game: everything below is either a plain object or a socket on a port the
operating system picks. TWO of the tests do need a display — the pair that check the
WINDOW draws the same row as the phone build a real page rather than reading
`panel/__main__.py` as text (#1282), and they skip where there is none, which is why the
file declares `TIER = "ui"`.

    C:\Python312\python.exe tests\test_panel_web.py
"""
from __future__ import annotations

TIER = "ui"        # Tk and a display — see tools/run_tests.py

import json
import os
import re
import ssl
import sys
import tempfile
import threading
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from panel import i18n as i18nmod          # noqa: E402
from panel import tabs as tabsreg          # noqa: E402
from panel import timers as timersmod      # noqa: E402
from panel.runtime import game_control as gamectl   # noqa: E402
from panel.runtime import gate as gatemod           # noqa: E402
from panel.runtime import health as healthmod       # noqa: E402
from panel.runtime import interrupt as interruptmod  # noqa: E402
from panel.runtime import day_reset as dayresetmod  # noqa: E402
from panel.runtime import panel_control as panelctl  # noqa: E402
from panel.runtime import panic as panicmod  # noqa: E402
from panel.runtime import recovery as recoverymod  # noqa: E402
from panel.runtime import web_control as webctl  # noqa: E402
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

    def last_health(self) -> str:
        """The status poll's last verdict — «nobody has asked lately» here (#1286).

        The page draws the daemon off this rather than asking for itself: the reading
        walks the process list and a phone polls faster than the status thread does.
        """
        return ""

    def claim(self, owner: str = "panel", priority: int = 0) -> bool:
        self.claimed.append(owner)
        return False                     # nothing in a test may drive a game

    def outranks(self, priority: int) -> bool:
        """Nobody is holding it, so a press has nothing to push aside (#1288)."""
        return False

    def claimed_by(self) -> "str | None":
        return None


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
    live: list = []

    def get(self, tab_id: str):
        return None

    def realize(self, tab) -> bool:
        """The registry draws a tab before the phone is handed it (#1215). A screen in
        this file is already whatever it is going to be, so this answers «nothing to
        draw» — and being here at all is what keeps the stand-in the same shape as
        `panel.tabs.TabRegistry`, which is what the API actually talks to."""
        return False


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
        # The REAL bookkeeping object, not a stand-in: `/api/state` reads
        # `recovery.state(now)` and the page draws its numbers, so a fake would only
        # pin the shape this file happens to imagine. It is pure state — no window, no
        # client, no thread — so there is nothing to fake (#1282; the routes here have
        # errored on its absence since the read was added).
        self.recovery = recoverymod.Recovery()
        # …and the same for «Включить обратно»: `/api/state` reads `panic.state(now)`
        # and `/api/panel` gates the resume on `panic.stopped`.
        self.panic = panicmod.Panic()
        # …and the gate, for the same reason (#1393): `/api/state` sends the phone
        # whether anything may run at all, and the real object is pure state — it reads
        # the light above and this runtime's `game.up()`, and probes nothing until asked.
        self.gate = gatemod.DaemonGate(self)
        # …and the profile's one light, for the same reason: `/api/profiles` draws the
        # phone's copy of the tab strip out of the LAST verdict the window's status poll
        # made (#1299), and a fake would pin a shape this file invented.
        self.health = healthmod.ProfileHealth()
        # …and the register of runs in flight, for the same reason again: `/api/state`
        # draws what is playing and the step it has reached, and `/api/interrupt` presses
        # its one press (#1300). Pure state, thread-safe, no window and no client — a
        # fake would only pin a shape this file invented.
        self.interrupts = interruptmod.Interrupts()
        # …and this profile's server-day boundary, for the same reason once more (#1333):
        # `/api/timers` and `/api/state` ask when each errand is next due, and a daily
        # one's answer IS the game's 00:00. The real object, pointed at this test's own
        # home — it is a small JSON file and an arithmetic helper, with no client behind
        # it unless something calls `refresh()`, which no route does.
        self.day = dayresetmod.DayReset(self, os.path.join(home, "day_reset.json"))
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


def _shell_page():
    """A real window with a real page in it, or `None` where there is no display.

    Two facts in this file are about the WINDOW rather than about the web: that its game
    row is built from `game_control.CONTROLS`, and that its restart button takes its word
    and its route from `panel_control`. Both used to be asserted by reading
    `panel/__main__.py` as text and looking for a name in it — which passes over dead
    code, fails on a rename, and is not the fact anybody cares about (#1282, audit §4.4).

    The harness that builds a real page against a temporary profile already exists in
    `tests/test_panel_page_build.py`; this borrows it rather than growing a second one.
    A machine with no display gets `None`, and the caller checks the web half only —
    that is why this file declares `TIER = "ui"`.
    """
    sys.path.insert(0, str(_REPO / "tests"))
    try:
        import test_panel_page_build as pagebuild

        import tkinter as tk

        tk.Tk().destroy()
    except Exception:                                  # noqa: BLE001 — no display
        return None
    try:
        return pagebuild._Harness(staged=False)
    except Exception:                                  # noqa: BLE001
        return None


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


def test_a_failed_errand_tells_the_phone_when_it_will_be_retried():
    """The row carries its retry, so «ошибка» comes with the reason the clock changed.

    A timer whose scenario ended in FAIL keeps its `last_run` and is tried again after
    `retry_sec` (#1127), which is minutes where the period is hours. Without the retry
    in the row the phone drew «каждый час · ошибка · следующий через 2 мин» — three
    facts, one of them apparently contradicting the others, and nothing to explain it.
    """
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        rt.schedule.timer_catalogue = rt.schedule.timer_catalogue.replace(
            timersmod.Timer(name="collect", scenario=("collect_base_resources",),
                            interval_sec=3600, retry_sec=120, enabled=True,
                            title="Collect"))
        now = time.time()
        rt.schedule.store.mark_failed("collect", when=now)
        row = {t["name"]: t for t in api.timers()["timers"]}["collect"]
        assert row["retry_sec"] == 120, row
        assert row["last_state"] == "failed", row
        # …and the countdown it explains is that retry, not the hourly period.
        assert abs(row["next"] - (now + 120)) < 2, row


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


def test_the_phone_draws_and_sets_the_at_once_flag():
    """The window's row grew a «сразу» box (#1288), so the phone has the same one.

    Both halves: the reading is in `/api/timers`, and the press writes the profile's own
    file when this window has no Timers tab — the same two branches the switch takes.
    """
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        row = {t["name"]: t for t in api.timers()["timers"]}["upkeep"]
        assert row["immediate"] is False, row

        assert api.set_timer_immediate("upkeep", True)["ok"] is True
        row = {t["name"]: t for t in api.timers()["timers"]}["upkeep"]
        assert row["immediate"] is True, row
        saved = json.loads(Path(rt.profiles.timers_json()).read_text(encoding="utf-8"))
        rows = saved["timers"] if isinstance(saved, dict) else saved
        by_name = {item["name"]: item for item in rows}
        assert by_name["upkeep"].get("immediate") is True, by_name["upkeep"]
        assert "immediate" not in by_name["collect"], "the other row was touched"


def test_the_at_once_box_goes_through_a_live_tab_like_the_switch_does():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        moved: list = []

        class _Tab:
            def set_immediate(self, name, on):
                moved.append((name, on))
                return True

        rt.tabs.get = lambda tab_id: _Tab() if tab_id == "timers" else None
        assert api.set_timer_immediate("upkeep", True)["ok"] is True
        assert moved == [("upkeep", True)]
        assert not os.path.exists(rt.profiles.timers_json()), (
            "the file was written behind a live tab's back")


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


def test_every_open_account_carries_its_own_light():
    """The phone's copy of the window's tab strip (#1299).

    One entry per open account, with the colour and the words already said — and a
    profile nothing has polled yet is AMBER, never green: a light that reads «all
    fine» because nobody looked is the one thing the whole rule exists to prevent.
    """
    with tempfile.TemporaryDirectory() as home:
        first, second, _ws = _two_profiles(home)
        second.health.update(
            type("_P", (), {"link": "online", "running": True,
                            "message": "online (pid 1)"})(),
            warm=True, stale=False, session="in_session")
        lights = apimod.WebApi(first).profiles()["lights"]
        assert [light["name"] for light in lights] == ["main", "second"], lights
        assert lights[0]["colour"] == "warn" and lights[0]["reason"] == "unread", lights
        assert lights[1]["colour"] == "ok", lights
        # …and each of them says WHY, in words, so a tap can explain the colour.
        assert all(light["text"] and light["tip"] for light in lights), lights


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
# TLS, when the person has a certificate of their own
# ---------------------------------------------------------------------------
def test_without_a_certificate_it_is_plain_http_and_says_so():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        assert webmod.WebServer(rt, token="t", api=api).scheme == "http"


def test_a_certificate_makes_it_https_in_the_address_it_hands_out():
    """An `http://` link to a server that only speaks TLS fails in a way nobody
    diagnoses on a phone, so the scheme follows the certificate."""
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        server = webmod.WebServer(rt, token="t", api=api, certfile="cert.pem")
        assert server.scheme == "https"


def test_a_certificate_that_will_not_load_refuses_to_serve():
    """THE failure worth preventing: believing you have TLS and serving plain HTTP.

    Anything that cannot be loaded — a path that is not there, a key that does not
    match — takes the server down with it instead of quietly falling back.
    """
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        server = webmod.WebServer(rt, host="127.0.0.1", port=0, token="t", api=api,
                                  certfile=os.path.join(home, "nothing.pem"))
        try:
            server.start()
        except (OSError, ValueError, ssl.SSLError):
            assert not server.running
            return
        finally:
            server.stop()
        raise AssertionError("it served without the certificate it was told to use")


# ---------------------------------------------------------------------------
# the client's life: start it, close it, put it back
# ---------------------------------------------------------------------------
#
# The three presses the window has, on the phone (#1221). What is pinned here is that
# the phone can press exactly them, that it presses them by playing the scenarios the
# window plays, and that the two front-ends decide availability out of the ONE table —
# a phone offering «Стоп» that the window greys out is the divergence CLAUDE.md forbids
# and the reason `panel/runtime/game_control.py` exists at all.
def _link_is(api, rt, link: str) -> None:
    """Pretend the probe found the client in this state, without a process to find."""
    api._status[rt.profiles.active] = (time.time(), link != gamectl.game_process.OFFLINE,
                                       link, "")


def test_the_state_page_carries_the_three_presses():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        _link_is(api, rt, gamectl.game_process.ONLINE)
        controls = api.state()["game"]["controls"]
        assert [c["id"] for c in controls] == ["launch", "quit", "restart"]
        # The words are locale KEYS the browser says out of the same table the window
        # uses — the very same keys, which is what makes the two buttons one button.
        english = i18nmod.load_locale("en")
        for control in controls:
            assert control["label"] in english, control
            assert not control["confirm"] or control["confirm"] in english, control


def test_a_press_that_would_mean_nothing_is_not_offered():
    """«Стоп» with no client, «Запуск» with one — the same rule the window greys by."""
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        _link_is(api, rt, gamectl.game_process.OFFLINE)
        off = {c["id"]: c["enabled"] for c in api.state()["game"]["controls"]}
        assert off == {"launch": True, "quit": False, "restart": False}
        _link_is(api, rt, gamectl.game_process.ONLINE)
        on = {c["id"]: c["enabled"] for c in api.state()["game"]["controls"]}
        assert on == {"launch": False, "quit": True, "restart": True}


def test_a_stranded_client_may_still_be_stopped_and_restarted():
    """`lost` is a client — the one most worth restarting — and `unknown` is one too.

    A second account's sockets cannot always be read from here, and answering "no
    client" to that would take the two presses away from the account most likely to
    need them from a phone.
    """
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        for link in (gamectl.game_process.LOST, gamectl.game_process.UNKNOWN):
            _link_is(api, rt, link)
            row = {c["id"]: c["enabled"] for c in api.state()["game"]["controls"]}
            assert row == {"launch": False, "quit": True, "restart": True}, link


def test_pressing_one_plays_the_scenario_and_says_so():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        _link_is(api, rt, gamectl.game_process.ONLINE)
        answer = api.game("restart")
        assert answer["ok"] and rt.played == ["restart_game"]
        # …under the game tag, so the log does not file it as a scenario somebody ran
        # by hand — and it is said BEFORE the run, so a failure inside the recipe still
        # leaves the intent on the record.
        assert any("[game] log.game.restarting" in line for line in rt.log.drain())


def test_pressing_the_one_that_no_longer_applies_runs_nothing():
    """A phone out of a pocket is showing a minute-old page, and a thumb is faster."""
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        _link_is(api, rt, gamectl.game_process.OFFLINE)
        answer = api.game("quit")
        assert answer["unavailable"] and not answer["ok"]
        assert rt.played == [], "a recipe ran for a client that is not there"


def test_a_press_refused_by_the_claim_is_busy_and_not_an_error():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        _link_is(api, rt, gamectl.game_process.ONLINE)
        rt.busy_next = True
        answer = api.game("quit")
        assert answer["busy"] and not answer["ok"]


def test_the_phone_cannot_invent_a_fourth_press():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        assert api.dispatch("POST", "/api/game", {},
                            {"action": "uninstall"})[0] == 404
        assert rt.played == []


def test_a_press_lands_on_the_account_it_names():
    """Two profiles, two clients — the one that closes is the one that was named."""
    with tempfile.TemporaryDirectory() as home:
        first, second, _ws = _two_profiles(home)
        api = apimod.WebApi(first)
        _link_is(api, second, gamectl.game_process.ONLINE)
        api.game("quit", "second")
        assert second.played == ["quit_game"] and first.played == []


def test_the_window_and_the_phone_draw_the_same_three():
    """The mirror, as a test rather than as a promise.

    Both front-ends build their row by walking `game_control.CONTROLS`: the window in
    `panel/__main__.py` (one button per entry, greyed through `available`), the page in
    `app.js` (one button per entry of `game.controls`). Neither may name a press of its
    own — that is how one front-end ends up with a button the other has never heard of.
    """
    # THE WINDOW: built, not grepped (#1282, audit §4.4). This used to assert that the
    # string «gamectl.CONTROLS» appears in `panel/__main__.py`, which passes over dead
    # code and fails on a rename — neither of which is the fact anybody cares about. So
    # a real page is built and its real row is compared to the table.
    harness = _shell_page()
    if harness is not None:
        try:
            app = harness.app
            buttons = app._game_buttons
            assert list(buttons) == [c.id for c in gamectl.CONTROLS], \
                f"the window's row is {list(buttons)}, the table is " \
                f"{[c.id for c in gamectl.CONTROLS]}"
            for control in gamectl.CONTROLS:
                assert buttons[control.id].cget("text") == app._t(control.label), \
                    f"{control.id}: the window words it its own way"
            # …and the greying is the table's rule, asked of the table, for both answers
            # it has: a link that is up enables what `available` enables, and one that
            # is not disables what it disables.
            for link in (gamectl.game_process.ONLINE, gamectl.game_process.OFFLINE):
                app._paint_game_buttons(link)
                for control in gamectl.CONTROLS:
                    on = str(buttons[control.id].cget("state")) != "disabled"
                    assert on == gamectl.available(control, link), \
                        f"{control.id} on link {link}: window says {on}, table says " \
                        f"{gamectl.available(control, link)}"
        finally:
            harness.close()

    script = (_REPO / "panel" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    # The browser is handed `enabled` and obeys it; a page computing it from the link
    # itself would be the second opinion this table exists to prevent.
    assert "control.enabled" in script
    for name in ("launch_game", "quit_game", "restart_game"):
        assert name not in script, \
            f"app.js names the scenario {name} — a press travels as an id, not a recipe"


# ---------------------------------------------------------------------------
# the PANEL's own life: putting it back on the code that is now on disk
# ---------------------------------------------------------------------------
#
# The press the window grew for an update, offered to the person who is holding a phone
# instead of standing at the machine (#1258). What is pinned here is that it exists only
# where there is a panel to restart, that it asks first, that the answer is written
# BEFORE anything closes — a phone handed a dead socket cannot tell «перезапускается»
# from «упало» — and that the window and the page press the one table.
class _Restarter:
    """A shell that only remembers it was asked to close itself."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


def _panel_is(shell):
    """Register (or take away) the one thing in this process that can restart it."""
    panelctl.set_handler(shell)


class _Windowed(_Runtime):
    """A runtime with a window: the hand-over is a queue and a real `after` delay.

    Stands in for the only case that matters live — a press arriving on an HTTP worker
    thread while a Tk event loop is turning — so the test can see that the restart is
    ARMED rather than carried out under the request that asked for it.
    """

    def __init__(self, home: str) -> None:
        super().__init__(home)
        self.root = object()                 # a window; nothing here draws with it
        self.posted: list = []
        self.armed: list = []
        self.tick = types.SimpleNamespace(
            arm=lambda name, delay, func: self.armed.append((name, delay, func)))

    def post(self, call) -> None:
        self.posted.append(call)


def test_the_state_page_carries_the_panel_itself():
    with tempfile.TemporaryDirectory() as home:
        _rt, api = _api(home)
        shell = _Restarter()
        _panel_is(shell)
        try:
            panel = api.state()["panel"]
        finally:
            _panel_is(None)
        assert panel["version"], "the phone is not told which version it is looking at"
        assert [c["id"] for c in panel["controls"]] == [panelctl.RESTART]
        # The words are locale KEYS, said by the browser out of the same table the
        # window's button and its message box are drawn from.
        english = i18nmod.load_locale("en")
        for control in panel["controls"]:
            assert control["label"] in english, control
            assert control["confirm"] in english, "a press this destructive asks first"


def test_a_process_that_is_not_a_panel_offers_no_restart():
    """A tab launched on its own answers this route too — and cannot restart a panel.

    Empty rather than greyed: the press does not EXIST there, which is not the same as
    a press that does not apply this second, and the page draws no card at all.
    """
    with tempfile.TemporaryDirectory() as home:
        _rt, api = _api(home)
        _panel_is(None)
        assert api.state()["panel"]["controls"] == []
        assert api.panel(panelctl.RESTART)["unavailable"] is True


def test_pressing_it_closes_the_panel_and_says_so_first():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        shell = _Restarter()
        _panel_is(shell)
        try:
            answer = api.panel(panelctl.RESTART)
        finally:
            _panel_is(None)
        assert answer["ok"] and shell.calls == 1
        # Said BEFORE anything is closed, so the record shows the intent even when the
        # shutdown then goes wrong halfway — and under the panel's own tag, not
        # «action», which is a scenario somebody ran.
        assert any("[panel] log.panel.restarting" in line for line in rt.log.drain())


def test_the_answer_is_written_before_the_floor_comes_out():
    """With a window, the shutdown is ARMED — the request that asked finishes first."""
    with tempfile.TemporaryDirectory() as home:
        rt = _Windowed(home)
        api = apimod.WebApi(rt)
        shell = _Restarter()
        _panel_is(shell)
        try:
            assert api.panel(panelctl.RESTART)["ok"]
        finally:
            _panel_is(None)
        assert shell.calls == 0, "the panel closed under the request that asked for it"
        assert len(rt.posted) == 1, "the Tk thread was reached some other way"
        rt.posted[0]()                                   # the pump gets round to it
        assert [(name, delay) for name, delay, _f in rt.armed] == [
            (panelctl.TICK, panelctl.DELAY_MS)]
        rt.armed[0][2]()                                 # …and the delay runs out
        assert shell.calls == 1


def test_the_phone_cannot_invent_a_second_panel_press():
    with tempfile.TemporaryDirectory() as home:
        _rt, api = _api(home)
        shell = _Restarter()
        _panel_is(shell)
        try:
            assert api.dispatch("POST", "/api/panel", {},
                                {"action": "uninstall"})[0] == 404
        finally:
            _panel_is(None)
        assert shell.calls == 0


def test_the_restart_is_the_windows_and_the_phones_one_press():
    """The mirror, as a test rather than as a promise (CLAUDE.md).

    Both front-ends draw the SAME row out of `panel/runtime/panel_control.py`: the
    window builds its button from the table and asks the table's question, the page
    posts the id to `/api/panel` and asks the very same question first.
    """
    # THE WINDOW: built and pressed, not grepped (#1282, audit §4.4). The word on the
    # button and the route it takes are both runtime facts, so they are asserted as
    # runtime facts — a rename can no longer break the test, and dead code can no longer
    # pass it.
    harness = _shell_page()
    if harness is not None:
        try:
            app = harness.app
            control = panelctl.BY_ID[panelctl.RESTART]
            assert app._update_restart_btn.cget("text") == app._t(control.label), \
                "the window's restart button no longer takes its word from the table"
            asked, sent = [], []
            import panel.__main__ as pm

            saved_ask = pm.messagebox.askyesno
            saved_request = panelctl.request
            pm.messagebox.askyesno = lambda *a, **kw: asked.append(a) or True
            panelctl.request = lambda rt, action=panelctl.RESTART: sent.append(action)
            try:
                app._restart_panel()
            finally:
                pm.messagebox.askyesno = saved_ask
                panelctl.request = saved_request
            assert asked, "the window restarts without asking"
            assert sent == [panelctl.RESTART], \
                f"the window restarts by some other route than the table's ({sent})"
        finally:
            harness.close()

    # …and the one fact with no runtime form in a harness: the handler is registered in
    # `Panel.__init__`, which is the boot this harness deliberately skips (a splash, a
    # daemon per profile, a lock on the machine). Read as text, and only this one.
    shell = (_REPO / "panel" / "__main__.py").read_text(encoding="utf-8")
    assert "panelctl.set_handler" in shell, \
        "nothing registers the shell — a press from the phone reaches nobody"
    script = (_REPO / "panel" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "'/api/panel'" in script
    assert "control.confirm" in script and "window.confirm" in script, \
        "the phone would restart the panel on one stray tap"
    html = (_REPO / "panel" / "web" / "static" / "index.html").read_text(encoding="utf-8")
    # ON «Состояние», not on a screen of its own: the remote control's own settings have
    # none by decision, and this is where what they need on the move goes (CLAUDE.md).
    state_page = html.split('id="view-state"', 1)[1].split("</section>", 1)[0]
    assert 'id="panel-controls"' in state_page, \
        "the restart left the state screen — the remote control still has no page"


# ---------------------------------------------------------------------------
# «Прервать» — the phone's half of the footer's button (#1300)
# ---------------------------------------------------------------------------
def _playing(rt, name: str = "steal_secret_task", tag: str = "timer", step: str = ""):
    """Put a run on this runtime's register, as the runner does while one is playing."""
    ctx = types.SimpleNamespace(step=step, cancelled=False)
    flag = interruptmod.Stop()
    return rt.interrupts.enter(name, tag, ctx, flag)


def test_the_state_page_says_what_is_playing_and_where_it_has_got_to():
    """The phone has no log scrolling past, so the step has to be ON the card.

    «What am I about to throw away» is answerable before the press, not after it — which
    is the whole difference between this and a bare Stop button.
    """
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        assert api.state()["interrupt"]["running"] == [], "nothing is playing yet"
        _playing(rt, step="WAIT wounded == 0 (line 7)")
        info = api.state()["interrupt"]
        assert [r["name"] for r in info["running"]] == ["steal_secret_task"], info
        assert info["running"][0]["tag"] == "timer", "who started it reaches the phone"
        assert "WAIT wounded == 0" in info["running"][0]["step"], info
        assert info["stopping"] is False, "nobody has pressed anything"


def test_the_phone_presses_the_same_stop_the_footer_does():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        run = _playing(rt, step="WAIT 30 (line 3)")
        answer = api.interrupt()
        assert answer["ok"] is True, answer
        assert [r["name"] for r in answer["stopped"]] == ["steal_secret_task"], answer
        assert run.flag.is_set(), "the run was never asked to stop"
        # …and it is in the log, with the step, because a press whose only trace is a
        # toast on a phone is a press nobody can account for a week later.
        said = "\n".join(rt.log.drain())
        assert "interrupt.asked" in said, said
        # A second press does not pretend to be a fresh one.
        rt.log.drain()
        api.interrupt()
        assert "interrupt.again" in "\n".join(rt.log.drain())


def test_pressing_it_with_nothing_playing_is_an_answer_and_not_an_error():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        answer = api.interrupt()
        assert answer["ok"] is True and answer["stopped"] == [], answer
        assert "interrupt.idle" in "\n".join(rt.log.drain())


def test_the_card_counts_the_runs_of_the_other_profiles():
    """The press reaches every open profile, so the button has to be offered for them.

    A window holds several accounts and the run that has to stop is not reliably the one
    whose page the phone is showing — a count, not a name: another account's recipe named
    on this account's card would read as this account's.
    """
    with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as away:
        rt, _api_one = _api(home)
        other, _api_two = _api(away)
        api = apimod.WebApi(rt)
        api.sessions = lambda: [("home", rt), ("other", other)]
        assert api.state()["interrupt"]["elsewhere"] == 0
        _playing(other, name="join_rally")
        info = api.state()["interrupt"]
        assert info["running"] == [], "the other profile's run is not this one's"
        assert info["elsewhere"] == 1, info


def test_the_interrupt_is_the_windows_and_the_phones_one_press():
    """The mirror, as a test rather than as a promise (CLAUDE.md).

    The footer's button and the card's are one press over one register: the window's
    stops every open profile through `panel/runtime/interrupt.py`, and the page posts to
    a route that calls the very same thing.
    """
    harness = _shell_page()
    if harness is not None:
        try:
            app = harness.app
            assert app._interrupt_btn is not None, "the footer has no «Прервать»"
            assert app._interrupt_btn.cget("text") == app._t("interrupt.button"), \
                "the button no longer takes its word from the locale table"
            # Greyed with nothing playing, live the moment something is — the same
            # condition the phone's button uses.
            app._paint_interrupt()
            assert str(app._interrupt_btn.cget("state")) == "disabled"
            run = _playing(app._rt, step="WAIT 30 (line 3)")
            app._paint_interrupt()
            assert str(app._interrupt_btn.cget("state")) == "normal", \
                "the button stayed grey while a scenario was playing"
            app._interrupt()
            assert run.flag.is_set(), "the footer's press did not reach the run"
        finally:
            harness.close()
            # …and the shell is unregistered with the window, exactly as `_panel_is(None)`
            # does above: a handler pointing at a destroyed window would answer every
            # later press in this file for a workspace that no longer exists.
            interruptmod.set_handler(None)

    # …and the one fact with no runtime form in a harness: the handler is registered as
    # the strip is built, so a press from the phone reaches every open profile.
    shell = (_REPO / "panel" / "__main__.py").read_text(encoding="utf-8")
    assert "interruptmod.set_handler" in shell, \
        "nothing registers the shell — a press from the phone reaches one profile only"
    script = (_REPO / "panel" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "'/api/interrupt'" in script
    html = (_REPO / "panel" / "web" / "static" / "index.html").read_text(encoding="utf-8")
    state_page = html.split('id="view-state"', 1)[1].split("</section>", 1)[0]
    assert 'id="interrupt-controls"' in state_page, \
        "the press left «Состояние» — it is the phone's copy of the window's footer"


# ---------------------------------------------------------------------------
# the address the PANEL hands out — the other half of the same promise
# ---------------------------------------------------------------------------
#
# `WebServer.scheme` above is only half of it: the link a person taps is written beside
# the switch, and it used to spell `http://` into it whatever the server was doing. A
# TLS-only server reached over `http://` answers nothing a phone can explain, which is
# the exact failure the scheme exists to prevent.
#
# Since #1313 the switch is a menu entry rather than a tab and the knobs are the
# WINDOW's, so what is pinned here is `panel/runtime/web_control.py` — with no display
# and no settings file: `scheme` and `address` read the saved block and the bound
# socket, and a stand-in can be both.

def _link(server=None, cert: str = "", token: str = "tok", port: int = 9761) -> str:
    """`web_control.address()` over a made-up setting and a made-up socket."""
    values = dict(webctl.defaults(), token=token, cert=cert, port=str(port))
    saved = (webctl.settings, webctl.serving)
    webctl.settings, webctl.serving = (lambda: dict(values)), (lambda: server)
    try:
        return webctl.address()
    finally:
        webctl.settings, webctl.serving = saved


def test_the_link_the_panel_shows_is_plain_http_until_a_certificate_is_named():
    assert _link() == "http://%s:9761/?token=tok" % webmod.addresses()[0]


def test_the_link_follows_the_certificate_of_the_server_that_is_serving():
    """The certificate that decides the scheme belongs to the socket, not to the field.

    The socket that is bound is the one a phone will meet, so its certificate is what
    the link must agree with — including when the saved block names none.
    """
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        tls = webmod.WebServer(rt, port=9999, token="theirs", api=api,
                               certfile="cert.pem")
        link = _link(server=tls)
        assert link.startswith("https://"), link
        assert link.endswith(":9999/?token=theirs"), link
        # …and the other way round: a certificate named in the setting does not make a
        # plain-HTTP socket into a TLS one.
        plain = webmod.WebServer(rt, port=9999, token="theirs", api=api)
        assert _link(server=plain, cert="cert.pem").startswith("http://")


def test_with_nothing_bound_the_panel_answers_from_the_saved_setting():
    """Before the switch goes on there is no socket to ask, and the block is all there is."""
    assert _link(cert="cert.pem").startswith("https://")


# ---------------------------------------------------------------------------
# from outside the house
# ---------------------------------------------------------------------------
#
# A forwarded port is how this is reached from outside, and the filter on the router is
# who may. What is pinned here is the half that is ours: a token cannot be guessed at
# leisure, a sign-in from a new address is said out loud, and a browser does not stay
# signed in for ever.

def test_wrong_tokens_lock_an_address_out():
    """Six wrong guesses and that address waits. Behind a forwarded port that is not
    optional: the guessing may then be done from anywhere, at any rate, all night."""
    attempts = webmod.Attempts(limit=3, lockout=60.0)
    peer = "203.0.113.7"
    assert attempts.locked(peer) == 0
    for _ in range(3):
        attempts.failed(peer)
    assert attempts.locked(peer) > 0, "three wrong tokens and it is still trying"
    # Another address is unaffected — one guesser must not shut the owner out.
    assert attempts.locked("198.51.100.4") == 0
    # …and the lockout ends by itself.
    assert webmod.Attempts(limit=3, lockout=0.0).failed(peer) == 1


def test_a_right_token_clears_the_count():
    attempts = webmod.Attempts(limit=3, lockout=60.0)
    attempts.failed("203.0.113.7")
    attempts.failed("203.0.113.7")
    attempts.passed("203.0.113.7")
    assert attempts.locked("203.0.113.7") == 0
    assert attempts.failed("203.0.113.7") == 1, "the old failures were remembered"


def test_a_stranger_is_shut_out_over_the_wire_and_told_when_to_come_back():
    with tempfile.TemporaryDirectory() as home, _Served(home) as served:
        served.server.attempts = webmod.Attempts(limit=2, lockout=30.0)
        for _ in range(2):
            status, _body, _h = served.ask("/api/state", token="wrong")
            assert status == 401
        status, body, headers = served.ask("/api/state", token="wrong")
        assert status == 429, "a guesser was allowed to keep guessing"
        assert headers.get("Retry-After"), headers
        assert json.loads(body)["error"] == "too_many"


def test_a_visitor_is_counted_by_the_address_they_came_from():
    """A forwarded port keeps the source address, so the socket IS the visitor.

    No header is read and none may be: a router rewrites the destination, not the
    source, and there is nothing in front of this server that could legitimately
    rename anybody.
    """
    with tempfile.TemporaryDirectory() as home, _Served(home) as served:
        served.server.attempts = webmod.Attempts(limit=2, lockout=30.0)
        request = urllib.request.Request(served.base + "/api/state")
        request.add_header("X-Panel-Token", "wrong")
        # A header claiming to be somebody else must change nothing at all.
        request.add_header("X-Forwarded-For", "198.51.100.1")
        request.add_header("CF-Connecting-IP", "203.0.113.9")
        for _ in range(2):
            try:
                urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError:
                pass
        assert served.server.attempts.locked("127.0.0.1") > 0, (
            "the caller was not counted by its own address")
        for invented in ("198.51.100.1", "203.0.113.9"):
            assert served.server.attempts.locked(invented) == 0, (
                f"a header renamed the visitor to {invented}")


def test_the_cookie_is_bounded_and_secure_only_behind_https():
    """`Secure` only when the connection really is TLS — a certificate, or a proxy
    saying `X-Forwarded-Proto`. A phone at home arrives in clear and must not get it."""
    with tempfile.TemporaryDirectory() as home, _Served(home) as served:
        _status, _body, headers = served.ask("/api/login", data={"token": "s3cret"})
        cookie = headers.get("Set-Cookie", "")
        assert f"Max-Age={webmod.COOKIE_MAX_AGE_SEC}" in cookie, cookie
        assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
        # Plain HTTP on the home network must NOT get `Secure`, or the phone could
        # never sign in at all.
        assert "Secure" not in cookie, cookie


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
# the tabs' own screens
# ---------------------------------------------------------------------------
class _Screen:
    """A tab with a phone screen, as far as the API is concerned."""

    ID = "demo"
    TITLE_KEY = "tab.demo"
    WEB_SCREEN = True

    def __init__(self) -> None:
        self.pressed: list = []

    def web_view(self) -> dict:
        return {"cards": [{"title": "tab.demo",
                           "rows": [{"label": "profile.nick", "value": "Somebody"}]}],
                "actions": [{"id": "refresh", "label": "tabx.refresh"}]}

    def web_press(self, action, args) -> dict:
        self.pressed.append((action, args))
        return {"ok": True}


def test_only_the_tabs_this_profile_built_offer_a_screen():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        assert api.screens()["screens"] == [], "a profile with no tabs offered one"
        screen = _Screen()
        rt.tabs.live = [screen]
        rt.tabs.get = lambda tab_id: screen if tab_id == "demo" else None
        assert api.screens()["screens"] == [{"id": "demo", "title": "tab.demo"}]


def _stand_ins(specs) -> list:
    """One stand-in per spec, as the shell would have built them — id, title, screen."""
    return [type("_T", (), {"ID": spec.id, "TITLE_KEY": spec.title_key,
                            "WEB_SCREEN": spec.load().WEB_SCREEN})()
            for spec in specs]


def test_a_tab_still_being_written_hands_the_phone_no_screen():
    """The phone shows what this profile BUILT, so the development gate reaches it too.

    Not a second rule — the same one (#1273). `screens()` walks the tabs the window has,
    and a tab hidden by the gate was never built, so there is nothing to offer. Pinned
    here because the guarantee is a consequence rather than a line of code: somebody
    listing the registry instead of `rt.tabs.live` would put a half-written tab on a
    phone with nothing failing.
    """
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        wip = {s.id for s in tabsreg.TABS if s.in_development}
        assert wip, "nothing is marked as still being written"

        rt.tabs.live = _stand_ins(tabsreg.resolve())
        offered = {s["id"] for s in api.screens()["screens"]}
        assert offered, "no screens at all — the stand-ins are wrong, not the gate"
        assert not offered & wip, sorted(offered & wip)

        # …and with «Разработка» on, the marked ones that have a screen are offered
        # exactly like any other tab.
        every = [s.id for s in tabsreg.TABS]
        rt.tabs.live = _stand_ins(tabsreg.resolve(enabled=every, known=every))
        assert {s["id"] for s in api.screens()["screens"]} & wip


class _TkThread:
    """One thread draining posted work — the whole of the window the press path needs.

    `panel/web/api.py` hands a press over with `rt.tick.post` and never makes a Tk call
    itself (panel/runtime/tick.py), so this is a faithful stand-in AND, unlike a real
    root, it can be held busy on purpose. Which is the whole of #1331: a press that the
    event loop is slow to get to must not be reported as a press the panel does not have.
    """

    def __init__(self) -> None:
        import queue

        self.q: "queue.Queue" = queue.Queue()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()

    def post(self, func) -> None:
        self.q.put(func)

    def stop(self) -> None:
        self.stopped.set()
        self.thread.join(2.0)

    def _pump(self) -> None:
        import queue

        while not self.stopped.is_set():
            try:
                func = self.q.get(timeout=0.02)
            except queue.Empty:
                continue
            try:
                func()
            except Exception:                        # noqa: BLE001 — as Tk would
                pass


def _off_thread(call, timeout: float = 10.0):
    """Run `call` on a worker and hand back what it returned.

    Everything in `panel/web/api.py` is reached from an HTTP worker, and the press path
    short-circuits on the main thread — so a test that calls it directly would exercise
    the branch that never happens live.
    """
    box: dict = {}
    done = threading.Event()

    def go() -> None:
        try:
            box["out"] = call()
        except Exception as exc:                     # noqa: BLE001
            box["raised"] = exc
        finally:
            done.set()

    threading.Thread(target=go, daemon=True).start()
    assert done.wait(timeout), "the call never came back"
    if "raised" in box:
        raise box["raised"]
    return box["out"]


class _SlowScreen(_Screen):
    """A tab whose press takes longer than the phone's budget for an answer."""

    def __init__(self, hold: float) -> None:
        super().__init__()
        self.hold = hold
        self.started = threading.Event()
        self.finished = threading.Event()

    def web_press(self, action, args) -> dict:
        self.started.set()
        time.sleep(self.hold)
        self.pressed.append((action, args))
        self.finished.set()
        return {"ok": True}


def test_a_press_the_window_is_slow_to_run_is_accepted_and_never_unknown():
    """#1331 — the lie that made people press twice.

    The press was run on the Tk thread and waited 1.5 s for it; anything slower fell out
    of the wait with an empty box and was answered `{"error": "unknown"}`, which is a 404
    and reads on the phone as «панель не знает такого нажатия». Measured live at 6–28 s
    per press, because `play_async` took the daemon's lease on the calling thread. The
    scenario then ran perfectly well — so the person was told their press had failed
    about a press that was working, and pressed it again.

    Nothing about the wait is the fix's point: a press may legitimately be slow. What it
    must never do is come back as an unknown action.
    """
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        tk_thread = _TkThread()
        rt.root = object()                 # there IS a window, so the press is handed over
        rt.tick = tk_thread
        # Longer than the READ budget (`TK_TIMEOUT_SEC`, 1.5 s) on purpose: that is the
        # wait the old press inherited, and anything past it came back as a 404.
        screen = _SlowScreen(hold=2.0)
        rt.tabs.live = [screen]
        rt.tabs.get = lambda tab_id: screen if tab_id == "demo" else None
        was = apimod.PRESS_TIMEOUT_SEC
        apimod.PRESS_TIMEOUT_SEC = 0.2
        try:
            answer = _off_thread(lambda: api.press("demo", "refresh", {}))
            assert answer.get("pending") is True, answer
            assert answer.get("ok") is True, answer
            assert "error" not in answer, answer
            # …and the ROUTE agrees: this is a 200, not the 404 an unknown press is.
            status, payload = _off_thread(
                lambda: api.dispatch("POST", "/api/screen/press",
                                     {}, {"id": "demo", "action": "refresh"}))
            assert status == 200, (status, payload)
            # The press was not cancelled by the answer — it was accepted, and it ran.
            assert screen.finished.wait(5.0), "the press was dropped, not deferred"
        finally:
            apimod.PRESS_TIMEOUT_SEC = was
            tk_thread.stop()


def test_the_three_answers_a_press_can_have_stay_three():
    """Done, refused-with-a-reason, and «there is no such press» — never merged (#1331).

    The last of them is the only 404. A tab that could not carry a press out says so
    with `ok: False` and its own words; a phone that is told `unknown` about that would
    be told the panel has no such button, which is a different fault with a different
    cure.
    """
    class _Choosy(_Screen):
        def web_press(self, action, args) -> dict:
            if action == "refresh":
                return {"ok": True}
            if action == "run":
                return {"ok": False, "reason": "web.ui.refused"}
            return {"error": "unknown"}

    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        screen = _Choosy()
        rt.tabs.live = [screen]
        rt.tabs.get = lambda tab_id: screen if tab_id == "demo" else None

        def route(action):
            return api.dispatch("POST", "/api/screen/press", {},
                                {"id": "demo", "action": action})

        assert route("refresh") == (200, {"ok": True})
        status, payload = route("run")
        assert status == 200 and payload["ok"] is False and payload["reason"], payload
        status, payload = route("nonsense")
        assert status == 404 and payload["error"] == "unknown", (status, payload)
        # …and a screen this profile does not have is the same 404, carrying what was
        # asked for, so a phone that is a version behind says which screen it meant.
        status, payload = api.dispatch("POST", "/api/screen/press", {},
                                       {"id": "nope", "action": "refresh"})
        assert status == 404 and payload.get("detail") == "nope", payload


def test_the_thread_that_pressed_never_waits_for_the_daemons_lease():
    """The other half of #1331, and the half that was making the presses slow.

    `play_async` took the WHOLE claim on the calling thread, and its third lock is the
    daemon's lease — another process, over a socket, measured at 6–28 s while that daemon
    was busy. Since every press is handed to the Tk thread, one press froze the event
    loop of every open profile for that long and then answered «unknown».

    So the claim comes in two halves: `reserve` here (two dictionaries under two locks)
    and `lease` on the worker. Pinned against the REAL `play_async`, with a lease that
    takes a second — the press must be accepted long before it returns, and the scenario
    must still run under it.
    """
    try:
        import tkinter as tk

        sys.path.insert(0, str(_REPO / "tests"))
        import fake_runtime

        root = tk.Tk()
        root.withdraw()
        rt = fake_runtime.cold_runtime(root)
    except Exception as exc:                         # noqa: BLE001 — headless
        print(f"    (skipped: {type(exc).__name__}: {exc})")
        return
    try:
        asked = threading.Event()
        played: list = []

        def lease(owner="panel") -> bool:
            asked.set()
            time.sleep(1.0)                          # a daemon with its hands full
            return True

        rt.game.reserve = lambda owner="panel", priority=0: True
        rt.game.lease = lease
        rt.game.release = lambda: None
        rt.game.on_settled = lambda: None
        rt.actions.run = lambda name, args=None, **kw: played.append(name) or True

        at = time.monotonic()
        assert rt.play_async("collect_base_resources", tag="web") is True
        took = time.monotonic() - at
        assert took < 0.3, f"the press waited {took:.2f}s for the lease"
        assert asked.wait(3.0), "nothing ever took the lease — the run was dropped"
        for _ in range(60):
            if played:
                break
            time.sleep(0.05)
        assert played == ["collect_base_resources"], played
    finally:
        root.destroy()


def test_the_page_has_a_word_for_each_of_the_three():
    """The phone must be able to SAY them — one toast per answer, all of them keys."""
    js = (Path(apimod.static_dir()) / "app.js").read_text(encoding="utf-8")
    assert "function pressWord(" in js, "the page has no way to name a press's outcome"
    english = i18nmod.load_locale("en")
    for key in ("web.ui.accepted", "web.ui.unknown", "web.ui.refused.why",
                "web.ui.done", "web.ui.refused"):
        assert f"T('{key}'" in js, f"{key} is in the locales and nothing says it"
        assert key in english, key
    # …and no press site left drawing an answer by hand, which is how the three merged.
    assert "answer.ok ? T('web.ui.done')" not in js, (
        "a press is still drawn as done-or-refused — «принято, идёт» has nowhere to go")


def test_a_screen_is_handed_over_as_data_and_a_press_reaches_the_tab():
    with tempfile.TemporaryDirectory() as home:
        rt, api = _api(home)
        screen = _Screen()
        rt.tabs.live = [screen]
        rt.tabs.get = lambda tab_id: screen if tab_id == "demo" else None
        view = api.screen("demo")
        assert view["id"] == "demo" and view["title"] == "tab.demo"
        assert view["cards"][0]["rows"][0]["value"] == "Somebody"
        assert api.press("demo", "refresh", {})["ok"] is True
        assert screen.pressed == [("refresh", {})]
        # …and a screen this profile does not have is a 404, not an empty page.
        assert api.screen("nope") == {"error": "unknown"}
        status, _payload = api.dispatch("GET", "/api/screen", {"id": "nope"}, {})
        assert status == 404


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


def test_no_field_is_small_enough_to_make_ios_zoom():
    """Under 16 px in a focused field and Safari zooms the page; the person pinches back.

    Every field, not only `<input>`: the account selector is a `<select>` and focusing
    one zooms exactly the same way.
    """
    css = _css()
    for what in ("input", "select", "textarea", r"\.picker"):
        for rule in re.findall(what + r"[^{]*\{[^}]*\}", css):
            for size in re.findall(r"font-size:\s*(\d+)px", rule):
                assert int(size) >= 16, f"a field is set to {size}px:\n{rule}"


def test_the_page_carries_a_switcher_when_there_is_more_than_one_account():
    """The header is a name with one profile open and a picker with two.

    A NATIVE `<select>`: on a phone that is the operating system's own picker, already
    thumb-sized and already in the right language, which no custom dropdown here would
    be.
    """
    html = (Path(apimod.static_dir()) / "index.html").read_text(encoding="utf-8")
    assert '<select id="profile-pick"' in html, "there is no account selector"
    js = (Path(apimod.static_dir()) / "app.js").read_text(encoding="utf-8")
    assert "/api/profiles" in js, "the page never asks which accounts are open"
    # …and every request carries the account, or the page would be showing one profile
    # while implying the other — the failure this whole feature exists to prevent.
    assert "function withProfile(" in js and "profile=" in js
    assert "{ profile: PROFILE }" in js, "a POST does not say which account it is for"


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
    """«ближайший: donate_alliance_tech» is the file's key, not what anybody calls it."""
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
    # …and the same for «сразу» (#1288), which travels the identical two branches.
    assert callable(getattr(TimersTab, "set_immediate", None)), (
        "TimersTab.set_immediate is gone — the phone's «сразу» box now writes a file "
        "the tab's boxes will overwrite")


def test_the_remote_control_belongs_to_the_window_and_not_to_a_profile():
    """It is a menu entry and a panel-wide block, and there is no tab left (#1313).

    One server answers for every open profile, so one copy of the port, the token and
    the certificate is the whole point: a `web` tab would be a page inside one account
    holding a setting that belongs to the machine, which is what this replaced.
    """
    from panel import tabs as tabsreg

    assert "web" not in tabsreg.BY_ID, (
        "the «Веб» tab is back in the registry — the remote control's knobs are the "
        "window's, and a per-profile page for them is the mistake #1313 undid")
    shell = (_REPO / "panel" / "__main__.py").read_text(encoding="utf-8")
    assert 'label=self._t("menu.web")' in shell, "no «Веб» entry in the menu bar"
    assert "webctl.apply(" in shell, (
        "nothing starts the remote control at boot — it exists to be reachable "
        "without anybody opening its dialog")


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

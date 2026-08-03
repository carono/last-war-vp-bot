"""What the phone may ask the panel, as JSON — and nothing the panel cannot already do.

The web front-end is the same kind of thing every tab is: it SHOWS what the runtime
holds and PRESSES what the runtime already presses. It runs no scenario of its own, it
assembles no Lua, it holds no gate — `CLAUDE.md` is binding on that, and the shape of
this file is what keeps it honest. Every route below is one call onto a
:class:`~panel.runtime.host.PanelRuntime`:

    /api/profiles   which accounts this window has open      rt.workspace
    /api/state      what one profile is doing right now      rt.game, rt.activity
    /api/timers     the errands, their switches, when next   rt.schedule
    /api/actions    the scenarios that exist                 rt.actions
    /api/log        what has been said                       rt.log (tapped)
    /api/i18n       the words to say it in                   panel/locales

ONE SERVER, EVERY PROFILE. A window may hold two accounts open at once (#1206) and it
is the ordinary way this bot is run, so the front-end that shows one of them and does
not say which is worse than no front-end at all — that exact confusion cost a live
session once, when one profile was reading the other's client and looked perfectly
healthy doing it. So every route takes `?profile=<name>`, `/api/profiles` lists what
there is, and anything not named falls back to the session the server was started from.
A runtime with no workspace behind it — a tab launched on its own, a test — answers for
itself and lists exactly one profile, which is the same code path with one session in it.

WHICH THREAD. Everything here is called from an HTTP worker thread, and two things in
the panel may not be touched from one: a Tk variable and a widget. So a knob is read by
handing the read to the Tk thread (falling back to the profile's file when nobody is
pumping), a timer's switch is moved through the Timers tab on the Tk thread when that
tab is in this window, and the process scan — which takes long enough to be felt — is
done HERE and cached per profile, never on the thread that draws.

NOTHING IS TRANSLATED INTO THE PAGE. `/api/i18n` hands over the whole locale table and
the browser says the words, exactly as a tab does: the panel's language is the phone's
language, and a key added to `panel/locales/` reaches both without a line of JavaScript
changing. The exceptions are the strings that are already sentences by the time this
sees them — a log line, a scenario's own failure reason, the client-status label the
process probe builds — and those are translated here because the key is gone by then.
"""
from __future__ import annotations

import collections
import os
import threading
import time

from .. import i18n as i18nmod
from .. import timers as timersmod
from ..runtime import game_process
from ..runtime.actions import list_actions
from ..runtime.log import severity_of, strip_ansi, tag_of

#: How long one answer of the process probe is reused. The scan walks every process on
#: the machine, which is tens of milliseconds of cold psutil and has already cost this
#: panel a visibly frozen window once (#1211); a phone polling every two seconds must
#: not repeat it, and with two profiles open it would otherwise do it twice. Well under
#: the time anything it reports actually changes.
STATUS_TTL_SEC = 5.0

#: How many log lines are held PER PROFILE for a phone that connects late. The window
#: keeps four thousand; this is a phone screen and a poll every couple of seconds.
TAIL_LINES = 400

#: How long to wait for the Tk thread when reading a knob off its widget. Short: the
#: file is a perfectly good answer, and a page that hangs is worse than one that is a
#: keystroke behind.
TK_TIMEOUT_SEC = 1.5


class _Feed:
    """One profile's log: a ring of numbered lines, and the tap filling it.

    A ring per profile rather than one shared: two accounts write into two different
    `LogBus`es (each session has its own), and a phone looking at one account must not
    be shown the other's lines with no way to tell them apart.
    """

    def __init__(self, rt, tail: int) -> None:
        self.rt = rt
        self.lock = threading.Lock()
        self.lines: collections.deque = collections.deque(maxlen=tail)
        self.seq = 0
        self.untap = None

    def attach(self) -> None:
        if self.untap is not None:
            return
        self._seed()
        self.untap = self.rt.log.tap(self.take)

    def detach(self) -> None:
        untap, self.untap = self.untap, None
        if untap is not None:
            untap()

    def take(self, line: str) -> None:
        """One line, on whoever's thread produced it. Cheap on purpose."""
        with self.lock:
            self.seq += 1
            self.lines.append((self.seq, strip_ansi(line)))

    def _seed(self) -> None:
        """Start from the tail of the profile's `panel.log`.

        A phone that connects after an hour of farming sees the hour, not a blank screen:
        the file is the record, the queue is only what has not been drawn yet.
        """
        try:
            with open(self.rt.profiles.panel_log(), encoding="utf-8",
                      errors="replace") as fh:
                tail = collections.deque(fh, maxlen=self.lines.maxlen)
        except OSError:
            return
        with self.lock:
            for raw in tail:
                self.seq += 1
                self.lines.append((self.seq, strip_ansi(raw.rstrip("\n"))))


class WebApi:
    """The JSON surface of one WINDOW — every profile it has open."""

    def __init__(self, rt, *, tail: int = TAIL_LINES) -> None:
        #: The session the server was started from: the default answer, and the only one
        #: when there is no workspace behind it.
        self.rt = rt
        self._tail = tail
        self._feeds: dict = {}               # profile name -> _Feed
        self._status: dict = {}              # profile name -> (read at, running, label)
        self._attached = False

    # -- which profiles there are -------------------------------------------
    def sessions(self) -> list:
        """``[(name, runtime)]`` for every open profile, the current one first.

        The workspace when there is one, this runtime alone when there is not — the two
        are the same shape on purpose, so nothing below has to ask which mode it is in.
        """
        workspace = getattr(self.rt, "workspace", None)
        if workspace is None:
            return [(self.rt.profiles.active, self.rt)]
        out = []
        for session in workspace.sessions:
            out.append((session.name, session.rt))
        return out or [(self.rt.profiles.active, self.rt)]

    def profiles(self) -> dict:
        """What the switcher at the top of the page is built from."""
        workspace = getattr(self.rt, "workspace", None)
        current = getattr(getattr(workspace, "current", None), "name", None)
        names = [name for name, _rt in self.sessions()]
        return {"profiles": names,
                "home": self.rt.profiles.active,
                # Which one the WINDOW is looking at. Shown so a person driving both can
                # see, from the phone, which account is on screen at the machine.
                "showing": current or self.rt.profiles.active}

    def _runtime(self, profile: str | None):
        """The runtime for ``profile`` — or the server's own when it names nothing.

        An unknown name falls back rather than 404s: a phone that has the second profile
        selected when that profile is closed at the machine should go on working, showing
        the one that is left, not go blank until somebody clears its address bar.
        """
        if profile:
            for name, rt in self.sessions():
                if name == profile:
                    return rt
        return self.rt

    def _feed(self, name: str, rt) -> _Feed:
        feed = self._feeds.get(name)
        if feed is None or feed.rt is not rt:
            if feed is not None:
                feed.detach()
            feed = _Feed(rt, self._tail)
            self._feeds[name] = feed
        if self._attached:
            feed.attach()                    # a profile opened after the server started
        return feed

    # -- the log ------------------------------------------------------------
    def attach(self) -> None:
        """Start collecting log lines, from every profile open now. Idempotent.

        A profile opened LATER is picked up on the first request that mentions it
        (:meth:`_feed`) — the workspace has no event to subscribe to, and a poll every
        couple of seconds is a perfectly good moment to notice.
        """
        self._attached = True
        for name, rt in self.sessions():
            self._feed(name, rt).attach()

    def detach(self) -> None:
        self._attached = False
        for feed in list(self._feeds.values()):
            feed.detach()
        self._feeds.clear()

    def _sync_feeds(self) -> None:
        """Tap every profile that is open now, and let go of the ones that are not.

        Called on every log poll — which is every couple of seconds — so a profile
        opened at the machine is being collected within one tick rather than from the
        first request that happens to name it. Without it the lines said in between
        would only survive because `panel.log` is re-read on seeding, and «only
        because of the file» is not a thing to lean on.
        """
        if not self._attached:
            return
        live = {}
        for name, rt in self.sessions():
            live[name] = rt
            self._feed(name, rt).attach()
        for name in [n for n in self._feeds if n not in live]:
            self._feeds.pop(name).detach()

    def log(self, since: int = 0, profile: str | None = None) -> dict:
        """The lines newer than ``since``, with the number to ask for next time.

        A caller that has fallen behind the ring (a phone in a pocket for an hour) is
        told so rather than silently handed a gap: ``reset`` means "what you had is no
        longer the beginning of this". The numbering is PER PROFILE, so switching the
        selector at the top of the page starts that profile's own sequence.
        """
        self._sync_feeds()
        rt = self._runtime(profile)
        feed = self._feed(self._name_of(rt), rt)
        with feed.lock:
            held = list(feed.lines)
            newest = feed.seq
        oldest = held[0][0] if held else newest + 1
        reset = bool(since) and since < oldest - 1
        rows = [self._line(n, text) for n, text in held if n > since or reset]
        return {"lines": rows, "next": newest, "reset": reset}

    @staticmethod
    def _line(number: int, text: str) -> dict:
        return {"n": number, "text": text, "tag": tag_of(text),
                "sev": severity_of(text)}

    # -- what the profile is doing ------------------------------------------
    def state(self, profile: str | None = None) -> dict:
        """One reading of everything the front page shows, for one profile."""
        rt = self._runtime(profile)
        name = self._name_of(rt)
        running, label = self._client_status(name, rt)
        step = rt.activity.current()
        return {
            "profile": name,
            "lang": rt.i18n.lang,
            "game": {"running": running, "text": label},
            # `busy` is a PROPERTY on the real link (panel/runtime/daemon.py) and a
            # method on none of them — read it, never call it.
            "daemon": {"up": rt.game.up(), "port": self._port(rt),
                       "busy": bool(rt.game.busy)},
            # `name` is passed through raw beside the sentence: the page marks the
            # scenario card that is running with it, and matching on the translated
            # sentence would be matching on a language.
            "activity": ({"key": step.key,
                          "name": str(step.fmt.get("name") or ""),
                          "text": rt.t(step.key, **step.fmt)}
                         if step is not None else None),
            "timers": self._due(rt),
            "time": time.time(),
        }

    def _name_of(self, rt) -> str:
        return str(rt.profiles.active)

    def _client_status(self, name: str, rt) -> tuple:
        """Is this profile's client up — cached per profile for :data:`STATUS_TTL_SEC`."""
        when, running, label = self._status.get(name, (0.0, False, ""))
        now = time.time()
        if now - when < STATUS_TTL_SEC:
            return running, label
        exe, user = self._client_args(rt)
        try:
            running, message = game_process.status(exe, user=user)
        except Exception as exc:             # noqa: BLE001 — a reading, never the server
            running, message = False, str(exc)
        label = i18nmod.translated(rt.t, message)
        self._status[name] = (now, bool(running), label)
        return bool(running), label

    def _due(self, rt) -> dict:
        """How many errands are switched on, and when the next one is due."""
        try:
            schedule = rt.schedule
            config = schedule.timer_config()
            records = schedule.store.records()
            catalogue = schedule.timer_catalogue
        except Exception:                    # noqa: BLE001 — a summary, never the server
            return {"on": 0, "next": None, "next_name": ""}
        on, soonest, whose = 0, None, ""
        for timer in catalogue:
            if not (config.get(timer.name) or {}).get("enabled"):
                continue
            on += 1
            when = catalogue.next_due(timer, config, records)
            if when is None:
                continue
            if soonest is None or when < soonest:
                # The TITLE, not the id: what the front page said until now was
                # «ближайший: alliance_upkeep», which is the key the file is keyed by
                # and not a thing anybody calls it (the tab has never shown it either).
                soonest, whose = when, self._timer_title(rt, timer)
        # `running` is a property on the scheduler, like `busy` on the game link.
        return {"on": on, "next": soonest, "next_name": whose,
                "running": bool(getattr(schedule.timers, "running", False))}

    # -- the errands ---------------------------------------------------------
    def timers(self, profile: str | None = None) -> dict:
        """Every configured errand: its switch, its period, and how it last ended."""
        rt = self._runtime(profile)
        schedule = rt.schedule
        config = schedule.timer_config()
        records = schedule.store.records()
        catalogue = schedule.timer_catalogue
        pending = set(schedule.timers.pending())
        rows = []
        for timer in catalogue:
            item = config.get(timer.name) or {}
            state, when = timersmod.last_attempt(records, timer.name)
            rows.append({
                "name": timer.name,
                "title": self._timer_title(rt, timer),
                "enabled": bool(item.get("enabled")),
                "interval_sec": int(item.get("interval_sec") or timer.interval_sec),
                "next": catalogue.next_due(timer, config, records),
                "last": when or None,
                "last_state": state,
                "queued": timer.name in pending,
                "steps": list(timer.scenario),
            })
        return {"timers": rows, "profile": self._name_of(rt),
                "running": bool(getattr(schedule.timers, "running", False)),
                "time": time.time()}

    def _timer_title(self, rt, timer) -> str:
        """What the row is called — the operator's own words, or the built-in key."""
        if timer.title:
            return timer.title
        if timer.label_key:
            return rt.t(timer.label_key)
        return timer.name

    def set_timer(self, name: str, enabled: bool,
                  profile: str | None = None) -> dict:
        """Tick or untick one errand — through the Timers tab when that profile has one.

        THE TAB'S BOXES WIN. `Schedule.timer_config` reads the widgets whenever they
        exist (panel/tabs/timers.py), so writing the file behind a live tab's back would
        be undone on the next tick and look, from the phone, like a switch that does not
        stay. With no such tab in this profile the file IS the configuration, and that
        is the branch below.
        """
        rt = self._runtime(profile)
        timer = rt.schedule.timer_catalogue.by_name(name)
        if timer is None:
            return {"error": "unknown"}
        tab = rt.tabs.get("timers")
        if tab is not None and hasattr(tab, "set_enabled"):
            done: dict = {}
            self._on_tk(rt, lambda: done.update(ok=bool(tab.set_enabled(name, enabled))))
            if done.get("ok"):
                return {"ok": True, "name": name, "enabled": bool(enabled)}
        schedule = rt.schedule
        config = dict(schedule.timer_config())
        item = dict(config.get(name) or {})
        item["enabled"] = bool(enabled)
        config[name] = item
        schedule.timer_catalogue = schedule.timer_catalogue.with_settings(config)
        timersmod.save_catalogue(schedule.timer_catalogue, rt.profiles.timers_json())
        return {"ok": True, "name": name, "enabled": bool(enabled)}

    def run_timer(self, name: str, profile: str | None = None) -> dict:
        """«Запустить сейчас» — onto the schedule's own queue, never a thread of its own.

        The same call the row's button makes, for the same reason: every errand runs
        single-file on the one worker, so a press from the phone while something else is
        running waits its turn instead of driving the game beside it.
        """
        rt = self._runtime(profile)
        timer = rt.schedule.timer_catalogue.by_name(name)
        if timer is None:
            return {"error": "unknown"}
        queued = bool(rt.schedule.timers.request(timer))
        return {"ok": queued, "queued": queued, "name": name}

    # -- the scenarios -------------------------------------------------------
    def actions(self, profile: str | None = None) -> dict:
        """Every scenario the panel can play, titled in the panel's language.

        The LIST is the same for every profile — scenarios belong to the bot, not to an
        account — but the titles follow the language of the profile being asked about.
        """
        rt = self._runtime(profile)
        return {"actions": list_actions(lang=rt.i18n.lang)}

    def run_action(self, name: str, profile: str | None = None) -> dict:
        """Play one scenario under that profile's game claim — `rt.play_async`, no more.

        ``busy`` is not a failure: it means something else is driving this client right
        now, which is the one answer a remote press must never override. And it is per
        profile, which is the point of naming one — a press meant for the second account
        must not land on the first one's client.
        """
        rt = self._runtime(profile)
        if rt.actions.resolve(name) is None:
            return {"error": "unknown"}
        started = rt.play_async(name, tag="web")
        return {"ok": bool(started), "busy": not started, "name": name}

    # -- the tabs' own screens ------------------------------------------------
    def screens(self, profile: str | None = None) -> dict:
        """Which of this profile's tabs offer a phone screen, in the window's order.

        A tab switched off in the profile is not built, so it is not here either —
        the phone shows what this profile HAS, exactly as the window does.
        """
        rt = self._runtime(profile)
        out = []
        for tab in rt.tabs.live:
            if not getattr(type(tab), "WEB_SCREEN", False):
                continue
            out.append({"id": tab.ID, "title": type(tab).TITLE_KEY})
        return {"screens": out}

    def screen(self, screen_id: str, profile: str | None = None) -> dict:
        """One tab's screen as data — built ON THE TK THREAD, where its widgets live.

        `web_view` is contracted to be cheap and to read no game (panel/tabs/base.py),
        so this costs a hop and a dictionary. What it must NOT do is read the client:
        a phone left on a screen would then poll the game for as long as it is awake.
        """
        rt = self._runtime(profile)
        tab = rt.tabs.get(screen_id)
        if tab is None or not getattr(type(tab), "WEB_SCREEN", False):
            return {"error": "unknown"}
        box: dict = {}

        def build() -> None:
            try:
                box["view"] = tab.web_view()
            except Exception as exc:     # noqa: BLE001 — one screen, never the panel
                box["error"] = str(exc)

        self._on_tk(rt, build)
        view = box.get("view")
        if view is None:
            return {"error": "empty", "detail": box.get("error", "")}
        view["id"] = screen_id
        view["title"] = view.get("title") or type(tab).TITLE_KEY
        return view

    def press(self, screen_id: str, action: str, args: dict,
              profile: str | None = None) -> dict:
        """One press on a tab's screen, on the Tk thread — the tab's own handler."""
        rt = self._runtime(profile)
        tab = rt.tabs.get(screen_id)
        if tab is None or not getattr(type(tab), "WEB_SCREEN", False):
            return {"error": "unknown"}
        box: dict = {}

        def go() -> None:
            try:
                box["result"] = tab.web_press(action, args or {})
            except Exception as exc:     # noqa: BLE001
                box["result"] = {"error": "failed", "detail": str(exc)}

        self._on_tk(rt, go)
        return box.get("result") or {"error": "unknown"}

    # -- the words -----------------------------------------------------------
    def words(self, profile: str | None = None) -> dict:
        """The whole locale table the page draws itself with.

        English underneath whatever the panel is set to, which is the same fallback
        `Translator.t` applies — so a locale that is behind shows English for the keys
        it lacks and its own words for the rest, on the phone exactly as in the window.
        """
        rt = self._runtime(profile)
        lang = rt.i18n.lang
        table = dict(i18nmod.load_locale(i18nmod.DEFAULT_LANG))
        if lang != i18nmod.DEFAULT_LANG:
            table.update(i18nmod.load_locale(lang))
        return {"lang": lang, "words": table}

    # -- routing -------------------------------------------------------------
    def dispatch(self, method: str, path: str, query: dict, body: dict) -> tuple:
        """``(status, payload)`` for one request. The server does the HTTP, this the panel.

        Split out from the handler so the whole surface can be exercised without a
        socket — tests/test_panel_web.py drives this directly and the live server only
        has to prove that a request reaches it.

        WHICH PROFILE travels the way each verb already carries things: a query parameter
        on a GET, a field on a POST body. Absent means the session the server belongs to.
        """
        if method == "GET":
            who = str(query.get("profile") or "") or None
            if path == "/api/profiles":
                return 200, self.profiles()
            if path == "/api/state":
                return 200, self.state(who)
            if path == "/api/timers":
                return 200, self.timers(who)
            if path == "/api/actions":
                return 200, self.actions(who)
            if path == "/api/i18n":
                return 200, self.words(who)
            if path == "/api/log":
                return 200, self.log(_int(query.get("since"), 0), who)
            if path == "/api/screens":
                return 200, self.screens(who)
            if path == "/api/screen":
                return _answer(self.screen(str(query.get("id") or ""), who))
        elif method == "POST":
            who = str(body.get("profile") or "") or None
            name = str(body.get("name") or "")
            if path == "/api/timers/set":
                return _answer(self.set_timer(name, bool(body.get("enabled")), who))
            if path == "/api/timers/run":
                return _answer(self.run_timer(name, who))
            if path == "/api/actions/run":
                return _answer(self.run_action(name, who))
            if path == "/api/screen/press":
                return _answer(self.press(str(body.get("id") or ""),
                                          str(body.get("action") or ""),
                                          body.get("args") or {}, who))
        return 404, {"error": "not_found"}

    # -- reaching the panel safely -------------------------------------------
    @staticmethod
    def _port(rt) -> int:
        try:
            return int(rt.daemon_port())
        except Exception:                    # noqa: BLE001 — a half-typed port box
            return 0

    def _client_args(self, rt) -> tuple:
        """Which executable to look for, and in whose Windows session.

        Read from the WIDGETS when there is a Tk thread to ask: a Tk variable read off
        that thread raises «main thread is not in main loop» whenever the main thread is
        not inside the event loop, and an HTTP worker never is. When nobody is pumping
        (the boot, a window going down) the profile's saved values answer instead —
        the same fallback the schedule already makes (panel/runtime/schedule.py).

        Both are asked THROUGH `game_process.profile_user`, never re-derived here: the
        login means nothing while «игра в RDP-сессии» is off, and that pair is decided
        in exactly one place.
        """
        box: dict = {}

        def read() -> None:
            box["exe"] = rt.settings.opt_str("game_exe")
            box["user"] = game_process.profile_user(rt.settings)

        self._on_tk(rt, read)
        if "exe" in box:
            return box["exe"], box.get("user")
        saved = _Saved(rt.settings)
        return saved.opt_str("game_exe"), game_process.profile_user(saved)

    @staticmethod
    def _on_tk(rt, func) -> None:
        """Run ``func`` on the Tk thread and wait, or run it here if there is none."""
        root = getattr(rt, "root", None)
        if root is None or threading.current_thread() is threading.main_thread():
            try:
                func()
            except Exception:                # noqa: BLE001 — a read, never the server
                pass
            return
        try:
            rt.tick.on_tk(func, timeout=TK_TIMEOUT_SEC)
        except Exception:                    # noqa: BLE001 — the window is going away
            pass


class _Saved:
    """A settings binder that reads the FILE only — no widget, no Tk, any thread.

    Handed to `game_process.profile_user` on the path where the Tk thread could not be
    reached, so the pair of knobs is still read by the one function that knows what they
    mean together.
    """

    def __init__(self, binder) -> None:
        self._values = getattr(binder, "values", {}) or {}
        self._defaults = getattr(binder, "defaults", {}) or {}

    def opt(self, key: str):
        if key in self._values:
            return self._values[key]
        return self._defaults.get(key)

    def opt_str(self, key: str) -> str:
        raw = self.opt(key)
        text = str(raw).strip() if raw is not None else ""
        return text or str(self._defaults.get(key) or "")

    def opt_bool(self, key: str) -> bool:
        return bool(self.opt(key))


def _answer(result: dict) -> tuple:
    """A command's result as an HTTP answer: an unknown name is a 404, not an «ok»."""
    if result.get("error") == "unknown":
        return 404, result
    return 200, result


def _int(raw, fallback: int) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return fallback


def static_dir() -> str:
    """Where the page itself lives — beside this module, shipped with the panel."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

"""What the phone may ask the panel, as JSON — and nothing the panel cannot already do.

The web front-end is the same kind of thing every tab is: it SHOWS what the runtime
holds and PRESSES what the runtime already presses. It runs no scenario of its own, it
assembles no Lua, it holds no gate — `CLAUDE.md` is binding on that, and the shape of
this file is what keeps it honest. Every route below is one call onto
:class:`~panel.runtime.host.PanelRuntime`:

    /api/state      what this profile is doing right now      rt.game, rt.activity
    /api/timers     the errands, their switches, when next    rt.schedule
    /api/actions    the scenarios that exist                  rt.actions
    /api/log        what has been said                        rt.log (tapped)
    /api/i18n       the words to say it in                    panel/locales

WHICH THREAD. Everything here is called from an HTTP worker thread, and two things in
the panel may not be touched from one: a Tk variable and a widget. So a knob is read
through :meth:`_setting` (which hops onto the Tk thread and falls back to the profile's
file when nobody is pumping), a timer's switch is moved through the Timers tab on the Tk
thread when that tab is in this window, and the process scan — which takes long enough
to be felt — is done HERE and cached, never on the thread that draws.

NOTHING IS TRANSLATED INTO THE PAGE. `/api/i18n` hands over the whole locale table and
the browser says the words, exactly as a tab does: the panel's language is the phone's
language, and a key added to `panel/locales/` reaches both without a line of JavaScript
changing. The two exceptions are the strings that are already sentences by the time this
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
#: not repeat it. Well under the time anything it reports actually changes.
STATUS_TTL_SEC = 5.0

#: How many log lines are held for a phone that connects late. The window keeps four
#: thousand; this is a phone screen and a poll every couple of seconds.
TAIL_LINES = 400

#: How long to wait for the Tk thread when reading a knob off its widget. Short: the
#: file is a perfectly good answer, and a page that hangs is worse than one that is a
#: keystroke behind.
TK_TIMEOUT_SEC = 1.5


class WebApi:
    """The JSON surface of one open profile. One of these per running server."""

    def __init__(self, rt, *, tail: int = TAIL_LINES) -> None:
        self.rt = rt
        self._lock = threading.Lock()
        self._lines: collections.deque = collections.deque(maxlen=tail)
        self._seq = 0                    # the number of the newest line held
        self._untap = None
        self._status: tuple = (0.0, False, "")   # (read at, running, label)

    # -- the log ------------------------------------------------------------
    def attach(self) -> None:
        """Start collecting log lines. Idempotent.

        Seeded from the profile's `panel.log` so a phone that connects after an hour of
        farming sees the hour, not a blank screen — the file is the record, the queue is
        only what has not been drawn yet.
        """
        if self._untap is not None:
            return
        self._seed()
        self._untap = self.rt.log.tap(self._take)

    def detach(self) -> None:
        untap, self._untap = self._untap, None
        if untap is not None:
            untap()

    def _take(self, line: str) -> None:
        """One line, on whoever's thread produced it. Cheap on purpose."""
        with self._lock:
            self._seq += 1
            self._lines.append((self._seq, strip_ansi(line)))

    def _seed(self) -> None:
        try:
            path = self.rt.profiles.panel_log()
            with open(path, encoding="utf-8", errors="replace") as fh:
                tail = collections.deque(fh, maxlen=self._lines.maxlen)
        except OSError:
            return
        with self._lock:
            for raw in tail:
                self._seq += 1
                self._lines.append((self._seq, strip_ansi(raw.rstrip("\n"))))

    def log(self, since: int = 0) -> dict:
        """The lines newer than ``since``, with the number to ask for next time.

        A caller that has fallen behind the ring (a phone in a pocket for an hour) is
        told so rather than silently handed a gap: ``reset`` means "what you had is no
        longer the beginning of this".
        """
        with self._lock:
            held = list(self._lines)
            newest = self._seq
        oldest = held[0][0] if held else newest + 1
        reset = bool(since) and since < oldest - 1
        rows = [self._line(n, text) for n, text in held if n > since or reset]
        return {"lines": rows, "next": newest, "reset": reset}

    @staticmethod
    def _line(number: int, text: str) -> dict:
        return {"n": number, "text": text, "tag": tag_of(text),
                "sev": severity_of(text)}

    # -- what the profile is doing ------------------------------------------
    def state(self) -> dict:
        """One reading of everything the front page shows."""
        running, label = self._client_status()
        step = self.rt.activity.current()
        due = self._due()
        return {
            "profile": self.rt.profiles.active,
            "lang": self.rt.i18n.lang,
            "game": {"running": running, "text": label},
            # `busy` is a PROPERTY on the real link (panel/runtime/daemon.py) and a
            # method on none of them — read it, never call it.
            "daemon": {"up": self.rt.game.up(), "port": self._port(),
                       "busy": bool(self.rt.game.busy)},
            # `name` is passed through raw beside the sentence: the page marks the
            # scenario card that is running with it, and matching on the translated
            # sentence would be matching on a language.
            "activity": ({"key": step.key,
                          "name": str(step.fmt.get("name") or ""),
                          "text": self.rt.t(step.key, **step.fmt)}
                         if step is not None else None),
            "timers": due,
            "time": time.time(),
        }

    def _client_status(self) -> tuple:
        """Is this profile's client up — cached for :data:`STATUS_TTL_SEC`."""
        when, running, label = self._status
        now = time.time()
        if now - when < STATUS_TTL_SEC:
            return running, label
        exe, user = self._client_args()
        try:
            running, message = game_process.status(exe, user=user)
        except Exception as exc:             # noqa: BLE001 — a reading, never the server
            running, message = False, str(exc)
        label = i18nmod.translated(self.rt.t, message)
        self._status = (now, bool(running), label)
        return bool(running), label

    def _due(self) -> dict:
        """How many errands are switched on, and when the next one is due."""
        try:
            schedule = self.rt.schedule
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
                soonest, whose = when, self._timer_title(timer)
        # `running` is a property on the scheduler, like `busy` on the game link.
        return {"on": on, "next": soonest, "next_name": whose,
                "running": bool(getattr(schedule.timers, "running", False))}

    # -- the errands ---------------------------------------------------------
    def timers(self) -> dict:
        """Every configured errand: its switch, its period, and how it last ended."""
        schedule = self.rt.schedule
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
                "title": self._timer_title(timer),
                "enabled": bool(item.get("enabled")),
                "interval_sec": int(item.get("interval_sec") or timer.interval_sec),
                "next": catalogue.next_due(timer, config, records),
                "last": when or None,
                "last_state": state,
                "queued": timer.name in pending,
                "steps": list(timer.scenario),
            })
        return {"timers": rows, "running": bool(schedule.timers.running),
                "time": time.time()}

    def _timer_title(self, timer) -> str:
        """What the row is called — the operator's own words, or the built-in key."""
        if timer.title:
            return timer.title
        if timer.label_key:
            return self.rt.t(timer.label_key)
        return timer.name

    def set_timer(self, name: str, enabled: bool) -> dict:
        """Tick or untick one errand — through the Timers tab when this window has one.

        THE TAB'S BOXES WIN. `Schedule.timer_config` reads the widgets whenever they
        exist (panel/tabs/timers.py), so writing the file behind a live tab's back would
        be undone on the next tick and look, from the phone, like a switch that does not
        stay. With no such tab in this profile the file IS the configuration, and that
        is the branch below.
        """
        timer = self.rt.schedule.timer_catalogue.by_name(name)
        if timer is None:
            return {"error": "unknown"}
        tab = self.rt.tabs.get("timers")
        if tab is not None and hasattr(tab, "set_enabled"):
            done: dict = {}
            self._on_tk(lambda: done.update(ok=bool(tab.set_enabled(name, enabled))))
            if done.get("ok"):
                return {"ok": True, "name": name, "enabled": bool(enabled)}
        schedule = self.rt.schedule
        config = dict(schedule.timer_config())
        item = dict(config.get(name) or {})
        item["enabled"] = bool(enabled)
        config[name] = item
        schedule.timer_catalogue = schedule.timer_catalogue.with_settings(config)
        timersmod.save_catalogue(schedule.timer_catalogue,
                                 self.rt.profiles.timers_json())
        return {"ok": True, "name": name, "enabled": bool(enabled)}

    def run_timer(self, name: str) -> dict:
        """«Запустить сейчас» — onto the schedule's own queue, never a thread of its own.

        The same call the row's button makes, for the same reason: every errand runs
        single-file on the one worker, so a press from the phone while something else is
        running waits its turn instead of driving the game beside it.
        """
        timer = self.rt.schedule.timer_catalogue.by_name(name)
        if timer is None:
            return {"error": "unknown"}
        queued = bool(self.rt.schedule.timers.request(timer))
        return {"ok": queued, "queued": queued, "name": name}

    # -- the scenarios -------------------------------------------------------
    def actions(self) -> dict:
        """Every scenario the panel can play, titled in the panel's language."""
        return {"actions": list_actions(lang=self.rt.i18n.lang)}

    def run_action(self, name: str) -> dict:
        """Play one scenario under the game claim — `rt.play_async`, and nothing else.

        ``busy`` is not a failure: it means something else is driving this client right
        now, which is the one answer a remote press must never override.
        """
        if self.rt.actions.resolve(name) is None:
            return {"error": "unknown"}
        started = self.rt.play_async(name, tag="web")
        return {"ok": bool(started), "busy": not started, "name": name}

    # -- the words -----------------------------------------------------------
    def words(self) -> dict:
        """The whole locale table the page draws itself with.

        English underneath whatever the panel is set to, which is the same fallback
        `Translator.t` applies — so a locale that is behind shows English for the keys
        it lacks and its own words for the rest, on the phone exactly as in the window.
        """
        lang = self.rt.i18n.lang
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
        """
        if method == "GET":
            if path == "/api/state":
                return 200, self.state()
            if path == "/api/timers":
                return 200, self.timers()
            if path == "/api/actions":
                return 200, self.actions()
            if path == "/api/i18n":
                return 200, self.words()
            if path == "/api/log":
                return 200, self.log(_int(query.get("since"), 0))
        elif method == "POST":
            name = str(body.get("name") or "")
            if path == "/api/timers/set":
                return _answer(self.set_timer(name, bool(body.get("enabled"))))
            if path == "/api/timers/run":
                return _answer(self.run_timer(name))
            if path == "/api/actions/run":
                return _answer(self.run_action(name))
        return 404, {"error": "not_found"}

    # -- reaching the panel safely -------------------------------------------
    def _port(self) -> int:
        try:
            return int(self.rt.daemon_port())
        except Exception:                    # noqa: BLE001 — a half-typed port box
            return 0

    def _client_args(self) -> tuple:
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
            box["exe"] = self.rt.settings.opt_str("game_exe")
            box["user"] = game_process.profile_user(self.rt.settings)

        self._on_tk(read)
        if "exe" in box:
            return box["exe"], box.get("user")
        saved = _Saved(self.rt.settings)
        return saved.opt_str("game_exe"), game_process.profile_user(saved)

    def _on_tk(self, func) -> None:
        """Run ``func`` on the Tk thread and wait, or run it here if there is none."""
        root = getattr(self.rt, "root", None)
        if root is None or threading.current_thread() is threading.main_thread():
            try:
                func()
            except Exception:                # noqa: BLE001 — a read, never the server
                pass
            return
        try:
            self.rt.tick.on_tk(func, timeout=TK_TIMEOUT_SEC)
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

"""What the phone may ask the panel, as JSON — and nothing the panel cannot already do.

The web front-end is the same kind of thing every tab is: it SHOWS what the runtime
holds and PRESSES what the runtime already presses. It runs no scenario of its own, it
assembles no Lua, it holds no gate — `CLAUDE.md` is binding on that, and the shape of
this file is what keeps it honest. Every route below is one call onto a
:class:`~panel.runtime.host.PanelRuntime`:

    /api/profiles   which accounts this window has open      rt.workspace
    /api/state      what one profile is doing right now      rt.game, rt.activity
    /api/game       start / close / restart the client       rt.play_async, via
                                                             runtime/game_control.py
    /api/panel      put the PANEL back on the code on disk   runtime/panel_control.py
    /api/interrupt  end whatever scenario is playing          runtime/interrupt.py
    /api/timers     the errands, their switches, when next   rt.schedule
    /api/triggers   the listeners, their switches, their ear  rt.schedule
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
import json
import os
import threading
import time

import profile_health

from .. import i18n as i18nmod
from .. import timers as timersmod
from .. import triggers as triggersmod
from ..runtime import autostart as autostartmod
from ..runtime import game_control, game_process, panel_control, provision
from ..runtime import updates
from ..runtime import interrupt as interruptmod
from ..runtime import opt_switch as optswitch
from ..runtime import profile_control as profilectl
from ..runtime import power as powermod
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

#: How long a PRESS waits for the Tk thread before answering «принято, идёт» (#1331).
#: A read that is late may fall back to the file; a press has no fallback — it has
#: already been handed over and is going to happen — so running out of patience here
#: says what is true and never that the press was not understood. Longer than the read
#: above because the answer is worth a moment's wait when it is quick, and unbounded
#: only in the sense that the press itself is not cancelled by it.
PRESS_TIMEOUT_SEC = 2.5

#: The screen that is not a tab: every warzone the game has. It is a menu modal in the
#: window because the list belongs to the GAME rather than to an account
#: (`panel/runtime/servers_dialog.py`), and the phone gets it here so that neither
#: front-end knows something the other does not (`CLAUDE.md`).
SERVERS_SCREEN = "servers"

#: How many warzones one screenful carries. There are thousands, and a phone that is
#: handed all of them scrolls a list nobody reads; the search box is what narrows it.
SERVERS_PAGE = 150

#: The screen that is not a tab either: the ONE hourly task that opens this panel when
#: it is not running. It belongs to the WINDOW rather than to an account
#: (`panel/runtime/autostart_dialog.py`, #1506) — every profile open here shares the same
#: task — and unlike «Веб» the phone gets the same switch the window has: turning the
#: watchdog off costs a restart that would otherwise have happened by itself, never the
#: channel the phone is reached through, so it is not the divergence «Веб» is.
AUTOSTART_SCREEN = "autostart"

#: …and the third: which language the PANEL speaks. One choice for the whole window —
#: every open profile switches at once (`panel/runtime/workspace.py`, #1515) — so it
#: belongs beside the two above rather than inside one account's pages. It reaches the
#: phone because with the window being retired (#1976) a switch only the window has is a
#: switch nobody has; unlike the remote control's own port and token, getting it wrong
#: costs a language and never the way back in.
LANGUAGE_SCREEN = "language"

#: …and the fourth: WHICH ACCOUNTS are open at all. The window has it on «Параметры»;
#: the phone had nothing, so somebody away from the machine could watch four profiles and
#: neither open a fifth nor close one that was misbehaving (`panel/runtime/profile_control.py`).
PROFILES_SCREEN = "profiles"


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
        self._status: dict = {}          # profile -> (read at, running, link, label)
        self._shared: dict = {}          # profile -> (read at, [other profiles on its client])
        self._attached = False
        #: What «Серверы» is filtered by on the phone. The WINDOW's, like the list
        #: itself — one server per window, one filter, whichever profile is being looked
        #: at (`panel/runtime/servers_dialog.py`).
        self._servers_needle = ""
        self._servers_undated = False

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
                # ONE LIGHT PER PROFILE — the phone's copy of the tab strip (#1299).
                # The window puts a colour on each profile's notebook tab so an account
                # that has stopped playing is visible without opening its page; the
                # picker is where the same labels live here, so the same colour goes
                # beside them, with the same words behind a tap.
                #
                # FREE: it is the LAST verdict the window's status poll made
                # (panel/runtime/health.py), not a reading taken here — a phone polling
                # every two seconds must not walk four socket tables to draw four dots.
                # A profile nothing has polled yet answers amber, «нечего сказать»,
                # which is what a tab launched on its own reports too.
                "lights": [self._light(rt) for _name, rt in self.sessions()],
                # Which one the WINDOW is looking at. Shown so a person driving both can
                # see, from the phone, which account is on screen at the machine.
                "showing": current or self.rt.profiles.active}

    def _light(self, rt) -> dict:
        """One profile's light, worded in ITS own language — never the browser's.

        Said here for the same reason the client's status is: the page has no locale
        table for sentences that carry a pid and an endpoint in them, and one reading
        worded twice is two readings waiting to disagree.
        """
        try:
            said = rt.health.state(rt.t)
        except Exception as exc:             # noqa: BLE001 — a light, never the server
            said = {"colour": "warn", "reason": "unread", "text": str(exc), "tip": []}
        return {"name": self._name_of(rt), **said}

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
        running, colour, reason, label = self._client_status(name, rt)
        step = rt.activity.current()
        return {
            "profile": name,
            "lang": rt.i18n.lang,
            # `colour` is the honest half and `running` the old one: a client that has
            # lost the server is still running, and the phone paints the COLOUR — the
            # three statuses and nothing else (#1911).
            #
            # `controls` is the client's whole life — start it, close it, put it back —
            # and it is computed HERE rather than in the browser on purpose: the window
            # greys the same three buttons off the same table
            # (panel/runtime/game_control.py), and a phone deciding for itself when a
            # press applies is how the two front-ends start disagreeing about it.
            # `recovery` is the same bookkeeping the window's status strip reads, out of
            # the same object on the runtime (panel/runtime/recovery.py): how many bad
            # readings in a row, how many restarts this client has been given, and how
            # long until another is allowed. Numbers, so the page says them in its own
            # language — and the phone is the front-end that NEEDS them, because the
            # person holding it cannot see the log scrolling past.
            "game": {"running": running, "colour": colour, "reason": reason,
                     "text": label,
                     "recovery": rt.recovery.state(time.time()),
                     "controls": game_control.state(
                         running, str((step.fmt.get("name") if step else "") or ""))},
            # `busy` is a PROPERTY on the real link (panel/runtime/daemon.py) and a
            # method on none of them — read it, never call it.
            #
            # `shared` is the one fault about a profile that looks like nothing at all:
            # two profiles on ONE client farm ONE account, and both report themselves
            # healthy doing it (#1250). The phone gets the READING and no button — the
            # login that separates them is typed on «Настройки» → «Игра», and that tab
            # has no phone screen by decision (CLAUDE.md, «The three divergences there
            # are»), so what it needs on the move comes here (#1263).
            #
            # `user` is WHICH WINDOWS SESSION this profile's client lives in, empty for
            # the one on the panel's own desktop. A reading and not a control: it is
            # PICKED from this machine's accounts on «Настройки» → «Игра» (#1263), and
            # that tab has no phone screen by decision — but which account a profile is
            # pointed at is exactly what somebody away from the machine needs to be able
            # to check, because getting it wrong looks identical to «клиент не запущен».
            # `stale` is «it answers the port and holds a client that is gone» — the
            # state the window's indicator draws amber (#1286). Read off the LAST
            # verdict the status poll made rather than asked for here: the page polls
            # faster than that poll runs, and the reading walks the process list.
            # Empty («nobody has asked lately») draws as it always did, off `up`.
            # THE LINK, and it is the same three statuses the window draws (#1911).
            # `colour` is the whole verdict; `lands` is the half of it a person can act
            # on — «панель дотягивается до клиента» — and the phone gets it because
            # amber for OUR wiring and amber for a deaf client want opposite responses.
            "link": {"up": rt.game.up(), "port": self._port(rt),
                       "colour": colour, "reason": reason,
                       "lands": rt.health.current.plumbing == profile_health.LANDING,
                       "busy": bool(rt.game.busy),
                       "shared": self._shared_client(name, rt),
                       "user": self._client_args(rt)[1] or ""},
            # `name` is passed through raw beside the sentence: the page marks the
            # scenario card that is running with it, and matching on the translated
            # sentence would be matching on a language.
            "activity": ({"key": step.key,
                          "name": str(step.fmt.get("name") or ""),
                          "text": rt.t(step.key, **step.fmt)}
                         if step is not None else None),
            "timers": self._due(rt),
            # THE PANEL ITSELF, which is the one thing on this page that is not about
            # an account: which version of the bot the window is running, and the press
            # that puts it back on the code that is now on disk
            # (panel/runtime/panel_control.py). Here rather than on a screen of its own
            # because the remote control's own settings have none by decision
            # (CLAUDE.md, «The divergences there are»), and what such a corner of the
            # panel genuinely needs on the move goes on «Состояние». Empty `controls`
            # in a process that is not a panel —
            # a tab launched on its own answers this route too.
            # `version` is the RELEASE this checkout is on, with the `+N-dev` mark when
            # it sits between two of them (#1274) — the same string the window draws,
            # out of the same cached reading, because «какая у тебя версия» must not
            # have two answers depending on which front-end was asked. It falls back to
            # the packaged number where there is no git to ask.
            "panel": {"version": updates.version_text(),
                      "controls": panel_control.state()},
            # «ПРОФИЛЬ РАБОТАЕТ» — the one switch this account has, drawn on the phone
            # exactly as in the window and writable from either (#1882,
            # panel/runtime/power.py). A MARK rather than a log line, because the line
            # scrolls away and a stopped profile looks exactly like an idle one — which
            # is how seven hours once went past with a dead client behind it. `on` is the
            # box; `off_for_sec` is what makes it uncomfortable enough to act on.
            "power": rt.power.state(time.time()),
            # «ПОДНИМАТЬ ИГРУ ПРИ ПАДЕНИИ» — the OTHER switch on «Главная», and until now
            # a switch the phone could not see (#1882 mirrored both ways, CLAUDE.md).
            # It matters on the move for the same reason the one above does: with it off,
            # `Recovery` still decides on a cure and the panel drops it — the client is
            # never put back, and nothing on the page says why an account has been
            # sitting kicked for an hour.
            "watchdog": optswitch.get(rt, "watchdog"),
            # …AND WHETHER ANYTHING MAY RUN AT ALL (#1393). The press above is one way to
            # arrive here and a daemon dying on its own is the other, so this is drawn
            # from its own object rather than from the mark: a profile whose daemon has
            # gone in the night is exactly as stopped as one somebody stopped on purpose,
            # and nothing else on this page says so. The LAST answer, never a fresh one —
            # a page that polls every two seconds must not probe a socket per request
            # (`panel/runtime/gate.py::state`).
            "gate": rt.gate.state(),
            # WHAT IS PLAYING, AND THE PRESS THAT ENDS IT (#1300). The phone's copy of the
            # button beside the window's status strip, and the same press: it reaches every
            # open profile, because a window holds several accounts and the run that has to
            # stop is not reliably the one whose page is being looked at. So the card shows
            # THIS profile's runs — with the step each has reached, which is what makes the
            # press worth pressing rather than guessing — and counts the ones running under
            # the other profiles, so the button is offered exactly when the window offers it.
            "interrupt": {**rt.interrupts.state(),
                          "elsewhere": self._runs_elsewhere(rt)},
            "time": time.time(),
        }

    def _runs_elsewhere(self, rt) -> int:
        """How many scenarios the OTHER open profiles are playing.

        Only a count: the phone needs it to know whether the press applies, and naming
        another account's recipe on this account's card would read as this account's.
        """
        total = 0
        for _name, other in self.sessions():
            if other is rt:
                continue
            try:
                total += len(other.interrupts)
            except Exception:                # noqa: BLE001 — a count, never the server
                pass
        return total

    def _name_of(self, rt) -> str:
        return str(rt.profiles.active)

    def _shared_client(self, name: str, rt) -> list:
        """Which OTHER profiles drive this profile's client — cached like the status.

        Off disk, so it costs a couple of small reads per profile and the state route
        is polled every two seconds by every phone that has the page open. The cache is
        the status poll's, for the same reason: a profile's client changes when somebody
        edits it, not between two ticks.
        """
        when, names = self._shared.get(name, (0.0, []))
        now = time.time()
        if now - when < STATUS_TTL_SEC:
            return names
        try:
            names = provision.sharing_with(rt.profiles, name)
        except Exception:                    # noqa: BLE001 — a reading, never the server
            names = []
        self._shared[name] = (now, names)
        return names

    def _client_status(self, name: str, rt) -> tuple:
        """Is this profile's client up, and what colour is its link — cached per profile
        for :data:`STATUS_TTL_SEC`.

        Two different questions and both come back: the process exists, and the panel's
        one verdict about it (`tools/lib/profile_health.py`). The phone paints the
        SECOND — the first is what it used to show, and a stranded client answered it
        with a cheerful «работает» all night long.

        The colour is READ, never made: the window's status poll takes every reading it
        needs anyway, and a page that polls faster than that poll must not be the thing
        that spends a round trip (#1911, and the same rule `panel/runtime/health.py`
        keeps about its own light).
        """
        when, running, colour, reason, label = self._status.get(
            name, (0.0, False, profile_health.BAD, profile_health.NO_CLIENT, ""))
        now = time.time()
        if now - when < STATUS_TTL_SEC:
            return running, colour, reason, label
        exe, user = self._client_args(rt)
        try:
            found = game_process.probe(exe, user=user)
            health = rt.health.current
            running = found.running
            colour, reason = health.colour, health.reason
            message = game_process.worded(found, colour == profile_health.OK, user)
        except Exception as exc:             # noqa: BLE001 — a reading, never the server
            running, colour, reason = False, profile_health.BAD, profile_health.NO_CLIENT
            message = str(exc)
        label = i18nmod.translated(rt.t, message)
        self._status[name] = (now, bool(running), colour, reason, label)
        return bool(running), colour, reason, label

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
            # …with the profile's own day boundary, exactly as the window asks it
            # (#1333): «раз в сутки» is the game's 00:00, so the phone's «ближайший
            # через …» must be counted to the same moment the scheduler will fire on.
            when = catalogue.next_due(timer, config, records, rt.day)
            if when is None:
                continue
            if soonest is None or when < soonest:
                # The TITLE, not the id: what the front page said until now was
                # «ближайший: donate_alliance_tech», the key the file is keyed by
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
                # The wait after a FAILED run (#1127), so the phone can say why the
                # next fire is minutes away on an hourly errand instead of leaving
                # «ошибка» beside a countdown that disagrees with the period.
                "retry_sec": int(timer.retry_sec),
                # The same moment the window's row shows, off the same day boundary
                # (#1333) — a daily errand's next turn is the server's midnight.
                "next": catalogue.next_due(timer, config, records, rt.day),
                "last": when or None,
                "last_state": state,
                "queued": timer.name in pending,
                # «сразу, без очереди» (#1288) — the phone draws and sets the same
                # box the window's row has, because the two are one runtime.
                "immediate": bool(item.get("immediate", timer.immediate)),
                # WHICH WEEKDAYS the row runs on, 1 = Monday … 7 = Sunday, empty for an
                # ordinary period. The window's row shows the days where a plain errand
                # shows its period, so the phone does too — a card saying «каждые 7 дн»
                # over an errand that only ever fires on a Sunday is the front-end
                # telling the person something that is not true (CLAUDE.md).
                "weekdays": list(timer.weekdays),
                "steps": list(timer.scenario),
                # THE OPERATOR'S OWN TITLE, empty where the row is a built-in one whose
                # label is a locale key (#1976). `title` above is what the row is CALLED
                # — translated — and an editor that sent that back would freeze a
                # built-in errand's label to whatever language the phone was in.
                "custom_title": timer.title or "",
                "args": dict(timer.args),
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
        # …AND DRAWN. An undrawn tab has no rows to tick (#1215) and no widgets for
        # `Schedule.timer_config` to read either, so the file below IS the configuration
        # — exactly the branch a profile without a Timers tab takes.
        if tab is not None and getattr(tab, "built", True) and hasattr(tab, "set_enabled"):
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

    def set_timer_immediate(self, name: str, immediate: bool,
                            profile: str | None = None) -> dict:
        """Mark one errand «сразу», or take the mark off (#1288).

        The same two branches as :meth:`set_timer`, for the same reason: while a Timers
        tab is drawn its boxes ARE the configuration, so this goes through the tab's own
        variable and lets its autosave write the file. With no such tab the file is the
        configuration and is written here.
        """
        rt = self._runtime(profile)
        timer = rt.schedule.timer_catalogue.by_name(name)
        if timer is None:
            return {"error": "unknown"}
        tab = rt.tabs.get("timers")
        if tab is not None and getattr(tab, "built", True) \
                and hasattr(tab, "set_immediate"):
            done: dict = {}
            self._on_tk(rt, lambda: done.update(
                ok=bool(tab.set_immediate(name, immediate))))
            if done.get("ok"):
                return {"ok": True, "name": name, "immediate": bool(immediate)}
        schedule = rt.schedule
        config = dict(schedule.timer_config())
        item = dict(config.get(name) or {})
        item["immediate"] = bool(immediate)
        config[name] = item
        schedule.timer_catalogue = schedule.timer_catalogue.with_settings(config)
        timersmod.save_catalogue(schedule.timer_catalogue, rt.profiles.timers_json())
        return {"ok": True, "name": name, "immediate": bool(immediate)}

    def edit_timer(self, name: str, *, interval_sec=None, weekdays=None,
                   profile: str | None = None) -> dict:
        """Re-schedule one errand from the phone: its period, its days, or both (#1976).

        The window has had an editor since it had a Timers tab and the phone had none,
        so an errand's period could be READ on a phone and changed only at the machine —
        the divergence `CLAUDE.md` forbids, arrived at by way of «the dialog is hard to
        draw». This is the half that is not a dialog: what an errand's schedule IS.

        THE SAME TWO BRANCHES as every switch above, for the same reason. While a Timers
        tab is drawn its widgets are the configuration and `with_settings` folds them
        back in on every save, so a period written past them would be undone on the next
        tick. With no such tab the saved catalogue IS the configuration and is written
        here — and `Catalogue.replace` writes the whole entry, which is what keeps the
        steps and the args exactly as they were.
        """
        rt = self._runtime(profile)
        timer = rt.schedule.timer_catalogue.by_name(name)
        if timer is None:
            return {"error": "unknown"}
        tab = rt.tabs.get("timers")
        if tab is not None and getattr(tab, "built", True) and hasattr(tab, "web_edit"):
            done: dict = {}
            self._on_tk(rt, lambda: done.update(ok=bool(tab.web_edit(
                name, interval_sec=interval_sec, weekdays=weekdays))))
            if done.get("ok"):
                return {"ok": True, "name": name}
        edited = timersmod.Timer(
            name=timer.name, scenario=timer.scenario,
            interval_sec=(timer.interval_sec if interval_sec is None
                          else timersmod._as_interval(interval_sec, timer.interval_sec)),
            retry_sec=timer.retry_sec, enabled=timer.enabled,
            immediate=timer.immediate,
            weekdays=(tuple(timer.weekdays) if weekdays is None
                      else timersmod._as_weekdays(weekdays, timer.weekdays)),
            args=dict(timer.args), title=timer.title, label_key=timer.label_key)
        schedule = rt.schedule
        schedule.timer_catalogue = schedule.timer_catalogue.replace(edited)
        timersmod.save_catalogue(schedule.timer_catalogue, rt.profiles.timers_json())
        return {"ok": True, "name": name}

    # -- the whole entry: add, edit, copy, delete (#1976) --------------------
    #
    # The window has had an editor since it had a Timers tab, and the phone had the
    # SCHEDULE half of it and nothing else — the steps, the args and the title could be
    # read on a phone and written only at the machine. That was a divergence with a
    # reason («a phone that could rewrite a scenario by a mistyped character is not a
    # remote control»), and the person has ended it: the web is the front-end, so it
    # gets the whole function (CLAUDE.md).
    #
    # The validation below is the dialog's, word for word — no name, a name another row
    # already answers to, no steps, args that are not a JSON object — because a refusal
    # the phone words differently from the window is two panels, not one.
    def _put_timer(self, rt, timer, drop: str | None = None) -> None:
        """Persist one entry — through a drawn Timers tab, or into the file.

        THE SAME TWO BRANCHES as every switch above, for the same reason: while that tab
        is drawn its widgets ARE the configuration and `Catalogue.with_settings` folds
        them back in on every save, so an entry written past them would be undone on the
        next tick.
        """
        tab = rt.tabs.get("timers")
        if tab is not None and getattr(tab, "built", True) and hasattr(tab, "web_save"):
            done: dict = {}
            self._on_tk(rt, lambda: done.update(
                ok=bool(tab.web_save(timer, drop=drop))))
            if done.get("ok"):
                return
        schedule = rt.schedule
        catalogue = schedule.timer_catalogue
        if drop and drop != timer.name:
            catalogue = catalogue.remove(drop)
        schedule.timer_catalogue = catalogue.replace(timer)
        timersmod.save_catalogue(schedule.timer_catalogue, rt.profiles.timers_json())

    def save_timer(self, *, name: str, original: str = "", title=None,
                   interval_sec=None, retry_sec=None, weekdays=None, args=None,
                   steps=None, profile: str | None = None) -> dict:
        """Add a new errand, or rewrite one whole — steps, args, title and schedule.

        ``original`` is the name the row had: empty for a new errand, and different
        from ``name`` when the person renamed it, which is a delete plus an add because
        the name is the key the last-run record is filed under.
        """
        rt = self._runtime(profile)
        catalogue = rt.schedule.timer_catalogue
        fresh = str(name or "").strip()
        was = str(original or "").strip()
        base = catalogue.by_name(was) if was else None
        if was and base is None:
            return {"error": "unknown"}
        if not fresh:
            return {"ok": False, "reason": "timers.editor.err_name"}
        clash = catalogue.by_name(fresh)
        if clash is not None and fresh != was:
            return {"ok": False, "reason": "timers.editor.err_taken",
                    "fmt": {"name": fresh}}
        scenario = timersmod._as_scenario(
            steps.splitlines() if isinstance(steps, str) else (steps or ()))
        if not scenario:
            return {"ok": False, "reason": "timers.editor.err_steps"}
        if isinstance(args, str):
            raw = args.strip()
            try:
                args = json.loads(raw) if raw else {}
            except ValueError as exc:
                return {"ok": False, "reason": "timers.editor.err_args",
                        "fmt": {"error": str(exc)}}
        if args is None:
            args = {} if base is None else dict(base.args)
        if not isinstance(args, dict):
            return {"ok": False, "reason": "timers.editor.err_args",
                    "fmt": {"error": '{"name": value}'}}
        if base is None:
            # A brand-new errand starts OFF: one nobody has read yet should not fire a
            # minute later. Everything else it has is what the editor sent.
            base = timersmod.Timer(name=fresh, scenario=scenario,
                                   interval_sec=timersmod.DEFAULT_INTERVAL_SEC,
                                   enabled=False)
        edited = timersmod.with_fields(
            base, name=fresh, title=title, interval=interval_sec, retry=retry_sec,
            scenario=scenario, args=args, weekdays=weekdays)
        self._put_timer(rt, edited, drop=(was or None))
        return {"ok": True, "name": fresh}

    def copy_timer(self, name: str, profile: str | None = None) -> dict:
        """A copy of one errand under a free name, switched off.

        Off, and under a name of its own, for the reason the window's «Копировать» has
        always had: the name is the id the schedule keys its clock on, so a copy that
        answered to the original's record would inherit its last run — and two clocks on
        one errand is rarely what a duplicate was for.
        """
        rt = self._runtime(profile)
        catalogue = rt.schedule.timer_catalogue
        timer = catalogue.by_name(name)
        if timer is None:
            return {"error": "unknown"}
        copy = timersmod.with_fields(timer, name=catalogue.unique_name(timer.name),
                                     enabled=False)
        self._put_timer(rt, copy)
        return {"ok": True, "name": copy.name}

    def delete_timer(self, name: str, profile: str | None = None) -> dict:
        """Delete one errand. The asking is the front-end's; this is the doing."""
        rt = self._runtime(profile)
        if rt.schedule.timer_catalogue.by_name(name) is None:
            return {"error": "unknown"}
        tab = rt.tabs.get("timers")
        if tab is not None and getattr(tab, "built", True) \
                and hasattr(tab, "web_delete"):
            done: dict = {}
            self._on_tk(rt, lambda: done.update(ok=bool(tab.web_delete(name))))
            if done.get("ok"):
                return {"ok": True, "name": name}
        schedule = rt.schedule
        schedule.timer_catalogue = schedule.timer_catalogue.remove(name)
        timersmod.save_catalogue(schedule.timer_catalogue, rt.profiles.timers_json())
        return {"ok": True, "name": name}

    # -- the standing orders -------------------------------------------------
    def triggers(self, profile: str | None = None) -> dict:
        """Every listener, its switch, the event it waits for and whether an ear is up.

        The window's «Таймеры» tab has drawn these under the errands since it had a
        wire half at all, and the phone did not — so the person holding one could see
        which errands were on and had no way to tell whether the alliance help was even
        listening. Same runtime, same two switches, same three states.
        """
        rt = self._runtime(profile)
        schedule = rt.schedule
        pending = set(schedule.timers.pending())
        watching = set(schedule.triggers.watching())
        rows = []
        for trig in schedule.trigger_catalogue:
            # The BOX, not `trigger_config`: that one folds in whether this window can
            # carry the order out at all, and a phone drawing an unticked box over a
            # trigger the window shows ticked is the two front-ends disagreeing about
            # one state. Whether anything is listening is what `status` says.
            if trig.name in pending:
                status = "queued"
            elif trig.name in watching:
                status = "listening"
            else:
                status = "off"
            rows.append({
                "name": trig.name,
                "title": self._trigger_title(rt, trig),
                "enabled": bool(trig.enabled),
                # «сразу, без очереди» (#1288) — the window's row has this box, so the
                # phone has it: a control a person can read but not move is the
                # divergence CLAUDE.md forbids.
                "immediate": bool(trig.immediate),
                "poll": bool(trig.is_poll),
                "signal": "" if trig.is_poll else trig.event_pattern,
                "status": status,
            })
        return {"triggers": rows, "profile": self._name_of(rt), "time": time.time()}

    def _trigger_title(self, rt, trig) -> str:
        """What the listener is called — the operator's own words, or the built-in key."""
        if trig.title:
            return trig.title
        if trig.label_key:
            return rt.t(trig.label_key)
        return trig.name

    def set_trigger(self, name: str, enabled: bool,
                    profile: str | None = None) -> dict:
        """Tick or untick one standing order — through the Timers tab when it is drawn.

        The same two branches as :meth:`set_timer`, for the same reason: while that tab
        is drawn its boxes ARE the configuration (`Schedule.trigger_config` reads the
        widgets), so a switch written straight to `triggers.json` would be undone by
        their next save and look, from the phone, like a switch that does not stay.
        """
        rt = self._runtime(profile)
        if rt.schedule.trigger_catalogue.by_name(name) is None:
            return {"error": "unknown"}
        done: dict = {}
        # `Schedule.set_trigger_enabled` already holds both branches — and it touches
        # the tab's variables, which is a Tk-thread-only thing and an HTTP worker is
        # never on that thread.
        self._on_tk(rt, lambda: done.update(
            ok=bool(rt.schedule.set_trigger_enabled(name, enabled))))
        if not done.get("ok"):
            return {"error": "unknown"}
        return {"ok": True, "name": name, "enabled": bool(enabled)}

    def set_trigger_immediate(self, name: str, immediate: bool,
                              profile: str | None = None) -> dict:
        """Mark one standing order «сразу», or take the mark off (#1288)."""
        rt = self._runtime(profile)
        schedule = rt.schedule
        if schedule.trigger_catalogue.by_name(name) is None:
            return {"error": "unknown"}
        tab = rt.tabs.get("timers") if rt.tabs is not None else None
        if tab is not None and getattr(tab, "built", True) \
                and hasattr(tab, "set_trigger_immediate"):
            done: dict = {}
            self._on_tk(rt, lambda: done.update(
                ok=bool(tab.set_trigger_immediate(name, immediate))))
            if done.get("ok"):
                return {"ok": True, "name": name, "immediate": bool(immediate)}
        flags = {t.name: bool(t.immediate) for t in schedule.trigger_catalogue}
        flags[name] = bool(immediate)
        schedule.trigger_catalogue = schedule.trigger_catalogue.with_enabled(
            schedule.trigger_catalogue.enabled_config(), flags)
        triggersmod.save_catalogue(schedule.trigger_catalogue,
                                   rt.profiles.triggers_json())
        schedule.triggers.sync()
        return {"ok": True, "name": name, "immediate": bool(immediate)}

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

    def run_action(self, name: str, profile: str | None = None,
                   args: dict | None = None) -> dict:
        """Play one scenario under that profile's game claim — `rt.play_async`, no more.

        ``busy`` is not a failure: it means something else is driving this client right
        now, which is the one answer a remote press must never override. And it is per
        profile, which is the point of naming one — a press meant for the second account
        must not land on the first one's client.

        ``args`` are the scenario's own ``ARGS``, exactly as a window button passes them
        (#1702). Without them a run started from the far side plays the recipe's
        DEFAULTS, which is a different run from the one the panel would have made — the
        golden-zombie chain then hunts with squad 1 because that is what its `ARGS` line
        says, whatever the person chose on «События». Values arrive from JSON, so they
        are strings and numbers already; anything else is dropped rather than handed to
        the player, because a `{name}` is substituted into Lua before it is parsed.
        """
        rt = self._runtime(profile)
        if rt.actions.resolve(name) is None:
            return {"error": "unknown"}
        clean = {str(k): v for k, v in (args or {}).items()
                 if isinstance(v, (str, int, float)) and not isinstance(v, bool)}
        # A PERSON PRESSED IT, on the phone (#1910). The web is the other front-end of
        # the same panel, never an automatic driver, so it passes the gate exactly as a
        # button in the window does.
        started = rt.play_async(name, clean or None, tag="web", human=True)
        return {"ok": bool(started), "busy": not started, "name": name}

    # -- the client's life ----------------------------------------------------
    def game(self, action: str, profile: str | None = None) -> dict:
        """Start the client, close it, or put it back — the window's three buttons.

        The same call the window makes and the same three scenarios, because both go
        through `panel/runtime/game_control.py`: the phone cannot press anything the
        person at the machine cannot, and neither can press a fourth thing.

        The press is checked against the client as it is RIGHT NOW rather than against
        whatever the page was showing when the thumb landed. A phone that has been in a
        pocket may be offering «Стоп» for a client that died two minutes ago, and the
        answer to that is `unavailable`, not a recipe run to no purpose. The reading is
        the cached probe every other route uses, so this costs nothing extra.
        """
        rt = self._runtime(profile)
        if game_control.get(action) is None:
            return {"error": "unknown"}
        running, _colour, _reason, _label = self._client_status(self._name_of(rt), rt)
        return game_control.play(rt, action, running)

    # -- the panel's own life -------------------------------------------------
    def panel(self, action: str, profile: str | None = None) -> dict:
        """Restart the panel — the same press the window has, from the far side (#1258).

        Why a phone may ask for it at all: an edit to a `.py` reaches the running panel
        only through a fresh interpreter, and the person making those edits is not
        always the person standing at the machine. What it costs is spelled out in the
        question the browser asks first, out of the table's own key.

        WHICH PROFILE only decides whose log says it. The restart is the WINDOW's — every
        open profile goes down and every one of them comes back up — and saying so in
        the log of the account the person happens to be looking at is the one place it
        will be read.

        The answer is written before anything closes: `panel_control.request` arms the
        shutdown a moment later, on the Tk thread, so this request finishes normally and
        the page can say what is about to happen.
        """
        rt = self._runtime(profile)
        if panel_control.get(action) is None:
            return {"error": "unknown"}
        return panel_control.request(rt, action)

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
        # …and the one screen that is not a tab. «Серверы» is the window's menu entry
        # (`panel/runtime/servers_dialog.py`): the list of warzones belongs to the GAME
        # and not to an account, so it is a menu modal in the window rather than a page
        # inside one profile — and the phone still gets it, because a reading the person
        # at the machine has is a reading the phone must have too (`CLAUDE.md`).
        out.append({"id": SERVERS_SCREEN, "title": "servers.title"})
        # …and the fourth: the one hourly task, for the same reason and by the same
        # decision as «Серверы» above — it belongs to the window and not to an account,
        # so the phone gets it here rather than as a page inside one profile.
        out.append({"id": AUTOSTART_SCREEN, "title": "menu.autostart"})
        out.append({"id": LANGUAGE_SCREEN, "title": "menu.language"})
        if profilectl.available():
            out.append({"id": PROFILES_SCREEN, "title": "menu.profile"})
        return {"screens": out}

    def screen(self, screen_id: str, profile: str | None = None) -> dict:
        """One tab's screen as data — built ON THE TK THREAD, where its widgets live.

        `web_view` is contracted to be cheap and to read no game (panel/tabs/base.py),
        so this costs a hop and a dictionary. What it must NOT do is read the client:
        a phone left on a screen would then poll the game for as long as it is awake.
        """
        if screen_id == SERVERS_SCREEN:
            return self._servers_view(profile)
        if screen_id == AUTOSTART_SCREEN:
            return self._autostart_view(profile)
        if screen_id == LANGUAGE_SCREEN:
            return self._language_view(profile)
        if screen_id == PROFILES_SCREEN:
            return self._profiles_view(profile)
        rt = self._runtime(profile)
        tab = rt.tabs.get(screen_id)
        if tab is None or not getattr(type(tab), "WEB_SCREEN", False):
            return {"error": "unknown"}
        box: dict = {}

        def build() -> None:
            try:
                # DRAWN FIRST, and here rather than above because this is the Tk thread:
                # since #1215 a tab the person at the machine has not opened has no
                # widgets, and most screens are a view of them. The phone must not see
                # less than the window does — so opening a screen draws the tab, once.
                rt.tabs.realize(tab)
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

    # -- «Серверы»: the screen with no tab behind it -------------------------
    def _servers_view(self, profile: str | None = None) -> dict:
        """Every warzone the game has, as the phone's cards — the window's own model.

        Read off the machine's list (`cache/servers.json`) and never off the game: the
        contract for a screen is that opening it costs no round trip (`panel/tabs/base.py`),
        and here it costs one file read. Filling that file is the two presses below.

        THE STAR-SECRET-TASK DAY comes from the profile's own book (#1467) — the list of
        warzones is the machine's, but what any of them was doing on a day is derived
        from THIS account's readings, so the screen is drawn for the profile the phone is
        looking at, exactly as the window's grid is drawn for the one on screen.
        """
        from ..runtime.paths import ensure

        ensure()
        import game_clock
        import server_list as model

        data = model.load()
        totals = model.summary(data)
        # The GAME's clock decides the stage — the same one the window's grid judges by.
        rows = model.view_rows(data, self._servers_needle, self._servers_undated,
                               now_ms=game_clock.now_ms())
        rt = self._runtime(profile)
        book = None if rt is None else rt.secret_days
        shown = rows[:SERVERS_PAGE]
        if book is not None:
            shown = book.decorate(shown)
        items = [{"text": "%s · %s" % (row["id"], row["name"]),
                  "detail": row["opened"],
                  "facts": [{"label": "servers.col.day",
                             "value": "—" if row["day"] is None else str(row["day"])},
                            {"label": "servers.col.season",
                             "value": row["step"] or "—"},
                            {"label": "servers.col.until",
                             "value": row["until"]},
                            # The window shows these two as their own columns; on the
                            # phone the same two readings are facts on the card.
                            {"label": "servers.col.secret",
                             "value": row.get("secret_state_key", ""),
                             "translate": True},
                            {"label": "servers.secret.source",
                             "value": row.get("secret_source_key", ""),
                             "translate": True},
                            {"label": "servers.col.secret_until",
                             "value": row.get("secret_until") or "—"}],
                  "pill": row["stage_key"]}
                 for row in shown]
        graph = {} if book is None else book.summary()
        head = {"title": "servers.title",
                "rows": [{"label": "servers.total", "value": str(totals["total"])},
                         {"label": "servers.dated", "value": str(totals["dated"])},
                         {"label": "servers.seasoned",
                          "value": str(totals.get("seasoned", 0))},
                         {"label": "servers.shown",
                          "value": "%d / %d" % (min(len(rows), SERVERS_PAGE), len(rows))},
                         {"label": "servers.filter",
                          "value": self._servers_needle or "—"},
                         # The graph's own health, the same line the window's grid shows
                         # under its buttons: how much has been seen, and how much of it
                         # the cycle contradicts.
                         {"label": "servers.secret.graph",
                          "value": "%s/%s/%s · %s · ✗%s" % (
                              graph.get("observations", 0), graph.get("servers", 0),
                              graph.get("days", 0),
                              graph.get("period") or "—", graph.get("conflicts", 0))}]}
        return {"id": SERVERS_SCREEN, "title": "servers.title",
                "cards": [head, {"rows": [], "items": items, "empty": "servers.empty"}],
                "actions": [
                    {"id": "search", "label": "servers.search",
                     "prompt": "servers.search", "value": self._servers_needle},
                    {"id": "undated", "label": "servers.only_undated"},
                    {"id": "refresh", "label": "servers.refresh"},
                    {"id": "dates", "label": "servers.fetch_dates"},
                    # The window marks the SELECTED row; a phone has no selection, so
                    # each of the three asks which warzone it is about. Same three
                    # observations, same book, same press behind them.
                    {"id": "secret_read", "label": "servers.secret.read"},
                    {"id": "mark_day", "label": "servers.secret.state.day",
                     "prompt": "servers.secret.mark.prompt", "value": ""},
                    {"id": "mark_post", "label": "servers.secret.state.post",
                     "prompt": "servers.secret.mark.prompt", "value": ""},
                    {"id": "mark_plain", "label": "servers.secret.state.plain",
                     "prompt": "servers.secret.mark.prompt", "value": ""}]}

    def _servers_press(self, action: str, args: dict, profile: str | None) -> dict:
        """The same four presses the window's grid has, and nothing it has not.

        The two that touch the game play the same scenario the window plays, in the
        profile the phone is looking at — a list is the game's, but a client belongs to
        an account, and the press has to go through one of them.
        """
        from ..runtime.paths import ensure

        ensure()
        import server_list as model

        if action == "search":
            self._servers_needle = str(args.get("text") or "").strip()
            return {"ok": True}
        if action == "undated":
            self._servers_undated = not self._servers_undated
            return {"ok": True}
        if action.startswith("mark_") or action == "secret_read":
            return self._secret_press(action, args, profile)
        if action not in ("refresh", "dates"):
            return {"error": "unknown", "detail": action}
        rt = self._runtime(profile)
        if rt is None:
            return {"error": "unknown", "detail": "no profile"}
        missing = len(model.undated(model.load()))
        if action == "dates" and not missing:
            return {"ok": False, "reason": "servers.all_dated"}
        rt.say("servers", "servers.log.dates" if action == "dates" else "servers.log.list")
        started = rt.play_async("read_server_list", tag="servers", human=True,
                                args={"store": "", "dates": missing if action == "dates" else 0})
        return {"ok": bool(started)} if started else {"ok": False, "reason": "servers.busy"}

    def _secret_press(self, action: str, args: dict, profile: str | None) -> dict:
        """The phone's half of the star-day book (#1467) — the window's three marks and
        its «прочитать из игры», with the warzone typed instead of selected.

        Nothing here is a tick: a mark is an OBSERVATION of what a warzone was doing, and
        the schedule is re-derived from all of them. The reading press plays the same
        scenario the window plays and writes down what came back, through the book's own
        `take_reading` — one parser, so the two front-ends cannot drift apart on what a
        scenario's line meant.
        """
        rt = self._runtime(profile)
        if rt is None:
            return {"error": "unknown", "detail": "no profile"}
        book = rt.secret_days
        if action == "secret_read":
            # `on_result`, not `on_done`: what the scenario READ travels on the Outcome,
            # and `on_done` is handed nothing at all — which is how the first live run
            # of this press said «записано: серверов 0» about a reading that had just
            # come back with counts in it.
            def landed(outcome=None) -> None:
                got = (getattr(outcome, "ctx", None) and outcome.ctx.vars) or {}
                written = book.take_reading(got)
                rt.say("servers", "servers.secret.log.recorded", count=written)

            rt.say("servers", "servers.secret.log.read")
            started = rt.play_async("read_secret_day", args={"server": 0},
                                    tag="servers", human=True, on_result=landed)
            return {"ok": bool(started)} if started else {"ok": False,
                                                          "reason": "servers.busy"}
        state = action.split("_", 1)[1]
        if state not in ("day", "post", "plain"):
            return {"error": "unknown", "detail": action}
        try:
            server = int(str(args.get("text") or "").strip())
        except ValueError:
            return {"ok": False, "reason": "servers.secret.no_row"}
        if server <= 0:
            return {"ok": False, "reason": "servers.secret.no_row"}
        book.record(server, book.today(), state, source="observed")
        rt.say("servers", "servers.secret.log.marked", server=server,
               state=rt.i18n.t("servers.secret.state.%s" % state))
        return {"ok": True}

    # -- «Автозапуск»: the screen with no tab behind it, either (#1506) ------
    def _autostart_view(self, profile: str | None = None) -> dict:
        """The one hourly task, read off Windows — never off a saved tick.

        Pre-translated into whole sentences here (`rt.t`), the same way `activity.text`
        is: the window's own wording is a key WITH parameters (`{task}`, `{profiles}`),
        and the generic row renderer has no way to fill one in — see
        `panel/runtime/autostart_dialog.py` for the sentences themselves.
        """
        rt = self._runtime(profile)
        info = autostartmod.status(rt.profiles)
        lines = [rt.t("autostart.shared")]
        if not info.supported:
            lines.append(rt.t("autostart.state.unsupported"))
        elif info.registered:
            lines.append(rt.t("autostart.state.on", task=info.task))
            lines.append(rt.t("autostart.state.profiles",
                              profiles=", ".join(info.profiles)))
            if not info.elevated:
                lines.append(rt.t("autostart.state.limited"))
        else:
            lines.append(rt.t("autostart.state.off"))
        last = self._autostart_last_text(rt, info.last)
        if last:
            lines.append(last)
        card = {"title": "autostart.frame",
                "items": [{"text": line} for line in lines]}
        action = ({"id": "disable", "label": "autostart.disable"} if info.registered
                  else {"id": "enable", "label": "autostart.enable"})
        return {"id": AUTOSTART_SCREEN, "title": "menu.autostart",
                "cards": [card], "actions": [action] if info.supported else []}

    def _autostart_last_text(self, rt, last: dict) -> str:
        """One sentence about the last hourly look — mirrors the window's own wording."""
        state = str((last or {}).get("state") or "")
        if not state:
            return ""
        when = time.strftime("%d.%m %H:%M", time.localtime(last.get("ts") or 0))
        if state == "running":
            return rt.t("autostart.check.running", when=when)
        if state == "started":
            return rt.t("autostart.check.started", when=when)
        if state == "restarted":
            return rt.t("autostart.check.restarted", when=when)
        return rt.t("autostart.check.failed", when=when, error=last.get("error") or "")

    def _profiles_view(self, profile: str | None = None) -> dict:
        """Every profile this installation has, and which of them this window holds.

        The list is the FOLDER, like the languages: a profile is a directory, so one made
        by hand is one more row here with nothing to register. Each row says whether it is
        open and whether it is the page the window is showing, and offers the one press
        that applies to it — «Открыть» for a profile that is closed, «Закрыть» for one
        that is open. The last open profile offers neither: a window with nothing open is
        a window with nothing in it, and the workspace refuses it (#1206).
        """
        rt = self._runtime(profile)
        workspace = getattr(rt, "workspace", None)
        open_names = list(workspace.names) if workspace is not None else [self._name_of(rt)]
        showing = getattr(getattr(workspace, "current", None), "name", "") or self._name_of(rt)
        try:
            everything = list(rt.profiles.list())
        except Exception:                    # noqa: BLE001 — a reading, never the panel
            everything = list(open_names)
        items = []
        for name in everything:
            is_open = name in open_names
            actions = []
            if not is_open:
                actions.append({"id": profilectl.OPEN, "label": "profile.open",
                                "args": {"name": name}})
            elif len(open_names) > 1:
                actions.append({"id": profilectl.CLOSE, "label": "profile.close_one",
                                "args": {"name": name}})
            # …AND THE TWO THAT USED TO STAY AT THE MACHINE (#1976). Renaming is offered
            # for the profile the window is showing and for every closed one — never for
            # one open on another page, which is the shell's own rule and is refused
            # there too; the row simply does not carry a press it would be told no for.
            if name == showing or not is_open:
                actions.append({"id": profilectl.RENAME, "label": "profile.rename",
                                "prompt": "profile.prompt_name", "value": name,
                                "args": {"name": name}})
            # Deleting is an `rmtree` of the account's whole directory, so it is offered
            # only where it could succeed — never on the last profile there is — and the
            # press is guarded by the name being TYPED BACK, checked below.
            if len(everything) > 1:
                actions.append({"id": profilectl.DELETE, "label": "profile.delete",
                                "prompt": "profile.delete.prompt", "value": "",
                                "args": {"name": name}})
            items.append({
                "text": name,
                # WHICH CLIENT this profile drives — the one fact that decides whether it
                # farms its own account or somebody else's (#1252). A reading here as it
                # is in the window's own section.
                "detail": self._profile_client_text(rt, name),
                "pill": ("web.ui.profile.showing" if name == showing
                         else "web.ui.profile.open" if is_open else ""),
                "actions": actions,
            })
        return {"id": PROFILES_SCREEN, "title": "menu.profile",
                "cards": [{"title": "menu.profile", "note": "profile.open_hint",
                           "items": items}],
                "actions": [{"id": profilectl.OPEN, "label": "profile.new",
                             "prompt": "profile.new.prompt", "value": ""}]}

    def _profile_client_text(self, rt, name: str) -> str:
        """«console, port 47654» / «session <login>, port 47655» — the window's words."""
        try:
            values = rt.profiles.load(name) or {}
        except Exception:                    # noqa: BLE001 — a reading
            values = {}
        port = values.get("daemon_port") or ""
        user = str(values.get("rdp_user") or "") if values.get("rdp_session") else ""
        if user:
            return rt.t("session.client.session", user=user, port=port)
        return rt.t("session.client.console", port=port)

    def _profiles_press(self, action: str, args: dict, profile: str | None) -> dict:
        """Open, close, rename or delete one profile — the SHELL's press, on its thread.

        A press with no name is «Создать»: the prompt's text arrives as `args.text`, and
        opening a name that has no directory yet is what creates it — the same thing the
        window's combo has always done and the command line before it.

        THE TYPED WORD IS THE CONFIRMATION for the two destructive ones (#1976), and it
        is checked HERE rather than in the shell because only this side knows what the
        row said: a delete happens when the profile's own name is typed back and never
        otherwise, and a rename needs a new name to be a rename at all. Both are the
        same guard the character switch uses on «Аккаунты» — a mis-tap on a list is what
        it is for, and «press it again» is no answer when the press removes an account's
        whole history.
        """
        if action not in profilectl.BY_ID:
            return {"error": "unknown"}
        if not profilectl.available():
            return {"ok": False, "reason": "web.ui.refused"}
        text = str(args.get("text") or "").strip()
        name = str(args.get("name") or "").strip() or text
        if not name:
            return {"ok": False, "reason": "web.ui.refused"}
        if action == profilectl.DELETE and text != name:
            return {"ok": False, "reason": "profile.confirm.refused"}
        if action == profilectl.RENAME and (not text or text == name):
            return {"ok": False, "reason": "profile.confirm.refused"}
        rt = self._runtime(profile)
        box: dict = {}
        done = threading.Event()

        def go() -> None:
            try:
                box["ok"] = profilectl.carry_out(action, name, text)
            finally:
                done.set()

        # HANDED OVER, NOT WAITED FOR ON A SHORT LEASH. Opening a profile builds a page
        # and its tabs — seconds, deliberately staged — so the answer that matters is
        # «принято, идёт» rather than a timeout dressed up as a refusal (#1331).
        self._hand_over(rt, go)
        if not done.wait(PRESS_TIMEOUT_SEC):
            return {"ok": True, "pending": True, "name": name}
        if not box.get("ok"):
            return {"ok": False, "reason": "web.ui.refused"}
        return {"ok": True, "name": name}

    def _language_view(self, profile: str | None = None) -> dict:
        """Which language the panel speaks, and the ones it could.

        THE LIST IS THE FOLDER, exactly as it is in the window: there is no table of
        languages anywhere in the code, so a twelfth locale file is a twelfth choice
        here with nothing to edit (`panel/i18n.py`). Each option is labelled with what
        that language calls ITSELF — data, not a key: «Русский» is not a word of the
        panel's to translate.
        """
        rt = self._runtime(profile)
        i18n = rt.i18n
        options = [{"value": lang, "text": i18n.name(lang)} for lang in i18n.available()]
        return {"id": LANGUAGE_SCREEN, "title": "menu.language",
                "cards": [{"title": "menu.language",
                           "fields": [{"key": "language", "label": "menu.language",
                                       "kind": "choice", "value": i18n.lang,
                                       "options": options}]}]}

    def _language_press(self, action: str, args: dict, profile: str | None) -> dict:
        """Switch the panel's language — EVERY open profile, as the window's menu does.

        On the Tk thread, because switching re-renders every registered widget
        (`Translator.retranslate`). The write is `set_lang`'s own; nothing here saves a
        second copy of the choice.
        """
        if action != "set" or str(args.get("key") or "") != "language":
            return {"error": "unknown"}
        lang = str(args.get("value") or "").strip()
        rt = self._runtime(profile)
        if lang not in rt.i18n.available():
            return {"ok": False, "reason": "web.ui.refused"}
        box: dict = {}

        def go() -> None:
            workspace = getattr(rt, "workspace", None)
            if workspace is not None and hasattr(workspace, "set_language"):
                box["moved"] = bool(workspace.set_language(lang))
                return
            # A tab launched on its own, or a test: one translator and no workspace.
            moved = rt.i18n.set_lang(lang)
            if moved:
                rt.i18n.retranslate()
            box["moved"] = bool(moved)

        self._on_tk(rt, go)
        return {"ok": True, "unchanged": not box.get("moved")}

    def _autostart_press(self, action: str, profile: str | None) -> dict:
        """The same switch the window's «Автозапуск» dialog has, and nothing it has not.

        Runs `schtasks` on THIS thread — the window does the same on the Tk thread with
        no hand-over of its own (`autostart_dialog.py`), so a subprocess of a few tens of
        milliseconds costs the HTTP worker no more than it costs the event loop.
        """
        if action not in ("enable", "disable"):
            return {"error": "unknown", "detail": action}
        rt = self._runtime(profile)
        want = action == "enable"
        try:
            autostartmod.set_enabled(rt.profiles, want)
        except RuntimeError as exc:
            said = i18nmod.translated(rt.t, exc)
            rt.say("autostart", "log.autostart.failed", error=said)
            return {"ok": False, "reason": said}
        if want:
            rt.say("autostart", "log.autostart.on",
                  profiles=", ".join(autostartmod.open_set(rt.profiles)))
        else:
            rt.say("autostart", "log.autostart.off")
        return {"ok": True}

    def press(self, screen_id: str, action: str, args: dict,
              profile: str | None = None) -> dict:
        """One press on a tab's screen, on the Tk thread — the tab's own handler.

        THREE ANSWERS, AND THEY ARE NOT THE SAME THING (#1331). A press may have been
        carried out (``ok``), may have been refused for a reason the tab knows (``ok``
        false, with what it said), or may name something this panel has no press for
        (``error: unknown``, a 404). It used to be able to answer the last of those to
        the first of the cases: the handler was run on the Tk thread and waited for
        1.5 s, and a press that took longer — measured at 6–28 s while `play_async`
        still took the daemon's lease on the calling thread — fell out of the wait with
        an empty box and was reported as an unknown action. The scenario then ran. A
        panel that says «ошибка» about a press that worked is worse than one that says
        nothing, because the person presses it again.

        So the hand-over does not decide the answer any more. The press is POSTED to the
        Tk thread and this waits :data:`PRESS_TIMEOUT_SEC` for it; running out means
        «принято, идёт» — the press is on the queue and the page says so — never that
        the panel did not understand it. Nothing is cancelled by the wait ending.
        """
        if screen_id == SERVERS_SCREEN:
            return self._servers_press(action, args or {}, profile)
        if screen_id == AUTOSTART_SCREEN:
            return self._autostart_press(action, profile)
        if screen_id == LANGUAGE_SCREEN:
            return self._language_press(action, args or {}, profile)
        if screen_id == PROFILES_SCREEN:
            return self._profiles_press(action, args or {}, profile)
        rt = self._runtime(profile)
        tab = rt.tabs.get(screen_id)
        if tab is None or not getattr(type(tab), "WEB_SCREEN", False):
            return {"error": "unknown", "detail": screen_id}
        box: dict = {}
        done = threading.Event()

        def go() -> None:
            try:
                rt.tabs.realize(tab)     # the same draw-before-asking as `screen`
                box["result"] = tab.web_press(action, args or {})
            except Exception as exc:     # noqa: BLE001
                box["result"] = {"error": "failed", "detail": str(exc)}
            finally:
                done.set()

        self._hand_over(rt, go)
        if not done.wait(PRESS_TIMEOUT_SEC):
            return {"ok": True, "pending": True}
        result = box.get("result")
        if not isinstance(result, dict):
            # A handler that answered nothing at all did still run. «Ok» is the honest
            # reading of that, and a tab owes the phone a better one — never a 404, which
            # would mean the press does not exist.
            return {"ok": True}
        return result

    def power(self, on: bool, profile: str | None = None) -> dict:
        """«Профиль работает» from the phone — the same switch the window's box is (#1882).

        Handed to the Tk thread because the switch IS a widget: a profile that is open in
        the window has its knob in front of the file, so a write that only touched the
        file would be undone by the next save (`panel/runtime/settings.py`). With no
        window — a tab launched on its own — `_on_tk` runs it here and the file is the
        switch.

        The vocabulary the front-ends share: `ok` it moved, `unchanged` it was already
        where the press asked for. Never «unavailable»: unlike the button it replaced,
        this one applies whichever way the profile currently is.
        """
        rt = self._runtime(profile)
        box: dict = {}
        self._on_tk(rt, lambda: box.__setitem__("moved", powermod.set_on(rt, bool(on))))
        return {"ok": True, "on": bool(on), "unchanged": not box.get("moved")}

    def watchdog(self, on: bool, profile: str | None = None) -> dict:
        """«Поднимать игру при падении» from the phone — the window's own box (#1882).

        Handed to the Tk thread for the reason every knob is: an open profile keeps its
        value in a Tk variable and the shell writes the whole snapshot out, so a write
        that only touched `config.json` is undone by the next save. Same vocabulary as
        the switch above — `ok` it moved, `unchanged` it was already there.
        """
        rt = self._runtime(profile)
        box: dict = {}
        self._on_tk(rt, lambda: box.__setitem__(
            "moved", optswitch.set(rt, "watchdog", bool(on))))
        return {"ok": True, "on": bool(on), "unchanged": not box.get("moved")}

    # -- ending what is playing ----------------------------------------------
    def interrupt(self, profile: str | None = None) -> dict:
        """«Прервать» from the phone — the same press the window's footer makes (#1300).

        NOT handed to the Tk thread, unlike «Включить обратно» above, and that is the
        point: the register sets flags under its own lock and the log is written from
        worker threads all day, so the press lands from this HTTP worker in microseconds.
        A Stop that first has to queue behind whatever is painting is a Stop that arrives
        when it is no longer needed.

        `count` is how many runs were asked to stop — zero is a perfectly good answer and
        not an error: the phone may have been in a pocket since the scenario ended. What
        the press cannot do is unsend a call already in the game's hands, and the log line
        each profile writes says so in words.
        """
        return interruptmod.request(self._runtime(profile))

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
            if path == "/api/triggers":
                return 200, self.triggers(who)
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
            if path == "/api/timers/now":
                return _answer(self.set_timer_immediate(
                    name, bool(body.get("immediate")), who))
            if path == "/api/timers/edit":
                return _answer(self.edit_timer(
                    str(body.get("name") or ""),
                    interval_sec=body.get("interval_sec"),
                    weekdays=body.get("weekdays"), profile=who))
            if path == "/api/timers/save":
                return _answer(self.save_timer(
                    name=str(body.get("name") or ""),
                    original=str(body.get("original") or ""),
                    title=body.get("title"), interval_sec=body.get("interval_sec"),
                    retry_sec=body.get("retry_sec"), weekdays=body.get("weekdays"),
                    args=body.get("args"), steps=body.get("steps"), profile=who))
            if path == "/api/timers/copy":
                return _answer(self.copy_timer(name, who))
            if path == "/api/timers/delete":
                return _answer(self.delete_timer(name, who))
            if path == "/api/timers/run":
                return _answer(self.run_timer(name, who))
            if path == "/api/triggers/set":
                return _answer(self.set_trigger(name, bool(body.get("enabled")), who))
            if path == "/api/triggers/now":
                return _answer(self.set_trigger_immediate(
                    name, bool(body.get("immediate")), who))
            if path == "/api/actions/run":
                return _answer(self.run_action(name, who, body.get("args") or {}))
            if path == "/api/game":
                return _answer(self.game(str(body.get("action") or ""), who))
            if path == "/api/panel":
                return _answer(self.panel(str(body.get("action") or ""), who))
            if path == "/api/power":
                return _answer(self.power(bool(body.get("on")), who))
            if path == "/api/watchdog":
                return _answer(self.watchdog(bool(body.get("on")), who))
            if path == "/api/interrupt":
                return _answer(self.interrupt(who))
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
    def _hand_over(rt, func) -> None:
        """Put ``func`` on the Tk thread WITHOUT waiting for it — or run it here.

        The press half of :meth:`_on_tk`. The caller does its own waiting, so it can
        tell «it finished» from «it is still going» — which :meth:`_on_tk` cannot,
        because a timeout there is indistinguishable from a call that never ran.

        A press is never dropped: with no window (a tab launched on its own, a test) or
        on the Tk thread already, it happens here and now.
        """
        root = getattr(rt, "root", None)
        if root is None or threading.current_thread() is threading.main_thread():
            func()
            return
        try:
            rt.tick.post(func)
        except Exception:                    # noqa: BLE001 — the window is going away
            func()

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

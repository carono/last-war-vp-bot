"""What the phone may ask the panel, as JSON — and nothing the panel cannot already do.

The web front-end is the same kind of thing every tab is: it SHOWS what the runtime
holds and PRESSES what the runtime already presses. It runs no scenario of its own, it
assembles no Lua, it holds no gate — `CLAUDE.md` is binding on that, and the shape of
this file is what keeps it honest. Every route below is one call onto a
:class:`~panel.runtime.host.PanelRuntime`:

    /api/profiles   which accounts this window has open      rt.workspace
    /api/state      what one profile is doing right now      rt.game, rt.activity
    /api/screen     one tab's own page, and the base's stock  rt.tabs, rt.resources
    /api/game       start / close / restart the client       rt.play_async, via
                                                             runtime/game_control.py
    /api/panel      put the PANEL back on the code on disk   runtime/panel_control.py
    /api/overlay    the buttons drawn over the client's window runtime/overlay.py
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
from .. import profile as profilemod
from .. import timers as timersmod
from .. import triggers as triggersmod
from ..runtime import autostart as autostartmod
from ..runtime import errand_stats as statsmod
from ..runtime import errand_art as artmod
from ..runtime import game_control, game_process, overlay as overlaymod
from ..runtime import panel_control, provision
from ..runtime import updates
from ..runtime import interrupt as interruptmod
from ..runtime import opt_switch as optswitch
from ..runtime import profile_control as profilectl
from ..runtime import power as powermod
from ..runtime.actions import list_actions
from ..runtime.log import severity_of, strip_ansi, tag_of
from . import coordlinks

#: How long one answer of the process probe is reused. The scan walks every process on
#: the machine, which is tens of milliseconds of cold psutil and has already cost this
#: panel a visibly frozen window once (#1211); a phone polling every two seconds must
#: not repeat it, and with two profiles open it would otherwise do it twice. Well under
#: the time anything it reports actually changes.
STATUS_TTL_SEC = 5.0

#: How long a screen the phone has stopped asking about still counts as OPEN.
#:
#: THE WEB HAD NO «SOMEBODY IS LOOKING» AT ALL until #2393, and that is a whole class of
#: hole rather than one tab's bug. A tab takes the reading that fills its screen in
#: `on_show` (`panel/tabs/base.py`) and the WINDOW is what calls it — so on the panel
#: that actually farms the accounts, which has no window at all, every board whose
#: numbers come from `on_show` said «неизвестно» for ever. «Гонка вооружений» is where it
#: was noticed: the phase running now is the one thing that card is for, and the events
#: board had not been read since the last time a window was open on the machine.
#:
#: So opening a screen IS the look, and closing it IS the leave — which is exactly what
#: «Read once, then LISTEN» allows: a person asking for a page is a press, and nothing
#: keeps reading once the page is gone. The phone re-asks `/api/screen` every couple of
#: seconds while a page is up, so a gap longer than this is somebody having navigated
#: away, put the phone down, or closed the tab.
LOOK_GAP_SEC = 30.0

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
#: Asked of that module rather than spelled again: the SERVICE sends presses to this
#: screen too (`panel/service/keeper.py::adopt`, #2068), and it cannot import this file.
PROFILES_SCREEN = profilectl.SCREEN

#: Routes that answer for the PANEL rather than for one of its accounts, and are
#: therefore answered whatever profile the request names — see `WebApi._not_mine`.
PANEL_WIDE = ("/api/profiles", "/api/theme", "/api/i18n")


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
        #: Which screens the phone is LOOKING at: `(profile, screen)` -> `(rt, tab, at)`.
        #: An entry appears when a screen is opened and goes when it has not been asked
        #: for in `LOOK_GAP_SEC` — see :meth:`_look`.
        self._looks: dict = {}
        self._looks_lock = threading.Lock()

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
                "showing": current or self.rt.profiles.active,
                # THE PALETTE, AND IT RIDES THE PANEL-WIDE ANSWER (#2061). The person's
                # words: «Цветовая тема, это настройка панели, не аккаунта» — so it is
                # read out of the panel's own settings, beside the language and the
                # remote-control block, and it travels on THIS route rather than on
                # `/api/state` because this is the one answer that is not about a
                # profile. Switching accounts therefore cannot make the page change
                # colour halfway through a sentence.
                "theme": self.theme(),
                # EVERY ACCOUNT THIS PANEL HAS, with the face, the level and the name the
                # person knows it by (#2061) — the picker is an avatar and a modal now,
                # and the person asked for «список всех доступных аккаунтов», which is
                # every profile and not only the ones that happen to be running.
                "accounts": self._accounts()}

    def _accounts(self) -> list:
        """The account list behind the header's avatar: open ones and closed ones.

        AN OPEN PROFILE DRAWS FROM THE LIVE HEADER — its own reading of the character,
        with its light beside it. A CLOSED one draws from what was written down the last
        time it WAS open (`panel/runtime/player_card.py`): there is one database for every
        account since #2025, so its name, level and face are a row away and cost neither a
        profile to open nor a client to run.

        A profile that has never been open under this version has no card yet and draws as
        its own name with no face — the honest answer, and one press from being filled in,
        because opening it is a press the phone already has (the «Профиль» screen).
        """
        from ..runtime import player_card as cardmod

        # ONE LIGHT PER PROFILE, and it rides the account it belongs to (#2061). It used
        # to be a list of its own beside this one, drawn by the chips under the header;
        # the chips are gone and the sheet draws the colour on the account's own row, so
        # a separate `lights` array would be a second copy of one verdict — the person's
        # rule for today, in their words: «лишнее убирай».
        #
        # FREE, as it always was: the LAST verdict the status poll made
        # (`panel/runtime/health.py`), never a reading taken here — a phone polling every
        # two seconds must not walk four socket tables to draw four dots.
        live = {}
        for name, rt in self.sessions():
            head = {}
            try:
                head = rt.header.state()
            except Exception:                # noqa: BLE001 — a reading, never the page
                head = {}
            live[name] = {"name": name, "open": True,
                          "nick": str(head.get("nick") or ""),
                          "level": int(head.get("level") or 0),
                          "avatar": str(head.get("avatar") or ""),
                          **self._light(rt)}
        try:
            everything = list(self.rt.profiles.list())
        except Exception:                    # noqa: BLE001 — a reading, never the page
            everything = list(live)
        out = []
        for name in everything:
            if name in live:
                out.append(live[name])
                continue
            card = cardmod.recall_for(profilemod.PROFILES_DIR, name)
            out.append({"name": name, "open": False,
                        "nick": str(card.get("nick") or ""),
                        "level": int(card.get("level") or 0),
                        "avatar": cardmod.face_link(card.get("uid", ""),
                                                    card.get("pic_ver", 0))})
        return out

    # -- the palette (#2061) -------------------------------------------------
    @staticmethod
    def theme() -> str:
        """Which of the three the panel draws in — `panel/profile.py` owns the answer."""
        try:
            return profilemod.theme()
        except Exception:                    # noqa: BLE001 — a colour, never the route
            return profilemod.DEFAULT_THEME

    @staticmethod
    def set_theme(want: str) -> dict:
        """Move it, for the whole panel. A name that is not one of the three is refused.

        No profile is involved on purpose: this is the one press on the front-end that
        is deliberately not about the account being looked at.
        """
        try:
            if not profilemod.set_theme(want):
                return {"error": "unknown"}
        except Exception as exc:             # noqa: BLE001 — a colour, never the route
            return {"ok": False, "error": str(exc)[:200]}
        return {"ok": True, "theme": profilemod.theme()}

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
        # …AND THE LOG'S COORDINATES TOO, which is where the window has had links since
        # it had a log (`panel/runtime/log_view.py`). Same marking, same parser (#1982).
        return coordlinks.mark_line({"n": number, "text": text, "tag": tag_of(text),
                                     "sev": severity_of(text)})

    @staticmethod
    def _progress(rt) -> "dict | None":
        """The lifecycle press's own steps, said in this panel's language (#2742)."""
        state = rt.progress.state()
        if not state:
            return None
        state["text"] = rt.t(state["label"]) if state.get("label") else ""
        for step in state.get("steps") or []:
            step["text"] = rt.t(step["key"], **(step.get("fmt") or {}))
        final = state.get("final")
        if final:
            final["text"] = rt.t(final["key"], **(final.get("fmt") or {}))
        return state

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
                     # HOW OLD THE SERVER'S ANSWER IS (#2061), in seconds, `-1` while it
                     # has never answered. The person asked for it in one word —
                     # «показывай» — because green rests on a moment with a five-minute
                     # shelf life, and a colour cannot carry a moment: an answer four
                     # seconds old and one four minutes old paint the same dot. Said as a
                     # number so the page words it in its own language, exactly as the
                     # header's own age already is.
                     "server_age": rt.health.state(rt.t).get("server_age", -1),
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
            # WHERE THE LIFECYCLE PRESS HAS GOT TO (#2742). `activity` beside it says
            # WHICH scenario is playing; this says what that scenario is DOING and how
            # it ended — the steps it named itself (`STEP` in the recipe), each with the
            # seconds it took, and a final point either way. Pre-translated here, the
            # same way `activity.text` is: the page draws a list, it does not compose
            # sentences. `None` when nothing has been pressed lately, and a finished run
            # stays readable for `progress.KEEP_SEC` so a person who put the phone down
            # still finds the answer.
            # THE BUTTONS DRAWN OVER THE CLIENT'S OWN WINDOW (#2768) — is the bar up,
            # and which press applies. A front-end of the panel like this page is, so
            # both of them offer the same two presses off the same table
            # (`panel/runtime/overlay.py`).
            "overlay": overlaymod.state(rt),
            "progress": self._progress(rt),
            "activity": ({"key": step.key,
                          "name": str(step.fmt.get("name") or ""),
                          "text": rt.t(step.key, **step.fmt)}
                         if step is not None else None),
            # …and NO `resources` here any more (#1990, second pass). The base's stock
            # was on this page and is now the «Профиль» screen's own card
            # (panel/tabs/profile.py). It had to move WHOLE: `BaseResources.state()` is
            # both the reading and the subscription — it raises the ear on
            # `push.resource.item.update` and marks the card as looked at — so a route
            # every open page polls every 2.5 s kept the capture alive for a card nobody
            # was necessarily reading. Asked from the tab's screen instead, the ear is up
            # exactly while somebody is looking at the stock and is given back two
            # minutes after the last look.
            # WHO IS PLAYING AND WHERE THEY ARE STANDING (#2016,
            # panel/runtime/header.py) — the strip along the top of every screen: the
            # character's name and HQ level, the warzone the client is looking at, the
            # scene (base, world map, operation) and the window on top of it. It rides
            # THIS route rather than one of its own because the strip is on screen
            # whatever page is open, so it would otherwise be a second poll at the same
            # pace for one line of text. The reading itself is paced in the runtime and
            # not here: the place is re-read at most every 10 s and the character every
            # 10 minutes, so a page polling every 2.5 s does not spend the game link on
            # a header.
            "header": rt.header.state(),
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
            #
            # `boot` IS THE PROOF, and `version` is not (#1994). The version string is
            # computed off git every time it is asked, so it changes the moment somebody
            # commits — with no restart, from the same process, running the same old code.
            # A fix was reported delivered on exactly that reading while eight panels went
            # on playing what they had imported. `boot` is a fact about THIS process
            # instead: which pid answered, when its code was imported, and the commit it
            # was imported from. Two polls that name the same pid are the same code,
            # whatever the version says.
            "panel": {"version": updates.version_text(),
                      "boot": updates.boot(),
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
        """Which OTHER OPEN profiles drive this profile's client — the alarm, cached.

        MEASURED AGAINST WHAT IS OPEN, never against every profile on disk (#2061). The
        fault this warns about is two panels farming ONE account: the lease makes them
        take turns, nothing looks broken, and one account's quota is spent on the other's
        game (#1250, #1252). That needs both of them to be RUNNING. A closed profile
        whose file happens to name the console is not doing anything to anybody — and on
        this machine four abandoned profiles name it, so the front page of the account
        that really owns the desktop carried a red warning about a collision that could
        not be occurring.

        It is the same rule the phone's own open-refusal already applies, in the same
        words: «measured against the profiles that are OPEN, never against every one on
        disk — a profile whose client nobody currently holds is free to take it»
        (`panel/headless.py::_may_open`). Two readings of one fault must not disagree.

        THE CONFIGURED CLASH IS NOT SWALLOWED, it is drawn where it is FIXED: every row
        of the «Профиль» screen says which client that profile would take and marks the
        ones that would collide (:meth:`_profiles_view`), the window's Settings page says
        it beside the boxes that set it, opening such a profile from a phone is REFUSED
        with the reason, and the boot writes it into the log. What is gone from the front
        page is an alarm about something that is not happening.

        Off disk, so it costs a couple of small reads per profile and the state route is
        polled every two seconds by every phone that has the page open. The cache is the
        status poll's, for the same reason: a profile's client changes when somebody
        edits it, not between two ticks.
        """
        when, names = self._shared.get(name, (0.0, []))
        now = time.time()
        if now - when < STATUS_TTL_SEC:
            return names
        try:
            open_now = set(self._open_names())
            names = [other for other in provision.sharing_with(rt.profiles, name)
                     if other in open_now]
        except Exception:                    # noqa: BLE001 — a reading, never the server
            names = []
        self._shared[name] = (now, names)
        return names

    def _open_names(self) -> list:
        """Every profile THIS window has open, by name.

        Off :meth:`sessions`, which is where every other answer about «what is open»
        comes from — a second way of asking would be a second answer waiting to disagree,
        and this one has to match the account list exactly. A process that is a lone tab
        rather than a window answers with its own name.
        """
        return [name for name, _rt in self.sessions()] or [self._name_of(self.rt)]

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
        # THE VERDICT IS NEVER MADE HERE, whatever happens below. It is the one the
        # status poll wrote (`panel/runtime/status.py`), and this probe is only for the
        # SENTENCE — the pid and the endpoint the poll's verdict does not carry.
        health = rt.health.current
        colour, reason = health.colour, health.reason
        running = bool(getattr(health, "running", False))
        try:
            found = game_process.probe(exe, user=user)
            running = found.running
            message = game_process.worded(found, colour == profile_health.OK, user,
                                          starting=rt.progress.starting())
        except Exception as exc:             # noqa: BLE001 — a reading, never the server
            # A SENTENCE THAT FAILED IS NOT A VERDICT (#1982 follow-up). This used to
            # answer «клиент игры не запущен» — red, «no client» — and cache it for the
            # TTL, over a light the panel had just painted green: two readings of one
            # thing, and the phone drew the wrong one. Now the failure costs the words
            # and nothing else.
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
    @statsmod.batched
    def timers(self, profile: str | None = None) -> dict:
        """Every configured errand: its switch, its period, and how it last ended.

        EVERY BLOB READ ONCE FOR THE WHOLE PAGE (#2660). A dozen of the lines below come
        off the same handful of blobs — the star list alone is read by three of them —
        and each read was a SELECT and a JSON parse of a list thousands of rows long, on
        the phone's ordinary poll.
        """
        rt = self._runtime(profile)
        # …and this is the errands page being LOOKED at (#2019) — see `triggers` below
        # and `panel/runtime/errand_reads.py`: at most one reading a minute, and only
        # while a page is actually asking.
        self._look_at_errands(rt)
        schedule = rt.schedule
        config = schedule.timer_config()
        records = schedule.store.records()
        catalogue = schedule.timer_catalogue
        pending = set(schedule.timers.pending())
        # WHAT IS OUT RIGHT NOW (#2408), by the name of the scenario rather than of the
        # row: a detached chain runs beside the schedule and is not «queued», so a card
        # offering ▶ over a hunt that is already marching would start nothing and say
        # nothing. Off the register every run goes through, so it costs no question.
        running = {getattr(run, "name", "") for run in rt.interrupts.running()}
        rows = []
        for timer in catalogue:
            if timer.name in HIDDEN_TIMERS:
                continue
            item = config.get(timer.name) or {}
            state, when = timersmod.last_attempt(records, timer.name)
            # WHAT «Гонка вооружений» IS DOING RIGHT NOW (#2635), and nothing at all for
            # every other row: the hour, its three chests, its points and the day behind
            # the «i». Nothing here asks the game — it is the last reading, kept
            # (`panel/runtime/arms_live.py`).
            arms = self._arms_card(rt, timer.name)
            rows.append({
                "name": timer.name,
                "title": self._timer_title(rt, timer),
                # …AND THE SENTENCE THE NAME WAS CUT OUT OF (#2061). The person's words:
                # «слишком длинные названия, сократи, должны быть лаконичные, а подробное
                # описание вынеси в кнопку i». A card's head is two or three words and the
                # rest lives behind the «i» — empty where the label has no short form, and
                # then the card draws no «i» at all rather than one that says the title
                # again.
                "about": self._timer_about(rt, timer),
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
                # …and whether one of its steps is running, which is what turns the
                # card's ▶ into a ■ (#2408).
                "running": any(step in running for step in timer.scenario),
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
                # THE KNOBS THIS ERRAND CARRIES (#2017) — what the gear on its row
                # opens. Empty for most rows; the ones that have any are the standing
                # orders whose rule used to be reachable only on the tab that owns the
                # list they spend.
                "options": schedule.options.fields(timer.name),
                # WHAT THIS ERRAND IS FOR, RIGHT NOW (#2019) — «+377 023 ждёт сбора»
                # under «Сбор ресурсов». Read off what the panel already has and never
                # bought with a question to the game; an errand nobody can answer for
                # free simply has no line (`panel/runtime/errand_stats.py`).
                "stat": statsmod.of(rt, timer.name),
                # …AND WHAT THE BASE PAID TODAY, IN PICTURES (#2743) — the person's
                # words: «вместо количества прогонов, красиво и ровно выводим иконки
                # ресурсов что собрали сегодня, только те, что с базы, сокращаем до
                # #.##M». Sent by the two rows about the base's own pile and empty for
                # every other errand, so no other card changes; the pictures are the
                # game's own, fetched off `/api/itemicon`, and a resource this machine
                # has no sprite for travels with an empty `icon` and draws its name.
                "res": statsmod.resources_of(rt, timer.name),
                # …AND WHETHER THAT ROW NEEDS A TALLER CARD (#2744) — the person's
                # words: «Если все ресурсы не влезут, то можно увеличить карточку в
                # полтора раза по высоте, это будет новый тип высоких карточек». The
                # panel decides and the phone draws: one card component, told which
                # shape it is in, never a second component and never a guess made from
                # the chips in the browser.
                "tall": statsmod.tall_card(rt, timer.name),
                # …AND THE DAY BROKEN UP BY PHASE, for the ONE row that has such a thing
                # (#2579). The person asked for it behind the «i»: «выводим иконками
                # каждый час события за сегодня и сколько там собрано сундуков в каждом
                # часе». Empty for every other errand, and empty here too until the day's
                # book has something in it — so the sheet grows a section rather than
                # showing an empty table.
                **arms,
                # …and the picture drawn for its card (#2019, #2340), as a NAME the
                # phone fetches once off `/api/errandicon` — a picture inside the view
                # would be tens of kilobytes on every poll of the page.
                # ONE KIND OF PICTURE, AND NO SECOND ONE (#2407). The row used to fall
                # back on the game's own SPRITE when this machine had no cover, and the
                # page drew that under a wash: two drawings of one card, told apart by
                # which files happened to be on the disk. A row with no cover now sends
                # nothing at all and the card draws the one placeholder every front-end
                # card without a picture draws.
                # …AND THE ARMS RACE WEARS THE HOUR IT IS IN (#2635) — the person's
                # words: «пусть картинка меняется в соответствии с часом гонки». The
                # game's own picture for the phase, where this machine has one; a phase
                # with no sprite keeps the errand's cover rather than borrowing another
                # phase's picture (`panel/runtime/arms_art.py`).
                "icon": (arms.get("arms") or {}).get("icon") or artmod.cover_for(timer.name),
                # …and WHERE the card crops it, which belongs to the picture rather than
                # to the stylesheet: crates sit low in one, a loaded bed high in another.
                "focus": artmod.cover_focus(timer.name),
            })
        return {"timers": rows, "profile": self._name_of(rt),
                "running": bool(getattr(schedule.timers, "running", False)),
                "time": time.time()}

    @staticmethod
    def _arms_card(rt, name: str) -> dict:
        """What «Гонка вооружений» carries beyond an errand's row — `{}` for the rest.

        Two things, and both come out of the ONE reading the panel already holds
        (`panel/runtime/arms_live.py`, #2635): `arms` is the HOUR running now — its
        name, its window, its three chests as the SERVER flags them, the points it has
        scored, the picture for its kind and how old the reading is — and `phases` is the
        whole day for the sheet behind the «i» (#2579).

        Nothing here asks the game. The reading is whatever landed last, the day's chests
        are the book the panel wrote while each hour was the current one
        (`panel/runtime/arms_book.py`), and the calendar is the six borders the server
        fixed a week ago.

        A DASH IS NOT A ZERO anywhere in it. A client that has not answered leaves the
        chests `None` and the points empty, so the card says «nobody has asked» instead
        of «nothing has been taken» — which on this card would be a lie about an hour
        that may well have paid all three.
        """
        if name != "perform_arms_race":
            return {}
        try:
            from ..runtime import arms_art, arms_book, arms_live
            from ..tabs.events import model as eventsmod

            calendar = ()
            tab = rt.tabs.get("events") if rt.tabs is not None else None
            if tab is not None:
                calendar = tab.arms().phases
            state, age = arms_live.state(rt, calendar)
            rows = arms_book.phases(rt, state.phases)
        except Exception:                # noqa: BLE001 — a card, never the page
            return {}
        out: dict = {}
        if rows:
            day = []
            for row in rows:
                kind = row.get("kind")
                day.append({"stage": row.get("stage"),
                            "label": (eventsmod.ARMS_KINDS.get(kind)
                                      or "events.arms.kind.other"),
                            "clock": (eventsmod.arms_phase_clock(row.get("start"),
                                                                 row.get("end"))
                                      if row.get("end") else ""),
                            "chests": row.get("chests"),
                            "all": row.get("all"),
                            "icon": arms_art.name_for(kind)})
            out["phases"] = day
        if state.kind is None and age is None:
            return out
        clock = ""
        for entry in state.phases:
            try:
                stage, _kind, start, end = entry
            except (TypeError, ValueError):
                continue
            if state.stage is not None and int(stage) == int(state.stage):
                clock = eventsmod.arms_phase_clock(start, end)
                break
        kind = state.kind
        out["arms"] = {
            "label": ((eventsmod.ARMS_KINDS.get(kind) or "events.arms.kind.other")
                      if kind is not None else ""),
            "clock": clock,
            # The points as the model already words them — `800 / 12000`, ungrouped,
            # because a grouped number reads to the coordinate parser as a tile (#1982).
            "points": eventsmod.arms_points(state) if state.score is not None else "",
            # One flag per chest of the hour, smallest total first; `None` where the
            # game would not say, and then the card draws no chests at all.
            "chests": ([1 if v else 0 for v in state.taken] if state.taken else None),
            "icon": arms_art.name_for(kind) if kind is not None else "",
            "until": state.seconds,
            "age": age,
        }
        return out

    def _timer_title(self, rt, timer) -> str:
        """What the row is CALLED — short, because it is a card's head (#2061)."""
        if timer.title:
            return timer.title
        return _short(rt, timer.label_key) or timer.name

    def _timer_about(self, rt, timer) -> str:
        """…and what the «i» beside it opens — the whole sentence, or nothing."""
        return "" if timer.title else _about(rt, timer.label_key)

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
            # Carried, never edited: the offset after the game's own reset is a property
            # of the ABILITY rather than a preference (`Timer.offset_sec`), and an edit
            # that dropped it would quietly move the Saturday shield to the boundary.
            offset_sec=timer.offset_sec,
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
        # SOMEBODY IS LOOKING AT THE ERRANDS (#2019) — the one place a read may be
        # booked from, at most once a minute and never while nothing is open
        # (`panel/runtime/errand_reads.py`). A LOOK, not a read: this returns at once
        # whatever the last one left.
        self._look_at_errands(rt)
        schedule = rt.schedule
        pending = set(schedule.timers.pending())
        watching = set(schedule.triggers.watching())
        rows = []
        for trig in schedule.trigger_catalogue:
            if trig.name in MOVED_TRIGGERS:
                continue
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
                "about": self._trigger_about(rt, trig),
                "enabled": bool(trig.enabled),
                # «сразу, без очереди» (#1288) — the window's row has this box, so the
                # phone has it: a control a person can read but not move is the
                # divergence CLAUDE.md forbids.
                "immediate": bool(trig.immediate),
                "poll": bool(trig.is_poll),
                "signal": "" if trig.is_poll else trig.event_pattern,
                "status": status,
                # …and its own knobs, drawn behind the gear (#2017). «rally_auto_join»
                # is the one that needed it: the squads it may send, the soldier floor
                # and the day's ceiling were all on «Ралли» and nowhere near the row
                # that says whether it is on.
                "options": schedule.options.fields(trig.name),
                # …and its own live line, where one is free (#2019).
                "stat": statsmod.of(rt, trig.name),
                # …and the base's take on the listener that watches the same pile (#2743).
                "res": statsmod.resources_of(rt, trig.name),
                # …and the same TALL shape when that row is long (#2744): the listener
                # that watches the base's pile draws the same chips as the harvest, so
                # it grows the same way rather than clipping them.
                "tall": statsmod.tall_card(rt, trig.name),
                # A LISTENER GETS A COVER TOO, on the same terms as a timer (#2370),
                # and since #2407 that is the ONLY picture a card of this page draws:
                # no cover, no sprite under a wash — a placeholder.
                "icon": artmod.cover_for(trig.name),
                "focus": artmod.cover_focus(trig.name),
            })
        # THE STANDING ORDERS THAT ARE IN NO CATALOGUE (#2017): «Автолут ★»,
        # «Автопомощь», «Автолут отрядов призрака». They are watchers a tab owns, and to
        # a person they are exactly what a trigger is — something that runs by itself
        # once it is switched on — so they are drawn among them, with the same switch
        # and the reading their own tab shows under the box.
        orders = [{"name": order.name,
                   "title": _short(rt, order.label_key) or order.name,
                   "about": _about(rt, order.label_key),
                   "enabled": order.enabled(),
                   "state": order.state_text(),
                   "hint": order.hint_key,
                   "options": schedule.options.fields(order.name),
                   "stat": statsmod.of(rt, order.name),
                   "icon": artmod.cover_for(order.name),
                   "focus": artmod.cover_focus(order.name)}
                  for order in schedule.options.orders()]
        return {"triggers": rows, "orders": orders,
                "profile": self._name_of(rt), "time": time.time()}

    @staticmethod
    def _look_at_errands(rt) -> None:
        """Say that the errands page is open, so its one reading may be booked."""
        try:
            rt.daily_reads.look()
        except Exception:                # noqa: BLE001 — a line, never the route
            pass

    def _trigger_title(self, rt, trig) -> str:
        """What the listener is CALLED — short, for the same reason (#2061)."""
        if trig.title:
            return trig.title
        return _short(rt, trig.label_key) or trig.name

    def _trigger_about(self, rt, trig) -> str:
        """…and the whole sentence behind its «i», or nothing."""
        return "" if trig.title else _about(rt, trig.label_key)

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

    def set_option(self, errand: str, key: str, value,
                   profile: str | None = None) -> dict:
        """Move one knob of one errand — the gear's own press (#2017).

        The value goes where it already lived: the owning tab's variable, or this
        profile's settings. Nothing is copied, so the tab's own page shows the new number
        the moment it is looked at. ON THE TK THREAD, because a knob's home is usually a
        widget and an HTTP worker is never on that thread.
        """
        rt = self._runtime(profile)
        done: dict = {}
        self._on_tk(rt, lambda: done.update(
            ok=bool(rt.schedule.options.write(errand, key, value))))
        if not done.get("ok"):
            return {"error": "unknown"}
        return {"ok": True, "errand": errand, "key": key}

    def set_order(self, name: str, enabled: bool,
                  profile: str | None = None) -> dict:
        """Switch one standing order that is in no catalogue on or off (#2017)."""
        rt = self._runtime(profile)
        order = rt.schedule.options.order(name)
        if order is None:
            return {"error": "unknown"}
        done: dict = {}
        self._on_tk(rt, lambda: done.update(ok=bool(order.set_enabled(enabled))))
        if not done.get("ok"):
            return {"error": "unknown"}
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

    def set_scheduler(self, on: bool, profile: str | None = None) -> dict:
        """The schedule's MASTER switch, from the phone (#2660).

        «Стоп всё» stops the scheduler thread, and until this route the only way back was
        the window's own checkbox — so a panel with no window, which is every live one,
        had a schedule that could be stopped and never started again. Through the tab
        where one is drawn, so its box and the thread cannot disagree; through the
        runtime where there is none.
        """
        rt = self._runtime(profile)
        tab = rt.tabs.get("timers")
        if tab is not None and getattr(tab, "built", True) \
                and hasattr(tab, "set_scheduler"):
            done: dict = {}
            self._on_tk(rt, lambda: done.update(ok=bool(tab.set_scheduler(on))))
            if done.get("ok"):
                return {"ok": True, "running": bool(on)}
        if on:
            rt.schedule.start()
            rt.say("timer", "timers.log.scheduler_on")
        else:
            rt.schedule.stop()
            rt.say("timer", "timers.log.scheduler_off")
        return {"ok": True, "running": bool(on)}

    def stop_timer(self, name: str, profile: str | None = None) -> dict:
        """End what THIS row is running, and nothing else (#2408).

        «Прервать» in the header stops everything the profile is doing, which is the
        wrong answer to «запустил не тем отрядом»: the golden hunt is a `DETACH`ed chain
        that lasts as long as its marches and is rarely the only thing running. Asks the
        runs of this errand's own scenarios to stop; an errand that was not running is
        answered `stopped: 0` rather than an error, because «уже не идёт» is a perfectly
        good outcome of pressing stop.
        """
        rt = self._runtime(profile)
        timer = rt.schedule.timer_catalogue.by_name(name)
        if timer is None:
            return {"error": "unknown"}
        asked = []
        for step in timer.scenario:
            asked.extend(interruptmod.stop_named(rt, step))
        return {"ok": True, "name": name, "stopped": len(asked)}

    # -- the scenarios -------------------------------------------------------
    def actions(self, profile: str | None = None) -> dict:
        """Every scenario the panel can play, titled in the panel's language.

        The LIST is the same for every profile — scenarios belong to the bot, not to an
        account — but the titles follow the language of the profile being asked about.
        """
        rt = self._runtime(profile)
        return {"actions": list_actions(lang=rt.i18n.lang)}

    def fetch_chat_photo(self, uid: str, ver: str, big: bool = False) -> dict:
        """Go and get ONE chat photograph off the game's own picture CDN.

        Asked for by the service, which serves the picture and cannot fetch it: it runs
        as LocalSystem and the far end resets its connection, while this process — an
        ordinary one in the person's own session — gets a 200 for the same address. The
        two share the disk, so all that has to travel back is whether the file is there.

        It belongs to no profile: a chat photograph is somebody else's picture, named the
        same way for every account on the machine, and it lands in the panel's own
        picture cache rather than in a profile's directory.

        NOT a sweep and not a clock — one photograph, on the request that draws it.
        """
        import chat_assets                 # `tools` is on the path in a panel process

        said = []
        got = chat_assets.photo_fetch(uid, ver, big=bool(big), log=said.append)
        if got:
            return {"ok": True}
        return {"ok": False, "reason": (said[-1] if said else "no such picture")}

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

    def stop_action(self, name: str, profile: str | None = None) -> dict:
        """Ask the runs of ONE scenario to halt — the window's «Стоп», on the phone.

        The «Сценарии» screen could start a run and not end it, so a recipe that turned
        out to be walking the wrong map had to be waited out or stopped by «Прервать»,
        which ends everything the profile is doing. This is `stop_timer`'s call for a
        scenario rather than an errand: it asks between steps, so the step in flight
        finishes and nothing is left half-sent. Nothing running is `stopped: 0` and not
        an error — «уже не идёт» is a perfectly good outcome of pressing stop.
        """
        rt = self._runtime(profile)
        if rt.actions.resolve(name) is None:
            return {"error": "unknown"}
        asked = interruptmod.stop_named(rt, name)
        return {"ok": True, "name": name, "stopped": len(asked)}

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

    # -- the buttons over the game ---------------------------------------------
    def overlay(self, action: str, profile: str | None = None) -> dict:
        """Draw the panel's buttons over the client's window, or take them away (#2768).

        The press starts and stops a HELPER PROCESS and nothing else: what the bar then
        does when a thumb lands on it is `/api/actions/run`, the same route this page
        uses. A refusal always says why — there is no desktop, this profile's client is
        in another Windows session, or the door could not be named — because «ничего не
        произошло» is the one answer nobody can act on.
        """
        rt = self._runtime(profile)
        if overlaymod.get(action) is None:
            return {"error": "unknown"}
        return overlaymod.play(rt, action)

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
        # IS THIS AN OPEN, or the same page still up? Answered before the hop, because
        # the answer decides what runs on the other side of it (#2393).
        opened = self._look(rt, screen_id, tab)

        def build() -> None:
            try:
                # DRAWN FIRST, and here rather than above because this is the Tk thread:
                # since #1215 a tab the person at the machine has not opened has no
                # widgets, and most screens are a view of them. The phone must not see
                # less than the window does — so opening a screen draws the tab, once.
                rt.tabs.realize(tab)
                if opened:
                    # …AND THE SAME THREE STEPS THE WINDOW TAKES WHEN A TAB IS SHOWN
                    # (`panel/__main__.py`, #1215): draw it, bring up what it is FOR,
                    # then let it read what its screen draws. A page opened on the phone
                    # is somebody looking at that tab, and until #2393 nothing said so —
                    # so a panel with no window never called `on_show` at all and every
                    # board that reads there stayed empty (see LOOK_GAP_SEC).
                    tab.ensure_loaded()
                    tab.on_show()
                box["view"] = tab.web_view()
            except Exception as exc:     # noqa: BLE001 — one screen, never the panel
                box["error"] = str(exc)

        self._on_tk(rt, build)
        view = box.get("view")
        if view is None:
            return {"error": "empty", "detail": box.get("error", "")}
        view["id"] = screen_id
        view["title"] = view.get("title") or type(tab).TITLE_KEY
        # EVERY COORDINATE ON IT IS A PLACE TO GO (#1982). Marked here, off the one
        # parser this repository has (`tools/lib/coords.py`), so the browser draws links
        # rather than deciding what a coordinate is — see `panel/web/coordlinks.py`.
        return coordlinks.mark_screen(view)

    def _look(self, rt, screen_id: str, tab) -> bool:
        """Note that the phone is on this screen. ``True`` when it has just been OPENED.

        The phone re-asks `/api/screen` while a page is up, so «open» is «nobody was
        asking a moment ago» — the first ask, or the first after a gap. Every other ask
        is the same page still there and must cost nothing: a look reported on each poll
        would be a read every couple of seconds, which is the background poll this
        repository forbids rather than the one press it allows.

        Whatever else has gone quiet is told it was LEFT, here, on the ask of some other
        screen — there is no clock behind this and there must not be one.
        """
        name = self._name_of(rt)
        now = time.time()
        key = (name, screen_id)
        with self._looks_lock:
            was = self._looks.get(key)
            self._looks[key] = (rt, tab, now)
            gone = [(k, v) for k, v in self._looks.items()
                    if k != key and now - v[2] > LOOK_GAP_SEC]
            for k, _v in gone:
                self._looks.pop(k, None)
        for _k, (other_rt, other_tab, _at) in gone:
            self._on_tk(other_rt, other_tab.on_hide)
        return was is None or (now - was[2]) > LOOK_GAP_SEC

    def screen_data(self, screen_id: str, kind: str, args: dict,
                    profile: str | None = None) -> dict:
        """A screen's BULK reading — the one thing a view may not carry (#2018).

        `screen` above is re-read on the phone's ordinary poll, so everything it returns
        travels every few seconds; the schematic map is tens of thousands of objects and
        would turn an open page into a steady stream. So the tab answers for it here
        instead, and the front-end decides when to ask (`panel/tabs/base.py::web_data`).

        **Not on the Tk thread**, unlike every other route that reaches a tab. That is
        the whole point of the split: this reads files and this profile's database, both
        of which take long enough to be felt, and the thread that draws four open
        profiles must not be the one waiting for SQLite. A `web_data` that touched a
        widget would be a bug in the tab, and the contract says so.
        """
        rt = self._runtime(profile)
        tab = rt.tabs.peek(screen_id)
        if tab is None or not getattr(type(tab), "WEB_SCREEN", False):
            return {"error": "unknown"}
        try:
            data = tab.web_data(kind, args or {})
        except Exception as exc:     # noqa: BLE001 — one reading, never the panel
            return {"error": "failed", "detail": str(exc)}
        if data is None:
            return {"error": "unknown"}
        return data

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
        by hand is one more row here with nothing to register.

        AN ACCOUNT HAS ONE STATE AND IT IS «WORKS OR DOES NOT» (#2068). The person's own
        words: «никаких режимов открыт/закрыт, только работает или нет». Open and closed
        are MECHANICS — a page in a notebook, a lock on a client — and offering them as
        the account's state is how somebody read «закрыт» about an account that was
        farming in another process and pressed «открыть» to be told «занято». So the row
        carries a switch called «Работает» (`panel/runtime/profile_control.py::
        set_working`) and a pill saying which of the three it is: working, working but
        something is wrong, or not working. The words for the second one are the profile's
        OWN — the same verdict the header's light draws, already in its language.

        The last open profile keeps its switch drawn and ON: a window with nothing open is
        a window with nothing in it and the workspace refuses it (#1206), so the press is
        turned down where it is carried out rather than hidden here — hiding it would make
        the one account that is running look like the one account that cannot be stopped.
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
        wanted = self._wanted_profiles()
        for name in everything:
            is_open = name in open_names
            actions = []
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
            # WOULD IT COLLIDE? Two profiles that name one client farm one account
            # between them (#1250), and this is where a person comes to give one of them
            # its own session — so the mark belongs on the row rather than on the front
            # page, which since #2061 warns only about profiles that are open TOGETHER
            # (:meth:`_shared_client`). Off the same reading both use.
            try:
                peers = provision.sharing_with(rt.profiles, name)
            except Exception:                # noqa: BLE001 — a reading, never the page
                peers = []
            state, said = self._working_state(name, is_open, name in wanted)
            items.append({
                "text": name,
                # THE ONE CONTROL AN ACCOUNT HAS (#2068), and it is a `Field` rather than
                # a control of its own: the front-end draws switches in exactly one place
                # (`panel/web/app/src/ui/FieldRow.tsx`) and a second one would be a second
                # thing to learn and a second thing to keep in step.
                "toggle": {"key": name, "label": "profile.working", "kind": "switch",
                           "value": is_open},
                "state": said,
                # WHICH CLIENT this profile drives — the one fact that decides whether it
                # farms its own account or somebody else's (#1252). A reading here as it
                # is in the window's own section.
                "detail": self._profile_client_text(rt, name),
                "note": (rt.t("web.ui.profile.shares", others=", ".join(peers))
                         if peers else ""),
                "pill": state,
                "actions": actions,
            })
        return {"id": PROFILES_SCREEN, "title": "menu.profile",
                "cards": [{"title": "menu.profile", "note": "profile.working.hint",
                           "items": items}],
                "actions": [{"id": profilectl.OPEN, "label": "profile.new",
                             "prompt": "profile.new.prompt", "value": ""}]}

    @staticmethod
    def _wanted_profiles() -> list:
        """What this machine wants farmed — the standing list, never «what is open».

        `panel/profile.py::keep_profiles` is written by a person and by nothing else
        (#2068), which is what makes it the right half of «работает»: an account that is
        wanted but has no page yet is coming up, not switched off, and the row says so
        instead of drawing a switch that flips itself back a second later.
        """
        try:
            return list(profilemod.keep_profiles() or [])
        except Exception:                    # noqa: BLE001 — a reading, never the page
            return []

    def _working_state(self, name: str, is_open: bool, is_wanted: bool) -> tuple:
        """One account's state as the three words a person reads, plus the reason.

        Green is «the panel holds it and its own verdict is green». Amber is the same
        account with anything else in its verdict — and the SENTENCE comes from that
        verdict rather than from a key here, because it carries a pid and an endpoint and
        is already worded in the profile's own language (:meth:`_light`). Grey is an
        account nobody is farming, and the reason is whether it is on its way up.
        """
        if not is_open:
            return (("profile.state.coming" if is_wanted else "profile.state.off"), "")
        rt = None
        for other, session_rt in self.sessions():
            if other == name:
                rt = session_rt
                break
        if rt is None:                       # open, and gone between two reads
            return ("profile.state.coming", "")
        light = self._light(rt)
        if str(light.get("colour") or "") == "ok":
            return ("profile.state.working", "")
        return ("profile.state.trouble", str(light.get("text") or ""))

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
        if action == "set":
            # THE SWITCH ON THE ROW (#2068) — «работает» / «не работает», which is the
            # only state an account has on this front-end now. It is carried out on the
            # Tk thread like every other press here, and it never comes back refused:
            # the wish is written first and the service brings the rest into line.
            if not profilectl.available():
                return {"ok": False, "reason": "web.ui.refused"}
            name = str(args.get("key") or "").strip()
            if not name:
                return {"ok": False, "reason": "web.ui.refused"}
            want = args.get("value")
            want = want if isinstance(want, bool) else str(want).lower() in ("1", "true", "on")
            rt = self._runtime(profile)
            box: dict = {}
            done = threading.Event()

            def flip() -> None:
                try:
                    box["said"] = profilectl.set_working(name, want)
                finally:
                    done.set()

            self._hand_over(rt, flip)
            if not done.wait(PRESS_TIMEOUT_SEC):
                return {"ok": True, "pending": True, "name": name}
            return box.get("said") or {"ok": True, "pending": True, "name": name}
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
                # A knob this press moves says «from web» in the profile's own log
                # (#1957). The label travels on a context variable and this function is
                # what crosses onto the Tk thread, so it is what carries it.
                with profilemod.writing("web"):
                    box["result"] = tab.web_press(action, args or {})
            except Exception as exc:     # noqa: BLE001
                # A CRASH IS SAID IN WORDS, AND THE INTERNALS GO TO THE LOG (#2074).
                # It used to travel as `detail`, so a tab that reached for a widget it
                # had never drawn told the person «отказано: 'PlayersTab' object has no
                # attribute '_noted'» — a sentence that names nothing they can act on
                # and hides the one thing that matters, WHICH screen and WHICH press.
                # The journal gets the type, the message and the traceback; the phone
                # gets a sentence and the name of the press it was.
                try:
                    rt.dbg("web").warning("%s: press %r raised %s: %s",
                                          screen_id, action, type(exc).__name__, exc,
                                          exc_info=True)
                    rt.say("panel", "web.ui.crashed.log", screen=screen_id,
                           action=action, error=type(exc).__name__)
                except Exception:        # noqa: BLE001 — a log, never the answer
                    pass
                box["result"] = {"ok": False, "reason": "web.ui.crashed"}
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

    def reset_resource_day(self, profile: "str | None" = None,
                           whole: bool = False, day: str = "") -> dict:
        """Forget one GAME day's take — the base's book, and the whole tally on ask.

        THE ONE DOOR THERE IS, and it has to be a door (#2747): the runtime holds both
        tallies in memory and writes them back whole on the next gain, so a row deleted
        in the database under a running panel is undone a minute later without a word.
        `panel/runtime/resource_book.py::clear_day` changes the copy and the row
        together.

        It clears ONE day and never the history beside it. The default is today's, and
        the default is the BASE's book alone — which is what the errand card of «Сбор
        ресурсов» draws.
        """
        rt = self._runtime(profile)
        book = getattr(rt, "resource_book", None)
        if book is None:
            return {"ok": False, "error": "no_book"}
        try:
            dropped = book.clear_day(day or None, whole=bool(whole))
        except Exception as exc:         # noqa: BLE001 — a reset, never the page
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **dropped}

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
        """One request, with anything it WRITES labelled as the web's (#1957).

        A settings write says where it came from in the profile's own log, and the
        label travels on a context variable — so it is put on here, once, rather than
        at each of the thirty handlers that might move a knob. A press that hops onto
        the Tk thread carries it over itself (:meth:`press`, :meth:`_on_tk`).
        """
        if method == "GET":
            return self._dispatch(method, path, query, body)
        with profilemod.writing("web"):
            return self._dispatch(method, path, query, body)

    def _dispatch(self, method: str, path: str, query: dict, body: dict) -> tuple:
        """``(status, payload)`` for one request. The server does the HTTP, this the panel.

        Split out from the handler so the whole surface can be exercised without a
        socket — tests/test_panel_web.py drives this directly and the live server only
        has to prove that a request reaches it.

        WHICH PROFILE travels the way each verb already carries things: a query parameter
        on a GET, a field on a POST body. Absent means the session the server belongs to.
        """
        if method == "GET":
            who = str(query.get("profile") or "") or None
            refused = self._not_mine(path, who, query, body)
            if refused is not None:
                return refused
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
            if path == "/api/screen/data":
                # A BULK reading, asked for on its own (#2018) — see `screen_data`.
                # Everything but `id`/`kind`/`profile` is handed to the tab as its own
                # arguments, which is how the map is narrowed to one warzone.
                extra = {k: v for k, v in query.items()
                         if k not in ("id", "kind", "profile")}
                return _answer(self.screen_data(str(query.get("id") or ""),
                                                str(query.get("kind") or ""),
                                                extra, who))
        elif method == "POST":
            who = str(body.get("profile") or "") or None
            refused = self._not_mine(path, who, query, body)
            if refused is not None:
                return refused
            name = str(body.get("name") or "")
            if path == "/api/chatphoto":
                # A PICTURE FETCHED WHERE THE NETWORK IS (#2418). The route that serves
                # chat photographs lives in the SERVICE, and the service runs as
                # LocalSystem: measured live, its own request to the game's picture CDN
                # is reset by the far end («WinError 10054») while the identical address
                # answers 200 from this session. So the service asks a panel — an
                # ordinary process in the person's own session — to go and get it, and
                # then serves the file off the disk both of them share. It is one fetch
                # for one photograph somebody looked at, exactly as if the service had
                # made it: never a sweep, never a clock.
                return _answer(self.fetch_chat_photo(
                    str(body.get("photo") or ""), str(body.get("ver") or ""),
                    bool(body.get("big"))))
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
            if path == "/api/timers/scheduler":
                return _answer(self.set_scheduler(bool(body.get("enabled")), who))
            if path == "/api/timers/stop":
                return _answer(self.stop_timer(name, who))
            if path == "/api/triggers/set":
                return _answer(self.set_trigger(name, bool(body.get("enabled")), who))
            if path == "/api/errand/option":
                return _answer(self.set_option(str(body.get("errand") or ""),
                                               str(body.get("key") or ""),
                                               body.get("value"), who))
            if path == "/api/orders/set":
                return _answer(self.set_order(name, bool(body.get("enabled")), who))
            if path == "/api/triggers/now":
                return _answer(self.set_trigger_immediate(
                    name, bool(body.get("immediate")), who))
            if path == "/api/actions/stop":
                return _answer(self.stop_action(name, who))
            if path == "/api/actions/run":
                return _answer(self.run_action(name, who, body.get("args") or {}))
            if path == "/api/game":
                return _answer(self.game(str(body.get("action") or ""), who))
            if path == "/api/panel":
                return _answer(self.panel(str(body.get("action") or ""), who))
            if path == "/api/overlay":
                return _answer(self.overlay(str(body.get("action") or ""), who))
            # …and the one press that names no profile (#2061): the palette is the
            # PANEL's, so `who` is deliberately not passed on.
            if path == "/api/theme":
                return _answer(self.set_theme(str(body.get("theme") or "")))
            if path == "/api/power":
                return _answer(self.power(bool(body.get("on")), who))
            if path == "/api/watchdog":
                return _answer(self.watchdog(bool(body.get("on")), who))
            if path == "/api/resources/reset":
                return _answer(self.reset_resource_day(
                    who, bool(body.get("whole")), str(body.get("day") or "")))
            if path == "/api/interrupt":
                return _answer(self.interrupt(who))
            if path == "/api/screen/press":
                return _answer(self.press(str(body.get("id") or ""),
                                          str(body.get("action") or ""),
                                          body.get("args") or {}, who))
        return 404, {"error": "not_found"}

    def _not_mine(self, path: str, who, query: dict, body: dict):
        """``(409, …)`` when the request names a profile THIS panel has not got (#2068).

        THE SILENT SUBSTITUTION WAS THE BUG. `_runtime` falls back to the server's own
        session when it does not recognise a name, and every route below took that
        answer without saying so — so `GET /api/state?profile=default` asked of a panel
        holding two test accounts came back **200, with one of the test accounts in it**,
        named as itself and looking perfectly healthy. A machine that had two panels up
        (one real, one left over from a check) therefore answered the person's page out
        of the wrong one, and «не открывается профиль default» was the only symptom of
        it. An answer about the wrong account is worse than no answer, because nothing
        in it says which account it is about.

        The fallback itself stays where it is useful — a request that names NOBODY still
        gets the server's own session, which is what a page that has never chosen an
        account asks for. What is refused is a request that names somebody: it is a
        question about one account and this panel cannot answer it.

        Three kinds of route are exempt, and each for a stated reason:

        * the ones that are about the PANEL and not an account — the profile list itself
          and the palette. A phone whose remembered account is on another panel must
          still be able to ask what this one has, or it can never recover;
        * `/api/i18n`, which is words. A page that cannot fetch words cannot draw the
          refusal either, and no account's state travels in a dictionary;
        * the «Профиль» screen, whose whole purpose is naming a profile this panel has
          not got — that is what opening one IS (`panel/runtime/profile_control.py`).
        """
        if not who or path in PANEL_WIDE:
            return None
        names = [name for name, _rt in self.sessions()]
        if who in names:
            return None
        if path.startswith("/api/screen"):
            wanted = str((query or {}).get("id") or (body or {}).get("id") or "")
            if wanted == PROFILES_SCREEN:
                return None
        return 409, {"error": "no_such_profile", "profile": who, "profiles": names}

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
        # LABELLED AS THE WEB'S, on whichever thread it ends up running (#1957). A
        # settings write says where it came from in the profile's log, and the label
        # travels on a context variable — which a hop onto the Tk thread does not
        # carry. So the wrapper is what crosses, not the label.
        def labelled() -> None:
            with profilemod.writing("web"):
                func()

        root = getattr(rt, "root", None)
        if root is None or threading.current_thread() is threading.main_thread():
            try:
                labelled()
            except Exception:                # noqa: BLE001 — a read, never the server
                pass
            return
        try:
            rt.tick.on_tk(labelled, timeout=TK_TIMEOUT_SEC)
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


#: The suffix a SHORT label lives under (#2061). A key that has one is drawn on the card
#: and the key itself becomes what the «i» opens; a key that has not is drawn whole and
#: gets no «i». So shortening a label is adding one string to eleven locale files, and
#: nothing in either front-end has to be told about it.
SHORT_SUFFIX = ".short"

#: …AND «session_kick» SINCE #2579, for the same reason and by the person's own words:
#: «карточку восстановления после кика тоже скрой, на главной тоже должен быть дубль,
#: если нету, то добавь». Its recovery is a press on «Состояние» now
#: (`panel/runtime/game_control.py`, the fourth control), beside the client's other
#: three — and the listener itself is untouched: it still watches, `recovery.py` still
#: does the automatic recovery, and `/api/triggers/set` still answers for the switch.
#:
#: Listeners whose card lives on ANOTHER screen and is therefore not drawn among the
#: errands (#2573). «Лог стягов» records every alliance banner for whoever is working on
#: the bot and acts on nothing, so the person moved its card to «Разработка», beside the
#: recorder and the busy grids. The order itself did not move — the schedule still owns
#: it, `/api/triggers/set` still answers for it, and the tab draws the schedule's own
#: switch rather than a second copy.
MOVED_TRIGGERS = frozenset({"rally_monitor", "session_kick"})

#: Errands whose card is NOT drawn on «Таймеры», because the same thing is already a
#: press on another screen (#2579). «Перезапуск игры» is the one: «Состояние» has the
#: client's three lifecycle buttons, and the person's words about the card here were
#: «карточку перезапуска игры скрыть, это дубль на основной странице». The row itself is
#: untouched — the schedule still owns it, it still fires, and `/api/timers/set` still
#: answers for it — so nothing is lost but the second drawing of it.
HIDDEN_TIMERS = frozenset({"restart_game"})


def _short(rt, label_key: str) -> str:
    """What a card calls this errand: its short label if there is one, else its label."""
    if not label_key:
        return ""
    said = rt.t(label_key + SHORT_SUFFIX)
    # `I18n.t` answers with the KEY when nothing is under it — the panel's own «a screen
    # full of `secret.tasks.left` is a bug report» rule — so that is what «no short form»
    # looks like here.
    if said and said != label_key + SHORT_SUFFIX:
        return said
    return rt.t(label_key)


def _about(rt, label_key: str) -> str:
    """The whole sentence behind the «i», or `""` when the card already says it all."""
    if not label_key:
        return ""
    said = rt.t(label_key + SHORT_SUFFIX)
    if not said or said == label_key + SHORT_SUFFIX:
        return ""
    return rt.t(label_key)


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

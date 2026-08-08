"""Running an `actions/*.md` scenario — the one door the panel presses through.

`CLAUDE.md` is binding: every ability of the bot is one scenario under
`src/lastwar_bot/actions/`, and the panel is a player, not a bot. This is the player's
side of that rule, made obvious and one line long, so that doing the right thing is
easier than assembling Lua or spawning a tool by hand.

It exists in the runtime rather than in a tab because three different tabs press
scenarios (Scenarios runs one, Timers runs them on a clock, Rally raises one) and
because a tab launched on its own must be able to press without the shell around it.

`script_engine`'s heavy dependencies (cv2, win32) are imported inside the interpreter,
so importing the package is cheap and a Lua-only scenario runs without them — which is
why the import here is deferred to the call.
"""
from __future__ import annotations

import contextlib
import glob
import os
import re

from . import claims
from .activity import Activity
from .interrupt import Interrupts, Stop
from .paths import SRC

#: Where the blessed (tested) scripts live; the experimental ones sit in `dev/` beside
#: them, and the non-recursive glob below deliberately skips that folder unless asked.
ACTIONS_DIR = os.path.join(SRC, "lastwar_bot", "actions")

#: Runtime plumbing rather than user-facing scenarios — hidden from the picker even
#: though the file is there. `watchdog` is ticked by the runner, not run by hand.
HIDDEN_ACTIONS = frozenset({"watchdog"})

#: The DSL primitives that need the client to be IN FRONT — it is clicked at real screen
#: coordinates, or photographed. Last War ignores `PostMessage`, so `CLICK` raises the
#: window and `FIND` screenshots it (`inputs.click(mode="foreground")`); one desktop has
#: one foreground, and two scenarios doing this at once press into each other's client.
#:
#: Everything else in the DSL is headless Lua through that profile's own daemon, which
#: is why this list is short and why zero of the blessed scenarios are on it today
#: (docs/research/multi-profile-panel.md §4.6). The guard exists so that the day one of
#: them is, it is already correct.
_VISION_RE = re.compile(r"^\s*(FIND|CLICK|CLICK_AT|PRESS|DRAG|TYPE)\b", re.IGNORECASE)


class Outcome:
    """How a scenario ended: whether it ran, and what it said if it did not.

    A scenario names its own failure — `create_rally.md` alone distinguishes six
    (no target of that level, a solo target, an unknown squad, no squad screen, the
    screen refusing the squad, everything pressed and no banner). A caller that only
    sees a bool trades all of that for "it did not work", so `play()` hands back the
    reason the scenario itself gave.

    The text is the scenario's own, and it is shown verbatim — which is what the panel
    already does with every timer's FAIL reason. The scenario is the authority on why
    it stopped; the panel's job is to repeat it, not to re-diagnose it.
    """

    __slots__ = ("ok", "reason", "ctx")

    def __init__(self, ok: bool, reason: str = "", ctx=None) -> None:
        self.ok, self.reason, self.ctx = bool(ok), reason or "", ctx

    def __bool__(self) -> bool:
        return self.ok

    def __repr__(self) -> str:
        return f"<Outcome ok={self.ok} reason={self.reason!r}>"


class ActionRunner:
    """Runs scenarios, checks them, and reads them back for the editor."""

    def __init__(self, log, claim=None, release=None, target=None,
                 activity=None, interrupts=None) -> None:
        self._log = log                   # the LogBus
        self._claim = claim               # callable(owner) -> bool, or None
        self._release = release
        # callable() -> {"game_port": int, "game_token": str, "game_user": str} —
        # WHICH client this runner's scenarios drive, under whose lease, and in which
        # Windows session it lives. See :meth:`_target_kw`.
        self._target = target
        # What is being played, for the strip along the bottom of the window
        # (panel/runtime/activity.py). A scenario is the longest thing the panel ever
        # does — a recipe with a WAIT in it holds the game for minutes — and its name
        # is the one word that says what the wait is FOR.
        self._activity = activity if activity is not None else Activity()
        # WHICH RUNS ARE IN FLIGHT, and how to end one (panel/runtime/interrupt.py).
        # THIS class is where it has to be hooked up, because this is the one door every
        # scenario goes through however it was started — a press through `play_async`, a
        # timer's multi-step errand building its own context, an auto-order calling
        # `play` on its own worker. A register hung on any of those would stop that one
        # and leave the others unstoppable, which is exactly the state «Стоп всё» was in.
        self._interrupts = interrupts if interrupts is not None else Interrupts()

    def _target_kw(self) -> dict:
        """The client this runner presses into, as keyword arguments for a context.

        Without it the interpreter falls back to the environment, which names ONE
        daemon for the whole process — so a profile on a non-default port pressed its
        scenarios into the console session's client while its captures and its children
        correctly drove the other one, and two profiles open at once could not both be
        right at all (#1206). A runner built without a target keeps the old behaviour,
        which is what a bare harness wants.

        `game_user` is the third of them and the one a LAUNCH could never use: it names
        the Windows session the client lives in, which is what `START_GAME` needs and
        what the port cannot say — a client that is not running yet has no daemon
        attached to it (#1218). Absent means this desktop, so it is left out rather
        than sent as an empty string.
        """
        if self._target is None:
            return {}
        try:
            target = self._target() or {}
        except Exception:                 # noqa: BLE001 — a read, never the run
            return {}
        return {key: target[key] for key in ("game_port", "game_token", "game_user")
                if target.get(key) is not None}

    # -- running ------------------------------------------------------------
    def context(self, on_event=None, **kw):
        """A fresh interpreter context whose events land in the log.

        EVERY context built here carries a stop flag, whether the caller asked for one or
        not (`panel/runtime/interrupt.py`). Without it a scenario is simply unstoppable:
        the interpreter checks `ctx.cancel` at every boundary it has, and a `None` there
        means those checks do nothing — which is why until now only the one tab that
        remembered to pass an `Event` could end a run. A caller that HAS its own flag
        keeps it: the two are held together and either of them ends the run.
        """
        from lastwar_bot import script_engine
        for key, value in self._target_kw().items():
            kw.setdefault(key, value)
        kw["cancel"] = Stop(kw.get("cancel"))
        return script_engine.new_context(
            on_event=on_event if on_event is not None else self._log.put, **kw)

    def run(self, name: str, args: dict | None = None, *, hwnd: int = 0,
            ctx=None, on_event=None, tag: str = "action", **kw) -> bool:
        """Play the named scenario. ``True`` if it ran to the end.

        ``kw`` reaches `script_engine.run_action` untouched — that is where `profile`
        and `cancel` go, and where a new interpreter option arrives without this class
        having to learn about it first.

        THE CONTEXT IS ALWAYS BUILT HERE, even when the caller passed none, because a run
        that nobody holds a context for is a run nobody can stop or describe: the stop
        flag and the step the run has reached both live on it (:meth:`context`). And the
        run is entered in the register for exactly as long as it lasts, so «Прервать»
        reaches it whoever started it.

        ``False`` without playing anything when the context has ALREADY been interrupted.
        That is the multi-step errand: the schedule shares one context across an errand's
        steps, and the steps behind the one that was stopped must not be played into
        whatever made somebody press the button.
        """
        from lastwar_bot import script_engine
        if ctx is None:
            # `on_event` may arrive either as the named argument or inside `kw` (this
            # signature has taken both since long before the register) — popped either
            # way, so the context is never handed two of them.
            spare = kw.pop("on_event", None)
            ctx = self.context(on_event=on_event if on_event is not None else spare,
                               hwnd=hwnd, variables=args or {}, **kw)
        elif getattr(ctx, "cancelled", False):
            self._log.say(tag, "interrupt.dropped", name=name)
            return False
        with self._foreground(name) as held:
            if held is not None:
                self._refused(name, held, ctx)
                return False
            with self._activity.step("activity.action", name=name):
                with self._registered(name, tag, ctx):
                    ok = bool(script_engine.run_action(name, hwnd=hwnd,
                                                       variables=args or {}, ctx=ctx))
        if getattr(ctx, "cancelled", False):
            # IT REALLY STOPPED. Said separately from «прерываю», because between the two
            # there can be seconds — a run inside a call into the game notices only when
            # the call comes back — and the difference between «asked» and «done» is the
            # whole reason a person presses a Stop twice.
            self._log.say(tag, "interrupt.halted", name=name)
        return ok

    @contextlib.contextmanager
    def _registered(self, name: str, tag: str, ctx):
        """Hold this run in the register for as long as it is running.

        In a `finally`, like every lock in this codebase that has ever been left taken:
        a run that stayed on the register after ending would be «прервать» pressing a
        flag nobody reads, and the button would say it stopped something for the rest of
        the session.
        """
        flag = getattr(ctx, "cancel", None)
        if not hasattr(flag, "set"):
            # A context built straight off `script_engine.new_context` — a test, a caller
            # older than :meth:`context`. It gets a flag now rather than being left
            # unstoppable, and whatever it was carrying is kept.
            flag = Stop(flag)
            try:
                ctx.cancel = flag
            except Exception:                # noqa: BLE001 — a register, never the run
                pass
        run = self._interrupts.enter(name, tag, ctx, flag)
        try:
            yield run
        finally:
            self._interrupts.leave(run)

    # -- the desktop's one foreground (#1226) --------------------------------
    @contextlib.contextmanager
    def _foreground(self, name: str):
        """Hold the desktop's foreground for ``name``, if ``name`` needs it.

        Yields ``None`` when the scenario may run, and the NAME OF THE HOLDER when
        another profile is already clicking at real screen coordinates. Two things
        make this cheap enough to leave in the path of every run: a scenario that is
        headless Lua — which is all of the blessed ones — never asks at all, and a
        profile whose client is in its own Windows session is exempt, because its
        desktop is its own (docs/research/multi-profile-panel.md §4.6).
        """
        if not self.needs_foreground(name):
            yield None
            return
        with claims.Foreground(self._owner(name), exempt=self._own_desktop()) as fg:
            yield fg.taken

    def _own_desktop(self) -> bool:
        """Does this runner drive a client on a desktop of its OWN? (An RDP profile.)"""
        return bool(self._target_kw().get("game_user"))

    def _owner(self, name: str) -> str:
        who = getattr(self._activity, "name", None)
        return f"{who}/{name}" if who else name

    def _refused(self, name: str, held: str, ctx) -> None:
        """Say the run did not happen, and why, in the two places that ask."""
        self._log.say("action", "busy.foreground", owner=held, name=name)
        if ctx is not None and not getattr(ctx, "fail_reason", ""):
            try:
                ctx.fail_reason = f"foreground held by {held}"
            except Exception:             # noqa: BLE001 — a reason, never the refusal
                pass

    @staticmethod
    def needs_foreground(name: str) -> bool:
        """Does the named scenario click or look at the screen?

        Read off the FILE rather than the parsed tree: this is asked before every run,
        the answer is a property of the text, and parsing costs more than a scan of a
        few dozen lines. A scenario that cannot be read at all is treated as headless —
        the run is about to fail on the same missing file and will say so properly.
        """
        from lastwar_bot import script_engine
        path = script_engine.resolve_action(name)
        if path is None:
            return False
        try:
            with open(path, encoding="utf-8") as fh:
                return any(_VISION_RE.match(line) for line in fh)
        except OSError:
            return False

    def play(self, name: str, args: dict | None = None, *, hwnd: int = 0,
             on_event=None, cancel=None, **kw) -> Outcome:
        """Play the named scenario and report HOW it ended, not just whether.

        Use this wherever the answer to "why not?" is worth showing. `run()` stays for
        the callers that only branch on success.

        ``cancel`` is named rather than left to ``kw`` because it has to reach the
        CONTEXT: `run_action` only reads its own `cancel` when it is building one, and
        this method always builds it. A Stop that quietly did nothing would be worse
        than no Stop at all.
        """
        ctx = self.context(on_event=on_event, hwnd=hwnd, variables=args or {},
                           cancel=cancel)
        ok = self.run(name, args, hwnd=hwnd, ctx=ctx, **kw)
        reason = str(getattr(ctx, "fail_reason", "") or "").strip()
        if not reason and getattr(ctx, "cancelled", False):
            # An interrupted run left no FAIL reason — it never reached one — and «no
            # reason given» would read as a scenario that broke silently. The halt reason
            # is the honest one, and it is the same sentence the log carries.
            reason = str(getattr(ctx, "halt_reason", "") or "").strip()
        return Outcome(ok, reason, ctx)

    def run_text(self, text: str, *, ctx=None, label: str = "cmd",
                 on_event=None, tag: str = "cmd") -> bool:
        """Play DSL source that is not (yet) a file — the typed command line.

        On the register like a scenario, and for the same reason: a typed `WAIT 300` is
        every bit as long as one in a file, and a command line nobody can stop is a hung
        panel with a good explanation.
        """
        from lastwar_bot import script_engine
        if ctx is None:
            ctx = self.context(on_event=on_event)
        elif getattr(ctx, "cancelled", False):
            self._log.say(tag, "interrupt.dropped", name=label)
            return False
        with self._activity.step("activity.cmd"):
            with self._registered(label, tag, ctx):
                ok = bool(script_engine.run_text(text, ctx=ctx, label=label))
        if getattr(ctx, "cancelled", False):
            self._log.say(tag, "interrupt.halted", name=label)
        return ok

    @property
    def interrupts(self):
        """The register of runs in flight (panel/runtime/interrupt.py)."""
        return self._interrupts

    # -- reading and checking ------------------------------------------------
    def resolve(self, name: str):
        """Where the named scenario lives, or ``None``."""
        from lastwar_bot import script_engine
        return script_engine.resolve_action(name)

    @staticmethod
    def problem(text: str) -> "str | None":
        """The first parse error in DSL source, or ``None`` if it is sound.

        The editor calls this before it saves, and the run button before it runs: a
        scenario that cannot be parsed should say so at the keyboard, not halfway
        through driving the game.
        """
        from lastwar_bot import script_engine
        try:
            source, _defaults = script_engine.prepare_source(text, None)
            script_engine.parse_text(source)
        except Exception as exc:          # noqa: BLE001 — any parse failure is the answer
            return str(exc)
        return None


def action_titles(path: str, name: str) -> dict:
    """The title lines of one action script, by language.

    A script's first `#` line is its English title, which is why the picker read
    English while the rest of the UI was Russian. A script may now add a language
    tag to any of its leading comment lines —

        # Claim the alliance gifts — ordinary and premium
        # ru: Подарки альянса — обычные и премиальные

    — and the picker prefers the one matching the UI. Untagged is the fallback, so
    every existing script keeps working untouched and translating one is adding a
    line to it.
    """
    out: dict = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                s = raw.strip()
                if not s:
                    if out:
                        break             # the leading comment block is over
                    continue
                if not s.startswith("#"):
                    break
                body = s.lstrip("#").strip()
                if not body:
                    continue
                tag, sep, rest = body.partition(":")
                if sep and tag.strip().isalpha() and len(tag.strip()) == 2:
                    out.setdefault(tag.strip().lower(), rest.strip())
                else:
                    out.setdefault("", body)
    except OSError:
        pass
    if not out:
        out[""] = name
    return out


def list_actions(include_dev: bool = False, lang: str | None = None) -> list[dict]:
    """Enumerate the action scripts as ``{name, title, dev}``.

    The blessed ones (``actions/*.md``) always; ``actions/dev/*.md`` too when asked
    for. The dev folder is hidden by default so the picker offers only what works —
    but hiding it also hid `work_treasure` and `collect_trucks`, and reaching those
    used to be a code change rather than a checkbox.

    `title` is the script's own title line, in the UI's language when the script
    offers one (see :func:`action_titles`), falling back to the untagged line and
    then to the bare file stem.
    """
    paths = sorted(glob.glob(os.path.join(ACTIONS_DIR, "*.md")))
    if include_dev:
        paths += sorted(glob.glob(os.path.join(ACTIONS_DIR, "dev", "*.md")))
    out = []
    for path in paths:
        name = os.path.splitext(os.path.basename(path))[0]
        if name in HIDDEN_ACTIONS:
            continue
        titles = action_titles(path, name)
        title = titles.get(lang or "") or titles.get("") or name
        out.append({"name": name, "title": title,
                    "dev": os.path.basename(os.path.dirname(path)) == "dev"})
    return out

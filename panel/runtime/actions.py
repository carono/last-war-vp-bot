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


class ActionRunner:
    """Runs scenarios, checks them, and reads them back for the editor."""

    def __init__(self, log, claim=None, release=None) -> None:
        self._log = log                   # the LogBus
        self._claim = claim               # callable(owner) -> bool, or None
        self._release = release

    # -- running ------------------------------------------------------------
    def context(self, on_event=None, **kw):
        """A fresh interpreter context whose events land in the log."""
        from lastwar_bot import script_engine
        return script_engine.new_context(
            on_event=on_event if on_event is not None else self._log.put, **kw)

    def run(self, name: str, args: dict | None = None, *, hwnd: int = 0,
            ctx=None, on_event=None, **kw) -> bool:
        """Play the named scenario. ``True`` if it ran to the end.

        ``kw`` reaches `script_engine.run_action` untouched — that is where `profile`
        and `cancel` go, and where a new interpreter option arrives without this class
        having to learn about it first.
        """
        from lastwar_bot import script_engine
        if ctx is not None:
            kw["ctx"] = ctx
        elif on_event is not None or not kw.get("on_event"):
            kw.setdefault("on_event", on_event or self._log.put)
        return bool(script_engine.run_action(name, hwnd=hwnd,
                                             variables=args or {}, **kw))

    def run_text(self, text: str, *, ctx=None, label: str = "cmd",
                 on_event=None) -> bool:
        """Play DSL source that is not (yet) a file — the typed command line."""
        from lastwar_bot import script_engine
        if ctx is None:
            ctx = self.context(on_event=on_event)
        return bool(script_engine.run_text(text, ctx=ctx, label=label))

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

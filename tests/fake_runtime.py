"""Stand-ins for the panel runtime, shared by the panel tests.

Every panel test used to hand-roll its own minimal app: an echoing `_t`, a `_tr` that
sets a widget option, a list that collects log lines, a `_daemon_port` that points
nowhere. Those ad-hoc fakes were the tab interface before there was one
(docs/research/panel-tabs-refactor.md §1) — this is that interface, written down once.

Import it rather than growing a fourth copy:

    from fake_runtime import RecordingBus

Nothing here touches the game, the daemon or the network: a fake runtime is COLD by
construction, which is also what the standalone harness hands a tab at build time.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from panel import runtime as rtmod  # noqa: E402


class RecordingBus(rtmod.LogBus):
    """A LogBus that appends every line to a list instead of queueing it.

    The panel's `_log_put` and `_say` are both faces of the bus, so a stand-in that
    collects lines has to collect them HERE — one list, whichever door the line came
    through, exactly as the real panel has one sink.
    """

    def __init__(self, translate=None, lines: list | None = None) -> None:
        super().__init__(translate=translate)
        self.lines = [] if lines is None else lines

    def put(self, line: str) -> None:
        self.lines.append(line)


def attach_binder(app, settings: dict | None = None, defaults: dict | None = None):
    """Give ``app`` a settings binder holding ``settings``, and return it.

    With no widgets attached the saved dict IS the answer, which is what a stand-in
    wants: the knobs read exactly what the profile says, bounds and defaults included.
    ``defaults`` falls back to the panel's own SETTINGS_DEFAULTS, so a stand-in that
    never opened the Settings page behaves as an untouched profile does.
    """
    if defaults is None:
        import panel.__main__ as pm
        defaults = pm.SETTINGS_DEFAULTS
    binder = rtmod.SettingsBinder(profiles=None, defaults=defaults)
    binder.values = dict(settings or {})
    app._binder = binder
    return binder


def attach_bus(app, lines: list | None = None) -> RecordingBus:
    """Give ``app`` a recording bus wired to its own `_t`, and return it.

    ``app.logs`` ends up being the same list the bus writes to, so a test that already
    asserts on ``app.logs`` keeps working unchanged.
    """
    bus = RecordingBus(translate=getattr(app, "_t", None),
                       lines=lines if lines is not None else getattr(app, "logs", None))
    app._logbus = bus
    app.logs = bus.lines
    return bus


# ---------------------------------------------------------------------------
# a whole runtime, cold
# ---------------------------------------------------------------------------
class ColdGameLink:
    """A game link that refuses everything, and remembers being asked.

    "Refuses" is the honest model of a standalone tab before anything is running: no
    daemon, no client, no network. `asked` is what the contract test reads to prove a
    tab's `build()` did not touch the game.
    """

    def __init__(self):
        self.asked: list = []
        self.client = None
        self.busy = False

    def port(self) -> int:
        self.asked.append("port")
        return 47999

    def up(self) -> bool:
        self.asked.append("up")
        return False

    def evaluator(self):
        self.asked.append("evaluator")
        raise ConnectionRefusedError("cold runtime: no daemon")

    def claim(self, owner="panel") -> bool:
        self.asked.append("claim")
        return False

    def release(self) -> None: ...
    def rebind(self) -> bool:
        return False

    def jump(self, x, y, server, quiet: bool = False) -> bool:
        """Walking the camera is a game action like any other — refused, and recorded."""
        self.asked.append("jump")
        return False


def cold_runtime(root, profile: str | None = None, settings: dict | None = None):
    """A PanelRuntime with the game replaced by :class:`ColdGameLink`.

    Everything else is real — the translator reads the actual locale files, the binder
    the actual defaults — so a tab built against this is built against what it will
    really be handed, minus anything that would reach the network.
    """
    import panel.__main__ as pm
    from panel.runtime import host as hostmod

    rt = hostmod.PanelRuntime(root, defaults=pm.SETTINGS_DEFAULTS)
    if settings:
        rt.settings.values = dict(settings)
    rt.game = ColdGameLink()
    rt.log = RecordingBus(translate=rt.i18n.t)
    return rt

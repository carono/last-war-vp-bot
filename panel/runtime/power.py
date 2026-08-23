"""«Профиль работает» — one switch per profile, and everything automatic asks it.

WHAT IT IS. A checkbox on «Главная» and its counterpart on the phone's «Состояние»
card. Ticked, the profile lives: its daemon comes up, its client is put back when it
dies, its timers and triggers run. Unticked, NOTHING of that happens — the client is
closed, the daemon is stopped, and nothing brings either of them back until somebody
ticks it again.

IT REPLACED TWO BUTTONS (#1882). «Стоп всё» and «Включить обратно» were the same two
acts (`panel/runtime/panic.py`) behind a state nothing remembered: the mark lived in
memory, so a panel restarted five minutes later came up starting the daemon and putting
the client back, with nothing anywhere saying that somebody had deliberately stopped
this account. A switch is the shape that cannot do that — it is a SETTING, it is written
into the profile's own `config.json`, and a panel that opens finds it exactly as it was
left.

WHY THE FLAG AND NOT THE MARK IS THE TRUTH. Because there were two states to keep in
step — «somebody pressed stop» and «the daemon is down» — and the ways they could
disagree were the whole of #1393 and #1262. Now there is one: the flag says whether this
profile may do anything, `panel/runtime/gate.py` reads it beside the daemon's own
liveness, and every detector that acts by itself — the schedule, the triggers, the
watchdog, the recovery — asks that one gate. A daemon somebody starts by hand while the
switch is off therefore opens nothing: the gate is shut on the flag, not on the port.

PER PROFILE, LIKE EVERY OTHER ACCOUNT-SHAPED THING (`CLAUDE.md`). One of these lives on
each :class:`~panel.runtime.host.PanelRuntime` and reads that profile's own settings
binder, so one account being switched off says nothing whatever about the other.

WRITING IT IS THE TK THREAD'S. The knob is a widget (`panel/runtime/settings.py`), and a
widget is written where widgets are written; the ACTS the flip causes are handed to a
worker by `panel/runtime/panic.py`, because closing a client takes seconds and stopping
a daemon waits for a port. The phone reaches the same door through
`panel/web/api.py::power`, which hands the write over to the Tk thread exactly as every
other press from outside does.
"""
from __future__ import annotations

import time

from . import panic as panicmod

#: The profile's own knob — declared in `panel/runtime/settings.py::DEFAULTS`, saved by
#: the shell's ordinary auto-save, and true of a profile that has never been touched.
KEY = "profile_on"

#: …and when it was last switched OFF, so the mark can say «уже 7 часов» rather than
#: «выключен». Persisted for the same reason the flag is: a number that resets on every
#: restart is a number nobody can act on.
AT_KEY = "profile_off_at"


class _Memory:
    """A store for a runtime with no profile behind it — a test, a tab launched alone."""

    def __init__(self) -> None:
        self._v: dict = {}

    def opt(self, key: str):
        return self._v.get(key)

    def var(self, key: str):
        return None

    @property
    def values(self) -> dict:
        return dict(self._v)

    @values.setter
    def values(self, raw: dict) -> None:
        self._v = dict(raw)

    def save(self, raw: dict | None = None) -> None:
        if raw is not None:
            self._v = dict(raw)


class Power:
    """One profile's «may anything happen here at all», and since when it may not."""

    __slots__ = ("_settings", "_count")

    def __init__(self, settings=None) -> None:
        self._settings = settings if settings is not None else _Memory()
        #: How many times this session — «выключили и забыли» and «щёлкают весь день»
        #: must not look the same. Not persisted: it is about this run of the panel.
        self._count = 0

    # -- the reading ---------------------------------------------------------
    @property
    def on(self) -> bool:
        """Is this profile allowed to work? A profile that has never been touched is."""
        value = self._read(KEY)
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)

    @property
    def off(self) -> bool:
        return not self.on

    def since(self) -> float:
        """When it was switched off, or 0.0 while it is on."""
        try:
            return float(str(self._read(AT_KEY) or 0.0))
        except (TypeError, ValueError):      # a half-written knob is no timestamp
            return 0.0

    def state(self, now: "float | None" = None) -> dict:
        """What both front-ends draw. Numbers, never words (`CLAUDE.md`)."""
        now = time.time() if now is None else now
        off, since = self.off, self.since()
        return {"on": not off,
                "off_for_sec": int(now - since) if off and since else 0,
                "count": self._count}

    # -- the write -----------------------------------------------------------
    def set(self, on: bool, now: "float | None" = None) -> bool:
        """Persist the flip. ``False`` when the switch was already where it is asked for.

        The ACTS are not here — see :func:`set_on`. This is the value half, and it is
        deliberately separable: the checkbox in the window writes its own variable and
        the auto-save persists it, so what the panel needs from this door is the same
        write from a place that has no widget in front of it.
        """
        on = bool(on)
        if on == self.on:
            return False
        now = time.time() if now is None else now
        self._write(KEY, on)
        self._write(AT_KEY, 0.0 if on else now)
        if not on:
            self._count += 1
        return True

    # -- the store ------------------------------------------------------------
    def _read(self, key: str):
        try:
            return self._settings.opt(key)
        except Exception:                    # noqa: BLE001 — a reading, never the panel
            return None

    def _write(self, key: str, value) -> None:
        """The widget when there is one, the file when there is not.

        A widget beats the file everywhere else in the panel (`panel/runtime/settings.py`),
        so a write that only touched the file would be undone by the next read and lost
        by the next save. Tk thread, therefore — the caller is the checkbox's own command
        or a press handed over by `panel/web/api.py`.
        """
        settings = self._settings
        var = None
        try:
            var = settings.var(key)
        except Exception:                    # noqa: BLE001 — no binder is not a crash
            var = None
        if var is not None:
            try:
                var.set(value if isinstance(value, bool) else str(value))
                changed = getattr(settings, "changed", None)
                if changed is not None:
                    changed()
                return
            except Exception:                # noqa: BLE001 — fall through to the file
                pass
        try:
            raw = dict(settings.values)
            raw[key] = value
            settings.values = raw
            settings.save()
        except Exception:                    # noqa: BLE001 — one knob, never the panel
            pass


# -- the flip, with what it causes -------------------------------------------


def set_on(rt, on: bool) -> bool:
    """Move this profile's switch and carry it out. ``False`` when it was already there.

    Ticked: the daemon comes back, and whatever puts the client back — the six-hourly
    errand, the watchdog, the recovery — does it by itself, once. Unticked: the client is
    closed and the daemon stopped, HERE AND NOW rather than merely forbidden from being
    started again, because «выключен» has to mean the account is not playing, not that it
    will stop the next time something notices.

    Both directions go through `panel/runtime/panic.py`, which is where the two acts and
    their order live — and which puts them on a worker, since neither may be done on the
    Tk thread.
    """
    if not rt.power.set(bool(on)):
        return False
    if on:
        panicmod.resume(rt)
    else:
        panicmod.stop(rt)
    return True

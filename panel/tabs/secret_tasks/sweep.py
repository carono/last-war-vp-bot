"""«Автообъезд карты» — the wrist that keeps the passive capture fed.

The capture only learns tiles while the map moves, so something has to move it. This
walks the camera over a box around a centre, waypoint by waypoint, pass after pass,
resting between passes so the client is usable in between.

`panel/mapsweep.py` is the geometry (the serpentine waypoint list, and how long a box
takes); this is the loop around it. It was `Panel._start_sweep` / `_sweep_loop` /
`_sweep_centre` / `_sweep_rule_text`.
"""
from __future__ import annotations

import threading

from ... import mapsweep as mapsweepmod


class Sweep:
    """The camera walk, and the box it walks."""

    def __init__(self, rt, tab) -> None:
        self.rt = rt
        self.tab = tab
        self._stop = None       # threading.Event while sweeping, else None
        self._at = 0            # index of the next waypoint in the current pass
        self._pass = 0          # how many full passes are done

    @property
    def running(self) -> bool:
        return self._stop is not None

    # -- start / stop --------------------------------------------------------
    def toggle(self) -> None:
        if self.tab.sweep_var.get():
            self.start()
        else:
            self.stop()

    def start(self) -> None:
        if self._stop is not None:               # already sweeping
            return
        if self.centre() is None:
            self.tab.sweep_var.set(False)
            self.tab.say("sweep", "sweep.no_centre")
            return
        self._stop = threading.Event()
        self._at = 0
        self._pass = 0
        self.rt.put("[sweep] " + self.rule_text())
        if not self.tab.capture.running:
            # The sweep produces traffic; without the capture nobody reads it.
            self.tab.say("sweep", "sweep.no_monitor")
        threading.Thread(target=self._loop, args=(self._stop,), daemon=True).start()

    def stop(self) -> None:
        stop, self._stop = self._stop, None
        if stop is not None:
            stop.set()
            self.tab.say("sweep", "sweep.off")

    # -- the box -------------------------------------------------------------
    def centre(self) -> "tuple[int, int] | None":
        """The box's centre, or ``None`` when it has not been given one."""
        cx = self.tab.sweep_cx_var.get().strip()
        cy = self.tab.sweep_cy_var.get().strip()
        if not (cx.lstrip("-").isdigit() and cy.lstrip("-").isdigit()):
            return None
        return int(cx), int(cy)

    def box(self) -> tuple:
        """``(radius, step, dwell, rest, zoom)`` — the box, the pace, and the camera.

        THE CAMERA IS NOT A SETTING OF ITS OWN (#1265). How far back it sits and how far
        apart the waypoints go are one decision, not two — a step is meaningless without
        the height it was measured at — and that decision is the «Зум» control on the
        coordinate bar, where the person asked for it. So this reads the tab's level and
        takes both numbers from it; Settings keeps only what is genuinely about the box
        (how big) and the pace (how often).
        """
        import lua_actions
        opt = self.rt.settings
        zoom, step = lua_actions.zoom_level(getattr(self.tab, "_zoom_level", None))
        return (
            opt.opt_int("sweep_radius", low=mapsweepmod.MIN_RADIUS,
                        high=mapsweepmod.MAX_RADIUS),
            step,
            opt.opt_float("sweep_dwell", low=0.2, high=60.0),
            opt.opt_int("sweep_rest_min", low=0, high=1440) * 60.0,
            zoom,
        )

    def rule_text(self) -> str:
        """What the checkbox is about to do, in one phrase — box, jumps, minutes."""
        centre = self.centre()
        if centre is None:
            return self.tab.t("sweep.no_centre")
        radius, step, dwell, _rest, _zoom = self.box()
        jumps, seconds = mapsweepmod.describe(centre[0], centre[1], radius, step, dwell)
        return self.tab.t("sweep.rule", side=radius * 2 + 1, jumps=jumps,
                          mins=max(1, int(seconds // 60)))

    # -- the walk ------------------------------------------------------------
    def _loop(self, stop: threading.Event) -> None:
        """Walk the box, pass after pass, until the checkbox is cleared.

        The waypoint list is rebuilt at the start of each pass rather than held: the
        centre and the box are live fields, so retyping them takes effect on the next
        pass instead of needing the checkbox toggled.

        One tick is wrapped like the auto-loot watcher's: this is a background loop
        nobody is watching, so a single failed jump must cost a log line and not the
        sweep for the session.
        """
        last_err = ""
        dwell = mapsweepmod.DEFAULT_DWELL
        while not stop.is_set():
            try:
                centre = self.centre()
                if centre is None:
                    self.tab.say("sweep", "sweep.no_centre")
                    return
                radius, step, dwell, rest, zoom = self.box()
                points = mapsweepmod.waypoints(centre[0], centre[1], radius, step)
                if self._at >= len(points):
                    # A pass is done. Rest before the next one: the map does not change
                    # fast enough to be worth walking it back to back, and a gap is what
                    # lets an errand or a person use the client.
                    self._pass += 1
                    self._at = 0
                    self.tab.say("sweep", "sweep.pass_done", n=self._pass,
                                 mins=int(rest // 60))
                    if stop.wait(rest):
                        return
                    continue
                x, y = points[self._at]
                # Quiet: dozens of waypoints a pass, and one «переход / готово» pair each
                # would bury the findings the sweep exists to produce.
                #
                # Advance ONLY on a jump that really started. A refusal means an errand or
                # a button press holds the claim, and losing the waypoint would leave a
                # hole in the pass — exactly the band of tiles the sweep exists to cover.
                # It waits out the dwell and tries the same one again.
                if self.rt.game.jump(x, y, None, quiet=True, zoom=zoom):
                    self._at += 1
                last_err = ""
            except Exception as exc:      # noqa: BLE001 — one tick, not the loop
                err = f"{type(exc).__name__}: {exc}"
                if err != last_err:
                    last_err = err
                    self.tab.say("sweep", "log.sweep.error", error=err)
            if stop.wait(dwell):
                return

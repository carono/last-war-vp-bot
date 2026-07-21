"""Keep a :class:`GameState` current from a *live* capture of the game socket.

:class:`~bot.state.stream_reader.StreamReader` decodes bytes; this module is the
transport that feeds it in real time. It reuses the proven capture engine in
``tools/live_tshark`` (which drives Wireshark's ``dumpcap.exe`` from WSL) and its
``LiveDecoder`` — the only thing added here is the seam that hands each decoded
envelope to :meth:`StreamReader.apply`, so a running game continuously updates
the same passive state the offline path builds.

    from bot.state.live import LiveState

    with LiveState() as live:            # starts dumpcap, decodes in a thread
        live.wait_for(Scene.CITY, timeout=30)
        print(live.state.summary())

Windows-only at run time (needs Wireshark + npcap), so imports stay lazy and the
module loads anywhere for inspection.
"""
from __future__ import annotations

import os
import shutil
import threading
import time

from bot.core import protocol
from bot.state.game_state import GameState, Scene
from bot.state.stream_reader import StreamReader

# Where Wireshark's capture binaries live, in both path styles this bot may run
# under: WSL-Linux Python sees ``/mnt/c/...``; Windows Python sees ``C:\...``.
# ``tools/live_tshark`` only knows the ``/mnt`` form, so we resolve here and pass
# the concrete path down as an override — no duplication of the capture logic.
_WIRESHARK_DIRS = (
    "/mnt/c/Program Files/Wireshark",
    "/mnt/c/Program Files (x86)/Wireshark",
    r"C:\Program Files\Wireshark",
    r"C:\Program Files (x86)\Wireshark",
)


def _resolve_binary(name: str, override: str | None) -> str | None:
    """Locate a Wireshark binary regardless of interpreter/OS. ``None`` if absent."""
    if override:
        return override if os.path.exists(override) else None
    for directory in _WIRESHARK_DIRS:
        path = os.path.join(directory, name)
        if os.path.exists(path):
            return path
    return shutil.which(name) or shutil.which(name.removesuffix(".exe"))

# Surfaced so callers can distinguish "capture can't run here" (skip the test)
# from a genuine navigation failure. Defined in tools/live_tshark.
try:  # pragma: no cover - import shape depends on sys.path wiring
    from live_tshark import CaptureUnavailable
except Exception:  # the tools/ path is added by bot/__init__; be defensive
    class CaptureUnavailable(RuntimeError):
        """Wireshark, scapy or an interface is missing — nothing to capture."""


class LiveState:
    """Background live capture that keeps a :class:`GameState` current.

    Parameters mirror the tools' capture entry point: pin an ``interface`` or
    point at a non-default Wireshark with ``tshark`` / ``dumpcap``. Leave them
    unset to auto-discover.
    """

    def __init__(self, reader: StreamReader | None = None, *,
                 interface: str | None = None,
                 tshark: str | None = None, dumpcap: str | None = None) -> None:
        self.reader = reader if reader is not None else StreamReader()
        self._interface = interface
        self._tshark = tshark
        self._dumpcap = dumpcap
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._procs: list = []

    @property
    def state(self) -> GameState:
        return self.reader.state

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        """Begin capturing. Raises :class:`CaptureUnavailable` if it cannot."""
        import live_tshark as lt
        from live_sniffer import LiveDecoder

        tshark = _resolve_binary("tshark.exe", self._tshark)
        dumpcap = _resolve_binary("dumpcap.exe", self._dumpcap) or tshark
        if not dumpcap or not tshark:
            missing = "tshark.exe" if not tshark else "dumpcap.exe"
            raise CaptureUnavailable(
                f"{missing} not found — install Wireshark or pass its path")

        ifaces = lt.list_interfaces(tshark)
        if not ifaces:
            raise CaptureUnavailable("no capture interfaces found")
        if self._interface:
            ifaces = [(self._interface, f"iface {self._interface}")]

        reader = self.reader

        class _Bridge(LiveDecoder):
            def emit(self, direction, env):  # LiveDecoder hook
                reader.apply(protocol.Envelope.from_raw(direction, env))

        decoder = _Bridge()
        self._stop.clear()
        self._procs = []
        # "tcp" is the narrowest safe filter: the game endpoint has no stable
        # address or port and is dialled without DNS, so the flow is recognised
        # by frame shape, not by host — same choice tools/live_tshark makes.
        self._threads = [
            threading.Thread(
                target=lt.capture,
                args=(dumpcap, number, label, decoder, "tcp", self._stop, False,
                      self._procs),
                daemon=True,
            )
            for number, label in ifaces
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Killing the capture engines is what unblocks the reader threads (they
        # sit in a blocking stdout read), so kill before joining.
        for proc in self._procs:
            try:
                proc.kill()
            except Exception:
                pass
        self._procs = []
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads = []

    def __enter__(self) -> "LiveState":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.stop()

    # -- waiting -------------------------------------------------------------
    def wait_for(self, scene: Scene, timeout: float = 30.0,
                 poll: float = 0.25) -> bool:
        """Block until the live state reaches ``scene`` (or ``timeout``)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.state.scene is scene:
                return True
            time.sleep(poll)
        return self.state.scene is scene


__all__ = ["LiveState", "CaptureUnavailable"]

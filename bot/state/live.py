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

import glob
import os
import shutil
import subprocess
import tempfile
import threading
import time

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
                 tshark: str | None = None, dumpcap: str | None = None,
                 poll_interval: float = 1.5) -> None:
        self.reader = reader if reader is not None else StreamReader()
        self._interface = interface
        self._tshark = tshark
        self._dumpcap = dumpcap
        self._poll_interval = poll_interval
        self._stop = threading.Event()
        self._poller: threading.Thread | None = None
        self._procs: list = []
        self._tmpdir: str | None = None

    @property
    def state(self) -> GameState:
        return self.reader.state

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        """Begin capturing. Raises :class:`CaptureUnavailable` if it cannot.

        Each interface is captured to its own rolling pcap file with ``dumpcap``;
        a poller thread re-decodes those files through the robust offline reader
        (:meth:`StreamReader.from_pcap`) and folds the result into the shared
        state. This deliberately avoids the streaming ``live_sniffer`` decoder,
        whose mid-connection reassembly drops most of the game's frames — the very
        ``world.get.block`` markers the scene detector relies on.
        """
        import live_tshark as lt

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

        self._stop.clear()
        self._procs = []
        self._tmpdir = tempfile.mkdtemp(prefix="lwlive_")
        # One dumpcap per interface, each to its own file. The game flow is on a
        # single interface; the rest write near-empty files that decode to nothing.
        # "-b" ring-rotates so the files stay small (bounded re-decode cost) while
        # always retaining more than the scene window's worth of recent traffic.
        for number, _label in ifaces:
            base = os.path.join(self._tmpdir, f"if{number}.pcap")
            cmd = [dumpcap, "-i", str(number), "-f", "tcp",
                   "-b", "duration:5", "-b", "files:5", "-w", base]
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
            except Exception:
                continue
            self._procs.append(proc)
        if not self._procs:
            raise CaptureUnavailable("could not start any capture process")

        self._poller = threading.Thread(target=self._poll_loop, daemon=True)
        self._poller.start()

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._decode_once()
            except Exception:
                pass
            self._stop.wait(self._poll_interval)

    def _decode_once(self) -> None:
        """Re-decode every capture file and fold the freshest markers into state."""
        st = self.reader.state
        latest_world = latest_city = None
        best_ts = None
        for path in glob.glob(os.path.join(self._tmpdir or "", "*.pcap*")):
            try:
                if os.path.getsize(path) < 40:  # smaller than a pcap header
                    continue
                fresh = StreamReader.from_pcap(path)
            except Exception:
                continue  # a file mid-rotation / torn tail: retry next tick
            s = fresh.state
            if s.world_ts is not None:
                latest_world = max(latest_world or s.world_ts, s.world_ts)
            if s.city_ts is not None:
                latest_city = max(latest_city or s.city_ts, s.city_ts)
            if s.last_update_ts is not None and (best_ts is None
                                                 or s.last_update_ts > best_ts):
                best_ts = s.last_update_ts
                st.last_command = s.last_command
                st.last_update_ts = s.last_update_ts
                st.zoom = s.zoom
                if s.resources:
                    st.resources.update(s.resources)
        # Markers only ever move forward, so a ring file rotating away can't drag
        # the scene back.
        if latest_world is not None:
            st.world_ts = max(st.world_ts or latest_world, latest_world)
        if latest_city is not None:
            st.city_ts = max(st.city_ts or latest_city, latest_city)

    def stop(self) -> None:
        self._stop.set()
        for proc in self._procs:
            try:
                proc.kill()
            except Exception:
                pass
        self._procs = []
        if self._poller is not None:
            self._poller.join(timeout=2)
            self._poller = None
        if self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

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

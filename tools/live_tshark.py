#!/usr/bin/env python3
"""Live protocol decoding from WSL, using Wireshark's capture engine.

Scapy's own sniffing does not work reliably against npcap from the Windows-side
Python, but Wireshark does — and WSL can execute Windows binaries. So this
tool drives ``dumpcap.exe`` (the capture engine Wireshark itself uses), reads
the pcap stream straight off its stdout and decodes it as it arrives.

Everything protocol-related is imported from lastwar_proto.py and
live_sniffer.py — no logic is duplicated here. This module is only a transport:
Windows capture engine in, decoded commands out.

    python3 tools/live_tshark.py --list          # interfaces, with a traffic probe
    python3 tools/live_tshark.py                 # capture on every real interface
    python3 tools/live_tshark.py --iface 2       # pin one
    python3 tools/live_tshark.py --discover      # show every TCP flow, decode nothing

No Administrator prompt is needed as long as npcap was installed with the
"allow non-administrator capture" option, which is how Wireshark normally sets
it up.
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from live_sniffer import C_DIM, C_ERR, C_OK, C_RESET, LiveDecoder  # noqa: E402

WIRESHARK_DIRS = (
    "/mnt/c/Program Files/Wireshark",
    "/mnt/c/Program Files (x86)/Wireshark",
)

PCAP_MAGICS = {
    b"\xd4\xc3\xb2\xa1": ("<", 1_000_000),      # microsecond, little-endian
    b"\xa1\xb2\xc3\xd4": (">", 1_000_000),      # microsecond, big-endian
    b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000),  # nanosecond, little-endian
    b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000),  # nanosecond, big-endian
}


def find_binary(name: str, override: str | None = None) -> str | None:
    if override:
        return override if os.path.exists(override) else None
    for directory in WIRESHARK_DIRS:
        path = os.path.join(directory, name)
        if os.path.exists(path):
            return path
    return None


def list_interfaces(tshark: str) -> list[tuple[str, str]]:
    """Return [(number, label)] for real capture devices, skipping extcap ones."""
    try:
        out = subprocess.run([tshark, "-D"], capture_output=True, text=True,
                             timeout=30).stdout
    except Exception as exc:
        print(f"{C_ERR}could not list interfaces: {exc}{C_RESET}", file=sys.stderr)
        return []
    found = []
    for line in out.splitlines():
        match = re.match(r"\s*(\d+)\.\s+(\S+)\s*(?:\((.*)\))?", line)
        if not match:
            continue
        number, device, label = match.group(1), match.group(2), match.group(3) or ""
        if not device.startswith(r"\Device\NPF_"):
            continue  # ciscodump, randpkt, sshdump… are not live adapters
        found.append((number, label or device))
    return found


class PcapStream:
    """Incremental reader for the pcap byte stream dumpcap writes to stdout."""

    def __init__(self):
        self.buf = b""
        self.endian: str | None = None
        self.linktype: int | None = None

    def feed(self, chunk: bytes):
        self.buf += chunk
        if self.endian is None:
            if len(self.buf) < 24:
                return
            magic = self.buf[:4]
            if magic not in PCAP_MAGICS:
                raise ValueError(f"not a pcap stream (magic {magic.hex()})")
            self.endian, _ = PCAP_MAGICS[magic]
            self.linktype = struct.unpack(self.endian + "I", self.buf[20:24])[0]
            self.buf = self.buf[24:]
        while len(self.buf) >= 16:
            _ts, _us, incl, _orig = struct.unpack(self.endian + "IIII", self.buf[:16])
            if len(self.buf) < 16 + incl:
                return
            data = self.buf[16:16 + incl]
            self.buf = self.buf[16 + incl:]
            yield data


def capture(binary: str, iface: str, label: str, decoder: LiveDecoder,
            bpf: str | None, stop: threading.Event, verbose: bool) -> None:
    cmd = [binary, "-i", iface, "-P", "-w", "-"]
    if bpf:
        cmd += ["-f", bpf]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception as exc:
        if verbose:
            print(f"{C_DIM}iface {iface}: {exc}{C_RESET}", file=sys.stderr)
        return

    from scapy.layers.l2 import Ether

    reader = PcapStream()
    try:
        while not stop.is_set():
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            try:
                for raw in reader.feed(chunk):
                    if reader.linktype != 1:  # only Ethernet is expected here
                        continue
                    try:
                        decoder.handle(Ether(raw), label)
                    except Exception:
                        pass  # a malformed packet must not stop the capture
            except ValueError as exc:
                if verbose:
                    print(f"{C_DIM}iface {iface}: {exc}{C_RESET}", file=sys.stderr)
                break
    finally:
        proc.kill()


def probe_interfaces(dumpcap: str, ifaces, seconds: int) -> dict[str, int]:
    """Count packets per interface so the quiet ones can be reported as quiet."""
    counts: dict[str, int] = {}
    procs: list[subprocess.Popen] = []
    lock = threading.Lock()

    def run(number, label, proc):
        reader = PcapStream()
        seen = 0
        try:
            while True:
                # Blocks until dumpcap writes or is killed — an idle interface
                # never returns on its own, so the deadline is enforced by
                # killing the process, not by polling the clock here.
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                try:
                    seen += sum(1 for _ in reader.feed(chunk))
                except ValueError:
                    break
        except Exception:
            pass
        with lock:
            counts[f"{number}. {label}"] = seen

    threads = []
    for number, label in ifaces:
        try:
            proc = subprocess.Popen([dumpcap, "-i", number, "-P", "-w", "-"],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except Exception:
            continue
        procs.append(proc)
        thread = threading.Thread(target=run, args=(number, label, proc), daemon=True)
        thread.start()
        threads.append(thread)

    time.sleep(seconds)
    for proc in procs:
        proc.kill()
    for thread in threads:
        thread.join(2)
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--iface", help="interface number from --list; omitted = all of them")
    ap.add_argument("--list", action="store_true",
                    help="list interfaces and probe each for traffic")
    ap.add_argument("--discover", action="store_true",
                    help="show every TCP flow with its opening bytes, decode nothing")
    ap.add_argument("--filter", help="capture filter (BPF), e.g. 'tcp'")
    ap.add_argument("--raw", action="store_true", help="dump the full payload of each message")
    ap.add_argument("--probe-seconds", type=int, default=5, help="probe duration for --list")
    ap.add_argument("--tshark", help="path to tshark.exe")
    ap.add_argument("--dumpcap", help="path to dumpcap.exe")
    ap.add_argument("--verbose", action="store_true", help="report per-interface errors")
    args = ap.parse_args()

    tshark = find_binary("tshark.exe", args.tshark)
    dumpcap = find_binary("dumpcap.exe", args.dumpcap) or tshark
    if not tshark or not dumpcap:
        print(f"{C_ERR}Wireshark not found. Looked in:{C_RESET}", file=sys.stderr)
        for directory in WIRESHARK_DIRS:
            print(f"  {directory}", file=sys.stderr)
        print("Pass --tshark / --dumpcap explicitly.", file=sys.stderr)
        return 1

    ifaces = list_interfaces(tshark)
    if not ifaces:
        print(f"{C_ERR}no capture interfaces found{C_RESET}", file=sys.stderr)
        return 1

    if args.list:
        print(f"probing {len(ifaces)} interface(s) for {args.probe_seconds}s…\n")
        counts = probe_interfaces(dumpcap, ifaces, args.probe_seconds)
        for number, label in ifaces:
            key = f"{number}. {label}"
            seen = counts.get(key, 0)
            mark = f"{C_OK}{seen:>6} pkts{C_RESET}" if seen else f"{C_DIM}     idle{C_RESET}"
            print(f"  {mark}  {key}")
        print("\nPick one with --iface N, or run with no --iface to capture on all.")
        return 0

    targets = ([(args.iface, f"iface {args.iface}")] if args.iface else ifaces)

    decoder = LiveDecoder(discover=args.discover, show_raw=args.raw)
    stop = threading.Event()

    mode = "DISCOVER — listing every TCP flow" if args.discover else "decoding by frame shape"
    print(f"Last War live decoder via {os.path.basename(dumpcap)} — {mode}")
    print(f"interfaces: {len(targets)}   filter: {args.filter or 'none'}")
    print(f"{C_DIM}Ctrl+C to stop{C_RESET}\n")

    threads = [
        threading.Thread(target=capture,
                         args=(dumpcap, number, label, decoder, args.filter, stop, args.verbose),
                         daemon=True)
        for number, label in targets
    ]
    for thread in threads:
        thread.start()

    try:
        while not stop.is_set():
            time.sleep(0.3)
    except KeyboardInterrupt:
        stop.set()

    decoder.report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Offline analysis of a captured .pcapng — runs on the WSL side.

Reassembles TCP streams from a capture, and for every application-layer payload
tries to make sense of it:

  * `protoc --decode_raw`         (if protoc is on PATH)
  * `blackboxprotobuf.decode_message`

Plaintext HTTP/WS payloads are recorded as-is; TLS records are flagged as
encrypted (you cannot decode those from a plain pcap without keys — see
docs/research/sniffing-playbook.md §2).

Usage:
    python tools/analyze_pcap.py path/to/capture.pcapng
    python tools/analyze_pcap.py capture.pcapng --port 9339 --max-bodies 500

Output: results/analysis_<timestamp>.json

Backends: prefers pyshark (needs tshark installed); falls back to scapy.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS = REPO_ROOT / "results"

try:
    import blackboxprotobuf  # type: ignore
except Exception:
    blackboxprotobuf = None


# leading tag byte = (field << 3) | wire_type; accept wire-type 2 (len-delim)
# and wire-type 0 (varint) for field numbers 1..8 — see lastwar_mitm_addon.py.
_PROTOBUF_MAGIC = {
    0x0A, 0x12, 0x1A, 0x22, 0x2A, 0x32, 0x3A, 0x42,
    0x08, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38, 0x40,
}
_TLS_RECORD = {0x16, 0x17, 0x14, 0x15}  # handshake / appdata / ccs / alert


def classify(body: bytes) -> str:
    if not body:
        return "empty"
    b0 = body[0]
    if b0 in _TLS_RECORD and len(body) > 2 and body[1] == 0x03:
        return "tls"  # 0x16 0x03 0xNN ... = TLS record
    if body[:3] in (b"GET", b"POS", b"PUT", b"HEA", b"DEL") or body[:4] == b"HTTP":
        return "http"
    if b0 in _PROTOBUF_MAGIC:
        return "maybe_protobuf"
    return "binary"


def decode_raw_protoc(body: bytes) -> str | None:
    try:
        out = subprocess.run(
            ["protoc", "--decode_raw"],
            input=body,
            capture_output=True,
            timeout=10,
        )
        if out.returncode == 0 and out.stdout:
            return out.stdout.decode("utf-8", "replace")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return None


def decode_blackbox(body: bytes):
    if blackboxprotobuf is None:
        return None
    try:
        message, typedef = blackboxprotobuf.decode_message(body)
        return json.loads(json.dumps({"message": message, "typedef": typedef}, default=_json_default))
    except Exception:
        return None


def _json_default(o):
    if isinstance(o, bytes):
        try:
            return o.decode("utf-8")
        except UnicodeDecodeError:
            return {"__bytes_hex__": o.hex()}
    return str(o)


def iter_payloads_pyshark(pcap: str, port: int | None):
    import pyshark  # type: ignore

    disp = "tcp.payload"
    if port:
        disp = f"tcp.port == {port} && tcp.payload"
    cap = pyshark.FileCapture(pcap, display_filter=disp, use_json=True, include_raw=True)
    try:
        for pkt in cap:
            try:
                raw_hex = pkt.tcp.payload.replace(":", "")
                body = bytes.fromhex(raw_hex)
            except Exception:
                continue
            yield {
                "src": f"{pkt.ip.src}:{pkt.tcp.srcport}",
                "dst": f"{pkt.ip.dst}:{pkt.tcp.dstport}",
                "body": body,
            }
    finally:
        cap.close()


def iter_payloads_scapy(pcap: str, port: int | None):
    from scapy.all import IP, TCP, rdpcap  # type: ignore

    packets = rdpcap(pcap)
    for pkt in packets:
        if not (pkt.haslayer(TCP) and pkt.haslayer(IP)):
            continue
        tcp = pkt[TCP]
        payload = bytes(tcp.payload)
        if not payload:
            continue
        if port and port not in (tcp.sport, tcp.dport):
            continue
        yield {
            "src": f"{pkt[IP].src}:{tcp.sport}",
            "dst": f"{pkt[IP].dst}:{tcp.dport}",
            "body": payload,
        }


def choose_backend():
    try:
        import pyshark  # noqa: F401

        # pyshark needs tshark; verify it exists
        if subprocess.run(["which", "tshark"], capture_output=True).returncode == 0:
            return "pyshark"
    except Exception:
        pass
    try:
        import scapy  # noqa: F401

        return "scapy"
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Analyze a .pcapng for Last War protocol payloads")
    ap.add_argument("pcap", help="path to .pcap/.pcapng file")
    ap.add_argument("--port", type=int, default=None, help="only look at this TCP port")
    ap.add_argument("--max-bodies", type=int, default=1000, help="stop after N non-empty payloads")
    ap.add_argument("--backend", choices=["pyshark", "scapy"], default=None)
    args = ap.parse_args()

    pcap_path = Path(args.pcap)
    if not pcap_path.exists():
        print(f"error: no such file: {pcap_path}", file=sys.stderr)
        return 2

    backend = args.backend or choose_backend()
    if backend is None:
        print("error: neither pyshark (+tshark) nor scapy is available", file=sys.stderr)
        print("       pip install pyshark scapy   (and apt install tshark for pyshark)", file=sys.stderr)
        return 3

    print(f"[analyze] backend={backend} file={pcap_path} port={args.port or 'any'}")
    have_protoc = subprocess.run(["which", "protoc"], capture_output=True).returncode == 0
    if not have_protoc:
        print("[analyze] note: protoc not found — skipping --decode_raw (blackboxprotobuf still used)")
    if blackboxprotobuf is None:
        print("[analyze] note: blackboxprotobuf not installed — skipping that decoder")

    it = iter_payloads_pyshark if backend == "pyshark" else iter_payloads_scapy

    results = []
    stats = {"total": 0, "tls": 0, "http": 0, "maybe_protobuf": 0, "decoded_protobuf": 0, "binary": 0, "empty": 0}

    for i, item in enumerate(it(str(pcap_path), args.port)):
        if len(results) >= args.max_bodies:
            print(f"[analyze] hit --max-bodies={args.max_bodies}, stopping")
            break
        body = item["body"]
        stats["total"] += 1
        kind = classify(body)
        stats[kind] = stats.get(kind, 0) + 1

        entry = {
            "src": item["src"],
            "dst": item["dst"],
            "len": len(body),
            "kind": kind,
            "head_hex": body[:16].hex(),
        }

        if kind in ("maybe_protobuf", "binary"):
            bb = decode_blackbox(body)
            if bb is not None:
                entry["blackboxprotobuf"] = bb
                stats["decoded_protobuf"] += 1
            if have_protoc:
                pr = decode_raw_protoc(body)
                if pr:
                    entry["protoc_decode_raw"] = pr
        elif kind == "http":
            entry["preview"] = body[:200].decode("utf-8", "replace")

        results.append(entry)

    RESULTS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS / f"analysis_{ts}.json"
    out.write_text(
        json.dumps({"source": str(pcap_path), "stats": stats, "payloads": results}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n[analyze] summary:")
    for k, v in stats.items():
        print(f"  {k:18s} {v}")
    print(f"\n[analyze] wrote {out}")
    if stats["tls"] and not stats["decoded_protobuf"]:
        print("[analyze] payloads are mostly TLS — the pcap is encrypted. You need MITM")
        print("          or a TLS keylog to see plaintext (see sniffing-playbook.md §2).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

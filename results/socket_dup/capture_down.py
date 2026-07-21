"""Capture-only downstream watcher (no win32, no handle dup — never hangs).

Mirrors steal_via_socket.sniff_live_params' capture wiring, but records EVERY
downstream frame's `_id` + command to a JSONL file. Decoupled from the sender
so the flaky handle-duplication path can't stall the capture. Run this in the
background, fire results/socket_dup/dup_send.py during the window, then diff the
sent ids against the downstream _ids recorded here.

Usage: python capture_down.py <seconds> <out.jsonl>
"""
import json
import sys
import threading
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import steal_via_socket as S  # noqa: E402
import lastwar_proto as proto  # noqa: E402
from live_sniffer import LiveDecoder  # noqa: E402
from live_tshark import capture, find_binary, list_interfaces  # noqa: E402


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    out = sys.argv[2] if len(sys.argv) > 2 else "capture_down.jsonl"
    records = []
    live = open(out, "w", buffering=1)  # line-buffered: readable mid-run

    class Collector(LiveDecoder):
        def emit(self, direction, env):
            try:
                command = proto.envelope_command(env) or "(keepalive)"
                payload = proto.envelope_payload(env) or {}
            except Exception:
                return
            rid = payload.get("_id") if isinstance(payload, dict) else None
            rec = {"dir": direction, "id": rid, "cmd": command,
                   "ok": payload.get("success") if isinstance(payload, dict) else None,
                   "t": round(time.time(), 2)}
            records.append(rec)
            try:
                live.write(json.dumps(rec) + "\n")
                live.flush()
            except Exception:
                pass

    tshark = S._wireshark_binary("tshark.exe", find_binary)
    dumpcap = S._wireshark_binary("dumpcap.exe", find_binary) or tshark
    ifaces = list_interfaces(tshark)
    decoder = Collector()
    stop = threading.Event()
    procs = []
    threads = [
        threading.Thread(target=capture,
                         args=(dumpcap, num, lbl, decoder, "tcp", stop, False, procs),
                         daemon=True)
        for num, lbl in ifaces
    ]
    print(f"capturing {seconds:g}s across {len(ifaces)} ifaces -> {out}", flush=True)
    for t in threads:
        t.start()
    stop.wait(seconds)
    stop.set()
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass
    import subprocess
    try:
        subprocess.run(["taskkill.exe", "/F", "/IM", "dumpcap.exe"],
                       capture_output=True, timeout=10)
    except Exception:
        pass

    live.close()
    down = [r for r in records if r["dir"] == "down" and isinstance(r["id"], int)]
    up = [r for r in records if r["dir"] == "up" and isinstance(r["id"], int)]
    print(f"records={len(records)} down_with_id={len(down)} up_with_id={len(up)}", flush=True)
    print("wrote " + out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

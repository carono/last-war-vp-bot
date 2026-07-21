"""Live trap — record EVERY upstream (client->server) command.

Task #974: the base-building resource-collect command is not obviously named in
known_commands.txt and did not surface with a narrow --match filter. To identify
it, log every client-sent command while a human clicks a resource bubble once.

    /mnt/c/Python312/python.exe -X utf8 tools/trap_all_up.py --seconds 60 \
        --tshark "C:\\Program Files\\Wireshark\\tshark.exe" \
        --dumpcap "C:\\Program Files\\Wireshark\\dumpcap.exe"

Every `up` command is printed (with a * marker for names absent from
known_commands.txt) and written to --out as JSONL. Downstream is ignored to keep
the signal clean.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

VOCAB = Path(__file__).resolve().parent / "known_commands.txt"

C_HIT = "\033[92m"
C_NEW = "\033[93m"
C_DIM = "\033[2m"
C_RESET = "\033[0m"


def load_known() -> set[str]:
    if not VOCAB.exists():
        return set()
    names = set()
    for line in VOCAB.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        direction, _, command = line.partition(" ")
        if direction == "up" and command:
            names.add(command)
    return names


def run(args) -> int:
    import lastwar_proto as proto
    from live_sniffer import LiveDecoder
    from live_tshark import capture, find_binary, list_interfaces

    known = load_known()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sink = out_path.open("a", encoding="utf-8")
    lock = threading.Lock()
    seen: dict[str, int] = {}

    class _Trap(LiveDecoder):
        def emit(self, direction, env):
            if direction != "up":
                return
            command = proto.envelope_command(env)
            if not command:
                return
            with lock:
                seen[command] = seen.get(command, 0) + 1
                payload = proto.envelope_payload(env)
                record = {
                    "t": time.time(),
                    "dir": direction,
                    "command": command,
                    "novel": command not in known,
                    "payload": payload,
                    "envelope": env,
                }
                sink.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                sink.flush()
                mark = f"{C_NEW}*NEW*{C_RESET}" if command not in known else "     "
                summary = proto.summarize(payload)[:160] if payload else ""
                print(f"{mark} --> {command}   {summary}")

    tshark = find_binary("tshark.exe", args.tshark)
    dumpcap = find_binary("dumpcap.exe", args.dumpcap) or tshark
    if not tshark or not dumpcap:
        print("Wireshark not found — pass --tshark / --dumpcap", file=sys.stderr)
        return 1
    ifaces = list_interfaces(tshark)
    if args.iface:
        ifaces = [(args.iface, f"iface {args.iface}")]

    decoder = _Trap()
    stop = threading.Event()
    procs: list = []
    threads = [
        threading.Thread(target=capture,
                         args=(dumpcap, number, label, decoder, "tcp", stop,
                               args.verbose, procs),
                         daemon=True)
        for number, label in ifaces
    ]
    print(f"Logging ALL upstream commands for {args.seconds}s -> {out_path}")
    print(f"{C_DIM}Now click a resource bubble / Collect on a base building.{C_RESET}\n")
    for thread in threads:
        thread.start()
    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for proc in procs:
            try:
                proc.kill()
            except Exception:
                pass
        for thread in threads:
            thread.join(timeout=2)
        sink.close()

    print(f"\n=== upstream command tally ({sum(seen.values())} frames) ===")
    for name, count in sorted(seen.items(), key=lambda kv: -kv[1]):
        tag = " *NEW*" if name not in known else ""
        print(f"  {count:4d}  {name}{tag}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--out", default="results/trap_all_up.jsonl")
    ap.add_argument("--iface")
    ap.add_argument("--tshark")
    ap.add_argument("--dumpcap")
    ap.add_argument("--verbose", action="store_true")
    return run(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

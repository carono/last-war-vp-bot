"""Live trap for resource collection commands (Task #973).

Catches the commands that fire when a player collects resources in-game:
  - gather.collect.reward  — collect finished world-map gathering (troops returned)
  - city.building.collect  — collect from base buildings (farm, sawmill, mine)
  - OR any similar unknown command

Usage:
    # Run this, then in the game do ONE of:
    #   a) On world map: click a completed gathering march → "collect"
    #   b) On base screen: click a farm/sawmill/mine → "collect" (or "collect all")
    python3 tools/trap_resource_collect.py --seconds 300

    # Narrow search to known candidate:
    python3 tools/trap_resource_collect.py --match gather --seconds 120
    python3 tools/trap_resource_collect.py --match collect --seconds 120

Output is JSONL at results/trap_resource.jsonl. Decode with:
    python3 -m json.tool results/trap_resource.jsonl

After trapping gather.collect.reward, inject it:
    /mnt/c/Python312/python.exe tools/steal_via_socket.py \\
        --command gather.collect.reward \\
        --uuid-arr <uuid1,uuid2,...> \\
        --sniff-and-inject --force --server-id 935
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "tools/lib")
sys.path.insert(0, str(Path(__file__).resolve().parent))

VOCAB = Path(__file__).resolve().parent / "known_commands.txt"

C_HIT = "\033[92m"
C_NEW = "\033[93m"
C_DIM = "\033[2m"
C_RESET = "\033[0m"

# Commands we expect to see for resource collection (both world-map and base)
RESOURCE_CANDIDATES = {
    "gather.collect.reward",
    "city.building.collect",
    "resource.collect",
    "building.collect",
    "city.resource.collect",
    "collect.resource",
}


def load_vocabulary() -> set[tuple[str, str]]:
    if not VOCAB.exists():
        return set()
    pairs = set()
    for line in VOCAB.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        direction, _, command = line.partition(" ")
        if command:
            pairs.add((direction, command))
    return pairs


def run(args) -> int:
    try:
        import lastwar_proto as proto
        from live_sniffer import LiveDecoder
        from live_tshark import capture, find_binary, list_interfaces
    except ImportError as exc:
        print(f"protocol stack unavailable: {exc} — pip install scapy zstandard",
              file=sys.stderr)
        return 1

    known = load_vocabulary()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sink = out_path.open("a", encoding="utf-8")
    lock = threading.Lock()
    hits = {"matched": 0, "new": 0, "candidate": 0, "total": 0}

    class _Trap(LiveDecoder):
        def emit(self, direction, env):
            command = proto.envelope_command(env)
            if not command:
                return
            matched = args.match.lower() in command.lower() if args.match else False
            candidate = command in RESOURCE_CANDIDATES
            novel = bool(known) and (direction, command) not in known
            with lock:
                hits["total"] += 1
                if not (matched or candidate or novel):
                    return
                hits["matched"] += matched
                hits["candidate"] += candidate
                hits["new"] += novel
                payload = proto.envelope_payload(env)
                record = {
                    "t": time.time(),
                    "dir": direction,
                    "command": command,
                    "novel": novel,
                    "candidate": candidate,
                    "payload": payload,
                    "envelope": env,
                }
                sink.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                sink.flush()
                if candidate:
                    colour = "\033[95m"
                    tag = "CAND"
                elif novel:
                    colour = C_NEW
                    tag = "NEW "
                else:
                    colour = C_HIT
                    tag = "hit "
                arrow = "-->" if direction == "up" else "<--"
                summary = proto.summarize(payload)[:160] if payload else ""
                print(f"{colour}{tag}{C_RESET} {arrow} {command}   {summary}")
                if direction == "up" and command in RESOURCE_CANDIDATES:
                    print(f"\n  *** FOUND: {command} upstream payload: {payload} ***\n")

    tshark = find_binary("tshark.exe", args.tshark)
    dumpcap = find_binary("dumpcap.exe", args.dumpcap) or tshark
    if not tshark or not dumpcap:
        print("Wireshark not found — pass --tshark / --dumpcap", file=sys.stderr)
        return 1
    ifaces = list_interfaces(tshark)
    if args.iface:
        ifaces = [(args.iface, f"iface {args.iface}")]
    if not ifaces:
        print("no capture interfaces found", file=sys.stderr)
        return 1

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

    match_desc = f"*{args.match}*" if args.match else "(none)"
    print(f"Trapping: match={match_desc}  candidates={sorted(RESOURCE_CANDIDATES)}")
    print(f"Writing to {out_path}")
    print(f"\n{C_DIM}=== NOW DO ONE OF THESE IN THE GAME ==={C_RESET}")
    print(f"{C_DIM}  a) On world map: tap a completed gathering march → Collect{C_RESET}")
    print(f"{C_DIM}  b) On base: tap a farm/sawmill/mine → Collect (or tap 'Collect All'){C_RESET}")
    print(f"{C_DIM}  c) Try each in turn to capture multiple commands{C_RESET}\n")

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

    print(f"\n{hits['total']} commands — {hits['matched']} match filter, "
          f"{hits['candidate']} known candidates, {hits['new']} never seen before")
    if not hits["matched"] and not hits["candidate"] and not hits["new"]:
        print(f"{C_DIM}nothing caught. Did you perform the in-game action? "
              f"Check --iface picks a busy adapter.{C_RESET}")
        return 1
    print(f"decode: python3 -m json.tool {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--match", default="collect",
                    help="substring of command name to trap (default: %(default)s)")
    ap.add_argument("--seconds", type=int, default=300,
                    help="how long to listen (default: %(default)s)")
    ap.add_argument("--out", default="results/trap_resource.jsonl",
                    help="JSONL sink (default: %(default)s)")
    ap.add_argument("--iface", help="interface number from live_tshark.py --list")
    ap.add_argument("--tshark", help="path to tshark.exe")
    ap.add_argument("--dumpcap", help="path to dumpcap.exe")
    ap.add_argument("--verbose", action="store_true")
    return run(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

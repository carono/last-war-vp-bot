"""Live trap — record the frames of a command the captures have never shown.

Built for one question (task #882): **what does the client send when a player
robs a secret task?** No capture in this repo contains it, because the captured
account never robbed anything. The only way to learn the format is to watch the
wire while a human does it once.

    # in one terminal, then rob a task by hand in the game
    python3 tools/trap_command.py --match hero.dispatch --seconds 300

Everything matching `--match` is written to `--out` (JSONL, one envelope per
line) and printed as it arrives. Because the real command name is a guess,
**any command absent from `known_commands.txt` is flagged too** — a rob command
called something else entirely still gets caught.

The output is a transcript of live traffic: it can carry account identifiers.
Keep it in `results/`, which is not tracked. See `protocol.md` §6.
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


def load_vocabulary() -> set[tuple[str, str]]:
    """(direction, command) pairs the saved captures already showed.

    Direction matters: the client vocabulary alone would flag every one of the
    179 server pushes as new, which buries the one line that matters.

    Regenerate from a transcript produced by
    `lastwar_proto.py <pcap> --json out.json`:

        python3 -c "import json;print('\\n'.join(sorted(
            f\\"{r['dir']} {r['command']}\\" for r in json.load(open('out.json'))
            if r['command'] != '(keepalive)')))" > tools/known_commands.txt
    """
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
    if not known:
        print(f"{C_DIM}no vocabulary at {VOCAB} — new-command flagging is off"
              f"{C_RESET}", file=sys.stderr)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sink = out_path.open("a", encoding="utf-8")
    lock = threading.Lock()
    hits = {"matched": 0, "new": 0, "total": 0}

    class _Trap(LiveDecoder):
        def emit(self, direction, env):
            command = proto.envelope_command(env)
            if not command:
                return  # keepalive
            matched = args.match in command
            # The rob command's real name is unknown, so "never seen before"
            # is the second, weaker net under the name guess.
            novel = bool(known) and (direction, command) not in known
            with lock:
                hits["total"] += 1
                if not (matched or novel):
                    return
                hits["matched"] += matched
                hits["new"] += novel
                record = {
                    "t": time.time(),
                    "dir": direction,
                    "command": command,
                    "novel": novel,
                    "payload": proto.envelope_payload(env),
                    "envelope": env,
                }
                sink.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                sink.flush()
                colour = C_NEW if novel else C_HIT
                tag = "NEW " if novel else "hit "
                arrow = "-->" if direction == "up" else "<--"
                print(f"{colour}{tag}{C_RESET} {arrow} {command}   "
                      f"{proto.summarize(proto.envelope_payload(env))[:160]}")

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

    print(f"trapping {C_HIT}*{args.match}*{C_RESET} and any command outside the "
          f"{len(known)}-entry vocabulary")
    print(f"writing to {out_path}")
    print(f"{C_DIM}now do the thing in the game — rob a secret task by hand"
          f"{C_RESET}\n")
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

    print(f"\n{hits['total']} commands seen — {hits['matched']} matched "
          f"'{args.match}', {hits['new']} never seen before")
    if not hits["matched"] and not hits["new"]:
        print(f"{C_DIM}nothing caught. Check the game was actually driven, and "
              f"that --iface picked a busy adapter (live_tshark.py --list)."
              f"{C_RESET}")
        return 1
    print(f"decode further with: python3 -m json.tool {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=load_vocabulary.__doc__)
    ap.add_argument("--match", default="hero.dispatch",
                    help="substring of the command name to trap (default: %(default)s)")
    ap.add_argument("--seconds", type=int, default=300,
                    help="how long to listen (default: %(default)s)")
    ap.add_argument("--out", default="results/trap.jsonl",
                    help="JSONL sink (default: %(default)s)")
    ap.add_argument("--iface", help="interface number from live_tshark.py --list")
    ap.add_argument("--tshark", help="path to tshark.exe")
    ap.add_argument("--dumpcap", help="path to dumpcap.exe")
    ap.add_argument("--verbose", action="store_true",
                    help="report per-interface capture errors")
    return run(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

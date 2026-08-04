r"""How long a game call takes, end to end, on the live client (task #1230).

Answers the only two questions worth asking when the panel feels slow:

  * **when did the GAME react** — not when the call returned. Every chunk this sends
    ends with a `Debug.LogError`, so a watcher tailing `Player.log` on a second thread
    times the reaction independently of whatever the caller is doing.
  * **was it us or the client** — each sample logs the game's own `Time.deltaTime` in
    the very chunk being timed. A call costs TWO of the client's frames (one thread
    hijack each, and the main thread reaches the safe park once a frame), so a client
    at 20 fps answers in ~100 ms and there is nothing in the panel to fix.

Nothing here changes anything in the game: the chunk writes one line to the log.

    C:\Python312\python.exe tools\dev\call_latency.py                 # default daemon
    C:\Python312\python.exe tools\dev\call_latency.py --port 47655    # the other client
    C:\Python312\python.exe tools\dev\call_latency.py --samples 40

Background and the numbers this produced: docs/research/game-call-latency.md.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import lua_client  # noqa: E402  — HOST/PORT only
import lua_eval  # noqa: E402  — player_log_path(), no il2cpp stack


def rpc(port: int, req: dict, timeout: float = 60.0) -> dict:
    sock = socket.create_connection((lua_client.HOST, port), timeout=1.0)
    sock.settimeout(timeout)
    try:
        sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        sock.close()
    return json.loads(buf.decode("utf-8", "replace").splitlines()[0])


def sample(port: int, log: str, index: int, settle: float, early: bool) -> dict:
    """One call: how long until the game acted, how long until the panel was free."""
    marker = "LAT%d" % index
    chunk = ("CS.UnityEngine.Debug.LogError('%s dt='..tostring("
             "CS.UnityEngine.Time.deltaTime))" % marker)
    since = os.path.getsize(log) if os.path.exists(log) else 0
    seen: dict = {}

    def watch() -> None:
        while time.perf_counter() - started < 20:
            try:
                with open(log, "rb") as fh:
                    fh.seek(since)
                    text = fh.read().decode("utf-8", "replace")
            except OSError:
                text = ""
            if marker in text:
                seen["react"] = time.perf_counter() - started
                try:
                    seen["frame"] = float(text.split(marker + " dt=")[1].split()[0])
                except (IndexError, ValueError):
                    pass
                return
            time.sleep(0.002)

    started = time.perf_counter()
    watcher = threading.Thread(target=watch)
    watcher.start()
    req = {"op": "run", "chunk": chunk, "marker": marker, "settle": settle}
    if early:
        req["early"] = True
    reply = rpc(port, req)
    seen["round_trip"] = time.perf_counter() - started
    seen["ok"] = bool(reply.get("ok"))
    watcher.join()
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description="latency of one game call, measured live")
    ap.add_argument("--port", type=int, default=lua_client.PORT,
                    help=f"the daemon of the client to time (default {lua_client.PORT})")
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--settle", type=float, default=1.2,
                    help="the wait the call asks for (default 1.2, as a press does)")
    ap.add_argument("--patient", action="store_true",
                    help="sit out the whole settle, the way it was before #1230")
    args = ap.parse_args()

    log = lua_eval.player_log_path()
    print(f"daemon 127.0.0.1:{args.port}   log {log}")
    if not lua_client.is_running(port=args.port):
        print("no daemon there — start the panel, or tools/lua_daemon.py")
        return 1

    react, frames, trips = [], [], []
    for i in range(args.samples):
        got = sample(args.port, log, i, args.settle, not args.patient)
        if not got.get("ok"):
            print("  the daemon refused the call — is the client up?")
            return 1
        trips.append(1000 * got["round_trip"])
        if "react" in got:
            react.append(1000 * got["react"])
        if "frame" in got:
            frames.append(1000 * got["frame"])
        time.sleep(0.05)

    def q(values, p):
        return sorted(values)[min(len(values) - 1, int(p * len(values)))]

    if not react:
        print(f"nothing reached the log in {args.samples} tries — the client is not "
              f"running the chunks (a login screen? a wedged VM?)")
        return 1
    print("frame       p50 %5.1f  min %5.1f  max %5.1f ms  (%.0f fps)"
          % (q(frames, .5), min(frames), max(frames), 1000 / statistics.median(frames))
          if frames else "frame       unreadable")
    print("reaction    p50 %5.1f  p90 %5.1f  max %5.1f ms   <- when the GAME acted"
          % (q(react, .5), q(react, .9), max(react)))
    print("round trip  p50 %5.1f  p90 %5.1f  max %5.1f ms   <- when the panel was free"
          % (q(trips, .5), q(trips, .9), max(trips)))
    if frames:
        print("reaction / frame  p50 %.2f  -- a call is two of the client's frames, "
              "one per hijack" % statistics.median(r / f for r, f in zip(react, frames)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

r"""Does the answer channel still work, on the live client? (task #1232)

`tests/test_lua_answer_channel.py` proves the wrapper against a stand-in `CS` with no
game at all, which is where the fast feedback is. This is the other half: the same
questions asked of the REAL client, because the parts that cannot be faked are exactly
the parts that would break everything at once — whether xLua binds `System.IO.File`,
whether the shadowed `CS` still resolves the rest of the game, and whether an answer of
each shape survives the round trip.

Two halves, in one short burst so the client is handed back quickly (a neighbour is
usually driving the camera):

  * **the shapes an answer comes in** — nothing at all, one line, two hundred lines, a
    chunk that raised, one 8 KB line, and one with Cyrillic, German and Turkish in it.
    Each is read back through BOTH channels and the two are required to be IDENTICAL,
    which is the whole promise of the change: the caller cannot tell where the answer
    was written.
  * **the paths that really go into the game** — the dashboard's thirteen readings
    through its own parser, three read-only scenarios through the interpreter that plays
    them, and a gated press (`TAP … xall`) on a button whose count is currently zero.

**Nothing here changes anything in the game.** The scenarios are the `read_*` ones, the
gated presses are only run against a button the dashboard has just reported as empty —
so the gate reads 0 and stops — and the check fails loudly if one of them fires anyway.

    C:\Python312\python.exe tools\dev\check_answer_channel.py
    C:\Python312\python.exe tools\dev\check_answer_channel.py --port 47655
    C:\Python312\python.exe tools\dev\check_answer_channel.py --no-shapes

Timings, and what the channel costs: `tools/dev/call_latency.py` and
docs/research/game-call-latency.md.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (ROOT, os.path.join(ROOT, "tools", "lib"), os.path.join(ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lua_eval  # noqa: E402

#: The read-only scenarios played through the interpreter. Read-only on purpose: this
#: runs against somebody's live account, usually while another session is driving the
#: camera, so a check that moved anything would be a check nobody dares run.
SCENARIOS = ("read_graphics_load", "read_squad_state", "read_daily_checklist")

#: Which dashboard readings may lend their button to the gated-press check. Each is a
#: QUEUE — «nothing is waiting» is its ordinary state — so finding one at zero is likely,
#: and a gate that reads zero cannot spend anything.
IDLE_QUEUES = ("help_waiting", "visitors", "visitor_gifts", "treasures", "help_queues")

SHAPES = {
    "nothing at all": (
        "local _ = 1",
        lambda got: got == []),
    "one line": (
        "CS.UnityEngine.Debug.LogError('SH one')",
        lambda got: got == ["SH one"]),
    "200 lines, in order": (
        "for i=1,200 do CS.UnityEngine.Debug.LogError('SH n='..i) end",
        lambda got: got == ["SH n=%d" % i for i in range(1, 201)]),
    "a chunk that raised": (
        "CS.UnityEngine.Debug.LogError('SH before') error('deliberate')",
        lambda got: got == ["SH before"]),
    "one 8 KB line": (
        "CS.UnityEngine.Debug.LogError('SH long '..string.rep('x', 8192))",
        lambda got: len(got) == 1 and got[0] == "SH long " + "x" * 8192),
    "unicode": (
        "CS.UnityEngine.Debug.LogError('SH \u041f\u0440\u0438\u0432\u0435\u0442 "
        "Gr\u00fc\u00dfe \u011f\u0131\u015f')",
        lambda got: got == ["SH \u041f\u0440\u0438\u0432\u0435\u0442 "
                            "Gr\u00fc\u00dfe \u011f\u0131\u015f"]),
}


class Checker:
    def __init__(self, port: int) -> None:
        self.port = port
        self.failed = 0
        self.sentinel = " -- " + lua_eval.GAME_LOG_SENTINEL

    def rpc(self, req: dict) -> dict:
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=2.0)
        sock.settimeout(90)
        try:
            sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                part = sock.recv(65536)
                if not part:
                    break
                buf += part
        finally:
            sock.close()
        return json.loads(buf.decode("utf-8", "replace").splitlines()[0])

    def run(self, chunk: str, marker: str, settle: float = 2.0,
            via_game_log: bool = False):
        req = {"op": "run", "marker": marker, "settle": settle, "early": True,
               "chunk": chunk + (self.sentinel if via_game_log else "")}
        started = time.perf_counter()
        reply = self.rpc(req)
        return reply.get("lines") or [], 1000 * (time.perf_counter() - started)

    def check(self, name: str, passed, detail: str = "") -> None:
        if not passed:
            self.failed += 1
        print("  %-4s %-52s %s" % ("ok" if passed else "FAIL", name, detail))


def check_shapes(ck: Checker) -> None:
    print("the shapes an answer comes in (private file | the game's log)")
    for name, (chunk, want) in SHAPES.items():
        # A chunk that says nothing costs the whole settle, by design — keep it short.
        settle = 0.6 if "nothing" in name else 3.0
        got_file, ms_file = ck.run(chunk, "SH", settle=settle)
        got_log, ms_log = ck.run(chunk, "SH", settle=settle, via_game_log=True)
        ck.check(name, want(got_file) and want(got_log) and got_file == got_log,
                 "file %d line(s) %.0f ms | log %d %.0f ms | identical=%s"
                 % (len(got_file), ms_file, len(got_log), ms_log,
                    got_file == got_log))

    # The error of a chunk that raised: written down for a person, and carrying no
    # marker, so it can never be handed to a caller as one of its answers.
    answers = lua_eval.answer_log_path()
    since = os.path.getsize(answers) if os.path.exists(answers) else 0
    ck.run("error('deliberate, for the record')", "SH", settle=1.0)
    time.sleep(0.2)
    with open(answers, "rb") as fh:
        fh.seek(since)
        tail = fh.read().decode("utf-8", "replace")
    ck.check("a raised error is written down, unmarked",
             "lua-error" in tail and not any(ln.startswith("SH")
                                             for ln in tail.splitlines()),
             repr(tail.strip()[:70]))


def check_production(ck: Checker) -> None:
    print("\nthe paths that really go into the game")
    import game_buttons                                   # noqa: PLC0415
    from lastwar_bot import script_engine as se           # noqa: PLC0415
    from panel import dashboard as dash                   # noqa: PLC0415

    lines, ms = ck.run(dash.build_chunk(), dash.MARKER)
    values = dash.parse(lines)
    read = sum(v is not None for v in values.values())
    ck.check("the dashboard's readings, through its own parser",
             read == len(dash.KEYS),
             "%d/%d resolved, %.0f ms" % (read, len(dash.KEYS), ms))

    for name in SCENARIOS:
        said: list = []
        started = time.perf_counter()
        try:
            ok = se.run_action(name, hwnd=0, on_event=said.append)
        except Exception as exc:                          # noqa: BLE001
            ok = "raised: %s" % exc
        ck.check("scenario %s runs and reads" % name, ok is True and bool(said),
                 "%d line(s), %.0f ms" % (len(said), 1000 * (time.perf_counter() - started)))

    fired_anything = False
    tried = 0
    for reading in IDLE_QUEUES:
        if values.get(reading) != 0 or tried >= 2:
            continue
        for key, btn in game_buttons.BUTTONS.items():
            if not btn.count_lua or btn.count_lua != dash.BY_KEY[reading].expr:
                continue
            lines, ms = ck.run(se.gated_chunk(btn, 99), "ACT")
            gate = [ln for ln in lines if "gate left=" in ln]
            fired = [ln for ln in lines if "fired=" in ln]
            fired_anything = fired_anything or bool(fired)
            tried += 1
            ck.check("gated press %r reads its gate and stops" % key,
                     bool(gate) and not fired,
                     "%s, %.0f ms" % (gate[0] if gate else "no gate line", ms))
            break
    if not tried:
        print("       (no idle queue to borrow a button from — gated press not checked)")
    ck.check("nothing was pressed", not fired_anything)


def main() -> int:
    ap = argparse.ArgumentParser(description="the answer channel, on the live client")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("LW_DAEMON_PORT") or 47654),
                    help="the daemon of the client to check")
    ap.add_argument("--no-shapes", action="store_true",
                    help="skip the six answer shapes and check the production paths only")
    args = ap.parse_args()

    ck = Checker(args.port)
    try:
        ck.rpc({"op": "ping"})
    except OSError:
        print("no daemon on 127.0.0.1:%d — start the panel, or tools/lua_daemon.py"
              % args.port)
        return 1
    print("daemon 127.0.0.1:%d   answers %s\n"
          % (args.port, os.path.basename(lua_eval.answer_log_path())))

    if not args.no_shapes:
        check_shapes(ck)
    check_production(ck)

    print("\n%s" % ("ALL GREEN" if not ck.failed else "%d FAILED" % ck.failed))
    return 1 if ck.failed else 0


if __name__ == "__main__":
    sys.exit(main())

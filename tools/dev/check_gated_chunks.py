r"""Compile every `TAP … xall` chunk in the game's own Lua — without pressing anything.

`xall` sends ONE chunk that reads the button's count and presses only if it came back
above zero (`script_engine.gated_chunk`, task #1230). That chunk is assembled out of two
pieces of hand-written Lua — the button's count expression and its press — so the
interesting failure is a SYNTAX one, and it would only show up the first time somebody
ran that particular recipe against the real game.

This asks the live client's own Lua to compile each of them with `load` (the client runs
Lua 5.3, where `loadstring` is gone) and throws the result away. Nothing is
executed: no quota is spent, no window opens, no press lands. A button whose chunk does not compile is named with the error the VM gave.

    C:\Python312\python.exe tools\dev\check_gated_chunks.py
    C:\Python312\python.exe tools\dev\check_gated_chunks.py --port 47655

Needs a warm daemon (the panel starts one) and a client past the login screen.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "tools", "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import game_buttons  # noqa: E402
import lua_client  # noqa: E402
from lastwar_bot.script_engine import gated_chunk  # noqa: E402


def rpc(port: int, req: dict, timeout: float = 60.0) -> dict:
    sock = socket.create_connection((lua_client.HOST, port), timeout=1.0)
    sock.settimeout(timeout)
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


def main() -> int:
    ap = argparse.ArgumentParser(description="compile every gated press, run none of them")
    ap.add_argument("--port", type=int, default=lua_client.PORT)
    args = ap.parse_args()

    names = [n for n in game_buttons.names() if getattr(game_buttons.get(n), "count_lua", "")]
    if not names:
        print("no button declares a count — nothing to check")
        return 1
    bad = 0
    for name in names:
        button = game_buttons.get(name)
        chunk = gated_chunk(button, cap=int(button.max_taps))
        if "]==]" in chunk:                       # would close the long bracket early
            print(f"  ?    {name}: not checkable (the chunk contains a long-bracket end)")
            continue
        probe = ('local f, e = load([==[%s]==]) '
                 'CS.UnityEngine.Debug.LogError("SYN %s "..(f and "ok" or tostring(e)))'
                 % (chunk, name))
        reply = rpc(args.port, {"op": "run", "chunk": probe, "marker": "SYN " + name,
                                "settle": 3.0, "early": True})
        lines = reply.get("lines") or []
        if not reply.get("ok"):
            print(f"  !!   {name}: the daemon refused — {reply.get('error')}")
            bad += 1
        elif not lines:
            print(f"  !!   {name}: the game said nothing (is it past the login screen?)")
            bad += 1
        elif lines[-1].rstrip().endswith(" ok"):
            print(f"  ok   {name}")
        else:
            print(f"  FAIL {name}: {lines[-1].split(name, 1)[-1].strip()}")
            bad += 1
    print(f"\n{len(names) - bad}/{len(names)} gated presses compile in the game's Lua")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

r"""What the game knows about a warzone — when it opened, what day it is on, and the rest.

ANY warzone, not only the one the account plays in, and WITHOUT a jump: the client asks
the game server one question (`get.other.server.info`) and keeps the answer, which is the
warzone's opening moment. Everything else printed here is the arithmetic the client
already does for its own screens — see docs/research/server-info.md.

The ability itself is one recipe, `src/lastwar_bot/actions/read_server_info.md`; this
file only plays it and prints what came back.

    C:\Python312\python.exe tools\server_info.py              # the account's own warzone
    C:\Python312\python.exe tools\server_info.py 1234         # somebody else's, no jump
    C:\Python312\python.exe tools\server_info.py 1234 --raw   # the recipe's line, unparsed

Dates are printed on the GAME's clock, which is not this machine's
(docs/research/game-clock.md): the recipe hands back the game's «now» beside the opening
moment, and the offset between the two clocks is what turns one into the other here.
"""
import os
import sys
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "src"), os.path.join(_REPO, "tools", "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lastwar_bot import script_engine       # noqa: E402


def _fields(line: str) -> dict:
    """The recipe's `k=v k=v …` line as a dict; anything unparsable is left out."""
    out = {}
    for chunk in (line or "").split():
        if "=" in chunk:
            key, _, value = chunk.partition("=")
            out[key] = value
    return out


def _stamp(ms) -> str:
    """`<date> <time> UTC` for a game-clock millisecond, or `-` when there is none.

    Every millisecond printed here comes off the GAME's clock — the recipe reads them out
    of the client, never off this machine, whose clock was eleven seconds behind when
    `tools/lib/game_clock.py` was written. Epoch is epoch, so the rendering is plain UTC;
    what matters is that nothing on this side ever supplies a «now» of its own.
    """
    try:
        value = int(ms)
    except (TypeError, ValueError):
        return "-"
    if value <= 0:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(value / 1000.0))


def main() -> int:
    argv = [a for a in sys.argv[1:] if a != "--raw"]
    raw = "--raw" in sys.argv[1:]
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    server = int(argv[0]) if argv and argv[0].lstrip("-").isdigit() else 0

    said = []
    ok = script_engine.run_action(
        "read_server_info", hwnd=0,
        on_event=lambda msg: said.append(str(msg)),
        variables={"server": server},
    )
    line = ""
    for msg in said:
        if "warzone server=" in msg:
            line = msg.split("warzone ", 1)[1].strip().strip('"')
    if raw or not line:
        for msg in said:
            print(msg)
        return 0 if ok and line else 1

    f = _fields(line)
    print("warzone     %s%s" % (f.get("server", "?"),
                                "  (the account's own)" if f.get("own") == "1" else ""))
    print("opened      %s" % _stamp(f.get("open_ms")))
    print("day         %s" % f.get("day", "-"))
    print("week        %s" % f.get("week", "-"))
    print("day ends    %s" % _stamp(f.get("day_end_ms")))
    print("game clock  %s" % _stamp(f.get("now_ms")))
    if f.get("own") == "1":
        print("name        %s" % f.get("name", "-"))
        print("newest id   %s" % f.get("max", "-"))
    print("zone star   %s" % f.get("zone_star", "-"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

r"""The game's OWN record of the rallies we took part in — the trophy list (#1281).

The person playing asked the question that mattered: «how did you prove the banners
were real?» and gave the answer with it — **after a rally ends the game always pays a
trophy**, and the world map has a gift button beside the heroes listing every one and
what it was for. That list is EXTERNAL evidence: it does not come from the panel's log,
so it is the only thing that can say whether our count of joins matches reality rather
than merely matching itself.

Where it lives, found by asking the client which of its own managers hold something
reward-shaped rather than by guessing a name:

    DataCenter.CollectRewardDataManager.collectRewardList

One row per unclaimed trophy:

    uuid         the trophy's own id
    type         6 — the same march type a rally join is sent with
    pointId      the tile the rally attacked; THIS is what identifies which banner
    contentId    what was rallied
    expireTime   when the trophy stops being claimable
    rewardList   what it pays

**IT IS A CLAIM LIST, NOT A HISTORY.** A trophy expires about an hour after its rally —
measured across eight rows, `expireTime` minus the moment the panel first saw that
banner came out between 1:01:03 and 1:02:48, which is also what confirms the rows pair
with banners by `pointId` rather than by hope. So this can testify about the last hour
and about nothing before it, and a row leaving the list means claimed or expired, not
«did not happen».

**IT HOLDS ONLY THE RALLIES WE WERE IN.** Eight rows while the alliance ran forty-nine
banners in one earlier window: a rally somebody else fought pays us nothing and leaves
no row. So the list gives the exact number we WORKED, and «missed» stays a subtraction —
joinable banners minus these — rather than something it can show directly.

    C:\Python312\python.exe tools\dev\rally_trophies.py
    C:\Python312\python.exe tools\dev\rally_trophies.py --check 18:25:00 18:38:00

`--check` is the whole point: it counts the trophies whose banner the panel first saw
inside that window and prints them beside the joins the log confirmed there. Equal is
proof; unequal is our bug, and ours is the one that is wrong.

Read-only. Opens no window, claims nothing.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools", "lib"))
import lua_client  # noqa: E402

CHUNK = (
    "local m = DataCenter.CollectRewardDataManager local n = 0 "
    "pcall(function() for _, row in pairs(m.collectRewardList) do n = n + 1 "
    "  local function f(k) local ok, v = pcall(function() return row[k] end) "
    "    if ok and v ~= nil then return tostring(v) end return '?' end "
    "  local pays = 0 pcall(function() for _ in pairs(row.rewardList) do pays = pays + 1 end end) "
    "  CS.UnityEngine.Debug.LogError('TR uuid=' .. f('uuid') .. ' type=' .. f('type') "
    "    .. ' point=' .. f('pointId') .. ' content=' .. f('contentId') "
    "    .. ' expire=' .. f('expireTime') .. ' pays=' .. pays) end end) "
    "CS.UnityEngine.Debug.LogError('TR rows=' .. n)"
)

#: The march type a rally join is sent with, and the type these rows carry
#: (`MarchUtil.SendCreateMarchMessage(formation, 6, …)` — docs/research/rally-join.md).
RALLY_TYPE = "6"


def trophies(port: int) -> list:
    """One dict per unclaimed trophy the client is holding."""
    client = lua_client.DaemonClient(port=port, token="")
    out = []
    for line in client.run(CHUNK, marker="TR", settle=3.0, early=True) or []:
        if " uuid=" not in line:
            continue
        row = dict(part.split("=", 1) for part in line.split()[1:] if "=" in part)
        out.append(row)
    return out


def _sec(text: str) -> int:
    h, m, s = (int(x) for x in text.split(":"))
    return h * 3600 + m * 60 + s


def banners_seen(profile: str) -> dict:
    """`pointId -> the second the panel FIRST saw a banner attacking that tile`.

    Off `rally_monitor`'s own reading, which is the client's list rather than ours.
    """
    path = os.path.join(REPO, "profiles", profile, "debug.log")
    first: dict = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "READ_LUA rallies" not in line:
                continue
            stamp = re.match(r"^\[\d{4}-\d\d-\d\d (\d\d:\d\d:\d\d)", line)
            if not stamp:
                continue
            at = _sec(stamp.group(1))
            for m in re.finditer(r"point=(\d+)", line):
                point = m.group(1)
                if point not in first or at < first[point]:
                    first[point] = at
    return first


def joins_confirmed(profile: str, lo: int, hi: int) -> list:
    """The joins the LOG confirmed in the window — `joined = N` above zero."""
    path = os.path.join(REPO, "profiles", profile, "debug.log")
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "rally_auto_join" not in line or "READ_LUA joined = " not in line:
                continue
            stamp = re.match(r"^\[\d{4}-\d\d-\d\d (\d\d:\d\d:\d\d)", line)
            got = re.search(r"joined = (\d+)", line)
            if not stamp or not got or int(got.group(1)) <= 0:
                continue
            at = _sec(stamp.group(1))
            if lo <= at < hi:
                out.append((stamp.group(1), int(got.group(1))))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=lua_client.PORT)
    ap.add_argument("--profile", default="default")
    ap.add_argument("--check", nargs=2, metavar=("FROM", "TO"),
                    help="HH:MM:SS window to compare the log against")
    args = ap.parse_args()

    rows = trophies(args.port)
    print(f"trophies the client is holding: {len(rows)}")
    for row in rows:
        print("  point=%-8s type=%-3s content=%-8s pays=%s"
              % (row.get("point", "?"), row.get("type", "?"),
                 row.get("content", "?"), row.get("pays", "?")))
    rally = [r for r in rows if r.get("type") == RALLY_TYPE]
    print(f"of them rally trophies (type={RALLY_TYPE}): {len(rally)}")

    if not args.check:
        return 0
    lo, hi = _sec(args.check[0]), _sec(args.check[1])
    first = banners_seen(args.profile)
    inside = [r for r in rally
              if lo <= first.get(r.get("point", ""), -1) < hi]
    joins = joins_confirmed(args.profile, lo, hi)
    total = sum(n for _at, n in joins)
    print()
    print(f"window {args.check[0]}–{args.check[1]}")
    print(f"  trophies whose banner was first seen inside it : {len(inside)}")
    print(f"  joins the log confirmed inside it              : {total}"
          f"  ({', '.join(at for at, _n in joins) or '—'})")
    if len(inside) == total:
        print("  MATCH — the game's own record agrees with the log")
    else:
        print("  MISMATCH — the game's record is the one to believe")
    # A trophy older than about an hour has expired out of the list, so a window
    # further back than that cannot be checked this way and must not be called a
    # disagreement.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

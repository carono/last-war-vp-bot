#!/usr/bin/env python3
r"""One HTML page of the alliance duel, out of the ranking history — for reading.

    python tools/vs_report.py --sqlite profiles/default/leaderboard_history.db \
                              --out profiles/default/vs_report.html

The store keeps the week (`tools/lib/vs_duel.py`, #1304); this draws it. One
self-contained file — no scripts fetched, no fonts fetched, no network at all — so it
opens on a phone that is nowhere near this machine.

What it shows, in that order: the week's standing per side, a day-by-day strip saying
who won each day and by how much, and then a table per day with both alliances' players
sorted by score. Ours and theirs are two colours; the reader's own row is marked.

**The output is somebody's account and never belongs in the repository.** Default
destination is inside `profiles/`, which is git-ignored — names, uids, alliance tags and
server numbers all end up in it. `--out` somewhere tracked is refused, because the
easiest way to publish a hundred people's identifiers is to not think about it once.

`--me` marks a row as the reader's own. Left out, the live client is asked for it
through the Lua daemon, and if there is no client the page simply has no marked row.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

#: Written into a directory that is not git-ignored, this file is a hundred players'
#: identifiers in a tracked tree. The check is deliberately crude and deliberately
#: refuses rather than warns.
_ALLOWED_ROOTS = ("profiles", "results", "screenshots")

_CSS = """
:root{--bg:#12141a;--card:#1b1e27;--line:#2b303d;--ink:#e8eaf0;--dim:#98a0b3;
--own:#4da3ff;--own-bg:rgba(77,163,255,.12);--foe:#ff8a5c;--foe-bg:rgba(255,138,92,.12);
--me:#ffd23f;--win:#5fd68a}
*{box-sizing:border-box}
body{margin:0;padding:16px;background:var(--bg);color:var(--ink);
font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--dim);font-size:13px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:14px;margin-bottom:14px}
.sides{display:flex;gap:10px;flex-wrap:wrap}
.side{flex:1 1 240px;border-radius:10px;padding:12px;border:1px solid var(--line)}
.side.own{background:var(--own-bg);border-color:var(--own)}
.side.foe{background:var(--foe-bg);border-color:var(--foe)}
.side .tag{font-size:18px;font-weight:700}
.side .num{font-size:22px;font-weight:700;margin-top:6px}
.side .meta{color:var(--dim);font-size:13px;margin-top:4px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{padding:7px 8px;text-align:left;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase;
letter-spacing:.04em}
td.n,th.n{text-align:right}
tr.own td:first-child{border-left:3px solid var(--own)}
tr.foe td:first-child{border-left:3px solid var(--foe)}
tr.me{background:rgba(255,210,63,.14)}
tr.me td{font-weight:700}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.dot.own{background:var(--own)}.dot.foe{background:var(--foe)}
.bar{height:8px;border-radius:4px;background:var(--line);overflow:hidden;display:flex}
.bar i{display:block;height:100%}
.bar i.own{background:var(--own)}.bar i.foe{background:var(--foe)}
.day-head{display:flex;justify-content:space-between;align-items:baseline;gap:10px;
margin-bottom:6px}
.day-head b{font-size:16px}
.won{color:var(--win);font-weight:700}
.lost{color:var(--dim)}
details{margin-top:10px}
summary{cursor:pointer;color:var(--dim);font-size:13px;padding:4px 0}
.gap{color:var(--dim);font-size:13px}
@media(max-width:520px){body{padding:10px}th,td{padding:6px 5px;font-size:13px}}
"""


def _num(value) -> str:
    """A number with thin spaces between the thousands — readable on a phone."""
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def load(path: str) -> dict:
    """The newest snapshot of every VS board in the store."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    boards = [r[0] for r in conn.execute(
        "SELECT DISTINCT board_type FROM entries WHERE board_type LIKE 'al.battle.%'")]
    # The per-day boards first. A history that spans #1304's own commits holds BOTH the
    # split boards and the one un-split board that preceded them, and the un-split one
    # carries the same six days again — read in the other order, every player appears
    # twice. `seen` is what keeps the newer, per-day answer and drops the repeat.
    boards.sort(key=lambda name: ("/day=" not in name, name))
    seen: set = set()
    out: dict = {"players": {}, "sides": {}, "week": [], "at": 0}
    for board in boards:
        ts = conn.execute("SELECT MAX(ts) FROM entries WHERE board_type = ?",
                          (board,)).fetchone()[0]
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM entries WHERE board_type = ? AND ts = ? ORDER BY rank",
            (board, ts))]
        out["at"] = max(out["at"], ts or 0)
        if board.startswith("al.battle.vs.alliances"):
            for row in rows:
                key = ("side", row["day"], row["alliance_id"])
                if key in seen:
                    continue
                seen.add(key)
                out["sides"].setdefault(row["day"], []).append(row)
        elif board == "al.battle.rank.info/type=1":
            out["week"] = rows
        elif board.startswith("al.battle.rank.info/type=0"):
            for row in rows:
                key = ("player", row["day"], row["uid"])
                if key in seen:
                    continue
                seen.add(key)
                out["players"].setdefault(row["day"], []).append(row)
    conn.close()
    for day, rows in out["players"].items():
        rows.sort(key=lambda r: -(r["score"] or 0))
    out["week"].sort(key=lambda r: -(r["score"] or 0))
    return out


def my_uid() -> str:
    """The reader's own uid, asked of the live client. Empty when there is none."""
    try:
        from lua_client import get_evaluator
        ev = get_evaluator()
        for line in ev.run(
                'CS.UnityEngine.Debug.LogError("VSME "..tostring(LuaEntry.Player.uid))',
                marker="VSME", settle=1.5):
            if "VSME " in line:
                return line.split("VSME ", 1)[1].strip()
    except Exception:                            # noqa: BLE001 — no client is an answer
        pass
    return ""


def _side_card(row, side_rows) -> str:
    kind = "own" if row["side"] == "own" else "foe"
    total = sum(r["score"] or 0 for r in side_rows if r["alliance_id"] == row["alliance_id"])
    return (f'<div class="side {kind}"><div class="tag">[{_esc(row["alliance"])}]'
            f' <span class="gap">#{_esc(row["server_id"])}</span></div>'
            f'<div class="num">{_num(total)}</div>'
            f'<div class="meta">{_esc(row["name"])}</div></div>')


def _bar(own: int, foe: int) -> str:
    total = (own or 0) + (foe or 0) or 1
    return (f'<div class="bar"><i class="own" style="width:{own * 100 / total:.1f}%"></i>'
            f'<i class="foe" style="width:{foe * 100 / total:.1f}%"></i></div>')


def render(data: dict, me: str = "") -> str:
    days = sorted(d for d in data["players"] if d is not None)
    side_days = data["sides"]
    parts = ["<!doctype html><html lang=\"ru\"><head><meta charset=\"utf-8\">",
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             "<title>VS</title><style>", _CSS, "</style></head><body>"]
    at = time.strftime("%d.%m.%Y %H:%M", time.localtime(data["at"] or time.time()))
    parts.append(f"<h1>Дуэль альянсов</h1><div class=\"sub\">снято {at} · "
                 f"дней с данными: {len(days)}</div>")

    # The week: each side's total across every day that has rows.
    totals: dict = {}
    for day, rows in side_days.items():
        for row in rows:
            key = row["alliance_id"]
            entry = totals.setdefault(key, {"row": row, "score": 0, "won": 0})
            entry["score"] += row["score"] or 0
    for day, rows in side_days.items():
        if len(rows) == 2 and (rows[0]["score"] or 0) != (rows[1]["score"] or 0):
            best = max(rows, key=lambda r: r["score"] or 0)
            totals[best["alliance_id"]]["won"] += 1
    if totals:
        parts.append('<div class="card"><div class="sides">')
        for entry in sorted(totals.values(), key=lambda e: -e["score"]):
            row = entry["row"]
            kind = "own" if row["side"] == "own" else "foe"
            parts.append(
                f'<div class="side {kind}"><div class="tag">[{_esc(row["alliance"])}]'
                f' <span class="gap">#{_esc(row["server_id"])}</span></div>'
                f'<div class="num">{_num(entry["score"])}</div>'
                f'<div class="meta">{_esc(row["name"])} · дней выиграно: '
                f'{entry["won"]}</div></div>')
        parts.append("</div></div>")

    # The strip: who took each day, and by how much.
    if side_days:
        parts.append('<div class="card"><h1 style="font-size:16px">По дням</h1>')
        for day in sorted(side_days):
            rows = sorted(side_days[day], key=lambda r: -(r["score"] or 0))
            own = next((r for r in rows if r["side"] == "own"), None)
            foe = next((r for r in rows if r["side"] != "own"), None)
            own_score = (own or {}).get("score") or 0
            foe_score = (foe or {}).get("score") or 0
            lead = abs(own_score - foe_score)
            who = "выигран" if own_score > foe_score else "проигран"
            css = "won" if own_score > foe_score else "lost"
            parts.append(
                f'<div style="margin:10px 0"><div class="day-head"><b>День {day}</b>'
                f'<span class="{css}">{who}, отрыв {_num(lead)}</span></div>'
                f'{_bar(own_score, foe_score)}'
                f'<div class="gap" style="margin-top:4px">'
                f'<span class="dot own"></span>{_num(own_score)} &nbsp; '
                f'<span class="dot foe"></span>{_num(foe_score)}</div></div>')
        parts.append("</div>")

    if data["week"]:
        parts.append('<div class="card"><h1 style="font-size:16px">Итог за неделю'
                     '</h1>' + _table(data["week"], me) + "</div>")

    for day in days:
        rows = data["players"][day]
        parts.append(f'<div class="card"><h1 style="font-size:16px">День {day}</h1>'
                     f'{_table(rows, me)}</div>')

    parts.append("</body></html>")
    return "".join(parts)


def _table(rows, me: str, top: int = 30) -> str:
    """One ranking. The first `top` rows are open, the rest fold away."""
    head = ('<table><thead><tr><th class="n">#</th><th>Игрок</th><th>Альянс</th>'
            '<th class="n">Очки</th></tr></thead><tbody>')
    body = []
    for index, row in enumerate(rows, 1):
        kind = "own" if row["side"] == "own" else "foe"
        mine = " me" if me and str(row["uid"] or "") == str(me) else ""
        body.append(
            f'<tr class="{kind}{mine}"><td class="n">{index}</td>'
            f'<td>{_esc(row["name"])}</td>'
            f'<td><span class="dot {kind}"></span>[{_esc(row["alliance"])}] '
            f'<span class="gap">#{_esc(row["server_id"])}</span></td>'
            f'<td class="n">{_num(row["score"])}</td></tr>')
    if len(body) <= top:
        return head + "".join(body) + "</tbody></table>"
    rest = len(body) - top
    return (head + "".join(body[:top]) + "</tbody></table>"
            + f"<details><summary>ещё {rest}</summary>" + head
            + "".join(body[top:]) + "</tbody></table></details>")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sqlite", default="profiles/default/leaderboard_history.db")
    ap.add_argument("--out", default="profiles/default/vs_report.html")
    ap.add_argument("--me", default=None,
                    help="the uid to mark as the reader's own; asked of the live "
                         "client when left out")
    args = ap.parse_args()

    head = os.path.normpath(args.out).replace("\\", "/").split("/")[0]
    if head not in _ALLOWED_ROOTS and not os.path.isabs(args.out):
        print(f"refusing to write outside {'/, '.join(_ALLOWED_ROOTS)}/ — the page is "
              f"full of real names, uids and servers, and those trees are the "
              f"git-ignored ones", file=sys.stderr)
        return 1

    data = load(args.sqlite)
    if not data["players"] and not data["sides"]:
        print(f"no VS rows in {args.sqlite} — run tools/vs_rankings.py --sqlite first")
        return 1
    me = args.me if args.me is not None else my_uid()
    page = render(data, me=me)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    days = sorted(d for d in data["players"] if d is not None)
    print(f"{args.out} — {len(days)} day(s), "
          f"{sum(len(v) for v in data['players'].values())} player row(s), "
          f"{len(data['week'])} in the week's standing"
          + (", your row is marked" if me else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

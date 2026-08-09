#!/usr/bin/env python3
r"""One HTML page of everybody's rally squads, out of the rally archives — for reading.

    python tools/rally_report.py
    python tools/rally_report.py --input profiles/default/rally_log.jsonl \
                                --out profiles/rally_report.html

The rally monitor (`tools/rally_monitor.py`) archives one line per participant of every
`push.alliance.march.create/refresh` it sees, into `profiles/<profile>/rally_log.jsonl`.
This folds every profile's archive into one page: the players, each player's squads, the
last reading of each squad, and how each squad's power moved over the recorded window.

One self-contained file — no scripts fetched, no fonts fetched, no network at all — so
it opens on a phone that is nowhere near this machine. The charts are inline SVG built
in the page; there is no charting library.

**What identifies a squad between rallies: `armyInfo.f4`.**

That field is the squad slot the march was sent from — 1..4 on the sampled data, present
on 100% of 44 817 archived lines across four profiles. It is the only stable key there
is, and it was checked rather than assumed:

* two different slots of the same player never once shared a hero composition, so the
  slot is not being reused for unrelated armies;
* it survives a hero being swapped inside a squad, which a composition key does not —
  one player's slot 2 changed one of its five heroes mid-window and stayed slot 2;
* the formation preset (`armyInfo.f2.f13`) does NOT identify a squad: 253 players
  averaged 1.00 distinct formation values each, i.e. it is one setting per player, the
  same on every squad they own;
* the march uuid (`armyInfo.f1.f3`) is allocated per march, so keying on it turns every
  rally into a brand-new "squad" — which is what the previous report did.

**Power in a rally is what marched, not what the squad is worth.** A squad that lost
soldiers marches at a fraction of its power — 27 M at 1 725 hp where the same slot sends
56 M at 3 123 hp. So the page offers two readings of the same series: `мощь` as archived,
and `на бойца` (power ÷ curHp), which takes the wound out and shows the underlying
growth. Neither is derived from the other by the page's author's guess — both are printed
from the archived pair.

**The output is other people's accounts and never belongs in the repository.** Every row
carries a nickname and a uid, most of them belonging to players who never heard of this
tool. The default destination is inside `profiles/`, which is git-ignored; `--out`
somewhere tracked is refused.
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

#: Written into a directory that is not git-ignored, this file is two hundred players'
#: nicknames and uids in a tracked tree. The check is deliberately crude and deliberately
#: refuses rather than warns.
_ALLOWED_ROOTS = ("profiles", "results", "screenshots")

#: The drone / air-support slot — a squad row, but not a hero.
DRONE_ID = 1000000

#: Grade at which the exclusive weapon ("专武") starts carrying its bonus levels.
ZW_GRADE = 30


# --------------------------------------------------------------------------- reading


def _as_list(value):
    """A protobuf repeated field collapses to a bare dict when it occurs once."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _squad_rows(army):
    """The per-slot rows of a decoded ``armyInfo`` — heroes and the drone."""
    if not isinstance(army, dict):
        return []
    body = army.get("f2")
    if not isinstance(body, dict):
        return []
    return [row for row in _as_list(body.get("f2")) if isinstance(row, dict)]


def _slot(army):
    """The squad slot the march was sent from — ``armyInfo.f4``. See the module doc."""
    if not isinstance(army, dict):
        return 0
    value = army.get("f4")
    return value if isinstance(value, int) else 0


def _detail(army) -> dict:
    """Heroes, drone and formation of one archived march, in display shape."""
    heroes, drone = [], None
    for row in _squad_rows(army):
        hero_id = row.get("f1")
        grade = row.get("f15")
        if hero_id == DRONE_ID:
            payload = row.get("f16") if isinstance(row.get("f16"), dict) else {}
            drone = {"grade": payload.get("f2") if payload else row.get("f8")}
            continue
        bonus = [
            {"stage": b.get("f1"), "level": b.get("f2")}
            for b in _as_list(row.get("f17")) if isinstance(b, dict)
        ]
        bonus.sort(key=lambda b: b.get("stage") or 0)
        heroes.append({
            "id": hero_id,
            "slot": row.get("f4"),
            "level": row.get("f2"),
            "tier": row.get("f3"),
            "grade": grade,
            "zw": bonus,
        })
    heroes.sort(key=lambda h: h.get("slot") or 0)
    body = army.get("f2") if isinstance(army, dict) else None
    formation = body.get("f13") if isinstance(body, dict) else None
    return {"heroes": heroes, "drone": drone, "formation": formation}


def _hero_names() -> dict:
    """``heroId -> display name`` for the ids anybody has confirmed by eye.

    Most ids resolve to nothing — the table lives in the game's encrypted config
    (`tools/lib/hero_icons_map.py`), so the page falls back to `#<id>`.
    """
    try:
        import hero_icons_map as hero_map
    except Exception:                            # noqa: BLE001 — a missing table is fine
        return {}
    return {hero_id: name.replace("_", " ")
            for hero_id, name in getattr(hero_map, "CONFIRMED", {}).items()}


def load(paths) -> dict:
    """Fold every archive into ``{players: [...], sources: [...], window: [from, to]}``.

    The same rally reaches every profile that was watching, so the lines are deduplicated
    on ``(teamUuid, ownerUid, second, power, curHp)`` before anything is counted — four
    profiles of the same alliance carry 44 817 lines and 13 206 distinct readings.
    """
    seen: set = set()
    players: dict = {}
    sources: list = []
    lo = hi = 0.0

    for path in paths:
        kept = 0
        try:
            handle = open(path, encoding="utf-8")
        except OSError:
            continue
        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                uid = str(row.get("ownerUid") or "")
                stamp = float(row.get("timestamp") or 0)
                power = int(row.get("power") or 0)
                hp = int(row.get("curHp") or 0)
                team = str(row.get("teamUuid") or "0")
                key = (team, uid, round(stamp), power, hp)
                if not uid or key in seen:
                    continue
                seen.add(key)
                kept += 1
                lo = stamp if not lo else min(lo, stamp)
                hi = max(hi, stamp)

                player = players.get(uid)
                if player is None:
                    player = players[uid] = {"uid": uid, "name": "", "aliases": set(),
                                             "rallies": set(), "squads": {}, "seen": 0}
                player["seen"] += 1
                name = row.get("ownerName") or ""
                if name:
                    player["aliases"].add(name)
                    # The archive is read oldest-first per file but files interleave, so
                    # the displayed name is the one from the latest line, not the last
                    # line read.
                    if stamp >= player.get("_named", 0):
                        player["name"], player["_named"] = name, stamp
                if team != "0":
                    player["rallies"].add(team)

                army = row.get("armyInfoRaw")
                slot = _slot(army)
                squad = player["squads"].get(slot)
                if squad is None:
                    squad = player["squads"][slot] = {
                        "slot": slot, "rallies": set(), "seen": 0,
                        "points": [], "_best": (-1, 0.0), "detail": None,
                    }
                squad["seen"] += 1
                if team != "0":
                    squad["rallies"].add(team)
                squad["points"].append((stamp, power, hp))
                # The composition to display is the FULLEST reading, latest among equals.
                # A squad that marched wiped is archived with the one hero that survived,
                # and the newest line is not the one that says what the squad is.
                detail = _detail(army)
                mark = (len(detail["heroes"]), stamp)
                if mark > squad["_best"]:
                    squad["_best"], squad["detail"] = mark, detail
        sources.append({"path": path, "kept": kept})

    names = _hero_names()
    out = []
    for player in players.values():
        player.pop("_named", None)
        squads = []
        for squad in player["squads"].values():
            squad["points"].sort(key=lambda p: p[0])
            # One point per change: a refresh re-broadcasts the same march unchanged, and
            # a flat run of forty identical readings is forty pixels on top of each other.
            series = []
            for stamp, power, hp in squad["points"]:
                if series and series[-1][1] == power and series[-1][2] == hp:
                    continue
                series.append([round(stamp), power, hp])
            detail = squad["detail"] or {"heroes": [], "drone": None, "formation": None}
            for hero in detail["heroes"]:
                hero["name"] = names.get(hero["id"], "")
            full = max((hp for _, _, hp in series), default=0)
            squads.append({
                "slot": squad["slot"],
                "rallies": len(squad["rallies"]),
                "seen": squad["seen"],
                "first": series[0][0] if series else 0,
                "last": series[-1][0] if series else 0,
                "power": series[-1][1] if series else 0,
                "hp": series[-1][2] if series else 0,
                "peak": max((p for _, p, _ in series), default=0),
                "fullHp": full,
                "formation": detail["formation"],
                "heroes": detail["heroes"],
                "drone": detail["drone"],
                "series": series,
            })
        squads.sort(key=lambda s: s["slot"])
        last = max((s["last"] for s in squads), default=0)
        out.append({
            "uid": player["uid"],
            "name": player["name"] or player["uid"],
            "aliases": sorted(a for a in player["aliases"] if a != player["name"]),
            "rallies": len(player["rallies"]),
            "seen": player["seen"],
            "last": last,
            "power": sum(s["power"] for s in squads),
            "peak": sum(s["peak"] for s in squads),
            "squads": squads,
        })
    out.sort(key=lambda p: -p["peak"])
    return {"players": out, "sources": sources, "window": [round(lo), round(hi)]}


# --------------------------------------------------------------------------- drawing


_CSS = """
:root{--bg:#12141a;--card:#1b1e27;--line:#2b303d;--ink:#e8eaf0;--dim:#98a0b3;
--accent:#4da3ff;--warn:#ff8a5c;--good:#5fd68a;--gold:#ffd23f;
--s1:#4da3ff;--s2:#5fd68a;--s3:#ffd23f;--s4:#ff8a5c;--s0:#b07cff}
*{box-sizing:border-box}
body{margin:0;padding:16px;background:var(--bg);color:var(--ink);
font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
-webkit-text-size-adjust:100%}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--dim);font-size:13px;margin-bottom:14px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
input[type=search]{flex:1 1 200px;min-width:0;background:var(--card);color:var(--ink);
border:1px solid var(--line);border-radius:10px;padding:9px 12px;font-size:15px}
.seg{display:flex;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.seg button{background:var(--card);color:var(--dim);border:0;padding:9px 12px;
font-size:14px;cursor:pointer}
.seg button.on{background:var(--accent);color:#0d1017;font-weight:600}
.pl{background:var(--card);border:1px solid var(--line);border-radius:12px;
margin-bottom:10px;overflow:hidden}
.pl>.hd{display:flex;align-items:baseline;gap:8px;padding:12px 14px;cursor:pointer}
.pl>.hd:active{background:#222631}
.pl.open>.hd{border-bottom:1px solid var(--line)}
.nm{font-weight:600;flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;
white-space:nowrap}
.pw{font-variant-numeric:tabular-nums;font-weight:700;white-space:nowrap;
margin-left:auto}
.pw .up,.pw .dn{font-weight:600;font-size:12px;margin-left:4px}
.meta{color:var(--dim);font-size:12px;white-space:nowrap}
.bd{padding:0 14px 12px}
.sq{border-top:1px solid var(--line)}
.sq>.hd{display:flex;align-items:baseline;gap:8px;padding:10px 2px;cursor:pointer}
.sq>.hd:active{background:#222631}
.chip{display:inline-block;padding:1px 7px;border-radius:999px;font-size:12px;
font-weight:700;color:#0d1017}
.c1{background:var(--s1)}.c2{background:var(--s2)}.c3{background:var(--s3)}
.c4{background:var(--s4)}.c0{background:var(--s0)}
.sqbd{padding:2px 0 12px}
.heroes{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.hero{background:#222631;border:1px solid var(--line);border-radius:8px;padding:5px 8px;
font-size:12px;line-height:1.3}
.hero b{display:block;font-size:13px;font-weight:600}
.hero .g{color:var(--dim)}
.hero .zw{color:var(--gold);margin-left:6px}
.kv{display:flex;flex-wrap:wrap;gap:4px 14px;color:var(--dim);font-size:12px;
margin-top:4px}
.kv b{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
svg{display:block;width:100%;height:auto;touch-action:pan-y}
.legend{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--dim);
margin-top:6px}
.legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px}
.empty{color:var(--dim);font-size:13px;padding:10px 0}
.up{color:var(--good)}.dn{color:var(--warn)}
@media(max-width:520px){body{padding:10px}.pl>.hd{padding:11px 11px}.bd{padding:0 11px 10px}}
"""

_JS = r"""
var MODE = 'full';
var COL = ['#b07cff','#4da3ff','#5fd68a','#ffd23f','#ff8a5c'];

function num(v){
  v = Math.round(v || 0);
  return String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}
function big(v){
  if (v >= 1e6) return (v / 1e6).toFixed(v >= 1e7 ? 1 : 2).replace('.', ',') + ' M';
  if (v >= 1e4) return Math.round(v / 1e3) + ' k';
  return num(v);
}
function when(sec){
  var d = new Date(sec * 1000), p = function(n){ return (n < 10 ? '0' : '') + n; };
  return p(d.getDate()) + '.' + p(d.getMonth() + 1) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
}
function day(sec){
  var d = new Date(sec * 1000), p = function(n){ return (n < 10 ? '0' : '') + n; };
  return p(d.getDate()) + '.' + p(d.getMonth() + 1);
}
function value(pt){
  return MODE === 'unit' ? (pt[2] > 0 ? pt[1] / pt[2] : 0) : pt[1];
}
/* What a squad's power series is worth reading.
   `full` — only the marches that went out at (near) full strength, which is the only
   series where a rise or a fall is the squad changing rather than its wounds;
   `all`  — every archived reading, wounds and all;
   `unit` — power per soldier, which takes the wound out of every reading. */
function fullPoints(s){
  var floor = s.fullHp * 0.95;
  return s.series.filter(function(p){ return p[2] >= floor; });
}
function points(s){
  return MODE === 'full' ? fullPoints(s) : s.series;
}
function esc(s){
  return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];
  });
}

/* An inline SVG line chart. series = [{name, color, pts:[[t, power, hp], ...]}] */
function chart(series){
  var W = 640, H = 240, L = 58, R = 12, T = 14, B = 26;
  var pts = [];
  series.forEach(function(s){ s.pts.forEach(function(p){ pts.push(p); }); });
  if (!pts.length) return '<div class="empty">нет данных</div>';
  var xs = pts.map(function(p){ return p[0]; }), ys = pts.map(value);
  var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
  var y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
  if (x1 === x0) { x0 -= 1800; x1 += 1800; }
  if (y1 === y0) { y0 = y0 * 0.98 - 1; y1 = y1 * 1.02 + 1; }
  else { var pad = (y1 - y0) * 0.12; y0 -= pad; y1 += pad; }
  if (y0 < 0 && Math.min.apply(null, ys) >= 0) y0 = 0;   /* no negative power */
  var X = function(t){ return L + (t - x0) / (x1 - x0) * (W - L - R); };
  var Y = function(v){ return T + (1 - (v - y0) / (y1 - y0)) * (H - T - B); };

  var out = ['<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" font-family="inherit">'];
  for (var i = 0; i <= 3; i++) {
    var v = y0 + (y1 - y0) * i / 3, y = Y(v);
    out.push('<line x1="' + L + '" y1="' + y.toFixed(1) + '" x2="' + (W - R) +
             '" y2="' + y.toFixed(1) + '" stroke="#2b303d" stroke-width="1"/>');
    out.push('<text x="' + (L - 6) + '" y="' + (y + 4).toFixed(1) + '" fill="#98a0b3" ' +
             'font-size="12" text-anchor="end">' + big(v) + '</text>');
  }
  /* Under four days every tick would read the same date, so the clock goes in too. */
  var label = (x1 - x0) < 4 * 86400 ? when : day;
  for (var k = 0; k <= 2; k++) {
    var t = x0 + (x1 - x0) * k / 2, tx = X(t);
    var anchor = k === 0 ? 'start' : (k === 2 ? 'end' : 'middle');
    out.push('<text x="' + tx.toFixed(1) + '" y="' + (H - 6) + '" fill="#98a0b3" ' +
             'font-size="12" text-anchor="' + anchor + '">' + label(t) + '</text>');
  }
  series.forEach(function(s){
    if (!s.pts.length) return;
    var d = s.pts.map(function(p, i){
      return (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(value(p)).toFixed(1);
    }).join(' ');
    out.push('<path d="' + d + '" fill="none" stroke="' + s.color +
             '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>');
    var dots = s.pts.length <= 60 ? s.pts : [s.pts[0], s.pts[s.pts.length - 1]];
    dots.forEach(function(p){
      out.push('<circle cx="' + X(p[0]).toFixed(1) + '" cy="' + Y(value(p)).toFixed(1) +
               '" r="2.6" fill="' + s.color + '"><title>' + esc(s.name) + ' · ' +
               when(p[0]) + ' · ' + num(p[1]) + ' · ' + num(p[2]) + ' бойцов</title></circle>');
    });
  });
  out.push('</svg>');
  return out.join('');
}

function legend(series){
  return '<div class="legend">' + series.map(function(s){
    return '<span><i style="background:' + s.color + '"></i>' + esc(s.name) + '</span>';
  }).join('') + '</div>';
}

function squadSeries(s){
  return {name: 'Отряд ' + (s.slot || '?'), color: COL[s.slot] || COL[0], pts: points(s)};
}

/* The squad's headline number: what it marched at, at full strength, most recently.
   The last archived reading is not it — a squad that went out wiped is archived at a
   twentieth of its power, and calling that "the squad" is reading a casualty list. */
function headline(s){
  var pick = MODE === 'all' ? s.series : fullPoints(s);
  if (!pick.length) pick = s.series;
  var last = pick[pick.length - 1];
  return last ? value(last) : 0;
}

function delta(s){
  var pts = MODE === 'full' ? points(s) : s.series;
  if (pts.length < 2) return '';
  var a = value(pts[0]), b = value(pts[pts.length - 1]);
  if (!a) return '';
  var pc = (b - a) / a * 100;
  var cls = pc >= 0 ? 'up' : 'dn';
  return '<span class="' + cls + '">' + (pc >= 0 ? '+' : '') +
         pc.toFixed(1).replace('.', ',') + ' %</span>';
}

function heroCard(h){
  var name = h.name ? esc(h.name) : '#' + h.id;
  var zw = (h.zw || []).map(function(b){ return b.stage + ':' + b.level; }).join(' ');
  return '<div class="hero"><b>' + name + '</b>' +
         '<span class="g">★' + (h.tier == null ? '?' : h.tier) +
         ' · ур. ' + (h.level == null ? '?' : h.level) +
         (h.grade == null ? '' : ' · оруж. ' + h.grade) + '</span>' +
         (zw ? '<span class="zw">专武 ' + esc(zw) + '</span>' : '') + '</div>';
}

function squadBody(s){
  var parts = [];
  parts.push('<div class="heroes">' + s.heroes.map(heroCard).join('') +
             (s.drone ? '<div class="hero"><b>Дрон</b><span class="g">ур. ' +
              (s.drone.grade == null ? '?' : s.drone.grade) + '</span></div>' : '') +
             '</div>');
  var full = fullPoints(s), lastFull = full.length ? full[full.length - 1] : null;
  parts.push('<div class="kv">' +
    '<span>в полном составе <b>' + (lastFull ? num(lastFull[1]) : '—') + '</b></span>' +
    '<span>пик <b>' + num(s.peak) + '</b></span>' +
    '<span>последний выход <b>' + num(s.power) + '</b> при ' + num(s.hp) + ' из ' +
      num(s.fullHp) + ' бойцов</span>' +
    '<span>на бойца <b>' + (s.hp ? num(s.power / s.hp) : '—') + '</b></span>' +
    '<span>построение <b>' + (s.formation == null ? '—' : s.formation) + '</b></span>' +
    '<span>стягов <b>' + s.rallies + '</b> (в полном составе ' + full.length + ')</span>' +
    '<span>замечен <b>' + when(s.last) + '</b></span>' +
    '<span>с <b>' + when(s.first) + '</b></span></div>');
  var series = squadSeries(s);
  if (series.pts.length < 2) {
    parts.push('<div class="empty">на этом режиме у отряда одно измерение — ' +
               'график будет, когда он выйдет в стяг ещё раз</div>');
  } else {
    parts.push(chart([series]));
  }
  return '<div class="sqbd">' + parts.join('') + '</div>';
}

function playerBody(p){
  var series = p.squads.map(squadSeries).filter(function(s){ return s.pts.length >= 2; });
  var parts = [];
  parts.push('<div class="kv"><span>uid <b>' + esc(p.uid) + '</b></span>' +
    (p.aliases.length ? '<span>раньше <b>' + p.aliases.map(esc).join(', ') +
      '</b></span>' : '') +
    '<span>стягов <b>' + p.rallies + '</b></span>' +
    '<span>записей <b>' + p.seen + '</b></span>' +
    '<span>замечен <b>' + when(p.last) + '</b></span></div>');
  if (series.length) {
    parts.push(chart(series) + legend(series));
    var quiet = p.squads.filter(function(s){ return points(s).length < 2; });
    if (quiet.length) {
      parts.push('<div class="empty">не на графике: ' + quiet.map(function(s){
        return 'отряд ' + (s.slot || '?'); }).join(', ') +
        ' — меньше двух выходов на этом режиме</div>');
    }
  } else {
    parts.push('<div class="empty">пока по одному измерению на отряд — общего графика ' +
               'нет</div>');
  }
  p.squads.forEach(function(s, i){
    var who = s.heroes.map(function(h){ return h.name ? esc(h.name) : '#' + h.id; })
                      .join(', ') || 'состав не записан';
    parts.push('<div class="sq" data-sq="' + i + '"><div class="hd">' +
      '<span class="chip c' + (s.slot || 0) + '">' + (s.slot || '?') + '</span>' +
      '<span class="nm">' + who + '</span>' +
      '<span class="pw">' + num(headline(s)) + ' ' + delta(s) + '</span>' +
      '</div></div>');
  });
  return parts.join('');
}

function render(){
  var q = document.getElementById('q').value.trim().toLowerCase();
  var host = document.getElementById('list');
  var shown = 0, out = [], rows = [];
  DATA.players.forEach(function(p, i){
    if (q && p.name.toLowerCase().indexOf(q) < 0 && p.uid.indexOf(q) < 0) return;
    rows.push({i: i, p: p, sum: p.squads.reduce(function(a, s){
      return a + headline(s); }, 0)});
  });
  /* Ordered by the number actually printed, so switching the mode reorders the list
     instead of leaving it sorted by something the reader cannot see. */
  rows.sort(function(a, b){ return b.sum - a.sum; });
  rows.forEach(function(r){
    shown++;
    out.push('<div class="pl" data-pl="' + r.i + '"><div class="hd">' +
      '<span class="nm">' + esc(r.p.name) + '</span>' +
      '<span class="pw">' + num(r.sum) + '</span>' +
      '<span class="meta">' + r.p.squads.length + ' отр. · ' + r.p.rallies +
      ' стяг.</span></div></div>');
  });
  host.innerHTML = out.join('') ||
    '<div class="empty">никого не нашлось</div>';
  document.getElementById('count').textContent = shown + ' из ' + DATA.players.length;
}

document.addEventListener('click', function(ev){
  if (!ev.target.closest) return;
  /* Only the header row toggles — a click inside an open body (a hero card, the
     chart) must not fold the thing the reader is looking at. */
  var sqHead = ev.target.closest('.sq > .hd');
  var sq = sqHead && sqHead.parentNode;
  if (sq) {
    var pl = sq.closest('.pl');
    var p = DATA.players[+pl.dataset.pl], s = p.squads[+sq.dataset.sq];
    var open = sq.querySelector('.sqbd');
    if (open) { open.remove(); } else {
      pl.querySelectorAll('.sqbd').forEach(function(n){ n.remove(); });
      sq.insertAdjacentHTML('beforeend', squadBody(s));
    }
    return;
  }
  var plHead = ev.target.closest('.pl > .hd');
  var pl = plHead && plHead.parentNode;
  if (!pl) return;
  var body = pl.querySelector('.bd');
  if (body) { body.remove(); pl.classList.remove('open'); return; }
  pl.classList.add('open');
  pl.insertAdjacentHTML('beforeend',
    '<div class="bd">' + playerBody(DATA.players[+pl.dataset.pl]) + '</div>');
});

document.getElementById('q').addEventListener('input', render);
document.querySelectorAll('.seg button').forEach(function(b){
  b.addEventListener('click', function(){
    document.querySelectorAll('.seg button').forEach(function(o){ o.classList.remove('on'); });
    b.classList.add('on');
    MODE = b.dataset.mode;
    render();
  });
});
render();
"""


def render(data: dict) -> str:
    """The whole page — data, style and behaviour in one file."""
    window = data["window"]
    span = ""
    if window and window[1]:
        span = (time.strftime("%d.%m %H:%M", time.localtime(window[0])) + " — "
                + time.strftime("%d.%m %H:%M", time.localtime(window[1])))
    squads = sum(len(p["squads"]) for p in data["players"])
    kept = sum(s["kept"] for s in data["sources"])
    files = ", ".join(html.escape(os.path.basename(os.path.dirname(s["path"])) or s["path"])
                      for s in data["sources"] if s["kept"])
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Отряды в стягах</title><style>" + _CSS + "</style></head><body>"
        "<h1>Отряды в стягах</h1>"
        f'<div class="sub">{html.escape(span)} · игроков '
        f'{len(data["players"])} · отрядов {squads} · записей {kept} · '
        f'профили: {files or "—"}</div>'
        '<div class="bar"><input type="search" id="q" placeholder="имя или uid" '
        'autocomplete="off"><div class="seg">'
        '<button class="on" data-mode="full" title="только выходы полным составом">'
        'мощь</button>'
        '<button data-mode="all" title="каждая запись, включая раненые выходы">все '
        'выходы</button>'
        '<button data-mode="unit" title="мощь, делённая на число бойцов">на бойца'
        '</button></div>'
        '<span class="meta" id="count"></span></div>'
        '<div id="list"></div>'
        "<script>var DATA=" + payload + ";\n" + _JS + "</script>"
        "</body></html>"
    )


# --------------------------------------------------------------------------- entry


def _default_inputs() -> list:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return sorted(glob.glob(os.path.join(root, "profiles", "*", "rally_log.jsonl")))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", action="append", default=None,
                    help="a rally_log.jsonl to read; repeatable. Every profile's "
                         "archive when left out — a player's squads often sit in a "
                         "neighbour's capture rather than your own")
    ap.add_argument("--out", default="profiles/rally_report.html")
    ap.add_argument("--min-rallies", type=int, default=0,
                    help="drop players seen in fewer rallies than this")
    args = ap.parse_args()

    head = os.path.normpath(args.out).replace("\\", "/").split("/")[0]
    if head not in _ALLOWED_ROOTS and not os.path.isabs(args.out):
        print(f"refusing to write outside {'/, '.join(_ALLOWED_ROOTS)}/ — the page is "
              f"full of real nicknames and uids, and those trees are the git-ignored "
              f"ones", file=sys.stderr)
        return 1

    paths = args.input or _default_inputs()
    if not paths:
        print("no rally_log.jsonl found — the rally monitor writes one per profile "
              "while «Монитор стягиваний» is on", file=sys.stderr)
        return 1

    data = load(paths)
    if args.min_rallies:
        data["players"] = [p for p in data["players"] if p["rallies"] >= args.min_rallies]
    if not data["players"]:
        print("no rally rows in " + ", ".join(paths), file=sys.stderr)
        return 1

    page = render(data)
    directory = os.path.dirname(os.path.abspath(args.out))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(page)
    squads = sum(len(p["squads"]) for p in data["players"])
    points = sum(len(s["series"]) for p in data["players"] for s in p["squads"])
    print(f"{args.out} — {len(data['players'])} player(s), {squads} squad(s), "
          f"{points} reading(s), {os.path.getsize(args.out) // 1024} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

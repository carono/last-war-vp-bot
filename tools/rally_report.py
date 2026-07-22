#!/usr/bin/env python3
"""Render results/rally/monitor.jsonl into a standalone HTML rally report.

The rally monitor (``tools/rally_monitor.py`` / ``tools/watch_rally.py``) archives
every alliance rally (стяг) it sees on the wire, keeping each participant's decoded
``armyInfo`` squad — hero ids, tiers, levels, skills and the formation preset.

This tool folds that stream into one row per player. A player can send several
marches into different rallies, so every distinct march (keyed by its army uuid) is
kept and shown as its own squad in the expandable detail; the summary row aggregates
the player's peak power, army size (curHp) and how many rallies they joined.

    python3 tools/rally_report.py
    python3 tools/rally_report.py --input results/rally/monitor.jsonl --output results/rally/report.html

The page is self-contained — the parsed data is embedded inline, no external assets —
so it renders anywhere even though ``results/`` is git-ignored.

Field semantics inside ``armyInfo`` are inferred structurally — the game ships no
``.proto`` (see docs/research/protocol.md). The mapping used here:

    squad rows live at armyInfo._squad.f2.f2, one per slot:
        f1  = heroId          (50006..50027; 1000000 = air-support / drone slot)
        f2  = level           (troop level, e.g. 175)
        f3  = tier / stars    (5 == max on the sampled data)
        f4  = slot position   (1..6, marching order)
        f15 = skill grade     (inferred; per-hero upgrade counter)
        f17 = named skills     [{f1: skillId, f2: level}]
        f16 = drone payload    ({f1, f2}) on the 1000000 slot
    formation preset = armyInfo._squad.f2.f13
"""

from __future__ import annotations

import argparse
import html
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
DEFAULT_IN = os.path.join(_ROOT, "results", "rally", "monitor.jsonl")
DEFAULT_OUT = os.path.join(_ROOT, "results", "rally", "report.html")

DRONE_ID = 1000000


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _squad_rows(army_info):
    """The per-slot rows out of a decoded ``armyInfo`` block (or [])."""
    squad = (army_info or {}).get("_squad") or {}
    return _as_list((squad.get("f2") or {}).get("f2"))


def _formation(army_info):
    squad = (army_info or {}).get("_squad") or {}
    return (squad.get("f2") or {}).get("f13")


def _parse_squad(army_info):
    """Return {heroes:[...], drone:{...}|None, formation:int|None}."""
    heroes, drone = [], None
    for row in _squad_rows(army_info):
        if not isinstance(row, dict):
            continue
        hero_id = row.get("f1")
        if hero_id == DRONE_ID:
            info = row.get("f16") or {}
            drone = {"heroId": hero_id, "slot": row.get("f4"),
                     "grade": info.get("f2")}
            continue
        skills = [
            {"skillId": s.get("f1"), "level": s.get("f2")}
            for s in _as_list(row.get("f17")) if isinstance(s, dict)
        ]
        heroes.append({
            "heroId": hero_id,
            "slot": row.get("f4"),
            "level": row.get("f2"),
            "tier": row.get("f3"),
            "skillGrade": row.get("f15"),
            "skills": skills,
        })
    heroes.sort(key=lambda h: h.get("slot") or 0)
    return {"heroes": heroes, "drone": drone, "formation": _formation(army_info)}


def _squad_richness(squad):
    """How complete a snapshot is — used to keep the fullest reading of a march
    (the same army uuid is re-broadcast on every rally refresh, sometimes with
    fewer fields)."""
    skill_rows = sum(len(h.get("skills") or []) for h in squad["heroes"])
    return (len(squad["heroes"]), 1 if squad["drone"] else 0, skill_rows)


def consolidate(path):
    """Fold the raw jsonl into per-player records + totals.

    players[uid] = {uid, name, alliance, allianceAbbr, power, curHp,
                    rallies:int, seen:int,
                    marches:[{uuid, teamUuid, power, curHp, targetPos, squad}]}
    """
    players = {}

    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        for army in (obj.get("armies") or []):
            uid = str(army.get("ownerUid") or army.get("ownerName") or "?")
            rec = players.get(uid)
            if rec is None:
                rec = players[uid] = {
                    "uid": uid,
                    "name": army.get("ownerName") or uid,
                    "alliance": army.get("allianceName") or "",
                    "allianceAbbr": army.get("allianceAbbr") or "",
                    "power": 0, "curHp": 0,
                    "seen": 0, "_rallies": set(), "_marches": {},
                }

            rec["seen"] += 1
            rec["power"] = max(rec["power"], army.get("power") or 0)
            rec["curHp"] = max(rec["curHp"], army.get("maxHp") or army.get("curHp") or 0)
            if army.get("allianceName") and not rec["alliance"]:
                rec["alliance"] = army["allianceName"]
            team = army.get("teamUuid")
            if team:
                rec["_rallies"].add(str(team))

            squad = _parse_squad(army.get("armyInfo"))
            mid = str(army.get("uuid") or f"seen{rec['seen']}")
            existing = rec["_marches"].get(mid)
            march = {
                "uuid": mid,
                "teamUuid": str(team) if team else None,
                "power": army.get("power") or 0,
                "curHp": army.get("maxHp") or army.get("curHp") or 0,
                "targetPos": army.get("targetPos"),
                "squad": squad,
            }
            # a march can be re-broadcast; keep the fullest squad reading.
            if existing is None or _squad_richness(squad) > _squad_richness(existing["squad"]):
                rec["_marches"][mid] = march

    out = []
    for rec in players.values():
        marches = sorted(rec.pop("_marches").values(),
                         key=lambda m: m["power"], reverse=True)
        rec["marches"] = marches
        rec["rallies"] = len(rec.pop("_rallies"))
        out.append(rec)
    out.sort(key=lambda r: r["power"], reverse=True)

    totals = {
        "players": len(out),
        "marches": sum(len(r["marches"]) for r in out),
        "rallies": len({t for r in out for m in r["marches"] if m["teamUuid"] for t in [m["teamUuid"]]}),
        "totalPower": sum(r["power"] for r in out),
        "topPower": out[0]["power"] if out else 0,
    }
    return {"players": out, "totals": totals}


# --------------------------------------------------------------------------- #
#  HTML rendering
# --------------------------------------------------------------------------- #

_CSS = """
:root{
  --bg:#0b0e14; --panel:#141a26; --panel2:#1b2333; --line:#26304a;
  --ink:#e8edf7; --dim:#8b97b0; --gold:#f5c451; --hot:#ff5d5d;
  --cyan:#42d4e0; --grad1:#7c5cff; --grad2:#42d4e0;
}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 70% -10%,#1a2138 0,var(--bg) 60%);
  color:var(--ink);font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:32px 20px 80px}
header h1{font-size:30px;margin:0 0 4px;letter-spacing:.3px;
  background:linear-gradient(90deg,var(--grad1),var(--grad2));-webkit-background-clip:text;
  background-clip:text;color:transparent}
header .sub{color:var(--dim);margin-bottom:24px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:20px 0 30px}
.stat{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);
  border-radius:14px;padding:16px 18px}
.stat .n{font-size:26px;font-weight:700;letter-spacing:.5px}
.stat .l{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:1.2px;margin-top:2px}
.hint{color:var(--dim);font-size:12.5px;margin:0 0 10px}
table.players{width:100%;border-collapse:separate;border-spacing:0;
  background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
table.players thead th{text-align:left;color:var(--dim);font-size:11px;text-transform:uppercase;
  letter-spacing:1.2px;padding:12px 16px;border-bottom:1px solid var(--line);background:#10151f}
th.num,td.num{text-align:right}
tr.prow{cursor:pointer}
tr.prow>td{padding:13px 16px;border-bottom:1px solid var(--line)}
tr.prow:hover>td{background:#131a2a}
tr.prow.open>td{background:#161f31}
.tw{display:inline-block;width:14px;color:var(--dim);transition:transform .15s;margin-right:6px}
tr.prow.open .tw{transform:rotate(90deg);color:var(--cyan)}
.pname{font-weight:700}
.pally{color:var(--dim);font-size:12px}
.puid{color:var(--dim);font-size:11px}
.pw{color:var(--gold);font-weight:700}
.pill{display:inline-block;background:#0d1220;border:1px solid var(--line);border-radius:999px;
  padding:1px 9px;font-size:12px;color:var(--dim)}
tr.detail>td{padding:0;background:#0d111b;border-bottom:1px solid var(--line)}
tr.detail.hidden{display:none}
.dwrap{padding:14px 18px 20px}
.squad{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);
  border-radius:12px;padding:14px;margin-top:12px}
.squad:first-child{margin-top:0}
.shead{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px;
  flex-wrap:wrap}
.shead .st{font-weight:700;font-size:13px}
.shead .sm{color:var(--dim);font-size:12px;display:flex;gap:14px;flex-wrap:wrap}
.shead .sm b{color:var(--ink)}
.slots{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.slot{background:#0d1220;border:1px solid var(--line);border-radius:10px;padding:8px 9px;
  display:flex;flex-direction:column;gap:3px}
.slot .hid{font-weight:700;font-size:13px;display:flex;align-items:center;gap:6px}
.dot{width:9px;height:9px;border-radius:50%;flex:0 0 auto}
.slot .row{display:flex;justify-content:space-between;font-size:11px;color:var(--dim)}
.stars{color:var(--gold);font-size:11px;letter-spacing:1px}
.skills{display:flex;gap:4px;flex-wrap:wrap;margin-top:2px;min-height:4px}
.chip{font-size:10px;background:#182036;border:1px solid var(--line);border-radius:6px;
  padding:1px 6px;color:var(--cyan)}
.drone{margin-top:10px;font-size:12px;color:var(--dim);display:flex;align-items:center;gap:8px}
.drone b{color:var(--ink)}
footer{margin-top:44px;color:var(--dim);font-size:12px;text-align:center}
"""

_JS = """
const HUES={};
function hueFor(id){if(HUES[id]===undefined){HUES[id]=(Object.keys(HUES).length*47)%360;}return HUES[id];}
function fmt(n){return (n||0).toLocaleString('en-US');}
function stars(t){return '\\u2605'.repeat(t||0);}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

function heroSlot(h){
  const col=`hsl(${hueFor(h.heroId)} 70% 60%)`;
  const named=(h.skills||[]).map(s=>`<span class="chip">S${s.skillId}\\u00b7${s.level}</span>`).join('');
  const grade=h.skillGrade!=null?`<span class="chip">g${h.skillGrade}</span>`:'';
  return `<div class="slot">
    <div class="hid"><span class="dot" style="background:${col}"></span>#${h.heroId}</div>
    <div class="row"><span>Lv ${h.level??'\\u2014'}</span><span class="stars">${stars(h.tier)}</span></div>
    <div class="skills">${grade}${named}</div>
  </div>`;
}

function squadBlock(m,i){
  const slots=(m.squad.heroes||[]).map(heroSlot).join('')||'<div class="slot">no squad</div>';
  const drone=m.squad.drone?`<div class="drone">\\ud83d\\udee9\\ufe0f <span>Air support</span> <b>#${m.squad.drone.heroId}</b> \\u00b7 grade ${m.squad.drone.grade??'\\u2014'}</div>`:'';
  return `<div class="squad">
    <div class="shead">
      <div class="st">March ${i+1}${m.teamUuid?' \\u00b7 rally '+m.teamUuid.slice(-6):' \\u00b7 solo'}</div>
      <div class="sm">
        <span>\\u2694 <b>${fmt(m.power)}</b></span>
        <span>HP <b>${fmt(m.curHp)}</b></span>
        ${m.targetPos?`<span>target <b>${m.targetPos}</b></span>`:''}
        ${m.squad.formation?`<span>formation <b>${m.squad.formation}</b></span>`:''}
      </div>
    </div>
    <div class="slots">${slots}</div>${drone}
  </div>`;
}

function build(){
  const tb=document.getElementById('tbody');
  DATA.players.forEach((p,i)=>{
    const tr=document.createElement('tr');
    tr.className='prow';
    tr.innerHTML=`
      <td class="num">${i+1}</td>
      <td><span class="tw">\\u25b6</span><span class="pname">${esc(p.name)}</span>
          <div class="pally">${p.allianceAbbr?'['+esc(p.allianceAbbr)+'] ':''}${esc(p.alliance||'\\u2014')}</div>
          <div class="puid">uid ${esc(p.uid)}</div></td>
      <td class="num pw">${fmt(p.power)}</td>
      <td class="num">${fmt(p.curHp)}</td>
      <td class="num"><span class="pill">${p.rallies}</span></td>
      <td class="num">${p.marches.length}</td>`;
    const det=document.createElement('tr');
    det.className='detail hidden';
    det.innerHTML=`<td colspan="6"><div class="dwrap">${p.marches.map(squadBlock).join('')}</div></td>`;
    tr.addEventListener('click',()=>{tr.classList.toggle('open');det.classList.toggle('hidden');});
    tb.appendChild(tr);tb.appendChild(det);
  });
  document.getElementById('tp').textContent=fmt(DATA.totals.totalPower);
  document.getElementById('mp').textContent=fmt(DATA.totals.topPower);
}
build();
"""


def render_html(data, source):
    payload = json.dumps(data, ensure_ascii=False)
    t = data["totals"]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Last War — Rally Intel</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Rally Intel</h1>
    <div class="sub">Alliance rally (стяг) armies harvested from the wire · source: {html.escape(os.path.basename(source))}</div>
  </header>

  <div class="stats">
    <div class="stat"><div class="n">{t['players']}</div><div class="l">Players</div></div>
    <div class="stat"><div class="n">{t['rallies']}</div><div class="l">Rallies (стяги)</div></div>
    <div class="stat"><div class="n" id="tp"></div><div class="l">Combined power</div></div>
    <div class="stat"><div class="n" id="mp"></div><div class="l">Top power</div></div>
  </div>

  <p class="hint">Click a player to expand their marches — one squad per rally they joined.</p>
  <table class="players">
    <thead><tr>
      <th class="num">#</th><th>Player</th><th class="num">Power</th>
      <th class="num">Army (HP)</th><th class="num">Rallies</th><th class="num">Marches</th>
    </tr></thead>
    <tbody id="tbody"></tbody>
  </table>

  <footer>
    Squad field mapping is structurally inferred (no game .proto) — see
    tools/rally_report.py. Passive capture only.
  </footer>
</div>
<script>const DATA = {payload};</script>
<script>{_JS}</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", "--in", dest="src", default=DEFAULT_IN,
                    help="path to monitor.jsonl (default: results/rally/monitor.jsonl)")
    ap.add_argument("--output", "--out", dest="dst", default=DEFAULT_OUT,
                    help="path to the HTML report (default: results/rally/report.html)")
    args = ap.parse_args()

    if not os.path.exists(args.src) or os.path.getsize(args.src) == 0:
        raise SystemExit(f"error: {args.src} is missing or empty — nothing to report")

    data = consolidate(args.src)
    if not data["players"]:
        raise SystemExit(f"error: {args.src} has no rally armies to report")

    os.makedirs(os.path.dirname(args.dst) or ".", exist_ok=True)
    with open(args.dst, "w", encoding="utf-8") as fh:
        fh.write(render_html(data, args.src))

    t = data["totals"]
    print(f"wrote {args.dst}")
    print(f"  players={t['players']}  marches={t['marches']}  "
          f"rallies={t['rallies']}  combined power={t['totalPower']:,}")


if __name__ == "__main__":
    main()

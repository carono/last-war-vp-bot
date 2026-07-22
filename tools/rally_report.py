#!/usr/bin/env python3
"""Render results/rally/monitor.jsonl into a standalone HTML report.

The rally monitor (``tools/rally_monitor.py`` / ``tools/watch_rally.py``) archives
every alliance rally (стяг) it sees on the wire, keeping each participant's decoded
``armyInfo`` squad — hero ids, tiers, levels, skills and the formation preset.

This tool consolidates that stream into one record per player (the most complete
squad snapshot seen, plus the highest power and every rally the player joined) and
emits a single self-contained ``docs/rally-report.html`` — data embedded inline, no
external assets — so it renders anywhere even though ``results/`` is git-ignored.

    python3 tools/rally_report.py
    python3 tools/rally_report.py --in results/rally/monitor.jsonl --out docs/rally-report.html

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
DEFAULT_OUT = os.path.join(_ROOT, "docs", "rally-report.html")

DRONE_ID = 1000000


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _squad_rows(army_info):
    """The per-slot rows out of a decoded ``armyInfo`` block (or []).."""
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


def _squad_score(squad):
    """Rank a snapshot's richness so the fullest one wins (heroes, then drone,
    then how many named skills it carries)."""
    skill_rows = sum(len(h.get("skills") or []) for h in squad["heroes"])
    return (len(squad["heroes"]), 1 if squad["drone"] else 0, skill_rows)


def consolidate(path):
    """Fold the raw jsonl into per-player records + rally roster + totals."""
    players = {}          # ownerUid -> record
    rallies = {}          # teamUuid  -> {uuid, members:set, ...}

    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        for army in (obj.get("armies") or []):
            uid = str(army.get("ownerUid") or army.get("ownerName") or "?")
            squad = _parse_squad(army.get("armyInfo"))
            power = army.get("power") or 0
            team = army.get("teamUuid")

            rec = players.get(uid)
            if rec is None:
                rec = players[uid] = {
                    "uid": uid,
                    "name": army.get("ownerName") or uid,
                    "alliance": army.get("allianceName") or "",
                    "allianceAbbr": army.get("allianceAbbr") or "",
                    "power": 0, "maxHp": 0, "headSkinId": None,
                    "seen": 0, "rallies": set(), "squad": squad,
                    "_bestScore": (-1, -1, -1),
                }
            rec["seen"] += 1
            rec["power"] = max(rec["power"], power)
            rec["maxHp"] = max(rec["maxHp"], army.get("maxHp") or 0)
            if army.get("headSkinId"):
                rec["headSkinId"] = army["headSkinId"]
            if team:
                rec["rallies"].add(str(team))
            # keep the richest squad snapshot (heroes, then drone, then skills).
            score = _squad_score(squad)
            if score > rec["_bestScore"]:
                rec["_bestScore"] = score
                rec["squad"] = squad

            if team:
                r = rallies.setdefault(str(team), {
                    "teamUuid": str(team), "members": set(),
                    "leader": None, "targetPos": army.get("targetPos"),
                })
                r["members"].add(army.get("ownerName") or uid)
                if str(army.get("uuid")) == str(team):
                    r["leader"] = army.get("ownerName") or uid

    out_players = []
    for rec in players.values():
        rec["rallies"] = sorted(rec.pop("rallies"))
        rec.pop("_bestScore", None)
        out_players.append(rec)
    out_players.sort(key=lambda r: r["power"], reverse=True)

    out_rallies = []
    for r in rallies.values():
        r["members"] = sorted(r["members"])
        r["size"] = len(r["members"])
        out_rallies.append(r)
    out_rallies.sort(key=lambda r: r["size"], reverse=True)

    totals = {
        "players": len(out_players),
        "rallies": len(out_rallies),
        "totalPower": sum(r["power"] for r in out_players),
        "topPower": out_players[0]["power"] if out_players else 0,
    }
    return {"players": out_players, "rallies": out_rallies, "totals": totals}


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
a{color:var(--cyan);text-decoration:none}
.wrap{max-width:1180px;margin:0 auto;padding:32px 20px 80px}
header h1{font-size:30px;margin:0 0 4px;letter-spacing:.3px;
  background:linear-gradient(90deg,var(--grad1),var(--grad2));-webkit-background-clip:text;
  background-clip:text;color:transparent}
header .sub{color:var(--dim);margin-bottom:24px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:20px 0 36px}
.stat{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);
  border-radius:14px;padding:16px 18px}
.stat .n{font-size:26px;font-weight:700;letter-spacing:.5px}
.stat .l{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:1.2px;margin-top:2px}
h2{font-size:14px;text-transform:uppercase;letter-spacing:2px;color:var(--dim);
  margin:40px 0 16px;border-bottom:1px solid var(--line);padding-bottom:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
.card{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);
  border-radius:16px;padding:18px;position:relative;overflow:hidden}
.card::before{content:"";position:absolute;inset:0 0 auto 0;height:3px;
  background:linear-gradient(90deg,var(--grad1),var(--grad2))}
.card .top{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.card .name{font-size:18px;font-weight:700}
.card .ally{color:var(--dim);font-size:12.5px;margin-top:2px}
.rank{font-size:11px;color:var(--dim);background:#0d1220;border:1px solid var(--line);
  border-radius:999px;padding:2px 9px;white-space:nowrap}
.power{font-size:20px;font-weight:700;color:var(--gold);margin:12px 0 2px}
.metaline{color:var(--dim);font-size:12px;display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px}
.slots{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.slot{background:#0d1220;border:1px solid var(--line);border-radius:10px;padding:8px 9px;
  display:flex;flex-direction:column;gap:3px}
.slot .hid{font-weight:700;font-size:13px;display:flex;align-items:center;gap:6px}
.dot{width:9px;height:9px;border-radius:50%;flex:0 0 auto}
.slot .row{display:flex;justify-content:space-between;font-size:11px;color:var(--dim)}
.stars{color:var(--gold);font-size:11px;letter-spacing:1px}
.skills{display:flex;gap:4px;flex-wrap:wrap;margin-top:2px}
.chip{font-size:10px;background:#182036;border:1px solid var(--line);border-radius:6px;
  padding:1px 6px;color:var(--cyan)}
.drone{margin-top:10px;font-size:12px;color:var(--dim);display:flex;align-items:center;gap:8px}
.drone b{color:var(--ink)}
.form{margin-top:8px;font-size:12px;color:var(--dim)}
.form b{color:var(--ink)}
.rtable{width:100%;border-collapse:collapse;font-size:13px}
.rtable th,.rtable td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line)}
.rtable th{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:1px}
.rtable tr:hover td{background:#131a2a}
.mtag{display:inline-block;background:#182036;border:1px solid var(--line);border-radius:6px;
  padding:1px 7px;margin:1px 3px 1px 0;font-size:11.5px}
.lead{color:var(--gold)}
footer{margin-top:50px;color:var(--dim);font-size:12px;text-align:center}
"""

_JS = """
const HUES = {};
function hueFor(id){
  if(HUES[id]===undefined){
    const n=Object.keys(HUES).length;
    HUES[id]=(n*47)%360;
  }
  return HUES[id];
}
function fmt(n){return (n||0).toLocaleString('en-US');}
function stars(t){return '★'.repeat(t||0);}

function heroSlot(h){
  const hue=hueFor(h.heroId);
  const col=`hsl(${hue} 70% 60%)`;
  const skills=(h.skills||[]).map(s=>`<span class="chip">S${s.skillId}·${s.level}</span>`).join('');
  const grade=h.skillGrade!=null?`<span class="chip">g${h.skillGrade}</span>`:'';
  return `<div class="slot">
    <div class="hid"><span class="dot" style="background:${col}"></span>#${h.heroId}</div>
    <div class="row"><span>Lv ${h.level??'—'}</span><span class="stars">${stars(h.tier)}</span></div>
    <div class="skills">${grade}${skills}</div>
  </div>`;
}

function card(p,i){
  const slots=(p.squad.heroes||[]).map(heroSlot).join('') || '<div class="slot">no squad</div>';
  const drone=p.squad.drone?`<div class="drone">🛩️ <span>Air support</span> <b>#${p.squad.drone.heroId}</b> · grade ${p.squad.drone.grade??'—'}</div>`:'';
  const form=p.squad.formation?`<div class="form">Formation preset <b>${p.squad.formation}</b></div>`:'';
  return `<div class="card">
    <div class="top">
      <div>
        <div class="name">${esc(p.name)}</div>
        <div class="ally">${p.allianceAbbr?'['+esc(p.allianceAbbr)+'] ':''}${esc(p.alliance||'—')}</div>
      </div>
      <div class="rank">#${i+1}</div>
    </div>
    <div class="power">⚔ ${fmt(p.power)}</div>
    <div class="metaline">
      <span>HP ${fmt(p.maxHp)}</span>
      <span>${p.rallies.length} rall${p.rallies.length===1?'y':'ies'}</span>
      <span>seen ×${p.seen}</span>
    </div>
    <div class="slots">${slots}</div>
    ${drone}${form}
  </div>`;
}

function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

document.getElementById('cards').innerHTML = DATA.players.map(card).join('');

document.getElementById('rallies').innerHTML = DATA.rallies.map(r=>`
  <tr>
    <td>${r.size}</td>
    <td>${r.leader?'<span class="lead">'+esc(r.leader)+'</span>':'<span style=\\"color:var(--dim)\\">—</span>'}</td>
    <td>${r.members.map(m=>'<span class="mtag'+(m===r.leader?' lead':'')+'">'+esc(m)+'</span>').join('')}</td>
  </tr>`).join('');
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

  <h2>Players &amp; their squads</h2>
  <div class="grid" id="cards"></div>

  <h2>Rallies roster</h2>
  <table class="rtable">
    <thead><tr><th>Size</th><th>Leader</th><th>Members</th></tr></thead>
    <tbody id="rallies"></tbody>
  </table>

  <footer>
    Squad field mapping is structurally inferred (no game .proto) — see
    tools/rally_report.py. Passive capture only.
  </footer>
</div>
<script>const DATA = {payload};</script>
<script>
document.getElementById('tp').textContent = (DATA.totals.totalPower).toLocaleString('en-US');
document.getElementById('mp').textContent = (DATA.totals.topPower).toLocaleString('en-US');
{_JS}
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", default=DEFAULT_IN)
    ap.add_argument("--out", dest="dst", default=DEFAULT_OUT)
    args = ap.parse_args()

    data = consolidate(args.src)
    os.makedirs(os.path.dirname(args.dst) or ".", exist_ok=True)
    with open(args.dst, "w", encoding="utf-8") as fh:
        fh.write(render_html(data, args.src))

    t = data["totals"]
    print(f"wrote {args.dst}")
    print(f"  players={t['players']}  rallies={t['rallies']}  "
          f"combined power={t['totalPower']:,}")


if __name__ == "__main__":
    main()

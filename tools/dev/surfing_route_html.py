#!/usr/bin/env python3
r"""Render the LAST Street Run attempt as an ANIMATED track map — what the autopilot saw.

The bot now writes a per-frame snapshot of its perceived field to
``results/street_run/last_frames.txt`` (one line ``pz|lane|act|x,z,mid,speed …`` per sample,
coins dropped). Because each frame carries the LIVE x of a saw and the LIVE z of a moving
truck, replaying the frames in order animates their motion faithfully with no trajectory
guessing. This builds a single self-contained HTML with a play/scrub timeline: the camera
follows the runner, every hazard is drawn at the extent and type the bot modelled, and the
runner's lane and per-frame decision are shown.

The point is verification: watch it start-to-end beside the memory of the real run and say
where the bot's picture of the track diverges from what was actually on screen.

    C:\Python312\python.exe tools\dev\surfing_route_html.py
    -> results/street_run/last_route.html
"""
from __future__ import annotations

import json
import os
import sys

RESULT_DIR = os.path.join("results", "street_run")
FRAMES = os.path.join(RESULT_DIR, "last_frames.txt")
LOG = os.path.join(RESULT_DIR, "ai_moves.log")
CONFIG = os.path.join(RESULT_DIR, "config")
OUT = os.path.join(RESULT_DIR, "last_route.html")
CAR_UNIT = 8.24


def load_json(name):
    try:
        with open(os.path.join(CONFIG, name), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def classmap(mon, bounds):
    """One record per monster id: how the bot models it — category, length back/front, lane span."""
    out = {}
    for k, v in mon.items():
        mid = int(k)
        a = (v.get("asset") or "").lower()
        nm = (v.get("asset") or "").split("/")[-1].replace(".prefab", "")
        speed = float(v.get("move_speed") or 0)
        if (v.get("collide_damage") or 0) <= 0:
            mt = v.get("monster_type") or 0
            cat = "buff" if mt in (5, 7, 8, 9) else ("pickup" if mt else "coin")
            out[mid] = {"cat": cat, "back": 0.0, "front": 0.0, "lanes": 1}
            continue
        b = bounds.get(nm)
        back, front, lanes = 1.0, 1.0, 1
        if b and "back" in b:
            back, front = b["back"], b.get("front", 1.0)
            lanes = 3 if b.get("sx", 0) > 6 else 1
        cat = "obstacle"
        if "chexiang" in a or "truck" in a:
            if not (b and "back" in b):
                n = 1
                tail = a.rsplit("_", 1)[-1].replace(".prefab", "")
                if tail.isdigit():
                    n = int(tail)
                back, front = CAR_UNIT * n, 0.2
            if speed > 0:
                cat = "mover"   # honest name length (matches the planner; no 41-unit inflation)
            elif "xiepo" in a:
                cat = "ramp"
            else:
                cat = "carriage"
        elif "qiaodong" in a:   # only the arch opening is pass-under; gaojiaqiao is a solid
            cat, back, front, lanes = "bridge", 34.0, -31.5, 3
        elif "dianju" in a or "saw" in a:
            cat, back, front = "saw", 2.0, 2.0
        elif "zhalan" in a:
            cat = "fence"
        out[mid] = {"cat": cat, "back": round(back, 2), "front": round(front, 2), "lanes": lanes}
    return out


def read_frames(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        raw = [ln for ln in fh.read().splitlines() if ln.strip()]
    frames = []
    for ln in raw:
        p = ln.split("|")
        # newest: pz|lane|act|reach|d0,d1,d2|r0,r1,r2|py,busy|obs
        # older : pz|lane|act|reach|d0,d1,d2|r0,r1,r2|obs      oldest: pz|lane|act|obs
        py, busy = 0.0, 0
        if len(p) >= 8:
            pz, lane, act, reach = float(p[0]), int(p[1]), int(p[2]), int(p[3])
            wd = [int(x) for x in p[4].split(",")]
            wr = [int(x) for x in p[5].split(",")]
            pyb = p[6].split(",")
            py, busy = float(pyb[0]), (int(pyb[1]) if len(pyb) > 1 else 0)
            obsraw = p[7]
        elif len(p) >= 7:
            pz, lane, act, reach = float(p[0]), int(p[1]), int(p[2]), int(p[3])
            wd = [int(x) for x in p[4].split(",")]
            wr = [int(x) for x in p[5].split(",")]
            obsraw = p[6]
        else:
            pz, lane, act, reach = float(p[0]), int(p[1]), int(p[2]), 0
            wd, wr, obsraw = [-1, -1, -1], [0, 0, 0], (p[3] if len(p) > 3 else "")
        obs = []
        for tok in obsraw.split():
            f = tok.split(",")
            if len(f) >= 4:
                obs.append([float(f[0]), float(f[1]), int(f[2]), float(f[3])])
        frames.append({"pz": pz, "lane": lane, "act": act, "reach": reach,
                       "wd": wd, "wr": wr, "py": py, "busy": busy, "obs": obs})
    return frames


def read_death():
    if not os.path.exists(LOG):
        return None
    with open(LOG, "r", encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    for ln in reversed(lines):
        if ln.startswith("death "):
            d = {}
            for part in ln[6:].split():
                if "=" in part:
                    k, v = part.split("=", 1)
                    d[k] = v
            return d
    return None


_HTML = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Street Run — анимация маршрута глазами бота</title>
<style>
 body{margin:0;background:#12141a;color:#e6e6e6;font:13px/1.4 system-ui,sans-serif}
 header{padding:8px 14px;background:#1b1e27;border-bottom:1px solid #2a2e3a}
 header b{color:#8ecbff}
 #wrap{display:flex;gap:14px;padding:12px}
 #right{min-width:240px}
 canvas{background:#0c0d12;border:1px solid #2a2e3a;border-radius:6px}
 .ctl{display:flex;align-items:center;gap:10px;margin:8px 0}
 button{background:#2a2e3a;color:#e6e6e6;border:1px solid #3a3f4d;border-radius:5px;padding:5px 12px;cursor:pointer}
 button:hover{background:#333846}
 input[type=range]{flex:1}
 .row{display:flex;align-items:center;gap:8px;margin:3px 0}
 .sw{width:20px;height:13px;border-radius:3px;display:inline-block;border:1px solid #0006}
 .hud{font:12px/1.5 monospace;color:#bcd;background:#0c0d12;border:1px solid #2a2e3a;border-radius:6px;padding:8px;margin-top:10px}
 code{color:#ffd479}
</style></head><body>
<header><b>Анимация маршрута — играет: __WHO__</b> — весь забег от старта до конца.
 Полосы 0 л / 1 центр / 2 п. Камера едет с бегуном (он у низа, обзор вперёд вверх).
 Бегун ЖЁЛТЫЙ = он поднят (на крыше вагона / в прыжке). ⚠ монеты не записываются.
 Прямоугольник — препятствие во всю длину, как её видит модель.</header>
<div id="wrap">
 <canvas id="c" width="470" height="820"></canvas>
 <div id="right">
  <div class="ctl">
   <button id="play">▶ Играть</button>
   <button id="back">⟲ В начало</button>
  </div>
  <div class="ctl"><input type="range" id="seek" min="0" value="0"></div>
  <div class="ctl">Скорость: <button data-s="0.5">0.5×</button><button data-s="1">1×</button><button data-s="2">2×</button><button data-s="4">4×</button></div>
  <div id="hud" class="hud"></div>
  <div id="legend"></div>
 </div>
</div>
<script>
const FR = __FRAMES__, CLS = __CLS__, DEATH = __DEATH__;
const LANES=[32,36,40], NL=120, TX=30, WINDOW=200, BEHIND=30;
const cats={
 carriage:{c:'#e0524a',t:'вагон (стена; только по крыше через рампу)'},
 ramp:{c:'#4caf6a',t:'рампа-вагон (заезд на крышу)'},
 mover:{c:'#d98a2b',t:'движущийся грузовик (едет вперёд)'},
 bridge:{c:'#b060d0',t:'мост-ворота (подкат, все полосы)'},
 saw:{c:'#e0b020',t:'пила (ездит вбок; прыжок/обход)'},
 fence:{c:'#c8c048',t:'забор (низкий; прыжок/подкат)'},
 obstacle:{c:'#8a94a6',t:'препятствие'},
 buff:{c:'#5ab0ff',t:'бафф/рюкзак/союзник'},
 pickup:{c:'#7fd0c0',t:'подбираемое'},
 coin:{c:'#ffd85a',t:'монета'},
};
const cv=document.getElementById('c'),g=cv.getContext('2d'),W=cv.width,H=cv.height;
const seek=document.getElementById('seek'); seek.max=FR.length-1;
let i=0, playing=false, speed=1, acc=0, last=0;
function laneOf(x){let b=0,bd=9;for(let j=0;j<3;j++){const d=Math.abs(x-LANES[j]);if(d<bd){bd=d;b=j;}}return b;}
function draw(){
 const f=FR[i]; if(!f)return;
 const pz=f.pz, z0=pz-BEHIND, z1=pz+WINDOW-BEHIND;
 const sy=z=>H-16-(z-z0)/(z1-z0)*(H-32);
 const lx=l=>TX+l*NL+NL/2;
 g.clearRect(0,0,W,H);
 for(let l=0;l<3;l++){g.fillStyle=l==1?'#14161d':'#101219';g.fillRect(TX+l*NL,8,NL,H-16);}
 g.strokeStyle='#2a2e3a';for(let l=0;l<=3;l++){g.beginPath();g.moveTo(TX+l*NL,8);g.lineTo(TX+l*NL,H-8);g.stroke();}
 g.font='10px monospace';
 for(let z=Math.ceil(z0/10)*10;z<=z1;z+=10){const y=sy(z);g.strokeStyle='#1a1d26';g.beginPath();g.moveTo(TX,y);g.lineTo(TX+3*NL,y);g.stroke();g.fillStyle='#556';g.fillText(z.toFixed(0),2,y+3);}
 for(const o of f.obs){
  const [x,z,mid,sp]=o, k=CLS[mid]||{cat:'obstacle',back:1,front:1,lanes:1}, col=(cats[k.cat]||cats.obstacle).c;
  if(z+ (k.front||0) < z0-5 || z-(k.back||0) > z1+5) continue;
  const l0=k.lanes>=3?0:laneOf(x), l1=k.lanes>=3?2:laneOf(x);
  const yT=sy(z+(k.front||0)), yB=sy(z-(k.back||0));
  const X0=TX+l0*NL+5, X1=TX+(l1+1)*NL-5;
  if(k.cat=='bridge'){ // deck is overhead — pass under; draw faint so it never looks like a wall
   g.save();g.setLineDash([5,4]);g.strokeStyle=col+'aa';g.fillStyle=col+'22';
   g.fillRect(X0,yT,X1-X0,Math.max(4,yB-yT));g.strokeRect(X0,yT,X1-X0,Math.max(4,yB-yT));
   g.setLineDash([]);g.fillStyle=col;g.font='9px monospace';g.fillText('мост ⤵ проезд под',X0+3,(yT+yB)/2);g.restore();
   continue;}
  g.fillStyle=col+'cc';g.fillRect(X0,yT,X1-X0,Math.max(4,yB-yT));
  g.strokeStyle=col;g.strokeRect(X0,yT,X1-X0,Math.max(4,yB-yT));
  if(sp>0){g.fillStyle='#fff';g.font='9px monospace';g.fillText('↑'+sp.toFixed(0),X0+2,yT+9);}
 }
 // WHY: per lane, how far it is clear (red tick = first wall) and how far the DP reaches
 // ENDING in that lane (bar). Together they explain the bot's choice.
 const wr=f.wr||[0,0,0], wd=f.wd||[-1,-1,-1];
 for(let l=0;l<3;l++){
  const cx=lx(l);
  if(wr[l]>0){g.strokeStyle=(l===f.lane)?'#8ecbff':'#3aa060';g.globalAlpha=.55;g.lineWidth=(l===f.lane)?5:3;g.beginPath();g.moveTo(cx,sy(pz));g.lineTo(cx,sy(pz+Math.min(wr[l],WINDOW)));g.stroke();g.globalAlpha=1;g.lineWidth=1;}
  if(wd[l]>=0&&wd[l]<=WINDOW){g.strokeStyle='#ff5555';g.beginPath();g.moveTo(cx-13,sy(pz+wd[l]));g.lineTo(cx+13,sy(pz+wd[l]));g.stroke();}
  g.fillStyle='#9ab';g.font='9px monospace';g.fillText('r'+wr[l]+(wd[l]>=0&&wd[l]<WINDOW?' стена+'+wd[l]:''),cx-18,sy(pz)+13);
 }
 // player — yellow when raised (on a carriage roof / mid-jump): the height the flat map can't show
 const px=lx(f.lane), pscr=sy(pz), up=(f.py>0.5)||f.busy;
 g.fillStyle=up?'#ffcf40':'#8ecbff';g.beginPath();g.moveTo(px,pscr-9);g.lineTo(px-7,pscr+7);g.lineTo(px+7,pscr+7);g.closePath();g.fill();
 const A={0:'держит полосу',1:'← влево',2:'вправо →',3:'⤒ прыжок',4:'⤓ подкат'}[f.act]||f.act;
 if(i===FR.length-1 && DEATH){g.strokeStyle='#ff3b3b';g.lineWidth=3;g.beginPath();g.moveTo(px-10,pscr-10);g.lineTo(px+10,pscr+10);g.moveTo(px+10,pscr-10);g.lineTo(px-10,pscr+10);g.stroke();g.lineWidth=1;}
 // why-verdict
 const best=Math.max(wr[0],wr[1],wr[2]), bl=wr.indexOf(best);
 let why;
 if(best<=8) why=`<span style="color:#f88">ВСЕ полосы упираются в пределах ${best} — модель не видит сквозного пути. По правилу «тупиков нет» здесь ошибка модели (переблок) или нужен тайминг.</span>`;
 else if(bl===f.lane) why=`едет по лучшей полосе (reach ${best})`;
 else why=`<span style="color:#ffd479">лучшая полоса — ${['лев','центр','прав'][bl]} (reach ${best}), а бот в «${['лев','центр','прав'][f.lane]}» (reach ${wr[f.lane]}) → почему не туда?</span>`;
 document.getElementById('hud').innerHTML=
  `кадр <code>${i}/${FR.length-1}</code>  z=<code>${pz.toFixed(0)}м</code>  полоса <code>${f.lane}</code> (${['лев','центр','прав'][f.lane]})<br>`+
  `решение: <code>${A}</code>  reach=<code>${f.reach}</code>  высота=<code>${(f.py||0).toFixed(1)}</code>${up?' <span style="color:#ffcf40">(поднят: крыша/прыжок)</span>':''}<br>`+
  `<b>по полосам reach:</b> лев=<code>${wr[0]}</code> центр=<code>${wr[1]}</code> прав=<code>${wr[2]}</code><br>`+
  `<b>стена впереди (букетов):</b> лев=<code>${wd[0]}</code> центр=<code>${wd[1]}</code> прав=<code>${wd[2]}</code><br>`+
  `<b>почему:</b> ${why}`+
  (i===FR.length-1&&DEATH?`<br><span style="color:#ff8">СМЕРТЬ: полоса ${DEATH.lane}, anim ${DEATH.anim||'?'}</span>`:'');
 seek.value=i;
}
function tick(ts){
 if(playing){const dt=ts-last; acc+=dt*speed; while(acc>50){acc-=50; if(i<FR.length-1)i++; else {playing=false;document.getElementById('play').textContent='▶ Играть';}} draw();}
 last=ts; requestAnimationFrame(tick);
}
document.getElementById('play').onclick=e=>{playing=!playing;e.target.textContent=playing?'❚❚ Пауза':'▶ Играть';if(i>=FR.length-1)i=0;};
document.getElementById('back').onclick=()=>{i=0;draw();};
seek.oninput=e=>{i=+e.target.value;playing=false;document.getElementById('play').textContent='▶ Играть';draw();};
document.querySelectorAll('[data-s]').forEach(b=>b.onclick=()=>{speed=+b.dataset.s;});
let lg='<b>Легенда</b>';for(const k in cats){lg+=`<div class="row"><span class="sw" style="background:${cats[k].c}"></span>${cats[k].t}</div>`;}
lg+='<div class="row"><span class="sw" style="background:#8ecbff"></span>бот (треугольник)</div>';
lg+='<div class="row"><span class="sw" style="background:#3aa060"></span>зелёная линия вверх — докуда бот может уехать по этой полосе (reach)</div>';
lg+='<div class="row"><span class="sw" style="background:#ff5555"></span>красная чёрточка — где в полосе стена</div>';
lg+='<div class="hud" style="margin-top:8px">«Почему»: если у всех полос reach крошечный — бот считает, что сквозного пути нет (по твоему правилу это ошибка модели). Если у какой-то полосы reach большой, а бот не там — это и есть спорное решение.</div>';
document.getElementById('legend').innerHTML=lg;
draw();requestAnimationFrame(tick);
</script></body></html>"""


def main(argv):
    # `human` replays the recorded human run (results/street_run/human_frames.txt); default is
    # the last bot run (last_frames.txt). The two files are drawn identically, so a human run
    # and a bot run can be compared side by side.
    human = bool(argv) and argv[0] == "human"
    src = os.path.join(RESULT_DIR, "human_frames.txt" if human else "last_frames.txt")
    who = "человек" if human else "бот"
    out = os.path.join(RESULT_DIR, "human_route.html" if human else "last_route.html")
    mon = load_json("mon.json")
    bounds = load_json("bounds.json")
    frames = read_frames(src)
    if not frames:
        print("нет %s — сначала запиши забег (%s)"
              % (src, "street_run_ai.py record" if human else "street_run_ai.py run"))
        return
    cls = classmap(mon, bounds)
    used = {o[2] for f in frames for o in f["obs"]}
    cls = {m: cls[m] for m in used if m in cls}
    html = (_HTML
            .replace("__WHO__", who)
            .replace("__FRAMES__", json.dumps(frames, separators=(",", ":")))
            .replace("__CLS__", json.dumps({str(k): v for k, v in cls.items()}, separators=(",", ":")))
            .replace("__DEATH__", json.dumps(read_death() if not human else None)))
    os.makedirs(RESULT_DIR, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("frames=%d ids=%d (%s) -> %s" % (len(frames), len(cls), who, out))


if __name__ == "__main__":
    main(sys.argv[1:])

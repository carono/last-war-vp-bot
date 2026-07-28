#!/usr/bin/env python3
r"""Read the profession's («навыки профессии») active skills — and fire the ready ones.

What they are
-------------
Every account picks a profession — the client calls it a *mastery home*: 101 = Инженер
(Engineer), 102 = Военный лидер (Warlord). Its tree holds a dozen or so **active**
skills, each a banked charge on a long cooldown (23.5 h for most, up to 71.5 h) that
pays out when pressed: hours of base production, a batch of speed-ups, a random
survivor, an instant chunk off the build or research queue. Charges do not stack past
`max`, so one left unspent is that day's payout thrown away.

Everything here is read straight out of the live Lua VM through the warm daemon
(tools/lua_daemon.py) — no capture, no window, no pixels:

    DataCenter.MasteryManager
        :GetData()                          -- home_id (the profession), level
        :GetHomeDict(home_id)               -- the profession's mastery node ids
        :GetCurSkillIdByMasteryId(nodeId)   -- node -> the skill at its current level
        :GetSkillTemplate(skillId)          -- active_skills, cd_time, name, use position
        :GetMasteryGroupSkillState(nodeId)  -- the gate: 1 Normal / 2 Locked / 3 CD /
                                               4 Covered
    data:GetSkillChargeData(skillId)        -- {num, max} banked charges
    data:GetSkillAvailableTime(skillId)     -- epoch-ms the next charge lands

Only skills whose use-position is `SkillView` need no target and can be fired
headless; `Building` / `Field` ones want a world point and are listed but never
pressed here. The full protocol write-up is docs/research/occupation-skills.md.

Usage (run under the Windows Python so it can reach the daemon)

    /mnt/c/Python312/python.exe tools/occupation_skills.py            # list every skill
    /mnt/c/Python312/python.exe tools/occupation_skills.py --json     # same, machine-readable
    /mnt/c/Python312/python.exe tools/occupation_skills.py --use      # fire every ready
                                                                     no-target skill
    /mnt/c/Python312/python.exe tools/occupation_skills.py --use 10113  # fire just that one

`--use` is the same press the `use_profession_skill` button makes, one skill at a
time with a pause between presses: the cooldown is set by the SERVER's reply, so
firing the next one before that lands would double-press the same skill.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import lua_actions  # noqa: E402
import lua_client  # noqa: E402

MARKER = "ACT"
# One server round trip for use.desert.talent.skill ran up to ~8 s in the recording
# (the reply carries the whole reward list), so give a press room to land.
PRESS_SETTLE = 4.0


def _hexdec(h: str) -> str:
    try:
        return bytes.fromhex(h).decode("utf-8", "replace")
    except ValueError:
        return ""


def _num(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def read_skills(ev) -> dict:
    """`{now_ms, home_id, level, skills: [...]}` — every active skill of the profession."""
    out = {"now_ms": 0, "home_id": 0, "level": 0, "skills": []}
    for line in ev.run(lua_actions.occupation_skills_dump(), MARKER, 1.6):
        body = line[4:] if line.startswith("ACT ") else line
        if body.startswith("now "):
            parts = body.split(" ")
            out["now_ms"] = _num(parts[1])
            out["home_id"] = _num(parts[3]) if len(parts) > 3 else 0
            out["level"] = _num(parts[5]) if len(parts) > 5 else 0
        elif body.startswith("S "):
            rec = {}
            for tok in body[2:].split(" "):
                key, sep, value = tok.partition("=")
                if not sep:
                    continue
                rec[key] = value if key in ("pos",) else (
                    _hexdec(value) if key == "name" else _num(value))
            rec["ready"] = rec.get("st") == lua_actions.MASTERY_STATE_NORMAL
            rec["no_target"] = rec.get("pos") == "SkillView"
            rec["state"] = lua_actions.MASTERY_STATE_NAMES.get(rec.get("st", 0), "?")
            out["skills"].append(rec)
    out["skills"].sort(key=lambda s: (not (s["ready"] and s["no_target"]), s.get("sid", 0)))
    return out


def _fmt_wait(avail_ms: int, now_ms: int) -> str:
    if not avail_ms or not now_ms or avail_ms <= now_ms:
        return "now"
    minutes = (avail_ms - now_ms) / 60000.0
    return "%dh%02dm" % (int(minutes // 60), int(minutes % 60))


def print_table(state: dict) -> None:
    home = {101: "Инженер", 102: "Военный лидер"}.get(state["home_id"], "?")
    print("profession %s (home_id %d), mastery level %d"
          % (home, state["home_id"], state["level"]))
    if not state["skills"]:
        # A real state, not a failure: on a young account no node of the tree has a
        # skill learned yet (GetCurSkillIdByMasteryId is nil everywhere), so there is
        # nothing to fire and `xall` is a no-op. Say so rather than print a bare header.
        print("no active skills learned yet — nothing to fire")
        return
    print("%-7s %-10s %-9s %-7s %-9s %s"
          % ("skill", "state", "target", "charges", "next", "name"))
    for s in state["skills"]:
        print("%-7d %-10s %-9s %-7s %-9s %s"
              % (s.get("sid", 0), s["state"],
                 "none" if s["no_target"] else (s.get("pos") or "?").lower(),
                 "%d/%d" % (s.get("num", 0), s.get("max", 0)),
                 _fmt_wait(s.get("avail", 0), state["now_ms"]),
                 s.get("name", "")))
    ready = [s for s in state["skills"] if s["ready"] and s["no_target"]]
    print("\n%d no-target skill(s) ready to fire%s"
          % (len(ready), (": " + ", ".join(str(s["sid"]) for s in ready)) if ready else ""))


def use_ready(ev, skill_id: int | None = None) -> int:
    """Fire the ready no-target skills (or one named id). Returns how many were pressed.

    One press per chunk with a settle between them — never a loop inside the Lua, which
    would spin the game's main thread and freeze the client.
    """
    if skill_id is not None:
        ev.run(lua_actions.apply_occupation_skill(skill_id), MARKER, PRESS_SETTLE)
        after = read_skills(ev)
        hit = next((s for s in after["skills"] if s.get("sid") == skill_id), None)
        fired = bool(hit and not (hit["ready"] and hit["no_target"]))
        print("%s %d — %s" % ("fired" if fired else "not fired (gated)", skill_id,
                              hit["state"] if hit else "unknown"))
        return 1 if fired else 0

    pressed = 0
    while pressed < 10:
        before = read_skills(ev)
        ready = [s for s in before["skills"] if s["ready"] and s["no_target"]]
        if not ready:
            break
        target = ready[0]
        print("firing %d (%s) …" % (target.get("sid", 0), target.get("name", "")))
        ev.run(lua_actions.apply_next_occupation_skill(), MARKER, PRESS_SETTLE)
        pressed += 1
        time.sleep(0.5)
    print("pressed %d skill(s)" % pressed)
    return pressed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--use", nargs="?", const="all", metavar="SKILL_ID",
                    help="fire every ready no-target skill, or just the given id")
    ap.add_argument("--json", action="store_true", help="print the skill table as JSON")
    args = ap.parse_args()

    # Skill names are localised (Cyrillic, plus Roman-numeral tier marks); the Windows
    # console defaults to cp1251 and would die on them.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ev = lua_client.get_evaluator()
    try:
        if args.use:
            return 0 if use_ready(ev, None if args.use == "all" else int(args.use)) >= 0 else 1
        state = read_skills(ev)
        if args.json:
            print(json.dumps(state, ensure_ascii=False, indent=2))
        else:
            print_table(state)
        return 0
    finally:
        close = getattr(ev, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    sys.exit(main())

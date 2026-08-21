#!/usr/bin/env python3
"""Press every golden-zombie button once, in order, against the LIVE panel (#1702).

«Почему постоянная деградация?!» — because each fix was proved by pressing the one
button it touched, while the suite stayed green over the others. This is the answer: one
command that presses all seven through the panel's own web API and prints what each of
them said, so a commit can be refused on evidence rather than on hope.

    python3 tools/golden_round.py                 # against the panel on this machine
    python3 tools/golden_round.py --profile x     # …for another profile

It DOES send one march, and recalls the squad afterwards. Run it before a commit, not on
a timer.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

#: The order a person presses them in, and how long each is given before the log is read.
ROUND = (("rescan_golden", "scan_map", 45),
         ("find_golden", "golden_find_target", 30),
         ("goto_golden", "golden_goto_target", 20),
         ("attack_golden", "golden_attack_target", 25),
         ("state_golden", "golden_squad_report", 20),
         ("recall_golden", "golden_recall_squad", 30),
         ("forget_golden", "golden_forget_target", 15))


def gateway() -> str:
    """The Windows host as seen from WSL — its ports are not on 127.0.0.1 here."""
    out = subprocess.run(["ip", "route", "show", "default"], capture_output=True,
                         text=True).stdout
    return out.split()[2] if out.split() else "127.0.0.1"


def settings() -> dict:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "profiles", "settings.json"), encoding="utf-8") as fh:
        return json.load(fh).get("web") or {}


def call(url: str, body: dict | None, cookie: str = "") -> tuple:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    if cookie:
        req.add_header("Cookie", cookie)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode() or "{}"), resp.headers.get("Set-Cookie", "")


def tail(path: str, seconds: int) -> list:
    """The panel's own lines from the last `seconds`, newest last."""
    stamp = time.strftime("%H:%M", time.localtime(time.time() - seconds))
    with open(path, encoding="utf-8", errors="replace") as fh:
        fh.seek(max(0, os.path.getsize(path) - 400_000))
        fh.readline()
        return [ln.rstrip() for ln in fh if stamp <= ln[11:16]]


def verdict(lines: list, scenario: str) -> str:
    """How THAT scenario ended — not whatever the log happened to say last.

    The first version read the newest interesting line and kept reporting the
    auto-rally's business as the button's (#1702).
    """
    for line in reversed(lines):
        if re.search(rf"< action: (dev/)?{re.escape(scenario)} (OK|HALTED|FAILED)", line):
            return line.split("] ", 1)[-1].strip()[:110]
    return "— it never finished"


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="default")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args(argv)

    web = settings()
    port = args.port or int(web.get("port") or 9761)
    host = f"http://{gateway()}:{port}"
    _, cookie = call(f"{host}/api/login", {"token": web.get("token") or ""})
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log = os.path.join(here, "profiles", args.profile, "panel.log")

    bad = 0
    for action, scenario, wait in ROUND:
        # THE BUTTON WHERE THERE IS ONE, THE SCENARIO WHERE THERE IS NOT (#1702). The
        # round belongs on the TEST profile — that is the account where a wasted march
        # costs nothing — and a test profile usually has «События» switched off, which
        # answered 404 and stopped the round on its first press. The button is still
        # preferred: it is the path a person takes, and it is the one that can be wired
        # to the wrong scenario.
        try:
            answer, _ = call(f"{host}/api/screen/press",
                             {"profile": args.profile, "id": "events", "action": action},
                             cookie)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            answer, _ = call(f"{host}/api/actions/run",
                             {"profile": args.profile, "name": scenario}, cookie)
        time.sleep(wait)
        said = verdict(tail(log, wait + 5), scenario)
        ok = bool(answer.get("ok")) and "FAILED" not in said and "never finished" not in said
        bad += 0 if ok else 1
        print(f"{'ok ' if ok else 'BAD'} {action:<15} {said}")
    print(f"\n{len(ROUND) - bad}/{len(ROUND)} buttons answered")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

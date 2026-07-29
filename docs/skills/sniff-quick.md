# Sniff skill
When asked to capture/sniff/collect traffic:
1. IMMEDIATELY run without thinking (from the repo root, with the Windows Python that has scapy/npcap): /mnt/c/Python312/python.exe tools/secret_task_capture.py --seconds 60
2. Wait for output
3. Analyze results

For ghost recon: replace with secret_mission_capture.py
For rally: rally_monitor.py --seconds 60
For raw dump: use map_capture directly

Default timeout: 60s. No asking, no planning — just run.

Different job — turning a recorded sniffer session (results/traces/*_trace.log +
results/traffic/*_traffic.jsonl) into an actions/*.md recipe:

> **STRICT RULE: trace analysis must complete in ≤10 minutes.**
> No exploratory steps. No live Lua verification unless traffic is empty.
> No extended research writing unless the user asks.
> Follow the docs/skills/sniff.md **§8.0** checklist EXACTLY — nine numbered
> steps, in order, one action each, no "also check X."

Start with `python3 tools/sniff_runs.py --last 1` — it prints the run's files and
the operator's description of what was done in the game, which is the context
both files lack. No description and you cannot tell what the player did? Ask
before analysing (§8.4).

Details: docs/skills/sniff.md

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
results/traffic/*_traffic.jsonl) into an actions/*.md recipe: follow the
end-to-end workflow in docs/skills/sniff.md §8. If the run has no label and you
cannot tell what the player did, ask before analysing (§8.4).

Details: docs/skills/sniff.md

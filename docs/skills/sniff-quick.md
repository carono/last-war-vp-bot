# Sniff skill
When asked to capture/sniff/collect traffic:
1. IMMEDIATELY run without thinking (from the repo root, with the Windows Python that has scapy/npcap): /mnt/c/Python312/python.exe tools/secret_task_capture.py --seconds 60
2. Wait for output
3. Analyze results

For ghost recon: replace with secret_mission_capture.py
For rally: rally_monitor.py --seconds 60
For raw dump: use map_capture directly

Default timeout: 60s. No asking, no planning — just run.

Details: docs/skills/sniff.md

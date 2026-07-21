# Task #973 — user.leave.world inject

**Status:** TIMEOUT — no upstream _id seen (was game on world map?)

**inject rc:** 1

**Connection:** 192.168.1.254:50146 -> 15.197.233.176:17935

**Protocol:** `user.leave.world {worldId:0, serverId:935, _id:N}`

**inject stdout:**
```
[2mgame local port: :50146 (192.168.1.254 → 15.197.233.176:17935)[0m
[2mphase1: 105 socket candidates (tidx=40)[0m
sniffing upstream _id via scapy/npcap (open a menu or scroll the map)…
bg-dup: phase2 + probe-send started in background…
bg-dup: found via getsockname hval=0x1744

[10:50:19] GAME STREAM FOUND — 15.197.233.176:17935
    port 17935 — decoding from here

diag down#1 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#2 cmd=None _id=None
diag down#3 cmd=None _id=None
diag down#4 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#5 cmd=push.world.march.new _id=None
diag down#6 cmd=push.world.march.new _id=None
diag down#7 cmd=None _id=None
diag down#8 cmd=push.world.march.new _id=None
diag down#9 cmd=push.world.march.new _id=None
no upstream _id in 15 s — waiting (scroll map / open menu)…
diag down#10 cmd=None _id=None
diag down#11 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#12 cmd=push.world.march.new _id=None
diag down#13 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#14 cmd=None _id=None
diag down#15 cmd=push.world.march.new _id=None
diag down#16 cmd=push.world.march.new _id=None
diag down#17 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#18 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#19 cmd=push.running.boss.del _id=None
diag down#20 cmd=None _id=None
no upstream _id in 60 s — is the game on the world map?  up_packets=15
```

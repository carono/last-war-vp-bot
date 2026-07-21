# Task #971 — go.to.world inject via ws2.send (dup'd socket)

**Status:** SUCCESS — server_reply received

**inject rc:** 0

**Connection:** 192.168.1.254:51775 -> 34.145.128.94:17935

**inject stdout:**
```
[2mgame local port: :51775 (192.168.1.254 → 34.145.128.94:17935)[0m
[2mphase1: 151 socket candidates (tidx=40)[0m
sniffing upstream _id via scapy/npcap (open a menu or scroll the map)…
bg-dup: phase2 + probe-send started in background…
bg-dup: found via getsockname hval=0x22cc

[12:06:57] GAME STREAM FOUND — 34.145.128.94:17935
    port 17935 — decoding from here

diag down#1 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#2 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#3 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#4 cmd=None _id=None
diag down#5 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#6 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#7 cmd=None _id=None
diag down#8 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#9 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#10 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#11 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#12 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#13 cmd=None _id=None
diag down#14 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#15 cmd=None _id=None
no upstream _id in 15 s — waiting (scroll map / open menu)…
diag down#16 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#17 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#18 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#19 cmd=push.lw.alliance.alert.info.remove _id=None
diag down#20 cmd=push.lw.alliance.alert.info.remove _id=None
upstream _id=174  server_id=935
k1/k2 from wire: 0x2f/0x00
bg-dup handle ready (hval=0x22cc)
injecting _id=176  server_id=935  frame=60B  pre_seq=0xab1b59c3 up_pkts=9
ws2.send: sent 60 B — scapy confirmed (up_next_seq 0xab1b59c3→0xab1b59ff)
waiting up to 30 s for server reply _id=176…

[12:07:25] GAME STREAM FOUND — 3.33.246.23:17935
    port 17935 — decoding from here


[12:07:25] GAME STREAM FOUND — 172.65.210.24:17935
    port 17935 — decoding from here

down  cmd=None  _id=None  success=None
down  cmd=None  _id=None  success=None
down  cmd=None  _id=None  success=None
down  cmd=None  _id=None  success=None
down  cmd=push.vip.worker.detect.accumulate_count  _id=None  success=None
down  cmd=init  _id=None  success=None
down  cmd=push.formation.preset  _id=None  success=None
down  cmd=push.off.season.skip.cd  _id=None  success=None
down  cmd=push.utc.time  _id=None  success=None
down  cmd=push.lw.alliance.alert.info.remove  _id=None  success=None
down  cmd=push.world.march.new  _id=None  success=None
down  cmd=push.refresh.hero.lottery  _id=None  success=None
down  cmd=push.refresh.hero.switch  _id=None  success=None
down  cmd=push.setting  _id=None  success=None
down  cmd=push.science.group  _id=None  success=None
down  cmd=check.device.change  _id=2  success=None
down  cmd=push.al.sign  _id=None  success=None
down  cmd=city.attachment.effect  _id=3  success=None
down  cmd=lw.season.alliance.city.occupy.info  _id=4  success=None
down  cmd=lw.season.city.stronghold.occupy.info  _id=5  success=None
down  cmd=world.get.alliance.building  _id=6  success=None
down  cmd=lw.season.activity.eve.decisive.battle.info  _id=7  success=True
down  cmd=detect.event.get.card.box.list  _id=8  success=None
down  cmd=get.cross.server.king.info  _id=9  success=None
down  cmd=activity.pre.panel.info  _id=10  success=None
down  cmd=get.player.cross.server.list  _id=11  success=None
down  cmd=lw.worldTip.get  _id=12  success=None
down  cmd=rq.world.effect.alter.info  _id=13  success=True
down  cmd=alliance.skill.get.list  _id=14  success=None
down  cmd=lw.season.alliance.reward.progress  _id=15  success=None
down  cmd=lw.season.res.rq.reward  _id=16  success=True
down  cmd=act.boss.get.achievement.info  _id=17  success=None
down  cmd=activity.get.rank.reward  _id=18  success=None
down  cmd=alliance.congratulation.gain.congratulation.list  _id=19  success=None
down  cmd=common.chat.room.id  _id=20  success=None
down  cmd=battle.card.list  _id=21  success=None
down  cmd=battle.card.score.info  _id=22  success=None
down  cmd=world.flag.get.can.effect  _id=23  success=None
down  cmd=battle.field.will.open.time  _id=24  success=None
down  cmd=season.tower.info  _id=25  success=True
down  cmd=berserk.boss.hit.base.gain.info  _id=26  success=None
down  cmd=vip.get.reward.info  _id=27  success=None
down  cmd=news.center.init  _id=28  success=True
down  cmd=login.other  _id=29  success=None
down  cmd=get.bind.mail.reward  _id=30  success=None
down  cmd=hero.event.info.get  _id=31  success=None
down  cmd=al.battle.week.result.info  _id=32  success=None
down  cmd=hero.dispatch.treasure.v2.get.info  _id=33  success=None
down  cmd=push.news.center.init  _id=None  success=None
down  cmd=inquiry.list  _id=34  success=None
down  cmd=act.boss.get.achievement.info  _id=35  success=None
down  cmd=activity.get.rank.reward  _id=36  success=None
down  cmd=lockhart.unlock.level.get  _id=37  success=None
down  cmd=activity.hero.get.info  _id=38  success=None
down  cmd=ghost.recon.get.task.list  _id=39  success=None
down  cmd=ghost.recon.get.alliance.task.list  _id=40  success=None
down  cmd=community.binding.get.info  _id=41  success=None
down  cmd=alliance.boss.act.info  _id=42  success=None
down  cmd=zombie.rush.act.info  _id=43  success=None
down  cmd=zombie.rush.gain.plan.info  _id=44  success=None
down  cmd=hero.event.info.get  _id=45  success=None
down  cmd=get.dig.v2.activity.info  _id=46  success=None
down  cmd=get.parkour.activity.info  _id=48  success=None
down  cmd=exchange.info  _id=49  success=None
down  cmd=get.recharge.info  _id=50  success=None
down  cmd=lw.get.alliance.alert.info  _id=51  success=None
down  cmd=world.favo.get  _id=52  success=None
down  cmd=get.alliance.world.mark.info  _id=53  success=None
down  cmd=country.mark.list  _id=54  success=None
down  cmd=get.detect.info  _id=55  success=None
down  cmd=get.player.level.reward.info  _id=56  success=None
down  cmd=server.trends.info  _id=57  success=True
down  cmd=user.get.questionnaire.list  _id=58  success=None
down  cmd=server.badges.get  _id=59  success=None
down  cmd=get.king.info  _id=60  success=None
down  cmd=get.kingdom.positions  _id=61  success=None
down  cmd=get.kingdom.present.info  _id=62  success=None
down  cmd=get.kingdom.present.info  _id=63  success=None
down  cmd=new.get.info  _id=64  success=None
down  cmd=arena.info  _id=65  success=None
down  cmd=cross.throne.schedule  _id=66  success=True
down  cmd=get.hero.month.card.info  _id=67  success=None
down  cmd=user.get.shop.info  _id=68  success=None
down  cmd=user.get.shop.info  _id=69  success=None
down  cmd=user.get.shop.info  _id=70  success=None
down  cmd=user.get.shop.info  _id=71  success=None
down  cmd=user.get.shop.info  _id=72  success=None
down  cmd=user.get.shop.info  _id=73  success=None
down  cmd=user.get.shop.info  _id=74  success=None
down  cmd=user.get.shop.info  _id=75  success=None
down  cmd=user.get.shop.info  _id=76  success=None
down  cmd=user.get.shop.info  _id=77  success=None
down  cmd=user.get.shop.info  _id=78  success=None
down  cmd=user.get.shop.info  _id=79  success=None
down  cmd=user.get.shop.info  _id=80  success=None
down  cmd=get.week.card.info  _id=81  success=None
down  cmd=get.alliance.auto.invite.info  _id=82  success=None
down  cmd=get.notice.list  _id=83  success=True
down  cmd=hero.dispatch.list  _id=84  success=None
down  cmd=alliance.train.info  _id=85  success=None
down  cmd=world.get.march.infos  _id=86  success=None
[SUCCESS] world-init detected: world.get.march.infos _id=86 << inject_id=176
down  cmd=user.get.server.effect  _id=87  success=True
down  cmd=lw.req.world.occupy.info  _id=88  success=None
server_reply  _id=86  success=True  cmd=world.get.march.infos
```

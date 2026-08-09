# The player's avatar: where the picture is, and where the table is not

Task #1305. What a player wears beside their name is a small number on the wire and a
Unity sprite in the client. Both halves are reachable; the thing that joins them is not.

## The number

The march envelope of an alliance rally carries `headSkinId` beside `ownerUid`,
`ownerName`, `allianceId`, `allianceName` and `allianceAbbr`. It is absent on roughly
half the marches in a capture. `tools/rally_monitor.py` archived none of those five
fields until #1305 — the archive kept the uid, the name, the power and the army, and
dropped the rest, so **nothing captured before #1305 has an avatar or an alliance in it.**

The running client knows anyway, for one alliance:
`DataCenter.AllianceMemberDataManager.allianceMembers` holds a record per member with
`uid`, `name`, `headSkinId`, `power`, `rank`, `online`, `pointId` and about twenty more.
`tools/rally_report.py` asks it (`--no-live` turns that off) to fill in what the old
archives lack.

Observed values over a 100-member roster: `20002`, `20007`, `20008`, `20011`, `20012`,
`20014` (30 members between them), `21016` (1), `25000` (41), `25015` (4), and 25 members
whose record had no value at all.

## The picture

`Assets/Main/Sprites/UI/UIHeadIcon` in the asset index, 54 sprites, plus 3 more under
`Assets/Main/SeasonRes/S6/Sprites/UIHeadIcon`. Extract with the same machinery as the
hero icons:

```
python tools/extract_hero_icons.py --sets head,head_s6 --out results/head_icons
```

57 PNGs, ~640 KiB. They divide into `player_head_1` .. `player_head_25` — the avatars the
picker offers — three `_big` variants of them, and a couple of dozen named ones belonging
to seasons and bosses (`head_icon_Satan`, `ljq_S5_boss_datouxiang`, …).

## The join, which is not available

There is no `headSkinId -> sprite` table to be had:

* **No config table names one.** The live VM's `TableName` has no entry matching `head`,
  `avatar`, `portrait`, `touxiang` or `skin`-for-heads, and `GetTableData` returns
  nothing for sixteen plausible raw names (`head_icon`, `player_head`, `head_skin`,
  `avatar`, …). The datatables themselves are encrypted (`CHAC`), the same wall as the
  hero ids — see [`hero-icons.md`](hero-icons.md).
* **No config FILE names one either.** The asset index has 183 non-sprite paths matching
  `head`, and every one of them is a prefab, a shader or the sprite atlas.
* **The only globals that mention it** are UI window names (`UIPlayerChangeHeadIcon`,
  `UIPlayerHeadIconSelect`, `UIHeadIconShow`), whose modules load with the window.

So `tools/lib/head_icons_map.py` maps **one family, by a numbering hypothesis**:
`20000 + N` → `player_head_N` for N in 1..25. What supports it is that the pickable
sprites are numbered exactly 1..25 and every `20xxx` id observed falls inside that range.
What it is not is a confirmed table, and it is written down as a hypothesis in the module.

`21xxx` and `25xxx` are deliberately **not** mapped. `25000` is worn by 41 of 75 members
who have a value, which is what a default looks like — but knowing it is the default does
not say which of the 57 pictures it is, and guessing would put a stranger's face on a row.
Unmapped ids get a coloured square with the player's initial instead, and the generator
prints how many.

To fix it properly: open the avatar picker in the game, read which picture sits on which
id, and put the pairs in `head_icons_map.CONFIRMED` — a confirmed id always beats the
numbering rule.

## An uploaded photo is a different thing again

The member record also has `pic` and `picVer`: a player who uploaded their own photo
instead of picking an avatar. Two of the hundred had one. Those are not in the bundles at
all — they arrive over chat and land in the on-disk photo cache, which
`tools/chat_assets.py` already resolves (`md5(f"{uid}_{picVer}").jpg`). Not wired into the
report; noted so the next person does not re-derive it.

## A note on the folder

`tools/rally_report.py` copies one PNG per id into `<report>_avatars/` beside the page and
links to it relatively — the pictures travel with the report and nothing is fetched. Six
files, 50 KiB, for a page of 253 players: the same avatar shared by forty people costs one
file.

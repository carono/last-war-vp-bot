# The player's avatar: the cache first, the sprite second

Task #1305. There are two different pictures called «the avatar», and only one of them is
in the game's assets.

## The one that matters: the photo the player uploaded

**It is not in the bundles — it is in the client's photo cache**, because it belongs to
the player, not to the game. The client downloads it the first time it meets them and
keeps it in its download tree (`game_paths.local_images()`), keyed exactly the way the
chat-photo cache is:

    LocalImages/<last 6 digits of uid>/<md5(f"{uid}_{picVer}")>.jpg

On this machine that is 11 623 JPEGs across the uid buckets — i.e. everybody this client
has ever seen, which is precisely the set a report about people it has seen needs.

A uid alone does not name the file: `picVer` counts up every time a player changes their
picture, and nothing on the rally wire carries it. So `tools/lib/player_photos.py` finds
it by trying — hash `uid_0` … `uid_4000` and keep the highest one that is a file in that
uid's bucket. It cannot be fooled (a hash either names a file or it does not), it costs
about two seconds for 253 players, and the highest hit is the newest picture: the older
ones stay in the cache after a change. Observed `picVer` on this cache: 1 to 2 898,
median 53 — which is why the ceiling is 4 000 and why it is a real limit worth stating.

Coverage measured over the rally archives: **181 of 253 players** had a cached photo.
Sizes average 55 KiB, so `tools/rally_report.py` shrinks them to 128 px on the way into
the report's folder — 182 files came to 947 KiB instead of about 10 MB.

## The other one: the built-in avatar, and the table that is missing

The rest of this file is about the fallback — a player who never uploaded a photo wears
one of the game's own, and THAT one is a number on the wire and a sprite in the bundles.
Both halves are reachable; the thing that joins them is not.

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

## Which is why the cache comes first

The alliance roster's `pic` field looked like it meant «has an uploaded photo», and only
two of a hundred members had it set — which is why the photo route looked like a dead end
at first. It is not: 181 of 253 players have a picture in the cache. Whatever `pic` marks,
it is not what to test.

So `tools/rally_report.py` asks in this order — the player's own photo out of the cache,
the built-in sprite for their `headSkinId`, and a coloured initial for whoever neither can
place. In practice the sprite path now covers a handful of people, and would cover more on
a machine whose client has met fewer of them.

## A note on the folder

The pictures travel WITH the report as files: one per picture (`<uid>.jpg` for a cached
photo, `<headSkinId>.png` for a sprite, so forty people wearing the same built-in avatar
cost one file), relative links, nothing fetched. 211 files, 1 076 KiB, for a page of 291
players.

**One folder for the whole machine — `cache/avatars/`** (`game_paths.avatar_cache()`,
#1306). It was `<report>_avatars/` beside the page, which put a directory into
`profiles/` and the panel read it as an account; but the deeper reason it moved is that
a face is not an account's. The same player has the same picture whichever profile
happened to meet them first, so four profiles keeping four copies is four times the disk
for one answer. The operator's words: «Кеш файлы, аватары, можно делать общими для всех,
не обязательно это тянуть в профиль.» What IS a profile's — its log, its schedule, its
daemon, its budgets — stays isolated, and `profile-isolation.md` is that half.

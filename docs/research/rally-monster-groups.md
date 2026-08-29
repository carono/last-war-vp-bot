# What the game's own config says about a kind of banner (#2051)

Why this was read: the rally screen groups the day's caps into cards, and the first
question is what a GROUP is. A hand-written list of species names is what produced the
original complaint — «сезон сменил Роковую Элиту на крокодила» — because every season
renames the elite and the list stays where it was. So the client's own table was read
live instead: `lw_world_monster` through `LocalController.instance():getTable(...)`,
every column of it, on a running client, reading only (`actions/dev/_t2051_monster_cfg.md`).

## The table

97 columns. 12 115 rows. **68 name keys carry `boss = 1`** — the census the panel's kind
list has been generated from since #1317 (`tools/lib/rally_kinds.py`).

Values are reached as `row[index[col][1]]`; `getMetaData()` on any row of the table gives
the column index, which is the table's and not the row's. **`name` is an INDEX into the
string pool, not the locale key** — `getValue(table, id, "name")` resolves it, and doing
that once per group (68 asks) is what joins the census to the panel's own kinds.

## Finding 1 — the elite line is `special == 0`, and nothing else is

| kinds with `special = 0` | name keys |
| --- | --- |
| `doom_elite` | `300602`, `season_monster_name001`, `season_s2_monster_name001`, `season_s3_monster_name007`, `season_s4_monster_lang_name`, `s6_monster_eliteboss_name` |
| `blood_night_doom_elite` | `season_s4_monster_bossname_xueye` |

Every other kind of the 68 carries a non-zero `special`. `type` does NOT answer this —
the elite appears under types 1, 3, 17 and 21 across the seasons, which is exactly the
mistake #1317 corrected (the key had been `type == 8`, the Doom WALKER line).

## Finding 2 — the portrait puts this season's replacement beside it

`pic_name` is the species' own picture. Two kinds share a portrait with a `special = 0`
kind and no others do:

* `giant_crocodile` — `zyf_S6_eyu_datouxiang`, the same portrait as this season's elite
  (`s6_monster_eliteboss_name`). **This is «сезон сменил Элиту на крокодила», in the
  config's own words.**
* `bloodnight_alpha_wolf` — `zyf_S4_lang_datouxiang`, the Blood Night elite's.

So the group «Роковая Элита» is four kinds, and not one of them was chosen by hand.

## Finding 3 — which column names the SPRITE

Both candidates exist and only one is per-species:

* **`worldmap_icon` is the map PIN**, shared: `lyp_daditu_jijieguai` on most of the
  seasonal line, `nil` or `0` on the rest. Useless for telling kinds apart.
* **`pic_name` is the picture.** For the seasonal monsters it is a portrait — the game's
  own word for one is «touxiang» (`zyf_S6_eyu_datouxiang`, `mjc_S3_touxiang_jushachong`)
  — and for the older ones a world prefab (`world_monster_boss_big`,
  `world_monster_Violet`), which is what `docs/research/golden-zombies.md` found for
  config 1030000 and read as «`pic_name` is not an icon». Both are true: the column holds
  whichever the species has.

`tools/data/monster_icons.json` therefore prefers a portrait stem where a kind has both,
and among portraits the NEWEST season's — a kind that has run six seasons draws the face
the player is looking at now. 51 stems for 62 kinds; 49 came out of the bundle cache
(`tools/extract_monster_icons.py`), two are in bundles this machine has never downloaded.

## Finding 4 — the events are not species, and there is no «cannot be rallied» column

`activity` is nil on every `boss = 1` row in this build, so the General's Trial family
(`activity = 107`, per #1317) does not appear in the census at all — those rows are not
`boss = 1`. The two remaining events are matched off their own managers, exactly as the
join already does: `AllyDrillDataManager` for the Alliance Exercise and the invasion's
own lists for the Zombie Invasion. **That is why the «Событийные» group is a named list
and the elite group is not** — there is nothing in the boss census to read them off.

**No column means «a rally cannot be raised on this».** `auto_limit` was the candidate
and it is set on exactly two kinds (`oni_general`, `wandering_oniwagon`), which is not
that question. Anything of the sort has to come off a live banner instead.

## What was NOT read

Nothing was sent, nothing was changed, and the client was not driven: three
`READ_LUA` steps against `LocalController`, all inside the panel's own scenario player.

## Finding 5 — what stands in for «a rally cannot be raised on this» (#2055)

Finding 4 above is still true: no column of `lw_world_monster` SAYS that. What was read
next, on the same table and by the same means (`actions/dev/_t2055_rally_cfg.md`, two
`READ_LUA` steps, nothing sent), is the reward a rally pays the people who JOIN it:

| column | boss name keys carrying it |
| --- | --- |
| `participate_reward` | **47 of 68** |
| `restricted_Reward` | 47, the same split |
| `excess_Reward`, `effect_reward`, `stage` | nil on every row |
| `army2`, `call_time`, `call_rate`, `time_limit`, `recommendType` | one row each — not this question |
| `alliance_boss_gift` | 47 rows, a DIFFERENT 47: set on `cl_7_victim`, nil on `crimson_guard` |

A monster nobody can join a rally on has no participation reward to name, and the split
is exactly the one the player describes as «простые зомби и т.д.»: the nil side is the
zombie horde and the raiders, the roaming season beasts (`mutant_beast`, `crimson_legion`,
`bloodnight_alpha_wolf`), the sandworms, the glacieradons, the summoned mummies, the
airship, the oni general and the oniwagon; the rewarded side is the whole Doom Elite line
across six seasons, the Golden three, every seasonal boss and the zombie boss.

It agrees with what this machine has actually joined — the day's counts hold
`doom_elite`, `shadow_destroyer` and the fallback, all on the rewarded side, and nothing
on the nil side has ever been counted in any profile here.

**The list is `rally_kinds.NO_RALLY_KINDS`, and it hides a kind from what the panel DRAWS
and from nothing else.** The auto-join's own filter is `kinds_off` and its ceiling is the
profile's own number; neither is touched, so a kind named here by mistake costs a row on a
screen and never a banner.

Two kinds it drops are worth saying out loud, because they look wrong until the column is
read: **`desert_boss` — «Золотой вожак»** — is on the nil side and is therefore not one of
the Golden ones a rally goes out on, and **`bloodnight_alpha_wolf`** is too, although
#2051's portrait rule had put it in the elite group. Both keep their caps.

## The groups, as the player named them (#2055)

«Роковая элита» is Finding 1's line, read off `special == 0` and the portrait beside it.
«Событийные» is a list, in the player's own words — «событийные - это золотые боссы,
Инструкторы Авангарда» — with the Alliance Exercise and the Zombie Invasion kept beside
them at their own word, because the two are events as much as the rest and there is
nothing in the boss census to read any of it off (Finding 4). Everything left is «Другие».

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

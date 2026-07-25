# Hero icons: mapping `heroId` → icon file

Rally captures (`results/rally/monitor.jsonl`) describe squads with numeric
`heroId`s only. The extracted icons (`tools/dev/extract_hero_icons.py` →
`results/hero_icons/{big,small}/hero_icon_<Name>.png`) are keyed by the hero's
internal *resName*, not by id. `tools/hero_icons_map.py` bridges the two and is wired
into `tools/dev/rally_report.py` (icon + name shown per confirmed hero).

## Verified mechanics

* **Weapon grade = slot field `f15`.** In the sample its range is `1..30`,
  which matches the exclusive-weapon cap. (`rally_report.py` historically
  labelled `f15` "skillGrade" — it is the weapon grade.) The other slot fields:
  `f1`=heroId, `f2`=troop level, `f3`=tier/stars (all 5 in-sample), `f4`=slot
  position `1..6`, `f8`=20/26 (unconfirmed, not weapon grade), `f17`=awakened
  weapon slots, and on the drone slot (`heroId=1000000`) `f16`=drone payload.
* **`f17` = the awakened weapon's upgrade slots**, not "named skills" as first
  guessed. It is `[{f1: slot 1..4, f2: level}]` and appears **only** once the
  weapon is awakened (`f15 == 30` for all 217 f17-bearing heroes in
  `monitor.jsonl`). Slots unlock in order 1→2→3→4, each with its own level
  (in-sample max levels: slot 1 = 50, slot 2 = 20, slot 3 = 5; slot 4 unseen).
  Rendered per hero in `rally_report.py`.
* **`_zw` = "专武" / *zhuanwu* — the awakened exclusive-weapon skin.** Confirmed
  from the `gameres` index model names `A_Hero@<Name>_zhuanwu_*`. The awakened
  skin is worn at **weapon grade ≥ 30**; below that the base icon is used.
  Only these seven heroes ship a `_zw` icon, so the suffix applies to them only:
  `Audie_Murphy, Carly, Katyusha, Nimitz, Tesla, Tom, dva`.
* Other icon variants exist but are not driven by weapon grade:
  `_ur` (Unique/UR promotion skin — `Alex, David_Stirling, Doctor_Poison3,
  Ewan_McGregor, lambo, sara, MissHot`), `_awaken` (`Katyusha`), `_JP`
  (`Monica`, region skin).

## `heroId`s seen on the wire

18 hero ids plus the drone slot, from `results/rally/monitor.jsonl`:

```
50006 50007 50008 50009 50010
50013 50014 50015 50016 50017 50018 50019 50020 50021 50022
50025 50026 50027
1000000  ← air-support / drone slot (not a hero)
```

Confirmed anchors (eyeballed against the live game):

| heroId | resName / icon stem |
|-------:|---------------------|
| 50006  | `Audie_Murphy`      |
| 50009  | `Katyusha`          |

## Why the rest is not filled in (blocker)

The authoritative `heroId → resName` table lives in the game's config
datatable, which is **encrypted**:

* `LocalLow/FunFly/Last War-Survival Game/table/table_38321_*.data` — magic
  `CHAC`, high-entropy body (server-synced config; the `datatable` bundle in
  StreamingAssets is only a 1 KB placeholder).
* The locale blobs (`locale/<v>/ru.bytes`, `ru.bin`) are encrypted too — no
  plaintext hero names anywhere in `LocalLow`.
* The rally wire protocol never carries a hero display name (grep of all
  captures for hero names → nothing), and no public datamine exposes these
  internal ids.

So `hero_icons_map.CONFIRMED` intentionally holds only eyeball-verified ids; unknown
ids resolve to `None` and the report falls back to the coloured dot + `#id`
(never a wrong face).

## How to complete the table

Pick whichever is cheaper:

1. **Eyeball (matches the project's manual-verify culture, e.g. the star
   check).** Open the game, read the hero on a given id, and add
   `id: "resName"` to `hero_icons_map.CONFIRMED` (resName = the icon stem, i.e. the
   filename without the `hero_icon_` prefix and `.png`). Re-run
   `python3 tools/dev/rally_report.py`.
2. **Decrypt the config datatable.** Recover the `CHAC` key/scheme (likely from
   the il2cpp image — memory R/W on the process is open) and read the
   HeroConfig table's `id → resIcon`. That yields the full table at once, but is
   a real RE task and needs the D: bundle cache mounted.

### Narrowing hints for the eyeball pass

The seven `_zw` heroes must sit among the ids whose weapon grade reaches 30 in
the sample: `50006 50008 50009 50010 50017 50018 50019 50021`. With
`50006=Audie_Murphy` and `50009=Katyusha` fixed, the remaining five `_zw`
heroes (`Carly, Nimitz, Tesla, Tom, dva`) are five of
`{50008, 50010, 50017, 50018, 50019, 50021}` — check those first.

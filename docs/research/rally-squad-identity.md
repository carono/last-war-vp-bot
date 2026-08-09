# What identifies a squad between rallies

Task #1305. Measured over the four rally archives on this machine — 44 817 archived
lines, 13 206 distinct readings, 4 694 moments, 253 players, 544 squads, four days of a
live alliance.
**No value from those archives is reproduced here**; only counts, ratios and shapes.

## The archive

`tools/rally_monitor.py` writes one line per participant of every
`push.alliance.march.create` / `.refresh` it sees, into
`profiles/<profile>/rally_log.jsonl`. Per line: `timestamp`, `teamUuid`, `ownerUid`,
`ownerName`, `power`, `curHp`, `formation`, a parsed `heroes[]`, and the whole decoded
`armyInfo` verbatim in `armyInfoRaw`. `x` / `y` / `targetServer` are present in the
schema and were `null` on every archived line — nothing fills them today.

The panel's «Монитор стягиваний» switch only decides whether the archive is written at
all (`--out` versus `--no-archive`); it changes nothing in the shape.

## The key: `armyInfo.f4`

**`armyInfo.f4` is the squad slot the march was sent from.** Values 1..4, present on
100 % of lines. It is the only stable identity there is, and it holds up under the three
checks that matter:

* **It is not a march counter.** A player who joined 298 rallies has 3 distinct `f4`
  values, not 298.
* **Two slots of one player never share a hero composition.** Across all 544 squads,
  zero pairs of slots belonging to the same player had a composition in common — so the
  slot is not being recycled for unrelated armies.
* **It survives a hero swap, which a composition key does not.** One player's slot 2 was
  archived with two compositions differing in a single hero, before and after a point in
  time; keyed on the composition that is two squads with half a history each, keyed on
  the slot it is one squad with a swap in the middle.

Distribution of squads per player: 1 squad — 100 players, 2 — 40, 3 — 88, 4 — 25. Slots
unlock in order, which matches what `docs/research/hero-icons.md` says about the game's
own squad screen.

### What does NOT identify a squad

* **`formation` (`armyInfo.f2.f13`)** — the formation preset. 253 players averaged
  **1.00** distinct values each (max 2). It is one setting per player, the same on every
  squad they own, so it separates nothing.
* **The march uuid (`armyInfo.f1.f3`)** — allocated per march. Mean 17.26 distinct values
  per player, tracking the rally count exactly. Keying on it turns every rally into a
  brand-new "squad"; that is what the previous report (`tools/dev/rally_report.py`) did.
* **The hero composition** — 2.29 distinct sets per player on average, max 6. Usable as a
  label, not as a key: it splits on a swap (above) and it collapses to one surviving hero
  when a squad marched wiped.

## A rally is one measurement, not one per line

A rally is re-broadcast on every refresh and the archive keeps a line each time, so the
line count is not the sighting count. It can be collapsed without losing anything:
grouped by (player, slot, `teamUuid`), **the `(power, curHp)` pair was identical across
all the lines of a rally in 4 446 of 4 446 groups** — not one rally was archived with two
different readings. Power does not move inside a rally, because the march is fixed when
it is created.

So the unit of the archive is the moment a squad was seen: 13 206 distinct lines fold to
**4 694 moments** across 544 squads. The moment is stamped at the FIRST line of the
rally, not the last refresh.

`teamUuid == "0"` on ~2 % of lines — a create push arriving before the team id exists.
Those have no rally to group by; a ten-minute bucket per squad collapses them (453 such
lines in 120 squads, median 147 s apart, so a run of them is one create being repeated).

## Power is what marched, not what the squad is worth

`power` moves with `curHp`: the same slot was archived at full strength and at roughly
55 % of its soldiers, and the power at the reduced count was roughly 49 % of the full
figure. A squad's series read raw is therefore a saw, and the teeth are casualties, not
the player's progress.

Power per soldier (`power / curHp`) is not flat either — it drifted up by about 0.5 %
over the window on a squad whose soldier count never changed, which is the growth signal
worth reading. And at identical full soldier counts the raw power still varied by a few
per cent between marches, so something outside the archived pair moves it too
(buffs / active technology are the obvious candidates; not established).

`tools/rally_report.py` therefore offers three readings of the same series rather than
picking one: full-strength marches only (soldiers ≥ 95 % of that squad's maximum), every
march, and power per soldier.

## The same rally reaches every watching profile

Four profiles of one alliance held 44 817 lines and 13 206 distinct readings — two of
them overlapped on 11 901 of their ~12 500 each. Any tool reading more than one archive
must deduplicate; `(teamUuid, ownerUid, second, power, curHp)` reduced the four archives
to the 13 206 above with no observed collision between genuinely different readings.

The overlap is also why a report should read **all** profiles: a player's squads are
often in a neighbour's capture and not in your own.

## Odds and ends

* `armyInfo.f2.f2` is a repeated field and collapses to a bare dict when a squad marched
  with one row; iterating it without `_as_list` walks the dict's keys instead.
* Per squad row: `f1` heroId (`1000000` = the drone slot), `f2` level, `f3` tier,
  `f4` marching position, `f15` weapon grade (0..30), `f17` the exclusive-weapon (专武)
  bonus levels that only exist at grade 30. `rally_monitor.py` exposes `f17` under the
  name `skills`, which is what it was called before it was identified.
* Hero ids seen: 36 distinct, of which 10 resolve to a name through
  `tools/lib/hero_icons_map.py`. The rest render as `#<id>` — the id→name table is in the
  game's encrypted config, see `docs/research/hero-icons.md`.
* One uid was archived under two different nicknames — a rename inside the window. The
  report shows the latest and keeps the other as an alias.

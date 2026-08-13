# The player register — what a lap of the map really says about a player (#1335)

Goal: keep a standing list of the players this account has driven past — name, level,
power, coordinates, alliance, a mark of one's own — filled by the ordinary map sweep and
never emptied by one.

Method: no live probing was needed for the reading half. One recorded whole-server lap
at camera height 600 (`results/lv_a600.jsonl`, git-ignored) holds 6 723 player-base
tiles, 183 alliance-city tiles and 23 more, which is enough to answer «what is on a
tile» by counting rather than by guessing. The panel side is `panel/tabs/players/`, the
listener `tools/lib/world_index.py`, and the rule `panel/kept.py`.

---

## 1. What a base tile (`f2 = 6`) carries

Field presence over all 6 723 tiles of that lap, inside the tile's `f3` sub-message:

| field | on | what it is |
|---|---|---|
| `f1` | 100 % | the player's uid (a string) |
| `f14` | 100 % | their name |
| `f4` | 100 % | HQ level, 3…35 |
| `f27` | 100 % | country |
| `f3` | 100 % | the HQ's building id (`10100000` throughout) |
| `f7` | 24.7 % | the alliance's uuid — 32 hex |
| `f15` | 23.7 % | the alliance's TAG |
| `f10`, `f17` | 100 % | two epochs, `f17 = f10 + 7200` on 5 655 of them |
| `f13` | 100 % | a 0…10000 quantity; 9 000 on two thirds of tiles |
| `f18` | 100 % | `uint64 max` («never») on 90.6 %, a past or future epoch otherwise |
| `f23` | 61 % | 1 / 2 / 3 |
| `f26` | 39.6 % | a list of `{f1: config id, f2: n, f3/f5: expiry or int64 max}` |
| `f28`, `f31` | 100 % | float32 bit patterns, ≈0.35 and ≈0.82 |

Plus, on the tile itself rather than in `f3`: the packed coordinate (`f1`), the tile's
uuid (`f100`) and the server (`f102`/`f103`).

**A missing alliance is the normal case**, not a decode failure: three quarters of the
players on a mature server are in none.

## 2. What it does NOT carry, and what does

**No combat number of any kind.** Power, army power, lifetime kills and SVIP level are
only ever in a `get.user.info.multi` reply — the client sends one when a base is OPENED,
and a batched one for the alliance roster at login. Both are the same entry shape and
equally real (`docs/research/protocol.md` §7).

So the register folds them in **when they happen to arrive** and asks for nothing: a lap
sees seven thousand players, and seven thousand lookups is not a sweep. A row that has
never been opened carries `power = null`, which is «never looked up» and deliberately
not zero — the filters treat the two differently, and the table draws «—».

**This is a rule and not a shortcut.** No path on the page may top a row up: not opening
the tab, not a filter, not a sort, not a selected row. The one game read that did exist
asked which server this account is on, so that «свой / чужой сервер» could mean
something — and it was taken out: the server filter picks a NUMBER from the servers the
register already holds. `tests/test_players_registry.py` reads the tab's own source and
fails on the day anything there reaches for `rt.game`.

**No alliance NAME.** Only the tag. The full name is on the alliance's own tiles, which
the same lap drives past:

    f2 = 25   alliance city      f101: f7 uuid, f5 tag, f10 name
    f2 = 35   named facility     f101: f10 uuid, f9 tag, f11 name

joined by the alliance UUID, which is exact where a tag is not. Coverage is partial and
that is the game rather than the decoder: in that lap the base tiles named **107**
distinct alliances, the city and facility tiles **20**, and **11** of those were
alliances that also had a base on the map. Most alliances own no city.

**No note.** The note the client lets you write on another player is stored server-side
and arrives once, at login, as `user.remark.list` (`docs/research/protocol.md` §7). The
command that WRITES one has never been captured, so the register shows it read-only and
keeps the person's own mark as a separate field. Two notes, never one — the panel does
not keep a second version of something the game owns.

## 3. Shield, protection, «in battle» — NOT established

The task asked for the base's state if it is readable. It is not, from this evidence,
and the honest answer is a list of candidates rather than a field:

* **`f18`** — `uint64 max` on 90.6 % of tiles and an epoch on the rest, of which **155**
  were in the future at capture time. A protection expiry would look exactly like this,
  and so would half a dozen other things;
* **`f8` / `f9`** — present together on 10 % of tiles, both epochs, 62 of the `f8` in the
  future;
* **`f23`** — 1 / 2 / 3 on 61 % of tiles;
* **`f11`** — an epoch near the capture time on 2.3 %.

Two candidates were **ruled out**, which is worth as much:

* **`f26` is decorations, not a shield.** Its entries are `{config id, count, two
  expiries}` with ids in the 10 000 / 15 000 / 30 000 / 90 001 families and «never» as
  the commonest expiry — the same shape as the base decorations of
  [`decoration-upgrade.md`](decoration-upgrade.md);
* **`f28` / `f31` are not power.** They are float32 (≈0.35 and ≈0.82) and move
  monotonically with HQ level only because the higher levels sit nearer the middle of
  the map — a rendering scale, not a quantity about the player.

**What would settle it** is one live check rather than more counting: read a base whose
shield state is known (one's own, or an alliancemate's who has just put one up), and see
which of the four fields moves. Until somebody does that, nothing about a shield goes in
the register — a column that is wrong looks exactly like a column that is right.

## 4. Where it is kept, and the rule

The capture keeps a **live view** (`world_map.json`, `players` — evicted after fifteen
minutes, capped at 20 000 because a lap delivers 6 723 tiles in about three seconds) and
the panel keeps the **register** (`players.json`, per profile).

**A row leaves the register for exactly one reason: a person pressed «Забыть».** The
store is a `panel/kept.py` `Kept` that accepts `PERSON_ASKED` and nothing else, so a
removal for any other reason raises where it is written. A lap that drove over nobody, a
capture that was not running, a client that was not logged in and a panel that was
restarted are all the same event — «this read said nothing» — and none of them may take
a name off the list. Everything else the page does is a FILTER: «давно не виден» hides a
row and never removes it.

Two smaller versions of the same rule, both pinned by
`tests/test_players_registry.py`:

* a tile may not erase the numbers only a profile reply carries — an unknown never
  overwrites a known;
* a lap may not write the person's own mark at all. `note` is not in the set of fields a
  sweep is allowed to touch, so no spelling of that player's name tomorrow can reach it.

## 5. What it cost

Nothing per lap. The player rows come off map responses the profile's ONE capture is
already decoding for the secret tasks and the mines — a second npcap reader on the same
interface starves both (measured: `20 delivered / 0 map response(s)` against `5117 map
response(s)` in the same minute, 044c19f), which is why every listener lives inside that
one child. The panel merges the checkpoint on a twenty-second tick, off the Tk thread.

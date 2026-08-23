# The golden-zombie energy burner — a draft kept for a rewrite (#1904)

Two scripts here (`golden_energy_burner.sh`, `golden_hunt_watch.sh`) are the sanitised
remains of six throwaway shell loops that lived in `/tmp` and pressed the panel's web
API from outside. One of them ran unattended for two days, started the hunt 575 times,
and nobody could find it: it is in no timer, in no trigger and in no line of `panel/`,
so the panel's own screens had nothing to show. That is the first thing wrong with the
shape, and the reason this note exists at all.

They are kept because the BEHAVIOUR is worth having. They are not kept as something to
run again.

## What the six were

| original | what it added |
|---|---|
| `hunt_driver.sh` | pressed the «События» tab's own `hunt_golden` through `/api/screen/press`, then waited for the run to end by tailing the log |
| `gz_wait.sh` | just the wait: count the marches that left after a given line of the log |
| `burn.sh` | the loop proper — press `attack_golden_zombies_pair` every 60 s while the game link reads `online`, restart the client after three bad reads |
| `burn2.sh` | counted the marches that really left (a press says «ok» even when a busy squad sends nothing), cut a run that had stopped producing them, and re-walked the map every fifteen laps because the near ground farms out and «the nearest» drifts to ninety tiles |
| `burn_sj.sh` | the same for a second account, and deliberately dropped the stamina-buying: the bag's items are not a script's to spend |
| `sup_sj.sh` | a supervisor that put the loop back within two minutes of being killed |

`golden_energy_burner.sh` is the last two merged (the supervisor behind an explicit
`--supervise`, off by default), `golden_hunt_watch.sh` is the wait.

## What must change before any of it is reused

1. **It is an external loop, and the project has no place for one.** Every gate it holds
   — is a march actually going out, has the run stalled, is it time to re-scan the map,
   is the client up — belongs inside a scenario under `src/lastwar_bot/actions/`, and
   the repeat belongs to a TIMER the person can see and switch off. That is the whole
   fix: an ability plus a schedule entry, not a driver.
2. **It reads a log file to decide what the game did.** The counts it greps for
   (`READ_LUA launched = 1`) are the panel narrating itself. A scenario asks the game.
3. **It calls `/api/interrupt`.** That cuts whatever is running under that profile,
   which need not be its own run — the live one took the client away from a «Прорыв
   обороны» game and stalled the treasure trigger for five minutes (#1901). A stall is
   for the hunt to notice about itself; nothing may cut a stranger's run.
4. **It restarts the client on its own.** A recovery that aggressive is a decision for
   the panel, which knows what else is going on, not for a burner.
5. **The originals carried the panel's web token, its address and the account names in
   plain text.** Here they are asked for (`LW_PANEL_URL`, `LW_PANEL_TOKEN`, and the
   profile as an argument) with no defaults, so nothing about one machine is written
   down — the rule in `CLAUDE.md`.

The one thing worth taking almost as-is is the accounting: an attack counted when a
march is seen leaving rather than when a press returns, and a run judged by whether it
is still producing them. The hunt's own tally already works that way; the burner only
needed it because it was outside.

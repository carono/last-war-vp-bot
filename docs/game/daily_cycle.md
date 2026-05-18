# Daily cycle — canonical session

> Living document. **This is the bot's primary script template.** Most automation is just executing this sequence well, handling errors, and respecting timing.

A "session" is one pass through the routine, lasting 15–30 minutes. A player needs 2–3 sessions per day, spaced so that timed mechanics (resource overflow, alliance donations, secret mission returns, Arms Race windows) are not missed. The bot's job is to make these sessions hands-off.

## The canonical sequence

The order below is the one the user follows manually. The bot should follow the same order by default. Each step is a future Activity in the code.

1. **Open the game, dismiss intro popups.**
2. **Mail** — open, collect all rewards.
3. **Radar** — open, complete daily tasks. Most are collect-rewards / send-squad / call-rally. New seasons sometimes add mini-games here.
4. **Secret missions** — open, send all squads on missions. They return in 2–3 hours; the bot needs to come back for collection.
5. **Base — resource collection** — gather everything pending on the base. **Critical**: production storage overflows; once full, new production stops.
6. **Forbidden-zone building (`Запретная зона`, "tower")** — collect resources and send a squad to training. The UI of this building changes with development stage (different stages — different interface).
7. **Alliance — donations** — open alliance settings, perform all available donations. Donations accumulate 1 unit / 20 min, cap 30; capping = wasted potential.
8. **Alliance — gifts** — collect alliance gifts. Season may add extra buttons here with their own bonuses.
9. **Events (top-right)** — daily events (e.g. "kill a boss with a squad 3 times for a reward"), Arms Race, VS if available.
   - **Arms Race**: fixed schedule of 4-hour windows; each window has a single predetermined objective. The schedule does **not** change throughout the game's lifecycle.
   - **VS** (`дуэль альянсов`, alliance duel): when active, has daily fixed point objectives (different objective set each weekday). Earn points by doing the listed actions (e.g. Monday — radar tasks + hero level-ups + drone level-ups + resource collection; ~7.2 M points unlocks all chests). The action list per day is fixed; new actions may unlock as the player progresses.
10. **Monster rallies** — if **energy** is full enough, spend it on own monster rallies. Also join other players' rallies for rewards. The reward count is capped at 20 gifts per monster-rally type.

## Timing constraints

| Mechanic                | Cadence                            | Penalty for missing                  |
|-------------------------|------------------------------------|--------------------------------------|
| Resource production     | producers fill in hours            | overflow → production halts          |
| Alliance donation       | +1 unit / 20 min, cap 30           | capped donations are wasted          |
| Secret missions         | squads return in 2–3 h             | nothing collected until you return   |
| Arms Race               | 4-h windows on a fixed schedule    | missed-window rewards lost           |
| VS daily objectives     | reset per weekday                  | missed chest tiers                   |
| Monster rally rewards   | per rally-type cap of 20 gifts/day | excess rallies bring no reward       |

## What the bot does **not** do

- The chat is the main social loop of the game — the bot does not automate it.
- Anything that requires a real-time judgement call (e.g. choosing rally targets in a contested zone) stays under user control.

## Seasonal variations

A new season may temporarily change a step (extra buttons in alliance, extra mini-games in radar, additional event types). Baseline steps still apply; seasonal additions are handled as overrides for the duration of the season, then removed.

## Open questions

- Exact ordering preference: is the order above strict, or are some steps interchangeable?
- How does the bot decide when a session is "complete" — when all 10 steps run cleanly, or earlier?
- Should sessions be scheduled (e.g. every 8 h) or triggered (on user demand)?
- For VS — does the bot need to consult the day-of-week and compute the optimal path, or just blindly do all eligible actions?

# Glossary

Canonical Russian terms (as they appear in-game) with English explanations. We keep the Russian originals because OCR and template captures will return Russian; the English explanation is for readers and LLM prompts.

> Living document. Add an entry as soon as a new term appears in design discussion.

---

## Screens & navigation

### Base — **База**
The player's settlement screen. One of the two primary screens. Buildings, resource collection, research.

### World map — **Карта мира** / **Мир**
The other primary screen. Pannable strategic map populated with interactable objects.

### Modal — **Модалка**
A pop-up window opened over the current screen for a specific interaction (heroes, alliance, mail, hire, event detail, …). Most non-trivial interactions are modals. See [screens/modals.md](screens/modals.md).

### Session — _session_
One pass through the daily routine, ~15–30 min. A player needs 2–3 sessions per day.

---

## Time / progression

### Season — **Сезон**
A 2–3 month content block, like a DLC. Adds mini-games, new event types, sometimes extra UI buttons. When a season ends, the game reverts to the baseline.

### Daily cycle — _daily cycle_
The fixed sequence of activities a player runs each session. See [daily_cycle.md](daily_cycle.md).

---

## Resources & production

### Resource — **Ресурс**
Collectible currency/material (multiple kinds). Some collected passively on the base, others via interactions on the world map. Production overflows storage if not collected — once a producer is full, new production halts.
> _TODO: enumerate resource types and where each is obtained._

### Building — **Здание**
A structure on the base screen. Produces resources, hosts research, trains units, or unlocks features.
> _TODO: catalogue of buildings the bot must recognise._

### Build queue / research queue — _build/research queue_
Slots on the base for parallel construction/research. The top-right of the base screen surfaces how many are in use.

### Research — **Исследование**
A long-running upgrade started from a building. Counts against the research queue.
> _TODO: which building hosts research and how the slot/queue works._

### Forbidden zone / tower — **Запретная зона** / **Вышка**
A specific base building. Collects resources and dispatches squads to **training**. Its UI changes by development stage — different stages, different interface.

### Training — **Тренировка**
Long-running unit-development action launched from the forbidden-zone building.

### Drone — **Дрон**
A player-owned unit/feature that can be levelled up. Drone progress is one of the VS-event point sources.

---

## Heroes & survivors

### Hero — **Герой**
A unit/character the player owns. The heroes menu (bottom-left of world) lists owned and locked heroes, with filter tabs.
> _TODO: levels, ranks, skills, gear — to be detailed._

### Survivor — **Выживший**
A hero-like entity with its own hiring slot. Functionally similar to hero hire, differs in ticket type and bonuses.

### Hire — **Найм**
The action of spending **tickets** for a chance at a hero or survivor. Hire-modal has "hire 1" (free every ~2 days) and "hire 10" (paid). Outcome is shown via a card-flip cutscene; the cutscene is cosmetic — the result is fixed at the moment of hire. The slider at the bottom of the hero menu lists hire types: hero, survivor, plus seasonal variants.

### Ticket — **Билет**
Currency for hires. Different hire types use different ticket types.

---

## Alliance

### Alliance — **Альянс**
Player guild/clan. Modal opens from the bottom-right of the world screen.

### Alliance donation — **Пожертвование**
Periodic action contributing to the alliance. Accumulates 1 unit per 20 min, capped at 30. Cap = lost donations.

### Alliance gift — **Подарок альянса**
Free reward inside the alliance modal. May have seasonal variants with additional buttons.

### Alliance help — **Помощь** (альянса)
Other members can speed up your builds / research. The modal section shows what you have in flight and how much help you've received.

### Alliance shop — **Магазин альянса**
Tabs of shops trading in alliance/internal currencies.

### Members — **Участники** (альянса)
Member list inside the alliance modal.

---

## Activities & events

### Radar — **Радар**
A core daily activity. Issues tasks (collect bonus, send squad, summon rally, etc.) that the player completes for rewards.

### Secret mission — **Секретное задание**
World-screen activity launched from the bottom-left. Squad is dispatched, returns in 2–3 h with rewards.

### Monster — **Монстр**
PvE target on the world map. Hunted via the bottom-left "monster hunt" launcher and via rallies.

### Rally — **Ралли**
Coordinated multi-player attack. Used here mainly for monster rallies — own and joined. Reward count per monster-rally type is capped at 20 gifts/day.

### Energy — **Энергия**
A spendable pool consumed by rallies and other actions. Top-right of the world surfaces current energy.

### Event — **Событие**
Time-limited in-game activity. Buttons in the top-right of the world screen; visible set varies per player, per season, and per alliance membership; even individual event buttons can re-skin during a season.

### Daily event — _daily event_
A small everyday event ("kill a boss with a squad 3 times for a reward").

### Arms Race — **Гонка вооружений**
A fixed-schedule event with rolling 4-hour windows; each window has a single predetermined objective. The schedule does **not** change throughout the game's lifecycle.

### VS / Alliance duel — **VS** / **дуэль альянсов**
A daily-objective event when active. Each weekday has a fixed action list (e.g. Monday — radar tasks + hero level-ups + drone level-ups + resource collection). Points unlock tiers of chests (e.g. 7.2 M points unlocks all chests on a given day). New actions may unlock as the player progresses.

### Chest — **Сундук**
A tiered reward container, unlocked by accumulating event points.

### Boss — **Босс**
A scripted PvE target featured in some daily events.

### Busy squad — _squad on a task_
A squad currently dispatched (rally, secret mission, training). The world top-right surfaces how many squads are busy.

---

## UI / interaction

### Mail — **Почта**
Inbox accessible from the bottom-right of the world screen.

### Inventory — **Инвентарь**
Item bag accessible from the bottom-right of the world screen.

### Chat — **Чат**
In-game messaging strip along the bottom of the world screen.
> _TODO: clarify whether the strip is collapsed-by-default and expands on click._

### Profile — **Профиль**
Player avatar / account hub in the top-left corner.

### Attention marker — _red dot_ / **красная точка**
A small red dot drawn in a corner (typically top-right) of a button when there is something new or pending behind that button — unread mail, ready-to-collect rewards, completed builds, available alliance donations, etc. Also appears on tabs inside modals. The bot uses this as its primary "is there work to do?" signal: dot present → enter, dot absent → skip. See [overview.md → Attention markers](overview.md#attention-markers-red-dots).

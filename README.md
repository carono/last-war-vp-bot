# Last War Bot

> На русском: [`README.ru.md`](README.ru.md)

Automation for the PC client of *Last War — Survival Game*. Everything is driven
from a **control panel**: each ability is a named scenario you pick and press, and
the ones you put on the schedule run themselves.

The abilities do not look at the screen. Rather than hunting for a button and
clicking it, they ask the game itself to do the thing — through the game's own
scripting VM and the protocol it speaks to the server. That is why they survive
interface updates, work while the game window sits in the background, and never
mis-click.

> ⚠️ **Before you use any of this.** Automation is **against the rules of the
> game's servers**, and an account caught running it can be blocked or lost.
> This project is published to be read and tinkered with; if you run it, you run
> it **at your own risk** and carry whatever follows. It comes with no warranty
> and no support — see [`LICENSE`](LICENSE).

**What the bot can do today, ability by ability:
[`docs/farming.md`](docs/farming.md)** — на русском
[`docs/farming.ru.md`](docs/farming.ru.md). That list is the honest one: ✅ means
proven in the live game, 🟡 half-way, ❌ still done by hand, and the bar at the top
counts them.

## Installation

Download the archive, unpack it wherever you like, and run **`install.bat`**
from inside the folder that came out of it — that folder is the installation,
and nothing is copied anywhere else. It takes a bare Windows box to a panel on
the Desktop: it brings everything the bot needs, sets the dependencies up and
makes the shortcuts.
What it does, how to run it and what to do when it stops is one page —
[`docs/install/00-installer.md`](docs/install/00-installer.md); the manual route
is [`docs/install/`](docs/install/README.md).

What it needs: Windows 10/11 (64-bit), Python 3.12 and the Last War PC client.
The passive traffic capture behind the secret-task, ghost-recon and rally
monitors additionally wants [npcap](https://npcap.com), which the installer
offers — without it the panel still opens and the scenarios still play, only
those monitors stay silent.

## Running

- **`panel.bat`** opens the control panel. This is what the Desktop shortcut
  points at, and any argument is passed straight through
  (`panel.bat --profile second`).
- **`update.bat`** pulls the latest sources and refreshes the dependencies — the
  second Desktop shortcut. Local work is never thrown away: the pull is
  fast-forward only, and it stops and says so if a commit or an uncommitted
  change is in the way.

From a terminal:

```powershell
python -m panel                              # the control panel
python -m panel --profile second             # …on another account
python -m panel.tabs --list                  # which tabs exist
python -m panel.tabs.rally --profile default # one tab, in a window of its own
```

## Inside the panel

The panel speaks both Russian and English; the tab names below are how the
English interface spells them.

The window opens on **Main**: the account summary — the day's budgets and
everything waiting for you, read in one go — over the buttons that start and
restart the game client, the watchdog that notices when it has died, and a line
that says whether this checkout has fallen behind the repository and offers to
follow. Under it all is the log, where every coordinate the bot prints is a
clickable jump.

Everything else is a tab, and **every tab is a plugin**. Which ones a window shows
is the profile's business: a tab switched off is not built at all, so it starts
none of its captures, watchers or standing orders. Each one also opens on its own
(`python -m panel.tabs.<id> --profile <name>`), which is how one is worked on
without the other thirteen in the way.

| Tab | What it is for |
|---|---|
| Scenarios | the list of abilities, an editor for one, and the button that runs it |
| Timers | the errands on a clock, and the ones the wire sets off — added, edited and deleted from the tab itself |
| Settings | a page of sub-tabs: the interpreter for the child processes, the daemon, game paths, the auto-loot budget, the rally rules and the rest |
| Chat | the game's chat read live and answered from the panel, with emoji, stickers and photos drawn inline |
| Alliance | the roster — name, level, power, who is online and when the rest were last seen |
| Profile | this character at a glance: name, level, power, resources |
| Inventory | what is in the bag, searchable |
| Heroes | the hero roster with icons |
| Accounts | every character this login has, and one button to move the client onto another |
| Statistics | how much of each resource came in, per day |
| Rally | raising a rally, hearing about someone else's, joining it, and the daily budget for both |
| Secret Tasks | the starred raidable tiles, their countdowns, and the standing order that spends the day's robberies |
| Command Post | the raids the in-game secret post offers, the ghost operation among them |
| Develop | the two sniffers, recorded as one session — off by default, for work on the bot itself |

Every setting, every switch and every log belongs to a **profile** — one profile
per account, under `panel/profiles/<name>/`. Which tabs it shows, what its
schedule holds and when each errand last ran are all part of it, so two accounts
are farmed on two schedules and both survive a restart.

## How it is built

- **An ability is one file.** `src/lastwar_bot/actions/*.md` — a small
  declarative language ([`docs/dsl.md`](docs/dsl.md)) that composes presses,
  reads, jumps, waits and calls into other scenarios. One file, one ability.
- **The panel plays scenarios, it is not a bot.** A button runs a scenario by
  name and draws what comes back. No game logic, no gates and no step sequences
  live under `panel/`.
- **The panel is a shell plus plugins.** `panel/__main__.py` is a window, a
  notebook, a log and a menu, and knows what none of the tabs do; each tab lives
  in `panel/tabs/` and speaks only to the runtime in `panel/runtime/` — the
  daemon, the settings, the schedule, the child processes, the reads, the log
  bus. That is what makes a tab switchable off and runnable on its own.
- **The presses go through a warm daemon.** `tools/lua_daemon.py` keeps one hot
  connection into the game's VM, so a button dispatches in about a tenth of a
  second instead of re-resolving everything each time. The panel starts it by
  itself.
- **What is read off the wire is read passively.** The monitors watch the game's
  own traffic; nothing is injected into the connection.
- **Nothing plans a session.** The bot runs the scenarios it is given, on the
  schedule it is given. There is no goal-to-plan layer.

## Documentation

| Where | What |
|---|---|
| [`docs/farming.md`](docs/farming.md) · [`docs/farming.ru.md`](docs/farming.ru.md) | the feature list — what is automated, what is half-way, what is manual |
| [`docs/install/`](docs/install/README.md) | Windows installation, by installer or by hand |
| [`docs/dsl.md`](docs/dsl.md) | the scenario language, keyword by keyword |
| [`docs/actions-authoring.md`](docs/actions-authoring.md) | writing a scenario, and adding a primitive when the language lacks one |
| [`docs/panel-tabs.md`](docs/panel-tabs.md) | writing a panel tab |
| [`docs/architecture.md`](docs/architecture.md) | the original design, and where reality went instead |
| [`docs/game/`](docs/game/) | the game itself: overview, the daily cycle, glossary, per-screen notes |
| [`docs/research/`](docs/research/) | one file per ability — how it was found in the traffic or in the VM |
| [`AGENTS.md`](AGENTS.md) · [`CLAUDE.md`](CLAUDE.md) | orientation and the rules every contributor works by |

## Contributing

Two rules govern everything, and [`CLAUDE.md`](CLAUDE.md) states them in full:
**every ability is a scenario** in `src/lastwar_bot/actions/`, and **every panel
tab is a plugin** in `panel/tabs/`. A new ability is finished when it is one
runnable scenario, the panel only plays it, any new primitive is documented in
[`docs/dsl.md`](docs/dsl.md), and both farming files say what it does.

## License

MIT — [`LICENSE`](LICENSE). Which means, in the words of the licence itself, the
software is provided **"as is", without warranty of any kind**, and the author is
liable for nothing that comes of it.

Spelled out for this particular program: running it breaks the rules of the
game's servers, and the consequences — a blocked account, lost progress, lost
purchases — are yours alone. Nobody here promises the bot works, promises it will
keep working after the next game update, or owes you anything if it does the
wrong thing in your game. Read the code before you run it.

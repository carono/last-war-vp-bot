# Buttons drawn over the client's window (#2768)

A third front-end, and the smallest one: a bar of the panel's buttons that sits on top of
the game's own window, follows it about the desktop and, when a button is pressed, asks
the panel to play a scenario. The trial carries ONE button — «Сбор ресурсов»
(`collect_base_resources`) — because the question this pass had to answer is whether the
window holds and whether the press really plays, not which buttons there should be.

Files: `tools/game_overlay.py` (the bar), `panel/runtime/overlay.py` (the two presses and
the reading), `/api/overlay` + `state.overlay` in `panel/web/api.py`, `OverlayCard` in
`panel/web/app/src/views/StateView.tsx`, `tests/test_panel_overlay.py`.

## 1. What it is allowed to be

A FRONT-END. The bar presses `/api/actions/run` over the panel's ordinary web door with
the ordinary token — the same route the phone uses — and holds no Lua, no game step and
no gate of its own. Nothing in the helper knows what «collect the base» means; the
ability is `src/lastwar_bot/actions/collect_base_resources.md` and always was
(`CLAUDE.md`, «Everything is a scenario — the panel only plays them»).

That is also why the labels are not written in it: the words come from `/api/i18n` (the
panel's own locale table, in the panel's own language) and the name on a button is the
SCENARIO's own title off `/api/actions`, so a recipe renamed in its `# ru:` line is
renamed on the bar with no edit here.

## 2. Why a separate process

Two walls decide the shape, and neither is negotiable.

**The anti-cheat.** ACE kills a client whose process has been written into — a hook, an
injected renderer, a foreign thread started in private memory
(`docs/research/dll-injection-vs-ace.md`, `docs/research/socket-duplication.md`). So the
overlay never goes near the game process: it is an ordinary top-level window of an
ordinary process, positioned over another program's window the way a screen ruler is. The
client is never told it exists, and nothing is drawn INSIDE it.

**The desktop.** Only a process with a window station and a desktop can draw. The panel
that farms the accounts has no window at all (`panel/headless.py`) and Tk is either a
process's main loop or nothing, so the panel cannot grow a window on demand — it starts a
helper instead, in the session it is already standing in. Same wall as #2767's keyboard
hook, same answer.

## 3. Not costing the game its input

The client takes FOREGROUND input only (memory: «Input model»; the panel's own macros
ride on that). An overlay that activated itself every time a thumb landed on it would
break the thing it sits on top of. Two measures:

* the window carries `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`, so a click on a button is
  delivered without the window ever being activated and the game keeps the foreground;
* the bar is small and hugs one edge rather than covering the scene, and `-topmost` is
  re-asserted with `SWP_NOACTIVATE` on every tick so a client brought to the front does
  not paint over it.

It hides itself when the game is minimised, and when the window in front is neither the
game nor the bar — so it is never a lid over another program.

## 4. Whose client, and nothing asked in the background

The game window is found BY TITLE among the visible top-level windows of this session
(`game_paths.window_titles()`). Windows of another Windows session are not enumerable
from here at all, so an overlay started by one profile's panel can only ever attach to
that profile's own client — the isolation rule holding by construction rather than by a
check. A profile whose client lives in another session is refused with a REASON
(`overlay.reason.other_session`) instead of being handed a bar that would draw on the
wrong desktop; starting a window there needs that session's own token
(`tools/session_launch.py`) and SYSTEM to use it, which is a separate piece of work.

The panel is polled ONLY while a press this bar made is still running, and not at all
otherwise (`CLAUDE.md`, «Read once, then LISTEN»). The single clock is the position
follower, which reads the game window's rectangle from the window manager and asks the
game and the panel nothing.

## 5. The result of a press, in the panel's own words

«Идёт» is the bar's own; «готово» and a refusal are the PANEL's. When the run ends, the
bar shows the last log line the run wrote (`/api/log`, tag `action`, the newest line with
`sev` `error`/`warn` winning) — a sentence already in the panel's language, so the reason
a harvest was refused is the scenario's own and the overlay does not invent a second
wording for it. A press the panel would not take comes back as `busy` and says so.

## 6. The token is not on a command line

A command line is readable in every process list and the panel writes every child's
command down in `children-<pid>.json`. So the helper is told the URL and reads the door's
token itself out of the machine's `service.json` — the same file the service reads it
from. The exception is the debugging case where the PANEL holds the port rather than the
service: there the token is passed, because there is no file for the helper to find it
in.

## 7. One bar per profile

The helper is spawned through `rt.children`, which is per profile, written down per
profile and reaped per profile. «Is it up» is therefore «has THIS profile's factory got a
live child with the overlay's tag», never a module-level flag two open accounts would
share — and a panel that is closed or killed takes its bars with it.

## 8. What is deliberately not here yet

* **More buttons.** One is the trial. The set is the next conversation.
* **Another Windows session.** Refused with a reason (§4).
* **Moving the bar with a thumb.** It hugs an edge of the client's window; where it sits
  is `--anchor left|right`.
* **A reading on the bar.** It presses and reports; nothing on it is a number read from
  the game, so there is nothing for it to keep up to date.

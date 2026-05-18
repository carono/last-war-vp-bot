# Action scripts — DSL reference

Skills live as small declarative scripts in `src/lastwar_bot/actions/*.md`.
Each file is one skill; the file name (without `.md`) is the skill name.
The runtime is implemented in `src/lastwar_bot/script_engine.py`.

## A complete example

`go_to_base.md`:

```
# Navigate to the Base screen if we're not already there.

IF screen != base
    CALL click_base_button
    WAIT screen == base WITHIN 10s
```

`click_base_button.md`:

```
# Locate the bottom-right toggle whose icon takes us to Base, then click it.

FIND toggle_to_base.png
    CLICK
```

Reading top-to-bottom: when called, `go_to_base` first asks "is the
current screen NOT base?". If yes, it calls another script
(`click_base_button`) which finds the right button on the screen and
clicks it, then waits up to 10 seconds for the screen to become "base".

## Statements

All keywords are case-insensitive. One statement per line. Blank lines
and lines starting with `#` are comments.

### `IF condition` / `ELSE`

Run the indented block when the condition is true (or false for `ELSE`).
Both branches are optional bodies; the `ELSE` clause is optional.

```
IF screen == world
    CALL collect_world_items
ELSE
    LOG "Not on world, skipping"
```

### `WHILE condition [LIMIT N]`

Repeat the indented body while the condition is true. `LIMIT` caps the
number of iterations as a safety against infinite loops (default 20,
applied silently if no `LIMIT` clause is given). When the condition
becomes false the loop exits cleanly; when the LIMIT is hit while the
condition is still true the runtime logs a "LIMIT N reached" line and
continues with the next statement.

```
WHILE screen == unknown LIMIT 8
    PRESS ESC
    WAIT 0.4
```

### `PRESS <key>`

Send a single key press to the game window (foreground, real input —
DirectInput games ignore message-based key delivery). Supported names:
`ESC`, `ENTER`, `SPACE`, `TAB`, `BACKSPACE`, `DELETE`, `HOME`, `END`,
`PAGEUP`, `PAGEDOWN`, `UP`, `DOWN`, `LEFT`, `RIGHT`, `F1`..`F12`, plus
any single letter or digit (`A`, `Z`, `5`, …).

```
PRESS ESC
PRESS F5
```

### `FIND <template>.png`

Search the current screen for the named template (PNG file under
`src/lastwar_bot/game/templates/`). Indented statements run **only if
the template was found**, and they may use `CLICK` (no argument) to
click the match's centre. After a successful FIND, the match is saved
as the **LAST** result, used by the next `CLICK`.

```
FIND inventory.png
    CLICK
```

If the template doesn't match, the body is skipped (no error). The
script continues with the next sibling statement.

### `CLICK` / `CLICK (x, y)`

Two forms:

- `CLICK` — click the centre of the most recent successful `FIND`.
  Fails the script if there was no prior `FIND` or it didn't match.
- `CLICK (x, y)` — click absolute client coordinates. Useful for UI
  elements that can't be reliably found by template, e.g. the player
  avatar whose art changes per account.

```
CLICK (50, 50)
FIND inventory.png
    CLICK
```

### `READ_TEXT (x, y, w, h) INTO profile.<field>`

OCR the rectangular region `(x, y, w, h)` of the current screen
(coordinates in client pixels) and write the recognised text into the
named profile field. The active profile must be loaded — pass
`--profile <id>` when starting the bot.

```
READ_TEXT (300, 100, 400, 60) INTO profile.name
READ_TEXT (300, 180, 200, 50) INTO profile.level
```

Each assignment writes the field to disk immediately
(`./profiles/<profile_id>.json`). Empty OCR result is stored as an
empty string. Values are stored as text; downstream conditions
compare them as strings (e.g. `profile.level == "50"`).

### `CALL <action_name>`

Execute another script by name (e.g. `CALL click_base_button` runs
`actions/click_base_button.md`). The sub-script's failure propagates —
the calling script also fails.

### `WAIT condition [WITHIN N s]`

Poll the condition repeatedly until it becomes true, or fail after the
timeout (default 10 seconds). Useful right after a click to let an
animation settle.

```
WAIT screen == base WITHIN 15s
```

A special form, `WAIT N` (or `WAIT N s`), is a plain fixed-duration
sleep:

```
WAIT 1.5
```

### `LOG "message"`

Emit the message to the runtime log. Useful for tracing branches.

```
IF screen == unknown
    LOG "Don't know where we are; bailing out"
```

### `STOP ["reason"]`

Signal that the bot should halt entirely. Unwinds all enclosing blocks
and sub-actions. The runner notices the halt flag on the shared context
after the action returns and stops itself. Optional quoted reason is
surfaced in the log.

Typical use is inside a watchdog: if a condition requires immediate
abort, set the reason and stop.

```
FIND kicked_modal.png
    LOG "Another login detected"
    CLOSE_WINDOW
    STOP "kicked by another login"
```

### `CLOSE_WINDOW`

Send a `WM_CLOSE` message to the game window. This is the polite way to
ask the client to shut down (no force-kill). Pair with `STOP` to also
halt the bot.

## Conditions

Allowed in `IF` and `WAIT`:

- `screen == base` / `screen != base`
- `screen == world` / `screen != world`
- `screen == unknown` / `screen != unknown`
- `FOUND` — last `FIND` succeeded
- `NOT FOUND` — last `FIND` returned nothing
- `FIND <name>.png` — ad-hoc SIFT search now; true if visible. **Side
  effect**: on success updates `LAST` so the next `CLICK` lands on the
  match.
  ```
  WAIT FIND profile_modal_marker.png WITHIN 5s
  IF FIND popup_close.png
      CLICK
  ```
- `profile.<field> == "<text>"` / `profile.<field> != "<text>"` — string
  comparison against a field of the active profile. Missing field is
  treated as the empty string.
  ```
  IF profile.server == "972"
      CALL alliance_specific_thing
  ```

(More predicates are added as new primitives appear — extend
`Interpreter.eval_condition`.)

## Watchdog

The runner's tick loop runs a special action called `watchdog.md` (if
present) on every tick *before* the main heartbeat. The watchdog is the
designated place for "react to interrupt conditions" logic — modals
that need acknowledgment, network errors that warrant a shutdown,
account-locked dialogues, etc.

If the watchdog executes a `STOP`, the runner halts immediately and
won't run further ticks. Combine with `CLOSE_WINDOW` to also close the
game cleanly.

To disable, leave `watchdog.md` empty (only comments) or pass
`watchdog_action=None` to `BotRunner`.

## Profiles

Each operator of the bot picks a **profile id** on startup:

```
python -m lastwar_bot.ui --profile alice
```

The profile is loaded from `./profiles/<id>.json` (created on first
write). Scripts read fields via `profile.<field>` conditions and write
fields via `READ_TEXT (...) INTO profile.<field>`. The default profile
id is `default`.

A typical onboarding action — see `actions/capture_profile.md` — opens
the in-game profile modal and OCRs the player's name, level, and
server number into the profile. Other actions can then branch on the
captured values:

```
IF profile.server == "972"
    CALL alliance_972_routine
```

Profiles are persisted to disk on every write. The `profiles/` folder
is gitignored.

## References — what's a template, what's a script?

- A token that ends in `.png` is a **template** file, resolved against
  `src/lastwar_bot/game/templates/`.
- A token used after `CALL` is an **action name** (another `.md` script
  in `src/lastwar_bot/actions/`).

There's no implicit dispatch — you always say `FIND foo.png` or
`CALL foo`. No quotes, no brackets.

## Implicit state

While a script runs, the interpreter keeps a few pieces of state:

- `LAST` — the most recent successful `FIND` result (the match's centre
  point, in client coordinates). Reset to "none" when a `FIND` returns
  no match. Consumed by bare `CLICK`.
- `screen` — recomputed live from the current capture each time a
  condition evaluates `screen ==` or `screen !=`. So your script always
  sees the latest screen state, not a stale cache.
- `profile.<field>` — bound to the active profile loaded from
  `./profiles/<profile_id>.json`. Selected at launch with
  `--profile <id>` (defaults to `default`). Reads via the
  `profile.<field>` condition; writes via `READ_TEXT ... INTO
  profile.<field>`, which persists to disk immediately.

## Failure model

Every action returns OK / FAILED. An action fails when:

- An assert-like primitive raises: `CLICK` with no prior `FIND`, `WAIT`
  that times out, an unknown condition or keyword, a missing template /
  script file.
- A nested `CALL` fails (propagates).

A `FIND` that doesn't match is **not** a failure on its own — it simply
skips its body. Wrap it in an `IF FOUND ... ELSE ...` if you want to
react explicitly.

## Style

- Indent with 4 spaces (the parser accepts any consistent step, but 4
  is the convention).
- One statement per line.
- Keep each script tightly scoped to one concept. Compose larger flows
  with `CALL`.
- Prefer comments for *why*, not *what*.

## How an LLM is supposed to use this

This grammar is the contract the LLM works against:

1. Read the natural-language scenario from the user.
2. Reuse the existing primitives and templates wherever possible.
3. Generate a new `.md` file (or edit an existing one) using only the
   keywords above. Don't invent new ones — propose them in a comment
   if needed, and a maintainer will extend the runtime.

The shorter the grammar stays, the safer LLM-authored scripts are.

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

### `CLICK`

Click the centre of the most recent successful `FIND`. Fails the script
if there was no prior `FIND` or it didn't match.

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

## Conditions

Allowed in `IF` and `WAIT`:

- `screen == base` / `screen != base`
- `screen == world` / `screen != world`
- `screen == unknown` / `screen != unknown`
- `FOUND` — last `FIND` succeeded
- `NOT FOUND` — last `FIND` returned nothing

(More predicates are added as new primitives appear — extend
`Interpreter.eval_condition`.)

## References — what's a template, what's a script?

- A token that ends in `.png` is a **template** file, resolved against
  `src/lastwar_bot/game/templates/`.
- A token used after `CALL` is an **action name** (another `.md` script
  in `src/lastwar_bot/actions/`).

There's no implicit dispatch — you always say `FIND foo.png` or
`CALL foo`. No quotes, no brackets.

## Implicit state

While a script runs, the interpreter keeps two pieces of state:

- `LAST` — the most recent successful `FIND` result (the match's centre
  point, in client coordinates). Reset to "none" when a `FIND` returns
  no match. Consumed by `CLICK`.
- `screen` — recomputed live from the current capture each time a
  condition evaluates `screen ==` or `screen !=`. So your script always
  sees the latest screen state, not a stale cache.

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

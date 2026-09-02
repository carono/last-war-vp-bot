# A settings write leaves a trace (#1957)

## What happened

The panel's watchdog — «поднимать игру при падении» — was working on the live profile
one evening and was off the next morning. The client died at 07:35 and lay dead for
seven hours; nobody put it back. The panel that was running by then had `watchdog =
False`, and there was no way to say how it got there.

Not "hard to say": **impossible**. A profile's settings are stored as a WHOLE SNAPSHOT,
rewritten in full on every save, and nothing anywhere recorded a write:

* no line in `panel.log`,
* no line in `debug.log`,
* no history of the value,
* and not even a usable mtime, because every save rewrites the whole block whether or
  not anything in it moved.

Three hypotheses were tested against the live panel and all three were disproved — a
restart does not lose the setting, the window's checkbox writes through a trace the
moment it is ticked, and no commit of the work going on that night touches the watchdog
or writes settings. The cause is still unnamed, and it will stay unnamed: the evidence
was never written down.

## Why one quiet write is worse than it looks

**The default profile is the base and every other profile stores only its overrides**
(`panel/profile.py`, #1246). Three of the four profiles on that machine had no
`watchdog` key of their own at all, so all three were obeying the default profile's
value. One untick, wherever it happened, turned the watchdog off on four accounts at
once — and the same is true the other way: turning it back on in the default profile
turned it on for all four.

Nothing on either front-end says which knobs are a profile's own and which are the
default's, so the reach of a tick is invisible at the moment somebody makes it.

## What was done

### 1. Every save says what it moved

`ProfileManager.save` now diffs what the profile OBEYED before against what it obeys
now and writes one line per moved key into that profile's own `debug.log`:

```
[settings] watchdog: true -> false (own, from web)
[settings] tabs.config.rally.squads: [1] -> [1,3] (inherited, from panel)
[settings] watchdog: true -> gone, back to the default (own, from panel)
```

Four facts on the line, and each of them is one that had to be reconstructed by hand:

* **the key**, as a dotted path — a nested block is `tabs.config.<id>.<knob>`;
* **old → new**, so «кто это выключил» is a `grep` rather than an afternoon;
* **own or inherited** — whether this profile has a value of its own for that key, or
  is following the default profile's (the paragraph above is why it matters);
* **where the write came from** — `panel`, `web`, `timers`, `provision`, `new profile`.

The source travels on a context variable (`panel.profile.writing`), which a hop onto
another thread does not carry, so the web's door re-enters it on the far side of that
hop (`panel/web/api.py::_on_tk`). It is best effort by design: a write nobody labelled
reads `panel`, which says truthfully that it came from the panel itself and not through
any door this module knows the name of.

The diff is taken against what the profile obeys, so a save that changes nothing says
nothing — the panel saves on every traced write, and a line per save would be noise
rather than a record. A save that moves more than forty keys (seeding a new profile,
an import) prints the first forty and a count.

### 2. A knob with no widget keeps its last known value

`_collect_settings` in `panel/__main__.py` wrote a key only when its Tk variable
existed:

```python
var = self._opt_vars.get(key)
if var is not None:
    out[key] = var.get()
```

Since the snapshot is stored WHOLE, a key left out is a key DELETED, and the next load
answers with the code's own default — `False` for a switch. Widgets are not always
there: a save can happen during the boot before anything is drawn, the Settings page is
`LAZY` and makes its variables when somebody first looks at it (#1215), and a headless
panel has no widgets at all. Any of those saves silently wiped every knob it could not
see.

It now falls back to what the profile already had, so a value is only ever dropped by
somebody actually changing it — and if one is dropped anyway, the audit line above says
so at WARNING.

### 3. Making inheritance visible — the data door, and the open question

`ProfileManager.owns(key, name)` answers whether a profile's value for a knob is its
own or the default profile's. The audit line already uses it.

**Whether a front-end should SAY it beside the knob is the person's call, not an
agent's**, and it is written here rather than decided in passing. The case for it: a
tick in the default profile's Settings page reaches every profile that never overrode
that knob, and nothing on screen warns anybody of that before they press. The case
against: it is a word beside almost every knob on the page, most profiles are almost
entirely inherited, and a page that says «inherited» thirty times says nothing.

The shape it would take if it is wanted: `web_view`'s fields already carry a `hint`, so
an `inherited` flag on the field and one line in `panel/web/app/src/ui/FieldRow.tsx`
would draw it, plus one locale key in all eleven locales.

## Where the code is

| What | Where |
|---|---|
| the diff, the line, the label | `panel/profile.py` — `_audit`, `_flat`, `writing`, `save` |
| the source label crossing a thread | `panel/web/api.py::_on_tk` |
| the snapshot keeping what it cannot see | `panel/__main__.py::_collect_settings` |
| own vs inherited | `panel/profile.py::ProfileManager.owns` |
| pinned by | `tests/test_panel_settings_audit.py` |

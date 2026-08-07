# Releases, and how the panel updates itself

The bot IS the git checkout it runs from — there is no installer and no package. So
«обновить бота» means moving that checkout forward, and this file says what it moves
*to*, who decides, and how a release gets cut.

Read it before you tag anything, and before you change anything under
`panel/runtime/updates.py`.

---

## 1. The version scheme

**`vMAJOR.MINOR.PATCH`**, as an **annotated** git tag on `master`. Nothing else counts:
the panel matches `v[0-9]*` (`updates.TAG_GLOB`), so `backup/…`, `wip-…` and any other
branch-shaped tag is invisible to it and always will be.

| part | goes up when |
|---|---|
| **MAJOR** | the panel stops working the way it did — a profile has to be re-made, a setting is gone, an ability behaves differently enough that somebody's routine breaks |
| **MINOR** | an ability is added, or an existing one grows something a person can see: a new tab, a new button, a new reading, a new scenario |
| **PATCH** | a fix, a translation, a doc, a refactor — anything that leaves the panel doing what it already did, only correctly |

Annotated (`git tag -a`), never lightweight. `git describe` prefers annotated tags, and
the version line on «Главная» is drawn from `git describe`; a lightweight tag would work
until the day somebody put an annotated one nearby and then quietly stop.

There is no separate release branch, no `-rc`, no `-beta`. What is not tagged is the dev
state, and following it is one tick (§4).

## 2. What the panel does with it

`panel/runtime/updates.py` answers two questions, and both are about tags now.

**Which version is this?** `git describe --tags --long --match 'v[0-9]*'`, turned into a
string by `version_text()`:

| the checkout | the version says |
|---|---|
| exactly on `v1.4.0` | `v1.4.0` |
| seven commits past it | `v1.4.0+7-dev` |
| no release tag reachable | `1.0.0-dev` — the packaged `panel.__version__` plus the mark |
| no git at all (an unpacked zip) | `1.0.0` — the packaged number, plain |

`-dev` is the mark the version line carries when the code is BETWEEN releases: nothing
published contains exactly what is on disk. It is part of the identifier, like the `+7`
beside it, so it is not translated — it reads the same in the window, on the phone, in
`debug.log` and in a bug report.

**Is there a newer one?** The newest tag that `origin/<branch>` contains
(`git tag --list 'v[0-9]*' --merged origin/master --sort=-v:refname`), compared against
HEAD. A pull is `git merge --ff-only <that tag>` — so it lands exactly on the release and
leaves whatever has been pushed since it was cut alone. The branch stays attached: a
fast-forward onto a tag moves the branch, it does not detach HEAD.

Two conclusions exist only because of releases:

* **`dev_ahead`** — past the newest release and behind nothing. The ordinary state of a
  checkout that has taken a dev update, and of the machine the releases are cut on.
  Nothing is offered and nothing is wrong; the version line says `+N-dev`.
* **`no_release`** — the branch carries no release tag at all. Not «актуально»: the panel
  genuinely cannot say whether there is anything newer, and the way out is the tick.

## 3. Cutting a release

On `master`, with the work in it already proven in the live game and written up in
`docs/farming.md` / `docs/farming.ru.md` (that confirmation is what makes it releasable —
`CLAUDE.md`, «Feature list upkeep»):

```
# 1. the packaged fallback names the release it is about to become
#    panel/__init__.py:  __version__ = "1.4.0"
git commit -am 'release: 1.4.0'

# 2. the tag, annotated, with a one-line summary of what is in it
git tag -a v1.4.0 -m 'v1.4.0 — hospital healing, alliance gifts, 11 locales'

# 3. both, or nobody sees it: a tag is not pushed by `git push`
git push origin master
git push origin v1.4.0
```

Step 3 is the one that gets forgotten, and forgetting it is silent — every installed
panel keeps saying «актуальная версия» against yesterday's tag while the work sits on
`origin`. `git push --follow-tags` does both in one go if you prefer.

Nothing else is a release. No zip, no branch, no announcement the panel reads.

**Between releases, `__version__` is left alone.** It is a fallback for a checkout with
no git, and bumping it mid-cycle would have such a checkout claim a release that does not
exist yet.

## 4. «Обновлять до dev-версии»

A tick on the **«Разработка»** tab. Off by default, and off is the release channel.

* **off** — the panel only moves to published releases. A push made ten minutes ago is
  not an update, and is not offered as one.
* **on** — the panel moves to the tip of the upstream branch, unreleased work included.
  That is what this module did for every checkout before releases existed.

**It is panel-wide, not per profile** (`panel/profile.py::dev_updates`, the key
`dev_updates` in `panel/settings.json`). There is one checkout and every open profile
runs out of it; two profiles disagreeing about which channel it follows would be two
answers to a question with one subject.

**Why it is on «Разработка» and not a switch of its own.** Wanting the unreleased state
IS working on the bot, and having that tab switched on already says so — it is the same
thing `panel/tabs/__init__.py::DEV_TAB` calls **development mode** (#1273, the flag that
hides half-finished tabs). One switch, one meaning. A second checkbox would be a second
answer to the same question, and the first time the two disagreed there would be nothing
to settle it with.

Ticking it re-asks straight away: the tab publishes `update.channel` on the bus and the
block on «Главная» runs a fresh check, so the answer changes under the cursor rather than
at the next six-hourly poll.

**The phone has the reading, not the tick.** «Разработка» declares `WEB_SCREEN = False`
and always has (`CLAUDE.md`, «The three divergences there are») — this is that standing
exception, not a new one. What the phone DOES get is the consequence: the version on
«Состояние» is the same string the window draws, `+N-dev` mark included, so a checkout
following the branch says so wherever it is read.

## 5. What a person sees

| where | what |
|---|---|
| «Главная» → «Обновление» | `Версия v1.4.0 · master @ a1b2c3d`, the status line, «Проверить», «⭳ Обновить» when there is a release to take, «⟳ Перезапустить панель» always (#1258) |
| «Справка → О программе» | the same version string |
| the phone, «Состояние» | the same version string, and the restart press |
| `debug.log`, first line | `panel starting — profile 'default', version v1.4.0+3-dev (channel release)` |

All four come out of one cached reading (`updates.version_text`, 60 s), so they cannot
disagree with each other inside a poll.

## 6. If you are changing this

* **The channel is never remembered inside `updates.py`.** Both `check()` and `pull()`
  take it as an argument, so a tick can change the answer with no state to invalidate.
  The stored preference lives in `panel/profile.py` and nowhere else.
* **`rev-parse` on a release needs `^{commit}`.** An annotated tag's own hash is a number
  that appears nowhere in the history; everything else (`rev-list`, `merge`) peels by
  itself and `rev-parse` does not.
* **Tags are only fetched on the release channel.** `_fetch(..., tags=True)` — including
  the `+refs/tags/*` refspec on the anonymous-HTTPS retry, which a checkout with an SSH
  `origin` and no key depends on.
* `tests/test_panel_updates.py` runs all of it against real git in a temp directory —
  a bare origin, a working clone and a second clone playing the other developer. No
  network. Add to it before you change the behaviour, not after.

# «Вход с другого устройства» — the session kick, and where its flag is

> На русском: этот файл — исследовательская записка, как и все в `docs/research/`.
> Список возможностей для игрока — `docs/farming.md`.

**Read this before going into the client after a kick flag. It has been looked for
twice.** The second search (#1259) rediscovered a phrase already written down in
[`street-run-parkour.md`](street-run-parkour.md) in July and walked into a dead end
already documented in [`protocol.md`](protocol.md). Both cost about an hour each, and
both were avoidable by reading. That is the whole reason this file exists as its own
file rather than a paragraph inside another one.

## 1. What it is

The game is **single-session**. Logging the account in anywhere else kicks this client:
the server closes the connection and the client puts a modal on screen —

> **«В ваш аккаунт был выполнен вход с другого устройства»**

Observed twice, months apart:

* **2026-07-29** (street-run work): the client **froze mid-run**, the modal came up, and
  the client **closed when it was confirmed**. So the window is modal, it blocks, and
  confirming it ends the process — which matters for how long anything has to catch it.
* **2026-08-06** (#1259): the player logged in, was thrown out «a couple of minutes
  later», logged in again and stayed. Part of that was this panel's own restart — see
  [`server-link-status.md`](server-link-status.md) §4.4 — and the kick itself was seen
  by the player on screen.

## 2. The key, and how it was found

**`E100083`** in the game's own locale tables:

| lang | text |
|---|---|
| ru | В ваш аккаунт был выполнен вход с другого устройства |

Found by going **from the text**, which is the technique to reuse:

```bash
# the tables live in the install, not in the repo — point the tool at them
LW_LOCALE_DIR="<install>/Game/LastWar_Data/StreamingAssets/locale/<build>" \
    python3 tools/game_locale.py --term "…"
```

`tools/game_locale.py` without that variable says «no game found» and stops; the build
number under `locale/` changes with the client, so glob it rather than writing it down.
The RU table holds ~52 800 keys, and a plain substring scan over its values is what
turned the phrase into a key in one pass — `--term` matches the panel's glossary terms
and did NOT find this one.

Keys of the shape `E1000xx` are **server error codes**: the server sends the code and
the client renders whatever the table says. That is why the next step found nothing.

## 3. Where the flag is NOT (both dead ends, both already documented)

* **`login.other` is not the kick.** It is `MsgDefines.LoginOther` = `login.other`, and
  its handler (`LoginOtherMessage.HandleMessage`) updates alliance data —
  `UpdateAllianceBaseData`, `AllianceNoticeManager`, `payDollerTotal`.
  [`protocol.md`](protocol.md) already records it in the login trace as
  «`login.other {alliance}` → full alliance record». It is «another player's login
  info», not «logged in elsewhere».
* **Nothing in the client's Lua mentions it at all.** A scan of **48 534 functions**
  across every loaded module — `string.dump` on each, substring search — found zero
  references to `E100083`, `UIDisconnect` or `UICrossDisconnect`. The disconnect flow
  belongs to the **C# connection layer**, so there is no data manager holding a
  «kicked» field and nothing to poll the way an event's state is polled.

## 4. Where the flag IS

The WINDOW, because `UIManager` holds it whoever opened it:

```lua
UIManager.Instance:IsWindowOpen('UIDisconnect')
UIManager.Instance:IsWindowOpen('UICrossDisconnect')
```

That is `tools/lib/lua_actions.py::kicked_out()`. `UIChatKickUser` is chat moderation
and NOT this. The panel asks it only while the link is already `lost` — it is a round
trip into the VM and a healthy client always answers the same — and it fails CLOSED, so
anything unreadable is «no kick» and it can only ever ADD a reason.

**Not yet watched, and not to be assumed:** which of the two windows a real kick raises,
and whether it survives long enough for an eight-second poll to see it. The July
observation says the modal blocks until confirmed, which suggests it does — but nobody
has held a stopwatch to it. **The next live kick answers both, and the moment to look is
BEFORE anything restarts the client.**

## 5. The wrong conclusion this produced, and why it was convincing

#1259 read a client that had lost its link and found no modal, an empty window stack,
the whole HUD up and the city on screen, and wrote up:

> «A kick and an ordinary hang-up are indistinguishable not only by their sockets but by
> the client too.»

That is false, and the player disproved it in one sentence: they had **seen the message
with their own eyes**. The reading was taken at a moment chosen by nobody — after the
panel had already restarted the client — so it was evidence about that moment and
nothing else.

**One observation of an ABSENCE is not a property of the system.** The rule this
repository already had — ask what the player sees, `[[feedback_ask_what_the_player_sees]]`
— applies to negative findings first of all, because a negative finding closes a line of
enquiry and nobody reopens it.

## 6. What the panel does with it

A kick and a silent hang-up are the same ACT (restart) and a different EVENT, so they
get different sentences — «выкинуло: вход с другого устройства» against «связь
пропала» — and separate counters, in both front-ends. Both go through the same gate: a
restart is withheld while somebody has touched the machine in the last five minutes,
because being kicked is not a licence to close a window a person is playing in
(`panel/runtime/recovery.py`).

**The unresolved one, and it is a decision rather than a finding:** a kick means the
account is in use somewhere else. Restarting takes it back off whoever has it — and if
that is the owner, on their phone, the panel is fighting its own player. Nothing local
can see a phone. Left to the person deliberately.

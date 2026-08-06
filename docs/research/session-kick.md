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

## 4. Where the flag IS — caught live, 2026-08-06

The player kicked this client on purpose while a watcher polled it **twice a second**.
The whole recording:

```
22:43:15   link=online  dead=0   no window          city     <- baseline
22:45:08   link=lost    dead=6   no window*         city     <- the kick
                                                             (*by the stack; see below)
22:48:53   the panel, restarted, calls it: «связь с сервером пропала»
22:49:02                                  «выкинуло: вход с другого устройства»
22:52+     window STILL open, 7+ minutes later
```

**The sockets and the modal are simultaneous** — one poll apart at 0.5 s resolution.
Six half-closed, zero established, and the client sitting in the city with its HUD up.

### The window is `UICommonMessageTip` — not either of the guesses

`UIDisconnect` and `UICrossDisconnect` both stayed SHUT through the whole kick. What
opened was the client's generic message dialog, and its `View.tipText` carries the
message word for word:

```
Внимание
В ваш аккаунт был выполнен вход с другого устройства
```

Buttons `text1=110006`, `text2=110106`. Read it with
`UIManager.Instance:GetWindow('UICommonMessageTip').View.tipText`.

### Why it looked like «no window at all»

**`UICommonMessageTip` sets `DontPushWindowStack`.** So `GetStackTopWindow()` answers
`nil` and `WindowStack` is empty **with the modal plainly on screen**. That is what the
earlier reading did — it asked the stack, saw nothing, and concluded the kick leaves no
trace. Wrong accessor as well as wrong moment.

**`IsWindowOpen` is the only accessor that sees it**, and it has to be asked BY NAME:
sweeping all 2 221 names in `UIWindowNames` is what found it
(`TouchScreenEffect, UICommonMessageTip, UIMain, UINpcTalkLayer` were the four open).

### How long it holds, and whether a poll catches it

**Over seven minutes and still up when this was written**, unattended. The July
observation said the modal blocks until confirmed, and this agrees: it does not
self-dismiss. **The panel's ordinary eight-second poll catches it with room to spare** —
no fast polling is needed in production, and #1259's design (ask only while the link is
already `lost`) is comfortably enough.

### Is it distinguishable from an ordinary hang-up? Yes

| | stranded (server hung up) | kicked (logged in elsewhere) |
|---|---|---|
| sockets | half-closed, none established | the same |
| `UICommonMessageTip` | **not open** (watched live, twice) | **open, with text** |
| stack / `GetStackTopWindow` | empty / nil | empty / nil — no help |

The sockets alone cannot tell them apart; the window can. `UICommonMessageTip` is a
GENERIC dialog and proves nothing on its own — the client uses it for anything — so the
pair is what makes it conclusive: **a lost link AND a message tip carrying text**. That
is `lua_actions.kicked_out()`, and it is asked only while the link is already lost.

Proven end to end by accident of timing: the panel was brought back up while the client
was still kicked, and its very first poll said «выкинуло: вход с другого устройства»
rather than «связь пропала».

### What this does NOT fix

A kick means the account is being played somewhere else, so restarting cannot win it
back for long — it was watched failing at exactly that: restart, kicked again, «жду
10 мин». Whether the automation should stand down entirely on a kick instead of
restarting is a decision for the person, and it is the same open question as §6.

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

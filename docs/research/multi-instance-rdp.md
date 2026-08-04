# Multi-instance: a second client in its own Windows session, driven over TCP

Task #1106, the sequel to [#1105](multi-instance-second-user.md). That task proved a
second client **cannot** run as another user *inside this session* — ACE kills it after
~9 s with `0xDEADC0DE`, through every launch route tried. Its closing advice was "one
Windows session per client", with the caveat that a client on another desktop is out of
reach of this bot's foreground input.

**Verdict: it works, and the caveat matters less than it sounds.** A second client runs
in a second Windows session, that session is left *disconnected* (nobody looking at it,
the console stays with the first client), and everything headless drives it from here
over TCP. Measured today: the second client stayed up for the whole session against the
9-second ACE wall, and an unmodified `tools/dispatch_tasks.py` read 181 live dispatch
tasks out of the second account while the first one reported its own 209.

```
session 1 (<user1>, console)            session 4 (<user2>, disconnected)
├─ LastWar.exe  ── lua_daemon :47654  ├─ LastWar.exe  ── lua_daemon :47655
└─ tools/…  ─────────────────────── TCP ──────────────┘
```

Tools: [`tools/rdp_instance.py`](../../tools/rdp_instance.py) (the orchestrator) and
[`tools/session_launch.py`](../../tools/session_launch.py) (start a process inside an
existing session).

## 1. Why ACE does not object this time

#1105 narrowed the wall to one surviving explanation: *ACE requires the client's token
to be the interactive logon of the Windows session it runs in.* This route satisfies
that literally instead of working around it. The client is started with the token that
**already is** that session's logon — `WTSQueryUserToken(session)` — so the process user
and the session owner are the same account, exactly as if someone had double-clicked the
icon while sitting in that session. That the session happens to be disconnected changes
nothing: the token, the profile, the window station and the desktop are all the
session's own.

A side benefit: `WTSQueryUserToken` needs no password. Nothing about this route stores
or passes the second account's password — the only place it is still needed is the
initial RDP logon, and that comes out of Credential Manager (§4).

## 2. The four steps

| # | Step | How | Needs |
|---|---|---|---|
| 1 | Create the session | `mstsc` to **this machine's own RDP listener** with saved credentials | the account's password, once, in Credential Manager |
| 2 | Start the client | `session_launch.py --session N --game` | SYSTEM (`SeTcbPrivilege`) |
| 3 | Start the daemon | `session_launch.py --session N --script <daemon .cmd>` | SYSTEM |
| 4 | Leave the session disconnected | close the RDP client; `tscon <console session> /dest:console` if the console did move | SYSTEM |

SYSTEM comes from a scheduled task that `rdp_instance.py` creates, runs and deletes in
one elevated call; elevation itself is silent on this machine
(`ConsentPromptBehaviorAdmin = 0`).

Step 4 was a no-op in every run here — see §3.2.

## 3. What had to be discovered live

### 3.1 `mstsc` refuses `localhost` — silently

Connecting the machine to itself by the name `localhost` (or `127.0.0.1`) never reaches
the server. The client log shows the attempt and an immediate hang-up:

```
1024  RDP ClientActiveX is connecting to the server (localhost)
1105  Multi-transport connection dropped
1026  RDP ClientActiveX has been disconnected (Reason= 1800)
```

and the server-side logs (`RemoteConnectionManager`, `RdpCoreTS`,
`LocalSessionManager`) contain **nothing at all** for that moment, while `netstat` shows
the TCP connection was made and torn down. mstsc recognises its own machine and gives
up before the protocol starts. There is no dialog and no exit code — the process simply
disappears after ~4 s, which is what made it look like a credential problem at first.

**Any other address of the same machine works.** Verified: `127.0.0.2` (loopback,
needs no adapter and no name resolution — this is now the default), the LAN address
`192.168.1.254`, and the WSL gateway `172.19.160.1` all create the session. Only the
name that says "myself" is refused.

### 3.2 The console did not move — because RDP Wrapper is installed

On a stock Windows client SKU only one session may be *connected* at a time, so an
incoming RDP logon disconnects the console user. That did not happen here: during the
connect both sessions read as `active`, and the console stayed with `<user1>` throughout.
The reason is on this machine:

```
HKLM\SYSTEM\CurrentControlSet\Services\TermService\Parameters\ServiceDll
    = %ProgramFiles%\RDP Wrapper\rdpwrap.dll
```

i.e. concurrent remote sessions are enabled. **On a machine without the wrapper, expect
step 1 to take the console away** until step 4 puts it back — `rdp_instance.py` runs the
whole sequence unattended and calls `tscon` itself for exactly that case, and
`--restore-console` is there if it ever dies in the middle.

### 3.3 A disconnected session is a fully working session

Everything that matters kept working with nobody attached to session 4:

* the client runs (Unity, D3D11, the RTX 2070 — a disconnected RDP session still has a
  desktop and a rendering device), and does not throttle to death;
* the **thread hijack works into it** — `lua_daemon` warmed up normally
  (`hijacking tid=…, orig RIP=… (in ntdll SAFE_RIP+0x0)`), so il2cpp resolution and
  `SafeDoString` behave exactly as in the console session;
* the game account logs itself in: `dispatch_tasks.py` returned a full alliance list,
  which only exists after login.

What is *not* possible there: anything through the screen. No foreground input, no
`mss` screenshot — those reach the console desktop only. The second instance is a
headless-abilities instance.

### 3.4 Four traps in our own code, all found by running it

* **`ProcessIdToSessionId` lies about other users' processes.** It needs query rights on
  the process, and denial comes back as *session 0* — which reads as "a service" and is
  precisely the process being looked for. `WTSEnumerateProcesses` answers for every
  session without any per-process access; `rdp_instance.clients()` uses that.
* **`LastWarLauncher.exe` matches "lastwar".** Pinning the daemon to "the first process
  whose name contains lastwar" pinned it to the launcher, and the daemon never warmed.
  Both `clients()` and `il2cpp_probe.find_game_pid()` now match `lastwar.exe` exactly.
* **One profile's `%TEMP%` is unreadable from another account.** A bootstrap script left
  in `C:\Users\<user1>\AppData\Local\Temp` cannot be opened by `<user2>`; `cmd.exe` dies
  with `0xc0000142` and leaves a message box and no log. The script the other session
  runs now lives under the repo (`results/logs/daemon-<port>.cmd`), which
  Authenticated Users can read.
* **`SO_REUSEADDR` on Windows lets a second bind steal a live port.** Two daemons were
  found sharing `:47654`, and with two clients on the machine that silently routes calls
  into the wrong game. `lua_daemon` now binds with `SO_EXCLUSIVEADDRUSE`.

## 4. Addressing the second instance

One daemon per client, one port per daemon. `lua_client` takes the port from
`LW_DAEMON_PORT`, so **every existing tool already speaks to either instance**:

```bash
C:\Python312\python.exe tools\dispatch_tasks.py                        # instance 1 (:47654)
LW_DAEMON_PORT=47655 C:\Python312\python.exe tools\dispatch_tasks.py   # instance 2 (:47655)
```

Named instead of numbered, when a caller would rather not carry a port around:

```python
from instance_manager import get_instance, status
ev = get_instance("second")        # or get_instance() for this session's client
```

`tools/lib/instance_manager.py` keeps the registry. By default it holds only `main`
(:47654) — this session — because a second entry would have to name a Windows account,
and no account name is right on somebody else's machine. Register one in
`tools/data/instances.json` (copy `instances.example.json` beside it); `LW_INSTANCE`
names the default instance for a whole process.
Run it directly for a one-line health check of every instance:

```
  main       :47654  this session   warm  pid 102644
  second     :47655  <user2>        warm  pid 29352
```

Two guards make the addressing safe:

* a non-default port never falls back to a local `LuaEval` — an unreachable foreign
  daemon is an error, not a quiet redirect into the client of this session;
* a daemon with no `--pid` attaches to the client **of its own session**
  (`find_game_pid` prefers the caller's session), so it survives a client restart and
  can never grab the other instance's.

`--ping` reports which pid a daemon holds, which is the one-line way to check that the
two have not crossed:

```
[rdp] daemon :47655 {'ok': True, 'warm': True, 'pid': 29352}
```

### 4.1 The panel needs the session too, not only the port (#1204)

A profile drives the second client by naming its port (**Настройки → Общие → «Порт
lua-демона»**), and that is the whole of the *talking*. It is not the whole of the *looking*:
the status strip, the watchdog and the tabs that will not spend an errand on a dead
client all ask the process list, and there they ask by executable name — which both
clients share. A panel driving :47655 would therefore report the console session's client
as its own: "running (pid …)" over a second client that died hours ago, and a watchdog
relaunch that puts a **third** client on this desktop.

So the profile also names the session, on **Настройки → Игра → «Сессия Windows»**:

| Knob | Meaning |
|---|---|
| «Игра запущена в другой сессии Windows» | this profile's client is not the one on this desktop |
| «Логин сессии» | the Windows user logged on to that session (`<user2>`) |

…and **«Проверить»** beside them answers, in one line, which of the four states the
profile is actually in: the box unticked (this desktop), ticked with no login, nobody
logged on as that login (the session is not up — «Поднять сессию», the button beside the
verdict, creates it and everything in it), the session up and
holding no client (start it inside that session), or the whole of it in place with the
pid. A *disconnected* session is reported as disconnected and normal, because that is
how the second instance is meant to be left (§3.3).

The port is the other half of the same answer, so the page says when the two disagree:
a profile looking into `<user2>`'s session while its daemon port is still :47654 reads
one client's process list and presses the buttons of another. That warning sits under
the two rows and appears the moment either knob makes it true.

`panel/runtime/game_process.py` reads the pair (`profile_user`) and then counts only the
clients inside that session. Two details are load-bearing:

* the session's processes come from `WTSEnumerateProcesses`, **not**
  `ProcessIdToSessionId` — the latter needs query rights on the process, so another
  user's client comes back as "session 0", which reads as a service (`rdp_instance.py`
  learned this the same way, §3.4);
* "nobody is logged on to that session" is reported as its own sentence — «пользователь
  <user2> не залогинен» — never as `game not found`. Folding the two together is exactly
  what would have the watchdog relaunch a client that is alive. Every answer the probe
  gives is a `panel.i18n.Message` (the sentence and its locale key in one value), so the
  status strip says it in the panel's language and re-says it when the language changes.

Naming a session also **takes the launch buttons away**: «Запустить игру», «Перезапустить»
and the watchdog all refuse with one log line, because the launcher would start a client
on this desktop and `taskkill /IM LastWar.exe` would fell the client of whoever is farming
here. That session's client is brought up and taken down from its own session (§5).

## 5. Using it

Bringing the second instance up by hand — log in as that account (RDP or fast user
switching), run **`tools\start_instance.cmd 47655`** inside its session, then
*disconnect* the session (do not log off). The script starts the client and the daemon
and refuses to duplicate either, so running it twice is harmless. `--bring-up` does the
same thing without anyone logging in, and is the normal route.


```bash
# Windows Python — pywin32 lives there, not in WSL's python3
C:\Python312\python.exe tools\rdp_instance.py --status          # sessions, clients, daemons
C:\Python312\python.exe tools\rdp_instance.py --bring-up        # session -> client -> daemon
C:\Python312\python.exe tools\rdp_instance.py --bring-up --no-rdp   # session already exists
C:\Python312\python.exe tools\rdp_instance.py --ping
C:\Python312\python.exe tools\rdp_instance.py --lua "CS.UnityEngine.Debug.LogError('RDPINST hi')"
C:\Python312\python.exe tools\rdp_instance.py --stop            # daemon + client, session stays
C:\Python312\python.exe tools\rdp_instance.py --logoff          # …and end the session
C:\Python312\python.exe tools\rdp_instance.py --restore-console # panic button
```

The password for the second Windows account never appears in the repo, and since #1231
it is not readable on the machine either — the full account is in
[`rdp-session-credentials.md`](rdp-session-credentials.md). The short version:

```bash
C:\Python312\python.exe tools\rdp_instance.py --user <user2> --save-credential  # once, ever
C:\Python312\python.exe tools\rdp_instance.py --user <user2> --credentials      # what is stored
C:\Python312\python.exe tools\rdp_instance.py --user <user2> --bring-up --ask   # store nothing
```

The store is Windows' own — Credential Manager, DPAPI, fetched by mstsc itself, the same
mechanism as the RDP client's «remember me» tick. `--save-credential` does not ask for
the password: it runs `cmdkey /generic:TERMSRV/<host> … /pass`, which prompts on its own
console, so the password goes person → cmdkey → Credential Manager and never through
this repository. The entry survives reboots (one on this machine dates from 2024).

With nothing stored, `--bring-up` lets mstsc ask instead and keeps none of it — one
prompt per reboot. The stored entry **is readable** by anything running as the desktop
user: the unreadable credential type exists, but this logon was measured refusing to
spend it, so the choice is between a prompt and that exposure rather than between forms
of storage.

**The second account needs no privileges.** It runs as a member of **Guests** and
**Remote Desktop Users** and nothing else — measured from cold: the RDP logon, the
client, the daemon and a live game read all work, because the logon right comes from
Remote Desktop Users and the two privileged acts (the SYSTEM hop, the `taskkill`) belong
to the desktop side. That is what keeps the stored credential worth a game profile
instead of a machine.

The tool also sets the policy that lets an unsigned `.rdp` open without a prompt
(`AllowUnsignedFiles`); a dialog watcher clicks anything that still appears (it ticks
"do not ask again" first, so it stops appearing) — but never a dialog with somewhere to
type in it, which is what the credential prompt is.

## 6. Limits

* **Headless only.** Clicks, screenshots and the vision DSL cannot reach the second
  session. Everything through `SafeDoString` can.
* **The session does not survive a reboot or a logoff** — re-run `--bring-up`, or press
  «Поднять сессию» on **Настройки → Игра**, which runs the same sequence from the panel
  (#1231). Nothing else about the second instance needs re-doing: the credential and the
  profile survive, only the session does not.
* **One game account per Windows user**, unchanged: the client keeps its account under
  `%LOCALAPPDATA%`, so a third account needs a third Windows user.
* **The second client is not watched.** Nothing restarts it if it crashes; `--status`
  and `--ping` are the health check.
* **RDP Wrapper is doing the concurrency here** (§3.2). Without it the console moves
  during bring-up and comes back at the end, which is disruptive but not destructive.

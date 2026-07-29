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
session 1 (spame, console)            session 4 (casper, disconnected)
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
connect both sessions read as `active`, and the console stayed with `spame` throughout.
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
  in `C:\Users\spame\AppData\Local\Temp` cannot be opened by `casper`; `cmd.exe` dies
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

## 5. Using it

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

The password for the second Windows account is stored once, by #1105's tool, and never
appears in the repo:

```bash
C:\Python312\python.exe tools\launch_as_user.py --user casper --save-credential
```

`rdp_instance.py` copies it from there into the `TERMSRV/<server>` credential that mstsc
reads, and sets the policy that lets an unsigned `.rdp` open without a prompt
(`AllowUnsignedFiles`); a dialog watcher clicks anything that still appears (it ticks
"do not ask again" first, so it stops appearing).

## 6. Limits

* **Headless only.** Clicks, screenshots and the vision DSL cannot reach the second
  session. Everything through `SafeDoString` can.
* **The session does not survive a reboot or a logoff** — re-run `--bring-up`.
* **One game account per Windows user**, unchanged: the client keeps its account under
  `%LOCALAPPDATA%`, so a third account needs a third Windows user.
* **The second client is not watched.** Nothing restarts it if it crashes; `--status`
  and `--ping` are the health check.
* **RDP Wrapper is doing the concurrency here** (§3.2). Without it the console moves
  during bring-up and comes back at the end, which is disruptive but not destructive.

# Multi-instance: a second client as another Windows user, on the current desktop

Task #1105. Goal: run a second Last War client for a second game account **without
switching Windows sessions**, so the bot — whose input model is foreground-only —
can reach both windows on the desktop it already drives.

**Verdict: the Windows plumbing works completely; the game does not.** Any ordinary
process can be started as another Windows user, in the current session, drawing on
the current desktop. `LastWar.exe` started that way is killed by the ACE anti-cheat
after ~9 seconds with exit code `0xDEADC0DE`, through every launch route tried. The
arrangement that does work remains **one Windows session per client** (the second
session over RDP), which is what this machine was already doing.

Tool: [`tools/launch_as_user.py`](../../tools/launch_as_user.py) — it is the working
half, and is useful on its own for running *non-game* helpers as another user.

## 1. Why another Windows user

One Windows user holds exactly one install and one client profile: the game lives in
`%LOCALAPPDATA%\FunFly\Last War-Survival Game` and keeps its account state under the
same profile. A second game account therefore needs a second Windows user with its
own `%LOCALAPPDATA%`.

The straightforward way to get there — a second logon session — puts the second
client on a **different desktop**. This bot drives the game with foreground
`pydirectinput` (see `[[project_input_model]]`), and a window on a desktop that is
not the one attached to the console cannot be focused, clicked or screenshotted from
here. Hence the attempt to keep the second client in *this* session.

## 2. The mechanism (this part works)

Two pieces, both in `tools/launch_as_user.py`.

### 2.1 Let the other user onto WinSta0\Default

A process cannot draw on a window station / desktop it has no access to. The target
user's SID needs ACEs on both, mirroring the SDK's own `AddAceToWindowStation` sample:

| Object | Mask | ACE flags |
|---|---|---|
| `WinSta0` | `GENERIC_ACCESS` (0xF0000000) | `OBJECT`+`CONTAINER`+`INHERIT_ONLY` — so objects created *inside* the station inherit it |
| `WinSta0` | `WINSTA_ALL_ACCESS \| STANDARD_RIGHTS_REQUIRED` (0x000F037F) | `NO_PROPAGATE_INHERIT` |
| `Default` | `DESKTOP_ALL \| STANDARD_RIGHTS_REQUIRED` (0x000F01FF) | none |

Opened with `OpenWindowStation`/`OpenDesktop` for `READ_CONTROL|WRITE_DAC`, read with
`GetUserObjectSecurity`, appended with `AddAccessAllowedAceEx`, written back with
`SetUserObjectSecurity`. An unelevated member of `Administrators` can do all of it.

Two practical notes:

* **The grants are volatile.** Window stations and desktops are recreated at every
  logon, so the ACEs vanish with the session. The tool re-applies them on every
  launch (and `--revoke` takes them back).
* **pywin32 marshals access masks through a signed C long**, so `GENERIC_ACCESS`
  must be handed over as the negative number with the same bit pattern, or
  `AddAccessAllowedAceEx` raises `OverflowError: Python int too large to convert to
  C long`. `_signed()` in the tool does that.

Proof that this is load-bearing, measured on `charmap.exe` started as `casper` from
session 1 (`spame`'s session):

| grants | result |
|---|---|
| absent | process starts, hangs at ~5.3 MB, no window, status *Not responding* |
| present | ~16.8 MB, *Running*, window «Таблица символов» visible on the current desktop |

### 2.2 Start the process under the other user's token

`CreateProcessWithLogonW` (advapi32, via ctypes — pywin32 does not wrap it) with:

* `dwLogonFlags = LOGON_WITH_PROFILE` — loads the target's profile, so the child
  gets the target's `%LOCALAPPDATA%`/`%USERPROFILE%`;
* `lpEnvironment = NULL` — with `LOGON_WITH_PROFILE` that means "the target user's
  environment", which is exactly what a second install needs;
* `STARTUPINFO.lpDesktop = "WinSta0\Default"`.

It needs **no privileges at all**, only the target's password, and it puts the child
in the **caller's session** — the whole point. Verified: the child reports session 1,
`tasklist /V` shows it owned by `Carono\casper`, and its window enumerates and draws
on our desktop.

`lpDesktop` accepts `NULL`, `""`, `"Default"`, `"WinSta0\Default"` — all equivalent
here, because a `NULL` desktop inherits the caller's, and the caller (even a Windows
Python started through WSL interop) is already on `WinSta0\Default` in session 1.

> One trap: `notepad.exe` is an execution alias for the Store app. Started with a
> non-NULL `lpDesktop` it fails with `ERROR_ACCESS_DENIED` and the real UI turns up
> in a different process — it is useless as a smoke test. `--test` uses `charmap.exe`.

The alternative route, `LogonUser` + `LoadUserProfile` + `CreateEnvironmentBlock` +
`CreateProcessAsUser` (`--method asuser`), needs `SeAssignPrimaryTokenPrivilege`,
which **an elevated administrator does not have** — measured: an elevated token on
this machine carries `SeIncreaseQuota`, `SeDebug`, `SeImpersonate` and 21 others but
not `SeAssignPrimaryToken`, and both `SetTokenInformation(TokenSessionId)` and
`CreateProcessAsUser` fail with 1314 *"A required privilege is not held"*. Only
SYSTEM can take that route; the tool was driven from a SYSTEM scheduled task to test
it (§3).

## 3. The wall: ACE kills the client, whatever the route

Every attempt below ended the same way — `LastWar.exe` exits after ~9 s with
`0xDEADC0DE`, the ACE anti-cheat's termination code (the same one recorded in
`[[project_ace_thread_guard]]` for blocked remote threads):

| # | Route | Other client running? | Desktop | Result |
|---|---|---|---|---|
| 1 | `LastWarLauncher.exe` via `CreateProcessWithLogonW` | yes | `WinSta0\Default` | launcher runs, updates, starts the game — game dies |
| 2 | `Game\LastWar.exe` directly, same route | yes | `WinSta0\Default` | `0xDEADC0DE` @ 9 s |
| 3 | same | yes | freshly created `WinSta0\LWTest` | `0xDEADC0DE` @ 9 s |
| 4 | same, after killing every other client | **no** | `WinSta0\Default` | `0xDEADC0DE` @ 9 s |
| 5 | same, after logging the target's own RDP session off | no | `WinSta0\Default` | `0xDEADC0DE` @ 9 s |
| 6 | `CreateProcessAsUser` **from SYSTEM**, token session forced to 1 | no | `WinSta0\Default` | `0xDEADC0DE` @ 9 s |
| 7 | routes 2 and 6 again, on a **freshly updated install** of the target account | no | `WinSta0\Default` | died @ 9 s and @ 6 s |

Row 7 is a re-run after the account's install was updated, in case the first
attempts had been fighting a stale client. They were not: same wall, same timing.

Controls, so the finding is about the token and not about a sick machine:

* Non-game processes as the same target user, same route, same desktop — `charmap`,
  `cmd`, `taskkill`, `logoff` — all run fine and draw normally (§2.1).
* The client started **normally** by the interactive session owner, right after
  test 6, lives indefinitely (verified >90 s, ~1.3 GB resident).
* Two clients *did* coexist on this machine before any of this — one per Windows
  session (session 1 `spame`, session 3 `casper`). ACE therefore does not object to
  two clients per machine.

**The single-instance lock is not the barrier, and never was.** Two clients ran side
by side on this machine before any of this work (one per Windows session), so
whatever named object guards a second launch is already per-user or per-session and
a different Windows account clears it by itself. Test 4 settles it from the other
side: with *every* other client killed, the second-user launch still died. Nothing
here is about instance counting — the kill is unconditional.

What the tests rule out: the shared desktop (3), the second instance (4), the target
user owning another session (5), the secondary-logon service as parent and the
filtered/unprivileged token (6, which uses a proper primary token created by SYSTEM
with the session set explicitly).

What is left, unproven but the only surviving explanation: **ACE requires the
client's token to be the interactive logon of the Windows session it runs in** —
process user must be the session's logged-on user. A second logon for a different
user inside someone else's session is exactly what that check rejects.

The one experiment that would nail it — the *session owner's own* account started
through the same secondary-logon route — was not run; it needs that account's
password, and it only refines the wording, not the outcome.

## 4. What to do instead

* **One Windows session per client.** Log the second user in (RDP or fast user
  switching) and start the client there normally. Proven to work on this machine.
  The cost is that the bot's foreground input cannot reach a client on a different
  desktop, so the second client has to be driven from a bot instance running inside
  that session, not from this one.
* **Headless abilities are unaffected.** Everything that goes through the Lua VM /
  il2cpp rather than through clicks does not care which desktop the window is on.
* `tools/launch_as_user.py` stays useful for running *non-game* helpers as another
  user on this desktop, which is how tests 1–6 above logged the other user off,
  copied its logs and killed its processes without ever switching sessions.

## 5. Using the tool

```bash
# Windows Python — pywin32 lives there, not in WSL's python3
C:\Python312\python.exe tools\launch_as_user.py --check                  # environment report
C:\Python312\python.exe tools\launch_as_user.py --list-users             # who has a profile / an install
C:\Python312\python.exe tools\launch_as_user.py --user <name> --save-credential
C:\Python312\python.exe tools\launch_as_user.py --user <name> --test     # charmap, proves the plumbing
C:\Python312\python.exe tools\launch_as_user.py --user <name>            # the game (dies — see §3)
C:\Python312\python.exe tools\launch_as_user.py --user <name> --exe C:\Windows\System32\cmd.exe --args "/c ..."
C:\Python312\python.exe tools\launch_as_user.py --user <name> --revoke   # hand the grants back
```

Passwords are never stored in the repo. Resolution order: `--password` (discouraged —
visible in the process list) → `--password-env` (default `LW_ALT_PASSWORD`) →
`--password-file` → Windows Credential Manager (`LastWarVpBot/<domain>\<user>`,
DPAPI-encrypted for the caller) → interactive prompt. `--save-credential` writes the
Credential Manager entry, `--forget-credential` deletes it.

### 5.1 Setting it up

1. **Create the Windows account and install the game under it.** The account must
   have logged in at least once — until then Windows has not created its profile
   and there is nothing to load. `--list-users` shows which local accounts own a
   profile, and whether a Last War install is visible in it (`private (cannot
   tell)` for another user's profile is normal and harmless).
2. **Store the password once**, so nothing runs interactively afterwards:
   `--user user2 --save-credential`. It lands in Windows Credential Manager under
   `LastWarVpBot/<domain>\<user>`, encrypted by DPAPI for the calling account.
   `--forget-credential` removes it.
3. **The ACLs need no manual work.** The tool applies the WinSta0/desktop grants
   itself on every launch (§2.1) because they are volatile; `--grant-only`
   applies them without starting anything, `--revoke` takes them back.
4. **The exe path** defaults to that account's own
   `%LOCALAPPDATA%\FunFly\Last War-Survival Game\LastWarLauncher.exe`
   (`--game client` picks `Game\LastWar.exe` instead). Override with `--exe` or
   the `exe` key in the accounts file when the install is elsewhere.
   The caller does not need read access to it (§5, gotchas).

### 5.2 Several accounts at once

`--config accounts.json --all` runs one instance per entry, `--stagger SEC` spaces
the cold starts out. `--config accounts.json --user user3` picks a single entry.
The file (see `tools/data/accounts.example.json`, real ones are git-ignored):

```json
[
  {"user": "user2"},
  {"user": "user3", "exe": "C:\\Games\\LastWar\\LastWar.exe"}
]
```

Omit `password` and it comes from Credential Manager, which keeps the file
secret-free; omit `exe` and it resolves per profile. `domain`, `args` and `cwd`
are accepted per entry too.

### 5.3 The Lua daemon is single-instance — what would have to change

If the ACE wall is ever cleared, the bot side is **not** ready for two clients,
and the port is the smallest part of it. Three assumptions in the Lua stack are
hardcoded to "there is exactly one client":

| Where | Assumption | What multi-instance needs |
|---|---|---|
| `tools/lib/lua_client.py:23-24` | `HOST/PORT = 127.0.0.1:47654`, bound in `tools/lua_daemon.py:121` | a per-instance port, e.g. `base + index` (47654, 47655, …), passed to both the daemon and `get_evaluator()`; `DaemonClient` already takes `host`/`port` arguments, only the module-level default and the daemon's `bind` are fixed |
| `tools/lib/il2cpp_probe.py:89` `find_game_pid()` | returns the **first** process whose name contains "lastwar" | an explicit pid (or a pid chosen by owning user), threaded through `LuaEval`/`XR.X()` — otherwise both daemons drive the same client |
| `tools/lib/lua_eval.py:25` `player_log_path()` | `%LOCALAPPDATA%` of the **calling** process | the target account's `…\AppData\LocalLow\FunFly\…\Player.log`. Every Lua result is read back from that log, so a daemon pointed at the wrong one silently returns nothing — and another user's LocalLow is unreadable without a grant, so each daemon must run **as its own account** |

The last row is the real constraint: the natural shape is not one daemon on many
ports but **one daemon process per account, started with `launch_as_user.py`**,
each inheriting its own profile and reading its own `Player.log`, each on its own
port. That falls out of the tool for free — `--exe` the Windows Python and `--args`
the daemon script — and needs no change to `lua_daemon.py` beyond making the port
an argument (a `--port` flag defaulting to `lua_client.PORT`, plus passing it into
`bind`). None of this was implemented: with the client dying at 9 s there is
nothing to point a second daemon at, and untested changes to the daemon every
other tool depends on would be a regression risk for no gain.

### 5.4 Gotchas

* **Do not measure the child's liveness with `OpenProcess` + `GetExitCodeProcess`.**
  Unelevated, `OpenProcess` on a process owned by another user is denied and
  returns NULL; `GetExitCodeProcess` on a NULL handle fails without touching the
  output variable, so a caller that initialised it to `STILL_ACTIVE` (259) sees
  "still running" forever. That produced one false "survived 120 s" reading here
  before the process list showed it had died at 9 s like all the others. Read
  liveness from the process list, or from the handle `CreateProcess*` returned
  (that one is valid — it is how rows 1–7 above were timed). `--wait` in the tool
  now watches the new pid for a further 30 s and reports the death explicitly,
  because "a pid appeared" on its own reads as success when it is not.

* The game sits in the target user's private profile, which the caller cannot
  read — and that does not matter: the secondary-logon service opens the path
  while impersonating the target, so the launch works. `--check` reports it as
  *"unreadable from this account"* rather than *"missing"*, which needs
  `os.stat`: `os.path.exists` swallows `PermissionError` and answers False, so
  it cannot tell a private path from an absent one.
* Passing environment from WSL to the Windows Python needs `WSLENV`:
  `LW_ALT_PASSWORD=… WSLENV=LW_ALT_PASSWORD C:\Python312\python.exe …`.

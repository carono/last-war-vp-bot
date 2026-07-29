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

Controls, so the finding is about the token and not about a sick machine:

* Non-game processes as the same target user, same route, same desktop — `charmap`,
  `cmd`, `taskkill`, `logoff` — all run fine and draw normally (§2.1).
* The client started **normally** by the interactive session owner, right after
  test 6, lives indefinitely (verified >90 s, ~1.3 GB resident).
* Two clients *did* coexist on this machine before any of this — one per Windows
  session (session 1 `spame`, session 3 `casper`). ACE therefore does not object to
  two clients per machine.

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

Two gotchas worth knowing:

* The game sits in the target user's private profile, which the caller cannot
  read — and that does not matter: the secondary-logon service opens the path
  while impersonating the target, so the launch works. `--check` reports it as
  *"unreadable from this account"* rather than *"missing"*, which needs
  `os.stat`: `os.path.exists` swallows `PermissionError` and answers False, so
  it cannot tell a private path from an absent one.
* Passing environment from WSL to the Windows Python needs `WSLENV`:
  `LW_ALT_PASSWORD=… WSLENV=LW_ALT_PASSWORD C:\Python312\python.exe …`.

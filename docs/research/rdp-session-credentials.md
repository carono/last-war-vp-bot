# Bringing the second session up ourselves, without keeping a password

Task #1231. The panel used to refuse to create the second client's Windows session and
print a command line for the person to run instead — and that command line leaned on a
stored password which any process on this desktop could read back in clear.

Two questions, and they have different answers:

* **"can the panel bring the session up itself?"** — yes, and it does now. Nothing was
  missing but the wiring.
* **"can it do that without a password stored anywhere?"** — yes, at the cost of one
  prompt per reboot, and **no** if it has to be unattended. Creating a Windows
  interactive session *is* an authentication, and no Windows API manufactures one
  without a credential (§2).

> **This document was wrong once, and the correction is the interesting part.** The
> first version of it recommended keeping the password in the *unreadable* credential
> form — usable by the connection, readable by nothing, apparently the best of both.
> Then it was tested against a real logon and **the connection will not spend that
> form** (§3A). Unattended and unreadable are not available together here. What is
> available is the choice in §3B, and one mitigation worth more than either (§5).

## 0. The mechanism is already Windows' own — that part was never in doubt

Worth saying first, because it is easy to read the rest as though the bot invented a
password store. It did not. What holds the password is **Credential Manager**: DPAPI at
rest, keyed to this user and this machine, and **mstsc fetches it itself** — exactly the
thing the RDP client's «remember me» tick uses. Nothing in this repository decrypts it,
and since §4 nothing here even *receives* it.

Measured this session, and these are the four questions worth having answers to:

| | answer | evidence |
|---|---|---|
| Does a stored credential already bring the session up with no password typed? | **yes** | a cold `--stop --logoff` then `--bring-up`: connected in ~2 s, client started, daemon warm, a Lua chunk answered out of the second client. Nothing was typed. |
| Is the credential really what does it? | **yes** | with every entry for that target deleted and nothing else changed, the same connect **fails**. The control matters: without it, every other row could be caching. |
| Does it survive a reboot? | **yes** | a «remember me» credential on this machine was written **2024-07-02** and is still there; the machine last booted **2026-07-13**. `Persist = LOCAL_MACHINE`. |
| Is the `TERMSRV/` prefix needed? | it is the right one to use | `TERMSRV/127.0.0.2` connects; the bare `127.0.0.2` also connected here, but `TERMSRV/<host>` is the name Windows itself writes and the one to rely on. |

The single point of difference with «tick remember me and be done» is the credential's
**type**, and that is not a preference either — see §3A.

## 1. Where the password was, and what could read it

Both halves of the old arrangement were Windows *generic* credentials, written with
`CredWrite(… CRED_TYPE_GENERIC …)`:

| Target | Written by | Type | Persist |
|---|---|---|---|
| `LastWarVpBot/<domain>\<user2>` | `launch_as_user.py --save-credential` (#1105) | generic | local machine |
| `TERMSRV/<server>` | `rdp_instance.py` copied it there at every bring-up (#1106) | generic | local machine |

A generic credential is DPAPI-protected at rest and **handed back in plaintext to any
process running as that account**. Measured on this machine:

```
'LastWarVpBot/…'    type=GENERIC          blob_bytes=36  readable_plaintext=True
'TERMSRV/127.0.0.2' type=GENERIC          blob_bytes=36  readable_plaintext=True
'TERMSRV/<a real remote host>' type=DOMAIN_PASSWORD blob_bytes=0  readable_plaintext=False
```

That last line is the whole finding. A credential of type `CRED_TYPE_DOMAIN_PASSWORD` —
the type mstsc's own «remember me» writes — comes back with an **empty blob**: LSA uses
it for the connection and gives it to no caller, including the one that wrote it. The
two forms are equally convenient and not remotely equally exposed.

What made the exposure worth a task rather than a note: the second account is a member
of **Administrators** on this machine (checked with `net user`), so what sat in reach of
every script, every browser extension host and every game-adjacent process running as
the desktop user was an administrator's password, in clear, on demand.

### What happens after a reboot

| | survives a reboot | survives a logoff | survives a panel restart |
|---|---|---|---|
| the stored credential | **yes** (persist = local machine) | yes | yes |
| the second Windows session | **no** | no | yes |
| the client and daemon inside it | no | no | yes |

So the credential is not the thing that needs re-doing after a reboot — the *session*
is, and it needed a person at a terminal. On this machine the first account is logged on
automatically at boot (`AutoAdminLogon = 1` for it, its password kept as an LSA secret),
which is why the FIRST instance comes back by itself and the second one never did. Note
also that this occupies the machine's one autologon slot — see option D.

A **disconnected** session survives everything short of a reboot or a logoff, so in
practice the question is "once per boot", not "every time".

## 2. Why no route creates a session without a credential

This is the load-bearing part of the research, because three of the four options in the
task brief die on it.

`WTSQueryUserToken(session)` — which is how steps 2–4 start the client and the daemon
inside the session, with **no password at all** — hands over a logon that *already
exists*. It cannot make one. Nor can anything else:

* **S4U** (`LsaLogonUser` with `MSV1_0_S4U_LOGON`, and its friendly face
  `schtasks /ru <user> /np`) genuinely produces a token for a user without their
  password. It is a *network*-flavoured token belonging to session 0, with no window
  station, no desktop and no credentials to pass on. `SetTokenInformation(TokenSessionId)`
  can move a token into an existing session — never into a new one.

  Measured here, and it is worse than the theory: `schtasks /ru <user> /np` **prompts
  for the password anyway**, elevated or not, and hangs on the prompt; registering the
  same thing properly (`New-ScheduledTaskPrincipal -LogonType S4U`) is refused with
  `0x80070005` both as an elevated administrator **and as SYSTEM**. And a task that does
  run reports what the theory says it would — as the scheduler's own account, in
  `session=0`, with `[Environment]::UserInteractive` **False**. There is no desktop
  there for a client to draw on, which is the wall #1105 hit from the other side.
* **A service with `CreateProcessAsUser`** is the same story: it needs a token, and the
  only password-free way to a user's token is one of the two above.
* An interactive session is created by the terminal-services stack in response to a
  logon — at the console, over RDP, or through fast user switching — and every one of
  those is an authentication with a password, a smartcard (needs a KDC, i.e. a domain
  this machine is not in) or Windows Hello (interactive by construction).

So the credential question is only ever: **who holds it, and in what form.**

## 3. The options, and what each one costs

### A. Sealed credential — *tried, measured, and it does not work here*

The idea: keep the password where Windows keeps RDP passwords, as a `TERMSRV/<server>`
credential of type `CRED_TYPE_DOMAIN_PASSWORD` — the type mstsc's own «remember me»
writes. Unattended *and* unreadable, apparently the best of both.

Half of it is true. Such a credential is genuinely unreadable: written, then `CredRead`
returns a 0-byte blob, while the generic one at the same target returns its 36 bytes of
plaintext. Three credentials on this machine, saved by mstsc itself against real remote
hosts, are of exactly this type.

**The other half fails.** With the sealed credential in place and nothing else, the
connection does not happen:

| credential at `TERMSRV/127.0.0.2` | result |
|---|---|
| **nothing at all** (control) | mstsc opens, then no session |
| generic (readable) | **connected in ~2–6 s** |
| domain-password (unreadable), `CredWrite` | mstsc opens, ~25 s, vanishes — no session |

No dialog, no exit code, nothing but the client's own frame: the failure signature
`multi-instance-rdp.md` §3.1 records for `localhost`. The control row is what makes the
third one mean something — **the unreadable credential behaves exactly as if no
credential existed**. Three `UserName` spellings were tried (`<domain>\<user>`,
`<host>\<user>`, and mismatched against the `.rdp`); none changed it.

> **A retracted claim.** An earlier version of this file added a fourth row: the same
> failure with the credential written by `cmdkey /add:` rather than `CredWrite`, offered
> as proof that no field of ours was to blame. That row is withdrawn. `cmdkey` reads its
> `/pass` prompt from the **console**, not from stdin — fed through a pipe it stores an
> *empty* password and still exits 0. The tell came later, when the same trick against
> `/generic:` produced a credential whose blob was zero bytes; for the domain type the
> blob always reads back empty, so there it looked like success. The conclusion survives
> on the `CredWrite` row plus the control, but the corroboration did not exist.

An attempt to pin the cause on loopback specifically — the same two forms against this
machine's LAN address — was inconclusive: **the generic control failed there too**, so
that experiment says something about the address, not about the credential.

So this is **not the default**. `--seal` keeps it available, because the verdict is
about one configuration and a domain-joined install has a KDC and may well differ, and
`rdp_connect` falls back to the readable copy and says so — trying it costs one slow
bring-up, not a stranded instance. (That fallback earned itself immediately: the first
live bring-up ran the sealed attempt, failed, fell back, and the session came up.)

### B. Ask, and store nothing — *the answer to the question as asked*

`--ask`, and the panel whenever nothing is stored, open mstsc with its own credential
prompt. Windows asks, Windows checks, nothing is written anywhere. Everything after the
logon — client, daemon, console, tear-down — is unattended exactly as before.

* **Cost:** one password typed per reboot, at the machine. Not per bring-up: a
  disconnected session survives everything short of a reboot or a logoff.
* **Security:** the best available. There is no secret at rest to steal.

### B′. Store it in Credential Manager, the way the RDP client does — *unattended*

The alternative, and now that A is gone it is the only unattended one: a generic
`TERMSRV/<server>` credential, which this logon spends in a couple of seconds.

**`--save-credential` does not ask for the password itself.** It runs
`cmdkey /generic:TERMSRV/<host> /user:<domain>\<user> /pass`, and `cmdkey` prompts on
its own console: the password goes **person → cmdkey → Credential Manager**, never
through this process and never through an argument (which would put it in every process
listing). That is the whole of what the person wanted — Windows takes the password, and
this repository has no code that could print it even by accident.

One guard, because the failure mode is silent: `cmdkey` reads that prompt from the
console and, given a pipe instead, stores an **empty** password and reports success. So
what landed is read back, and an empty entry is deleted with a complaint rather than
left to surface at three in the morning as "the session will not come up".

* **Cost:** nothing after the one prompt, and it survives reboots (§0).
* **Security:** the entry is DPAPI-protected at rest and unreadable to other users and
  other machines — but a *generic* credential is readable by anything running as **this**
  user, which is the part that must be said rather than implied. `--credentials` says it.
  It is only tolerable once §5's mitigation is applied.

### C. An account with no password

Nothing to store because there is nothing to know. It needs
`LimitBlankPasswordUse = 0` (it is `1` here, the default) for the loopback RDP logon to
be accepted at all — and that switch is **machine-wide**: it stops being true that
blank-password local accounts are console-only, for every such account, over RDP and
SMB alike. On a box whose RDP listener answers on the LAN that is a bad trade for
avoiding one prompt per boot. Rejected — but it would be defensible on an isolated
machine with the listener firewalled to loopback and the second account demoted out of
Administrators.

### D. Autologon for the second account

Rejected on three counts, any one of which is enough:

1. Windows has **one** autologon slot and this machine's belongs to the first account —
   taking it would stop the bot's own session coming back after a reboot.
2. It still stores the password (cleartext in the registry, or an LSA secret with
   Sysinternals' Autologon — recoverable by SYSTEM either way), so it does not even
   answer the question being asked.
3. It logs the second account on **at the console**, which is the one place the second
   instance must not be.

### E. A scheduled task running as the second user

Two flavours, and neither creates the session:

* *"Run whether user is logged on or not"* + a stored password — the password becomes an
  LSA secret, which is a better hiding place than a generic credential, and the task
  runs under a **batch** logon in session 0: no desktop, so ACE kills the client exactly
  as in #1105.
* `/np` (S4U, nothing stored) — same session 0, same wall. And it is not even
  registerable here: see the measurements in §2.

The session-0 half is measured, not assumed. A probe run as a scheduled task reported:

```
nt authority\system
session=0
UserInteractive=False
```

It is, however, genuinely useful for the *other* half: a task registered **inside** the
second session with an "at log on" trigger, running `tools\start_instance.cmd <port>`,
brings the client and the daemon up on their own whenever that session logs on. Combined
with B or B′, a reboot then costs at most one password and no further attention.
Not implemented — the SYSTEM route already does this and works.

### F. A saved RDP connection with credential delegation

The one option that sounds like it dodges §2 entirely, and the reason it does not is
worth spelling out, because the mistake is easy to make.

CredSSP delegation is configured under
`HKLM\SOFTWARE\Policies\Microsoft\Windows\CredentialsDelegation` —
`AllowDefaultCredentials` with `TERMSRV/*` in its list makes the RDP client hand the
**logged-on user's own** credentials to the target without a prompt. It genuinely
removes a password dialog, and it stores nothing new.

It removes the wrong dialog. Delegation answers *"do not make me retype who I already
am"*; the question here is *"log in as somebody else"*. Delegating the desktop user's
default credentials to `127.0.0.2` authenticates as **the desktop user** — it would
create or reconnect that account's session, and the second client must be owned by the
second account's own interactive logon or ACE kills it (#1105). To delegate the second
account's credentials, mstsc would have to be *running as* that account, which needs its
password — the thing being avoided. `AllowFreshCredentials` is the same shape: "fresh"
means typed.

There is a cost, too, if anybody reaches for it anyway: `TERMSRV/*` tells the machine to
hand your credentials to *any* RDP target you connect to. On a workstation that also
opens sessions to real remote servers — this one has three saved — that is a wider
change than the problem deserves.

### G. A service under SYSTEM calling `CreateProcessAsUser`

Already how this works (`tools/session_launch.py`), already password-free, and §2 is why
it cannot be stretched to cover the logon. Nothing to change.

## 4. What was built

`tools/rdp_instance.py`:

```
--credentials        what is stored for this account, in what form, and who can read it
--save-credential    hand the typing to cmdkey — Windows stores it, we never see it
--forget-credential  store nothing again
--bring-up           use what is stored; ask when nothing is
--bring-up --ask     ask always, store nothing
--bring-up --stored  refuse to ask; fail instead (for unattended callers)
--bring-up --seal    try the unreadable form, falling back if it is not spent
```

Nothing is sealed behind anyone's back: the default path uses whatever is stored, and
`--credentials` names the exposure rather than leaving it to be discovered.

The panel: **Настройки → Игра → «Поднять сессию»**, beside «Проверить». It runs the same
sequence off the Tk thread with the tool's commentary going line by line into the panel
log, and re-reads the verdict when it finishes. The verdict for "nobody is logged on as
that user" now names that button instead of a command line.

When nothing is stored it says two things before Windows puts a password box on the
desktop: that the box is about to appear and what wanted it, and that it will appear
again after every reboot until the password is saved — with the one command that saves
it. A dialog nobody expected, and a dialog that returns forever with no explanation of
how to stop it, are two different kinds of bad, and both are cheaper to prevent than to
support.

The dialog-clicker learned one rule along the way: **a dialog with somewhere to type is
a dialog for the person.** It ticks "do not ask again" and presses «Да» only on dialogs
that ask nothing but yes or no — otherwise the no-storage route would have its credential
prompt answered, with an empty password, by the very automation that opened it.

## 5. The recommendation

**Take B′ if the machine has to come back on its own, B if it does not — and do the
mitigation either way.**

B′ (`--save-credential`, once) is the arrangement the RDP client itself offers: Windows
holds the password, mstsc spends it, the bot never sees it, and a reboot costs nothing.
B (`--ask`) keeps no secret at all and costs one prompt per boot — a disconnected
session survives everything else, so it is not a prompt anybody meets during a day's
farming.

Whichever is chosen, **the mitigation is not optional**, and under B′ it is the thing
that decides whether the stored credential matters at all:

> **The second Windows account does not need to be an Administrator.** It runs one game
> client in a session nobody looks at. On the machine this was written for it is in
> Administrators, which means what a readable credential exposes is an admin password.
> Demote it to a standard user and the same exposure buys an attacker a game profile.

That single change is worth more than anything the credential form could have bought,
and — unlike option A — it is available on every configuration.

## 6. What is true afterwards

* The panel raises the session itself; no command line is named to anybody any more.
* One prompt per boot, or none if the person accepts a readable stored credential and
  has been told plainly that it is readable.
* Nothing in this repository logs or prints a password, and the only code path that
  holds one at all is the opt-in `--seal` migration.
* Steps 2–4 (client, daemon, console) remain what they always were: no credential
  anywhere near them (`docs/research/multi-instance-rdp.md` §1).

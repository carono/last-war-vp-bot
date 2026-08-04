# Bringing the second session up ourselves, without keeping a password

Task #1231. The panel used to refuse to create the second client's Windows session and
print a command line for the person to run instead — and that command line leaned on a
stored password which any process on this desktop could read back in clear.

Two questions, and they have different answers:

* **"can the panel bring the session up itself?"** — yes, and it does now. Nothing was
  missing but the wiring.
* **"can it do that without a password stored anywhere?"** — not unattended. Creating a
  Windows interactive session *is* an authentication, and no Windows API manufactures
  one without a credential (§2). What is genuinely fixable is the *form* the secret is
  kept in, and that fix is large: it goes from **readable by anything you run** to
  **readable by nothing at all**.

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
* **A service with `CreateProcessAsUser`** is the same story: it needs a token, and the
  only password-free way to a user's token is one of the two above.
* An interactive session is created by the terminal-services stack in response to a
  logon — at the console, over RDP, or through fast user switching — and every one of
  those is an authentication with a password, a smartcard (needs a KDC, i.e. a domain
  this machine is not in) or Windows Hello (interactive by construction).

So the credential question is only ever: **who holds it, and in what form.**

## 3. The options, and what each one costs

### A. Sealed credential — *chosen, and now the default*

Keep the password where Windows keeps RDP passwords: a `TERMSRV/<server>` credential of
type `CRED_TYPE_DOMAIN_PASSWORD`. mstsc consumes it exactly as it consumes the one its
own «remember me» writes; `CredRead` returns nothing to anybody.

* **Cost to the person:** one prompt, once, ever (`--save-credential`).
* **Security:** the secret still exists — an attacker who is already SYSTEM, or who has
  the desktop user's own password (DPAPI master key), can still get at the vault. What
  goes away is the entire class of "anything running as me can print it": no script, no
  tool in this repo, and no process it spawns can read it any more. This repo's code
  touches the plaintext in exactly one place now — the one-time migration of an old
  readable credential — and never again.
* **Caveat, stated plainly:** the sealed *connect* has not been exercised live here,
  because doing so means logging off or reconnecting a session with a live farming
  client in it. The credential API half is measured (write, read-back-empty, delete —
  all confirmed); the consumption half rests on it being the same credential mstsc
  writes for itself, of which this machine holds three working examples. Because that
  is an inference and not a measurement, `rdp_connect` **falls back**: if the sealed
  connect produces no session and the old readable copy is still on the machine, it puts
  the readable one back, says so, and retries. A hardening that quietly stops the second
  instance coming up would be worse than the thing it hardened.

### B. Ask, and store nothing — *implemented alongside*

`--ask` (and the panel, whenever nothing is stored) opens mstsc with its own credential
prompt. Windows asks, Windows checks, nothing is written anywhere. Everything after the
logon — client, daemon, console, tear-down — is unattended as before.

* **Cost:** one password typed per reboot, at the machine.
* **Security:** the best available. There is no secret at rest to steal.
* This is the honest reading of "without storing a password", and it is why the panel
  never fails for want of a credential: with none stored it takes this route by itself.

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
  LSA secret (better than a generic credential, no better than option A), and the task
  runs under a **batch** logon in session 0: no desktop, so ACE kills the client exactly
  as in #1105.
* `/np` (S4U, nothing stored) — same session 0, same wall.

It is, however, genuinely useful for the *other* half: a task registered **inside** the
second session with an "at log on" trigger, running `tools\start_instance.cmd <port>`,
brings the client and the daemon up on their own whenever that session logs on. Combined
with option A or B, a reboot then costs at most one password and no further attention.
Not implemented — the SYSTEM route already does this and works.

### F. A service under SYSTEM calling `CreateProcessAsUser`

Already how this works (`tools/session_launch.py`), already password-free, and §2 is why
it cannot be stretched to cover the logon. Nothing to change.

## 4. What was built

`tools/rdp_instance.py`:

```
--credentials        what is stored for this account, and in what form
--save-credential    ask once, seal it (CRED_TYPE_DOMAIN_PASSWORD)
--forget-credential  delete the readable copies
--bring-up           sealed if there is one, readable ones sealed on the way past,
                     and Windows asks when there is neither
--bring-up --ask     ask always, store nothing
--bring-up --stored  refuse to ask; fail instead (for unattended callers)
```

A readable credential left over from #1105/#1106 is migrated to the sealed form the
first time a bring-up needs it. The `LastWarVpBot/…` entry is deliberately **left
standing** until the person runs `--forget-credential`: while it is there it is the way
back if the sealed form does not take.

The panel: **Настройки → Игра → «Поднять сессию»**, beside «Проверить». It runs the same
sequence off the Tk thread with the tool's commentary going line by line into the panel
log, says beforehand when Windows is about to ask for a password, and re-reads the
verdict when it finishes. The verdict for "nobody is logged on as that user" now names
that button instead of a command line.

The dialog-clicker learned one rule along the way: **a dialog with somewhere to type is
a dialog for the person.** It ticks "do not ask again" and presses «Да» only on dialogs
that ask nothing but yes or no — otherwise the no-storage route would have its credential
prompt answered, with an empty password, by the very automation that opened it.

## 5. What is still true afterwards

* One prompt per boot at worst, none at all with a sealed credential.
* The password is not readable by anything running as the desktop user.
* Nothing in this repository stores, logs or passes a password.
* Steps 2–4 (client, daemon, console) remain what they always were: no credential
  anywhere near them (`docs/research/multi-instance-rdp.md` §1).
* **Worth doing separately:** the second account is an Administrator and has no need to
  be. Demoting it costs nothing and shrinks what the remaining secret is worth.

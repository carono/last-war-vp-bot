# The account's characters — `account.login.new`, and the cache that is not them

Sources:

* a live capture of the client asking for its characters and the server answering
  (`tools/scratch/account_pcap.py`, 2026-08-02, 246 packets on the game stream);
* live reads of the running Lua VM — the roles list, the login cache, and
  `string.dump` of the handlers on both sides;
* the client driven through its own «Профиль → Аккаунт → Персонажи» path.

Task #1190: the panel's «Аккаунты» tab drew six characters on an account that has
two. The wire settled it.

## 1. The list the game draws

Pressing «Персонажи» runs `UIAccountManageView:OnBtnRoleClick`, which opens
`UIWindowNames.UIRoles`. That screen's `DataDefine` sends one message:

```lua
SFSNetwork.SendMessage(MsgDefines.AccountLoginNew)     -- "account.login.new"
```

On the wire that request is three fields and no credentials:

```json
{"airKey": "lwDid_<base64 of the device id>",
 "deviceId": "a594ed140224448fb45ad9c91aa5410f_n3d",
 "type": 1}
```

The direct reply is a bare `{"success": true}`. The data arrives right behind it as
a **`push.account.login.new`**, which describes the character in play and carries
the whole list in `accountArr`:

```
accountArr: 2 entries
  [1] id=935  gameUid=1522777203000972  gameUserName=Carono          gameUserLevel=35  zone=APS935  power=241514404  alAbbr=TLou
  [2] id=509  gameUid=2146058428000509  gameUserName=Игрок 3464d509  gameUserLevel=21  zone=APS509  power=4185296    alAbbr=RBs
```

**Two.** Not six. Per entry the server sends ~33 fields; the ones worth drawing are
`id` (the server), `gameUid`, `gameUserName`, `gameUserLevel` (HQ), `zone`, `power`
and `alAbbr` (alliance tag). It also sends `loginKey` and `uuid` — the credentials
for switching to that character (§4).

`DataCenter.AccountManager:AccountLoginHandle` parses `accountArr` through
`RolesInfo:Parse` into `AccountManager.rolesList` and opens `UIRoles`.

## 2. Reading it without opening a window

`rolesList` is empty until something asks — which is why an earlier reading of it
mid-session found nothing and the cache looked like the only source. Sending the
request by hand fills it and opens nothing:

```lua
SFSNetwork.SendMessage(MsgDefines.AccountLoginNew)      -- no arguments needed
```

Confirmed live: `rolesList` went 0 → 2 in about four seconds with
`IsWindowOpen(UIRoles) == false` throughout. The reply is asynchronous, so the
reader polls (`account_switch.read_accounts`, 6 s default).

One wrinkle: when the *screen* fills the list it prepends a placeholder entry whose
only field is `isEmpty = true` — its «add a character» slot. It is not a character
and is skipped.

`LuaEntry.Player.serverId` says which character is in play;
`WorldFavoDataManager.curServerId` is empty on a freshly logged-in client and
cannot be relied on alone.

## 3. The login cache, and why it was wrong

`DataCenter.AccountListManager:GetAccountInfos()` is a cache of **logins**.
`AddAcountInfo` keys an entry through `GetAcountInfoIndexByUidAndURLEnv` —
`gameUid` + `serverid` + `urlEnv` — so a login to a server the character has never
been on is a *new* row, never an update. Under it, `GetAccountInfoString()` is an
append-only log: 50 records spanning 19 server ids on this client.

What it held at the same moment the server said "two":

| server | gameUid | HQ | what it really is |
|--------|---------|----|-------------------|
| 935 | …000972 | 35 | Carono, in play |
| 972 | …000972 | 35 | the server it was created on (the uid ends in it) |
| 1012 | …000972 | 35 | a server it passed through |
| 8118 | …000972 | 35 | a cross-server event server |
| 509 | …000509 | 21 | the second character |
| 2105 | …002105 | 0 | made, never played |

Nothing removes those rows; `DeleteAcountInfo` exists and the client never calls
it. Drawing this table is the bug.

A first fix trimmed the cache by rule — one row per `gameUid`, drop HQ 0 — and
landed on the right two. It is gone: it inferred what the server states outright,
and its «deleted character» test (HQ 0) would have missed a character that was
played and then deleted. `--cache` still prints the cache, to show what the client
keeps.

## 4. Switching — the character screen's route, and the login screen's dead end

### 4.1 What did not work

The first `switch_account` reproduced the *login screen's* cell handler
(`UIAccountListCell.OnBtnSelectClick`). The capture shows what that actually puts
on the wire from inside a session:

```
--> az.account.login  {"pwd": "…", "userName": "", "deviceId": "…"}
<-- az.account.login  {"errorCode": "120618", "errorMsg": "email format error"}
```

The handler builds its message out of `AccountManager.param`, which the login
screen fills and nothing else does — so from inside the game it sends an empty user
name and the server rejects it. The tool reported `sent` because the send happened;
the switch did not. That handler is gone from the tool.

### 4.2 What the game does instead

Tapping a character runs `UIRolesCell:OnBtnClick`, whose whole body (read out of the
live VM with `string.dump`, task #1192) is a two-way branch: the `isEmpty`
placeholder opens `UIChooseServer` — its «add a character» slot — and a real
character opens

```lua
UIManager:GetInstance():OpenWindow(UIWindowNames.UIRoleLogin, self.param)
```

`self.param` is the `rolesList` entry, i.e. the server's own `accountArr` record.
That window shows the character and one button, and the button is
`UIRoleLoginView:OnClickLogin`:

```lua
CS.AccountCredentialManager.ClearAll()
CS.AccountCredentialManager.SetServerNetInfo(param.ip, param.port, param.zone)
CS.AccountCredentialManager.SetLoginKey(param.loginKey)
CS.AccountCredentialManager.SetUID(param.gameUid)
CS.AccountCredentialManager.Save()
CS.AIHelp.AIHelpProxy.Logout()
EventManager:GetInstance():Broadcast(EventId.SwitchAccount)   -- 99006
SFSNetwork.SendMessage(MsgDefines.UserCleanPost)              -- "user.clean.post"
```

So a switch is: **write the picked character's credentials over the saved ones, then
tell the server the session is done with.** Nothing is typed and nothing is asked of
the server first — every field is already in the record from §1. The `SwitchAccount`
broadcast is only the client's own cleanup (the chat cache is what listens to it).

Two details that cost a probe each:

* `AccountCredentialManager` is a **C# static** (`CS.AccountCredentialManager`), so
  those are `.`-calls with no `self`.
* `param.ip` is a **pipe-separated list of hosts**
  (`lastwar-game-cf.…|lastwar-game-us-aws-ali.…|…`) and `param.port` is a *string*.
  `SetServerNetInfo` takes the port either way; both forms were tried live against
  the current character's own values, which changes nothing.

### 4.3 The relog is in the reply, not in the press

That sequence run verbatim **does nothing**. The first live attempt saved the
credentials, sent `user.clean.post`, and then sat on the old character for 80 seconds
while the recipe polled — no error, every call returning cleanly.

What is missing is the other half of the handshake. `MsgDefines.UserCleanPost` has a
reply class, and its handler is one line:

```lua
-- Net.Msgs.Account.UserCleanPostMessage:HandleMessage
CS.SwitchAccountCheckGameVersionTools.ReloadGameByCheckLauncherVersion()
```

*That* is the relog. Sent by hand from inside a live session, the reply never comes:
`HandleMessage` was wrapped with a logger and watched across three sends over 14
seconds and never fired once, while `LuaEntry.Player.serverId` stayed put. So the
press has to make the call itself, straight after the send — and with it the switch
works first time.

The reload is **in-process**: the game keeps its pid, so the Lua daemon lives through
it and nothing has to be reattached. It does reset the Lua VM, though — a global
parked in `DataCenter` before the press (and any hook installed for a probe) is gone
on the other side, so nothing may be carried across the relog.

Timing, measured: `LuaEntry.Player.serverId` reads the new server about five seconds
after the press (briefly `-1` or `0` mid-reload), and the base is drawn a few seconds
after that.

### 4.4 How it is wired up

The ability is `actions/switch_account.md`, and playing it is all the panel's
«Сменить» button does. The Lua is `lua_actions.account_switch_press()` behind the
`switch_account` button; which character is parked in `DataCenter.__lw_switch_account`
first, because `TAP` carries no arguments.

The recipe gates the press on the two ways it would be a silent no-op, each with its
own refusal: `account_switch_target()` reads `0` when this account has no character on
that server and `-1` when that character is the one already in play. It also asks for
the list first if the session never has (`rolesList` is empty until something sends
`account.login.new`), and afterwards polls `LuaEntry.Player.serverId` until the client
comes back on the new server and then waits for its base — a switch that stalls
mid-relog is a failure, not a false "done".

Proven live on 2026-08-02: 935 → 509 and back, twice, both directions starting from a
session that had never asked for the character list.

## 5. Capture notes (worth keeping)

Three capture runs came back empty before one worked. What was wrong:

* **The port.** The client had moved from `:17935` to `:10012` and back across
  restarts. Read it live (`netstat -ano` for the game's pid) — a capture on a stale
  port is silent, not wrong-looking.
* **One interface is half a conversation.** On the default interface scapy
  delivered only the client's own packets; the server's side arrived on another.
  Sniffing every interface (as `map_capture` does) got both directions.
* **Connections, not directions.** The client holds several sockets to the game
  port at once (one live, the rest in `CLOSE_WAIT`). Their sequence spaces are
  unrelated, so merging them into one buffer decodes to nothing at all.
* **`iter_frames` yields `(envelope, start, end)`**, not the envelope alone.
* `wrpcap` refuses the mix of link types npcap hands back here (`KeyError: Raw`) —
  keep the reassembled bytes instead of a pcap.

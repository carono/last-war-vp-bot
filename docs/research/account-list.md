# The account list — a cache of logins, not of characters

Sources:

* live reads of the running Lua VM on a client logged into server 935 — the full field
  dump of every `AccountInfo`, the method table of `AccountListManager`, `string.dump`
  of the three methods that write it, and the persisted string it is parsed from;
* the panel's «Аккаунты» tab and `tools/account_switch.py`, which read the same table.

No traffic was needed: nothing here crosses the wire, it is all client-side cache.

## 1. What the tab was showing

Six rows on an account that has two characters:

| server | gameUid            | HQ | nickname          | urlEnv      |
|--------|--------------------|----|-------------------|-------------|
| 935    | 1522777203000972   | 35 | Carono            | `Online`    |
| 972    | 1522777203000972   | 35 | Carono            | `Online`    |
| 1012   | 1522777203000972   | 35 | Carono            | `Online`    |
| 8118   | 1522777203000972   | 35 | Carono            | `Online`    |
| 509    | 2146058428000509   | 21 | Игрок 3464d509    | `Online`    |
| 2105   | 1092741133002105   | 0  | Игрок 1aada2105   | `Online: 0` |

Four of them are one character. The `gameUid` is the character; `1522777203000972` is on
935 today and has been on 972 (where it was made — the uid ends in its home server),
1012 and 8118 before that. The sixth is a character that was created and never played:
HQ level 0, the auto-assigned placeholder nickname, and an environment string the client
never finished writing (`Online: 0`).

## 2. Why the extra rows are there

```lua
DataCenter.AccountListManager:GetAccountInfos()   -- m_accountInfos
```

is a cache of **logins**. `AddAcountInfo` keys an entry through
`GetAcountInfoIndexByUidAndURLEnv`, whose constants are `serverid`, `gameUid`, `urlEnv` —
so a login to a server the character has never been on before is a *new* row, not an
update of the old one. Every cross-server event that moves the client (8118 is one of
those event servers), every server transfer, every merge leaves its row behind for good.
Nothing ever removes one but `DeleteAcountInfo`, which the client does not call by itself.

Underneath, `GetAccountInfoString()` is an append-only log of `#`-separated login
records — 50 of them here, spanning 19 different server ids, several in an older field
layout that `ParseAccountInfos` drops. `MergeAccountInfoAndSave` folds what parses into
`m_accountInfos` in the order it was written, so **the position in the list is how recent
the login is**, and the last row for a `gameUid` is the server that character is on now.
On this client the last record of the whole log is the current one, server 935.

## 3. The list the server knows

`DataCenter.AccountManager.rolesList` / `GetRolesList()` is the authoritative one — the
characters the account actually has, as the server reports them. It is filled while the
account screen of the **login flow** is up, and it is empty (`count=0`) once you are in
the game. So it cannot be used to clean the list from inside a session, and the cleaning
has to come from the cache itself.

## 4. The rule

`account_switch.playable_accounts()` — two cuts, both of them are needed:

1. **One row per `gameUid`.** Of the rows sharing one, keep the one in play, else the
   highest HQ level, else the highest position in the cache (the freshest login). That
   drops the old-server and event-server rows and keeps the character on the server it
   is on now.
2. **Drop HQ level 0**, unless it is the character being played right now. A character
   that never reached level 1 was abandoned at creation or has since been deleted;
   there is nothing to switch to.

On the live client that leaves exactly the two characters the account has: 935 (HQ 35)
and 509 (HQ 21). `tools/account_switch.py --all` still prints the cache whole, marking
what the rule hides, which is how the table in §1 was taken.

Note that the level-0 cut is what removes a *deleted* character, and it does it by
inference — the client is never told a character is gone, its row just never carried an
HQ level. A character that was played to level 5 and then deleted would still be listed,
and would fail on the switch instead. None exists on this account to check against.

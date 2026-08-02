# 0. The installer (`install.bat`)

One file takes a bare Windows 10/11 box to a working control panel: it installs
Git and Python 3.12, clones this repository, installs the Python dependencies
and puts shortcuts on the Desktop. Nothing has to be there beforehand — no
Python, no Git, no terminal skills.

The manual route is still written down ([Python](01-python.md), [the
bot](03-bot.md)); this page is what the installer does in its place.

## Running it

1. Download `install.bat` from the repository root
   (`https://raw.githubusercontent.com/carono/last-war-vp-bot/v2/install.bat`),
   or use the copy in a checkout you already have.
2. Double-click it. It asks for administrator rights once — Windows shows the
   UAC prompt — and does the rest by itself.
3. When it finishes, **Last War - panel** is on the Desktop.

It is safe to run again. Whatever is already installed is detected and kept, an
existing checkout is fast-forwarded rather than re-cloned, and the dependencies
are refreshed. That makes it the repair tool too: a half-finished install is
fixed by running it a second time.

```
install.bat [options]

  --dir  PATH      where the repository goes  (default C:\LastWarBot; when run
                   from inside a checkout, that checkout)
  --branch NAME    branch to check out        (default v2)
  --repo URL       repository to clone from
  --pydir PATH     where Python 3.12 goes     (default C:\Python312)
  --profile NAME   an extra Desktop shortcut opening the panel on that panel
                   profile; may be repeated
  --no-npcap       do not offer to install npcap
  --no-shortcuts   do not touch the Desktop
  --yes            never ask anything
  --help           print the options and exit
```

Two accounts, two shortcuts:

```
install.bat --profile main --profile second
```

## What it puts where

| What | Where | Why there |
|---|---|---|
| Python 3.12.10 | `C:\Python312` (all users) | the panel's `Settings → General → Python` defaults to exactly this path, so the sniffers and every other child process it spawns find their interpreter with nothing configured |
| Git for Windows | its own default (`C:\Program Files\Git`) | on `PATH`, so `update.bat` and the tools can call it |
| the source | `C:\LastWarBot` | short, ASCII, no spaces — the game tooling passes these paths around a lot |
| dependencies | into that Python, not a venv | the panel and its children must share one interpreter; a venv would leave the children without the packages |
| shortcuts | the Desktop | `Last War - panel` and `Last War - update` |

The tree is created by an administrator, so the installer grants the person it
is installing for write access to it — the panel keeps its profiles, its logs
and every capture inside the repository directory.

### Why the shortcuts run as administrator

Both carry the "run as administrator" flag. The panel reads the game out of
another process' memory and npcap wants the rights too, and refreshing the
packages writes into an all-users Python. If you would rather it did not, untick
**Run as administrator** in the shortcut's Properties → Advanced.

The panel shortcut starts its console window minimised. That window is not
decoration: if the panel refuses to open, the error is in it.

## npcap

The passive traffic capture (secret tasks, ghost recon, rally, chat) reads the
wire through the npcap driver. Its free edition has no unattended installer, so
the installer offers to download it and opens its window for you to click
through — keep **Install Npcap in WinPcap API-compatible Mode** ticked. Answer
no and everything else still works; only the sniffers stay silent until npcap is
installed from [npcap.com](https://npcap.com).

`requirements-tools.txt` holds the Python side of that (scapy, zstandard) and is
installed along with `requirements.txt`.

## Afterwards

* **`panel.bat`** — opens the panel. Arguments pass straight through, so
  `panel.bat --profile second` opens it on another profile.
* **`update.bat`** — pulls the latest sources and refreshes the dependencies.
  The pull is fast-forward only: local commits or edits stop it with a message
  instead of being thrown away. The panel follows `origin` by itself as well
  ([03-bot.md](03-bot.md#keeping-it-up-to-date)); this is the route that also
  refreshes the Python packages, and the one that works when the panel will not
  start.

Where the game client lives is set in the panel itself, on its Settings page
under Game.

## When it goes wrong

* **The UAC prompt never appears** — right-click `install.bat` and pick *Run as
  administrator*.
* **"Checksum mismatch"** — the downloaded installer is not the file the vendor
  published. Nothing is run. Check the connection (a captive portal or a
  proxy substituting the download does this) and try again.
* **"Clone failed"** — if the repository is private, sign in when Git asks. Or
  clone it by hand and re-run with `--dir` pointing at the clone.
* **"Could not fast-forward"** — the checkout has local commits or edits.
  Commit, stash or discard them; the installer never discards them for you.
* **Python did not install** — run the downloaded installer by hand; the
  installer prints its path (`%TEMP%\lw-install\python-installer.exe`).
* **A Python other than 3.12** — only 3.12 is accepted: part of the CV stack
  still ships no 3.13 wheels. An existing 3.12 anywhere on the machine is
  reused rather than a second one installed; point at a specific one with the
  `LW_PYTHON` environment variable. Nothing has to be told about it afterwards:
  when `C:\Python312` is not there, the panel launches its children with the
  interpreter it is running under itself.

## Bumping the pinned versions

Python, Git and npcap are pinned by URL at the top of `install.bat`, and the
first two are checked against a SHA-256 recorded next to them. Bumping one means
changing the URL **and** its checksum in the same edit — take the checksum from
the vendor (`certutil -hashfile <file> SHA256`, or the digest GitHub reports for
a release asset). A pinned URL with a stale checksum stops the install dead,
which is the intended failure.

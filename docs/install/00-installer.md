# 0. The installer (`install.bat`)

Unpack the archive wherever you like and run `install.bat` from inside the
folder that came out of it. That folder **is** the installation: nothing is
cloned, copied or downloaded into a directory of its own. What the installer
does is put the surroundings in place — Python 3.12, Git, the Python
dependencies — and drop shortcuts to the panel in that folder onto the Desktop.

Nothing has to be there beforehand: no Python, no Git, no terminal skills.

The manual route is still written down ([Python](01-python.md), [the
bot](03-bot.md)); this page is what the installer does in its place.

## Running it

1. Download the archive —
   `https://github.com/carono/last-war-vp-bot/archive/refs/heads/v2.zip`.
2. Right-click it and pick **Extract All**. Choose a folder you can write to and
   intend to keep — Documents, for instance. Do **not** run `install.bat`
   straight out of the .zip window: that copy lives in a temporary folder
   Windows deletes afterwards, and the installer refuses to run from there.
3. Open the unpacked folder and double-click `install.bat`. It asks for
   administrator rights once — Windows shows the UAC prompt — and does the rest
   by itself. Windows may also warn that the file came from the internet:
   **More info → Run anyway**.
4. When it finishes, **Last War — панель** is on the Desktop.

It is safe to run again. Whatever is already installed is detected and kept and
the dependencies are refreshed. That makes it the repair tool too: a
half-finished install is fixed by running it a second time.

**Moved the folder? Run it again.** The Desktop shortcuts and the editable
package install both point at the old place until it does.

```
install.bat [ключи]

  --pydir ПУТЬ        куда ставить Python 3.12 [по умолчанию C:\Python312]
  --profile ИМЯ       ещё один ярлык: панель на этом профиле.
                      Ключ можно повторять — по ярлыку на аккаунт
  --daemon-shortcut   ярлык демона; обычно не нужен, панель поднимает его сама
  --no-npcap          не предлагать установку npcap
  --no-shortcuts      не трогать рабочий стол
  --yes               ничего не спрашивать
  --help              показать это и выйти
```

There is no option for where the bot goes — it is already there, in the folder
`install.bat` sits in.

Two accounts, two shortcuts:

```
install.bat --profile main --profile second
```

## What it puts where

| What | Where | Why there |
|---|---|---|
| the bot | the folder you unpacked into | it is already there; the installer never moves or copies it, and every path it works by is relative to `install.bat` |
| Python 3.12.10 | `C:\Python312` (all users) | the panel's `Settings → General → Python` defaults to exactly this path, so the sniffers and every other child process it spawns find their interpreter with nothing configured |
| Git for Windows | its own default (`C:\Program Files\Git`) | on `PATH`, so `update.bat` and the tools can call it |
| dependencies | into that Python, not a venv | the panel and its children must share one interpreter; a venv would leave the children without the packages |
| shortcuts | the Desktop | `Last War — панель`, `Last War — обновление`, and `Last War — демон` with `--daemon-shortcut` |

The bot's own files — its profiles, its logs, every capture — are written inside
that same folder. Back it up by copying the folder; move it by moving the folder
and running `install.bat` again.

Git is set up but never required: the sources arrived in the archive, so nothing
in the install needs it. It is there for `update.bat` and for the panel's own
«Обновление» block, both of which work only when the folder is a git checkout
rather than an unpacked archive. If it cannot be installed the run carries on
with a warning.

### Why the shortcuts run as administrator

Both carry the "run as administrator" flag. The panel reads the game out of
another process' memory and npcap wants the rights too, and refreshing the
packages writes into an all-users Python. If you would rather it did not, untick
**Run as administrator** in the shortcut's Properties → Advanced.

The panel shortcut starts its console window minimised. That window is not
decoration: if the panel refuses to open, the error is in it.

### Where it refuses to run

Three checks happen before anything is installed, and before the UAC prompt:

* **the folder is not the bot's** — `panel\`, `requirements.txt` and
  `pyproject.toml` have to be beside `install.bat`. Copying `install.bat` out on
  its own and running it does nothing but say so.
* **the folder is a temporary one** (`…\AppData\Local\Temp\…`, or a `Temp1_…`
  name) — that is `install.bat` started from inside the .zip preview rather than
  from an unpacked folder. Everything would appear to work and then be deleted.
* **the path has a `!` or a `%` in it** — batch files cannot be run from such a
  path reliably. Rename the folder or unpack somewhere else.

A network path (`\\server\share\…`) is a warning rather than a refusal, but the
panel will not start from one: `panel.bat`, `update.bat` and `daemon.bat` all
`cd` into their own folder, which a UNC path refuses. Unpack onto a local disk.

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
* **`update.bat`** — refreshes the dependencies, and pulls the latest sources
  when the folder is a git checkout. From an unpacked archive there is no
  history to pull, and it says so instead of failing at git: update the sources
  by downloading a fresh archive and unpacking it over the folder, replacing the
  files. Your profiles, logs and captures sit in folders of their own and
  survive that.
* **`daemon.bat`** — starts the Lua daemon in a window of its own. The panel
  starts its own, so this is only for driving the game without the panel.

Where the game client lives is set in the panel itself, on its Settings page
under Game.

## When it goes wrong

* **The UAC prompt never appears** — right-click `install.bat` and pick *Run as
  administrator*.
* **Windows says it protected your PC** — SmartScreen, because the archive came
  from the internet. *More info* → *Run anyway*.
* **"Это не папка бота"** — `install.bat` was moved out of the unpacked folder,
  or the archive was unpacked only partly. Unpack it again and run the copy that
  came with it.
* **"Запуск идёт из временной папки"** — the .zip was never unpacked. Right-click
  it, *Extract All*, and run `install.bat` from the folder that appears.
* **"Checksum mismatch"** — the downloaded installer is not the file the vendor
  published. Nothing is run. Check the connection (a captive portal or a
  proxy substituting the download does this) and try again.
* **Python did not install** — run the downloaded installer by hand; the
  installer prints its path (`%TEMP%\lw-install\python-installer.exe`).
* **A Python other than 3.12** — only 3.12 is accepted: part of the CV stack
  still ships no 3.13 wheels. An existing 3.12 anywhere on the machine is
  reused rather than a second one installed; point at a specific one with the
  `LW_PYTHON` environment variable. Nothing has to be told about it afterwards:
  when `C:\Python312` is not there, the panel launches its children with the
  interpreter it is running under itself.
* **The panel starts but cannot save its profile** — the folder is somewhere the
  person running the panel may not write to (`C:\Program Files`, another
  account's Documents). Move the folder somewhere of your own and run
  `install.bat` again.

## Bumping the pinned versions

Python, Git and npcap are pinned by URL at the top of `install.bat`, and the
first two are checked against a SHA-256 recorded next to them. Bumping one means
changing the URL **and** its checksum in the same edit — take the checksum from
the vendor (`certutil -hashfile <file> SHA256`, or the digest GitHub reports for
a release asset). A pinned URL with a stale checksum stops the install dead,
which is the intended failure.

# Territorial.io Friend-Bot — Windows app

A desktop app that opens the **real** [territorial.io](https://territorial.io/),
plays on its own with a smart economy, and never attacks your friend.

It is a single window (no website). You type your name, optionally your friend's
name, pick a game mode and press **Start** — the bot enters the game, presses
**Ready** and plays. Watch it live and stop it any time.

## Features

- **Smart economy** — never dumps 100% of its balance. It sets the bottom power
  bar to a calculated % (more early to grab cheap land, less when large), attacks
  only a few open fronts so troops stay for defence, and **saves** (banking
  balance + interest) when there is nothing good to take.
- **Naval expansion** — when boxed in by water it crosses the sea with boats (B)
  to reach new land, and zooms out to see the whole map.
- **Friend by name** — type your friend's in-game name; the bot finds their label
  on the map and treats that territory as un-attackable. (Needs the Tesseract OCR
  engine; if it isn't installed, use the **colour** picker instead — always works.)
- **Online modes** — Battle Royale, Team, 1v1, Zombie. These play against **real
  players**, so they are locked behind a consent checkbox ("I play online at my
  own responsibility"). Local/offline Custom Scenario modes are always available.
- **Live status** — territory size, land fronts, naval crossings, current
  behaviour (expand / naval / save), attack power %, and time left.

## Run from source

```bash
pip install -r requirements.txt
python -m playwright install chromium
python app.py
```

A native window opens. If your machine has no webview runtime, it falls back to
opening the panel in your default browser.

### Check the live site matches the bot (`diagnose.py`)

Before trusting a run, confirm the bot's assumptions still hold against the
**real** site. This opens territorial.io in a visible window and reports whether
the name input, the menu buttons and the game canvas are where the bot expects:

```bash
python diagnose.py            # visible window + report + screenshots in ./diag/
python diagnose.py --headless # report only
```

If it prints `MISMATCH` or lists menu texts "NOT found", send that report and the
`diag/` screenshots and the selectors can be calibrated to the live UI.

### Run the offline tests

The bot's game-driving needs a real browser and the live site, but everything
else is covered by an offline test suite (control API, config/consent rules, and
the in-page vision JS syntax):

```bash
pip install pytest httpx
python tests/test_app.py
```

> The bot launches its own Chromium. To instead drive an already-open Chrome,
> set `TIO_CDP=http://localhost:<port>` (Chrome started with
> `--remote-debugging-port=<port>`).

## Build the Windows `.exe`

Pushing to GitHub runs `.github/workflows/build-windows.yml`, which builds a
self-contained app (Chromium bundled) with PyInstaller and uploads
`TerritorialFriendBot-windows.zip` as a workflow **artifact**. Download it from
the run's Artifacts, unzip, and run `TerritorialFriendBot.exe`.

To build locally on Windows:

```powershell
pip install -r requirements.txt pyinstaller
$env:PLAYWRIGHT_BROWSERS_PATH="0"; python -m playwright install chromium
pyinstaller --noconfirm --windowed --name TerritorialFriendBot --collect-all playwright --add-data "static;static" app.py
```

## Responsible use

Online modes involve real players, and running a bot may violate the game's
rules. They are disabled until you tick the consent box. Use at your own risk.

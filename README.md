# MintMail

**A modern mail client for Linux (Linux Mint, Ubuntu, Debian) and macOS, built with Qt (PySide6) — with an AI that reads, sorts, files, summarizes, writes and acts with you, always with your approval.**

> 🇫🇷 Version française : [README.fr.md](README.fr.md)

Multi-account IMAP/SMTP, smart inbox, AI summaries and folder sorting, smart replies, Google Calendar / CalDAV, offline mode, encrypted sync between your machines. No cloud service imposed: your mail, keys and settings stay with you.

## Download

- **Linux (`.deb`)**: **Releases** tab → `mintmail_X.Y.Z_all.deb`, then:
  ```
  sudo apt install ./mintmail_X.Y.Z_all.deb
  ```
  Dependencies (Python 3 and the Qt / PySide6 interface, installed in the package's private environment) come automatically. To update, install the new `.deb` (or use *Settings → Updates*); your settings and cache are kept.
- **macOS (`.dmg`)**: `MintMail-X.Y.Z-macos.dmg`, attached to each Release (or build it yourself on a Mac: `sh packaging/build-macos.sh`). Drag MintMail to *Applications*. The app is not signed by Apple yet: right-click → **Open** the first time. Updates are manual on macOS (download the new `.dmg`, replace the app). To try MintMail without installing anything: `packaging/mac-essai.command`.
- **Source code**: **Code → Download ZIP**, or `git clone`.
- **Build the package yourself**: `make deb` (needs `dpkg-deb` and `python3`) → `dist/mintmail_<version>_all.deb`.

Requirements: Linux Mint 21+ / Ubuntu 22.04+ / Debian 12+ (Python ≥ 3.9) or macOS. An IMAP/SMTP mail account (Gmail, Outlook, OVH, Infomaniak…). Windows (`.msi`) is planned.

## Features

- **Mail**: multiple accounts, all IMAP folders (tree, create / rename / move), conversations, instant search (plus server-side search), attachments (preview, save all, drag and drop), HTML signatures, sending identities (aliases), templates, undoable or scheduled sending (even with the window closed), real-time reception (IMAP IDLE), offline mode (queued actions replayed, sending never lost).
- **AI** (off by default; your choice of provider: NVIDIA, **local Ollama**, or any OpenAI-compatible service): summary of each message, priority sorting, phishing alert, **folder sorting with your approval**, an assistant that can act (confirmed action plan), natural-language search, writing help, optional prepared draft replies, learning of your filing habits.
- **Productivity**: “Today” page (`T` key), tasks with due dates read from the text, free time-slot suggestions, invitations (accept / decline in one click), contacts (vCard), **Google Calendar** (no duplicates, conflict alerts) or CalDAV.
- **Control**: spam / blocking by address or domain, automatic rules, one-click unsubscribe (RFC 8058), remote images blocked, passwordless **OAuth** sign-in for Google / Microsoft.
- **Sync between your machines**, no server: accounts, signatures, rules, contacts, tasks… encrypted and authenticated.
- **Interface**: 3 styles (Aurora, Paper, Terminal), swipe gestures, command palette (`Ctrl+K`), keyboard shortcuts, full context menu, **complete built-in help** (`F1`, instant search).

## Getting started

1. Launch **MintMail** from the menu (or `mintmail`). With no account, a demo mode is shown.
2. Settings (`Ctrl+,`) → Accounts → add your account (app password for Gmail / Yahoo / iCloud, or OAuth sign-in).
3. `F1` opens the full help. The text is also here: [docs/HELP.md](docs/HELP.md) (English) and [docs/AIDE.md](docs/AIDE.md) (French).

**Google / Microsoft sign-in (OAuth)**: MintMail cannot ship a shared client ID; a built-in wizard guides you through creating **your own** (once, 4 steps). See the help, section “Google / Microsoft sign-in”. Credentials can be pre-installed for a fleet of machines: `data/oauth-clients.json.example`.

## Screenshots

Screenshots will be added to [`docs/screenshots/`](docs/screenshots/README.md) (list of the 12 screens and a capture script are provided). *No image is included yet.*

## Languages

The interface is available in **French, English, Dutch, German and Spanish**: Settings → Appearance → “Interface language” (Automatic = system language; restart required). The help (F1) and the command line are in French and English (English for the other languages). **Dutch, German and Spanish are AI translations not reviewed by native speakers** — please report defects. More languages can be pre-translated with `tools/translate_catalog.py`. Details and limits: [docs/I18N.md](docs/I18N.md).

## Updates

Settings → **Updates**: MintMail looks for a new version on GitHub (every hour while running and at each launch, anonymous request, can be turned off). On Linux it installs it in one click after checking a **signature**, with your administrator password. On macOS it announces the new version and you download the `.dmg`. How it works and its security: [docs/UPDATES.md](docs/UPDATES.md). Publishing a version: [docs/RELEASING.md](docs/RELEASING.md) (`tools/release.sh`).

## Security

A full security audit (flaws found and fixed, remaining risks, method and limits) is in [SECURITY.md](SECURITY.md), along with how to report a vulnerability.

## Development

```
make test    # all tests (engine and UI logic; the Qt window itself is tested only if PySide6 is installed)
make deb     # builds dist/mintmail_<version>_all.deb
make docs    # regenerates docs/AIDE.md and docs/HELP.md from the built-in help
tools/bump-version.sh X.Y.Z   # new version (VERSION + CHANGELOG)
tools/release.sh              # publishes a signed version (see docs/RELEASING.md)
```

- `mintmail/`: the application (`qt/` Qt interface — `qt/window.py` main window, `qt/compose_window.py` composer, `qt/settings_window.py` settings —, `backend.py` IMAP/SMTP, `store.py` SQLite cache + settings, `ai_*.py` AI, `syncdata.py` + `p2p.py` sync, `oauth.py` / `gcal.py` / `caldav.py`, `help_content.py` help…).
- `tests/`: automated tests; the Qt interface logic is separated from rendering and tested without a screen — see “Project status”.
- `packaging/`: `build-deb.sh` (Linux package), `build-macos.sh` (macOS `.dmg`), `mac-essai.command` (try on a Mac); `.github/workflows/`: tests (CI), automatic `.deb` and `.dmg` publication on each `vX.Y.Z` tag.
- Version history: [CHANGELOG.md](CHANGELOG.md); design notes: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). *Commits before v1.10.0 are snapshots reconstructed from the successive deliveries.*

## Project status

The tests cover the logic (storage, simulated IMAP/SMTP, simulated AI, sync, OAuth, calendar, help…), but the **real Qt rendering is not verified automatically**: please report any visual defect through *Issues*. Google Calendar, OAuth and CalDAV were tested against simulated servers, not the real services. The sync encryption is home-made and **has not been independently audited**: use it only on trusted networks and machines. The macOS build is new and unsigned.

## License

Free software under the **MIT license** — see [LICENSE](LICENSE): you may use, modify and redistribute it, including commercially, provided the copyright notice is kept. No warranty.

Developed by [SAEC](https://saec.me) · contact: contact@saec.me

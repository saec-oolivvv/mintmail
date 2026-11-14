# Architecture and history of the Qt port

MintMail has a **single interface: Qt (PySide6)**, identical on Linux and macOS (Windows planned). The former GTK interface was removed in **1.35.0** (the `--gtk` option is ignored).

## Engine / interface split

- **Engine** (pure Python modules, tested without a screen): `backend.py` (IMAP/SMTP), `store.py` (SQLite cache, settings, password storage), `ai_*.py`, `syncdata.py` + `p2p.py`, `oauth.py`, `gcal.py`, `caldav.py`, `htmlsafe.py`, `themes.py`, `help_content.py`, `update_text.py`, `updater.py`, and the interface-logic modules under `mintmail/qt/` that do not import Qt (`viewmodel.py`, `folderops.py`, `maintenance.py`, …).
- **Interface** (PySide6, files named `*window.py` or `ui_*.py` in `mintmail/qt/`): the windows, delegates and widgets.
- Guard rail: `tests/test_core_portable.py` fails if an engine module imports GTK or Qt, and if a new module is not classified (engine or interface). The Qt window itself is tested only where PySide6 is installed (`tests/test_qt_window.py`).

## Port history

1.17–1.20 message list, reader and composing · 1.21–1.23 settings, filters, AI assistant · 1.24–1.27 reader AI card, help and updates, folder tree and gestures, context menu and palette · 1.29–1.30 multi-selection, saved searches · 1.31 Qt becomes the default interface · 1.32–1.34 start-up safety checks, signatures, contacts, templates, Today page, calendar, attachments, sync, AI everywhere · **1.35.0 GTK removed**, last missing functions ported (folder management, server-side search, pin push, error log, full screen, copy address, interface language, Today at launch, full composer formatting).

Files removed in 1.35.0: `app.py`, `window.py`, `listing.py`, `folders.py`, `widgets.py`, `reader.py`, `compose.py`, `settings*.py`, `help_view.py`, `updates_ui.py`, `extras.py`, `style.py`, the GTK `assistant.py` panel, `ai_features.py`, `tests/gtkstub.py`. Colors and styles (Aurora, Paper, Terminal) live in `themes.py`. The tests that drove the GTK window were removed; their Qt equivalents are in `tests/test_qt_viewmodel.py`, `tests/test_organizer_ai.py` and `tests/test_qt_window.py`.

## macOS

`packaging/build-macos.sh` (run on a Mac) builds `MintMail-<version>-macos.dmg` (PyInstaller + PySide6, only the Qt modules that are used); `packaging/mac-essai.command` runs MintMail on a Mac without installing anything permanently. The `.github/workflows/macos.yml` workflow builds the `.dmg` on a GitHub-hosted Mac and attaches it to each Release. Not signed by Apple: right-click → Open the first time. Passwords are kept in the macOS Keychain through Apple's `security` tool (no authorization prompt). Updates: Linux installs the signed `.deb`; on a Mac MintMail downloads the `.dmg` for the machine's architecture (arm64 or x86_64), verifies its `.sha256` and opens it (drag to Applications).
To do: signing + notarization (Apple Developer account), Windows (`.msi`).

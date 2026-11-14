# Automatic updates

MintMail updates itself from the **Releases** of its GitHub repository (Linux `.deb`). User summary: Settings → **Updates** (automatic check at every launch and then every hour, one-click installation with your administrator password). This document explains how it works and its **security**, then how to set the system up. **macOS**: “Install” downloads the `.dmg` of the new version for your processor (`MintMail-X.Y.Z-macos-arm64.dmg` or `-x86_64.dmg`, attached to the Release by GitHub Actions), checks its SHA-256 against the `.dmg.sha256` published with it, then opens it in the Finder: you drag MintMail into Applications and relaunch. There is **no SAEC signature** on this path (the `.dmg` is built by GitHub, which never holds the private key): protection is HTTPS to github.com plus the checksum, so a compromised GitHub account could replace both. Apple signing and notarization are planned.

## What the user sees

- **At launch**, if a newer version is known, a **banner** slides in under the title bar: “MintMail X is available”, the current version, the first news item of the Release, and three actions — **Install now**, **Release notes** (the Release page), **Later** (postpones 24 h for that version; an even newer version reappears at once). ✕ hides it until the next launch.
- A **“⬆ Update X” badge** stays at the bottom of the sidebar as long as the update is not installed, even if the banner was postponed; a click opens Settings → Updates.
- **During installation** the banner shows a progress bar (download), then “Checking the signature…”, then “Installing… (your administrator password is requested)”. Then: “MintMail X is installed” with **Restart now** (restarts the window through a fixed command). On failure: the exact reason and **Retry**.
- The detected update is **remembered** (local settings, never synced): it is shown immediately at the next launch, without waiting for the network. This memory is **revalidated on every read** (versions, GitHub hosts): a modified settings file cannot make a fake update pointing elsewhere appear, and the signature is checked anyway before any installation.
- **Already installed**: if the update was installed in the meantime (or from another window), the banner does not offer it a second time: it shows “installed” with **Restart now**.
- **Desktop notification** (once per version) if the window is not in the foreground; can be turned off with the notifications.
- **Diagnostics**: `mintmail --check-update` prints the version, the repository, whether the verification key is present, the result of the check and the exact cause of an error (no interface, nothing installed). Exit code: 0 up to date, 10 update available, 1 error. The last result is also written to the log and recalled in Settings → Updates.
- The check runs 8 seconds after **every** launch (even if a check was made this morning: a version published in the meantime is announced at once), then every hour while MintMail runs. It can be turned off. Requests are conditional (ETag: a very light “304” reply).

## Security principle

Installing a package with administrator rights allows anything on the machine, so the system is designed so that **GitHub is never taken at its word**.

| Element | Role |
|---|---|
| SAEC **private** key | Signs every `.deb` (RSA 3072 / SHA-256). Stays with you, protected by a passphrase, never in the repository. |
| **Public** key (`data/update-pubkey.pem`) | Built into the package: `/usr/share/mintmail/update-pubkey.pem`, owned by root. No setting, no Release and no hacked GitHub account can replace it. |
| GitHub (Release) | Mere **transport**: `mintmail_X.Y.Z_all.deb`, `mintmail_X.Y.Z_all.deb.sig`, `SHA256SUMS`. |
| `apply_update.py` (root, via pkexec) | Copies the package into a private folder (without following symbolic links), re-checks the signature **on the copy**, checks it really is `mintmail` (type `all`) and that the version is **strictly newer**, then installs with apt. |
| polkit | `auth_admin`: password asked at every installation. Never a silent installation. |

Refused: missing or invalid signature, signature from another key, package modified by a single byte, package other than MintMail, same or older version (no downgrade), corrupted download (checksum) or too large, host other than GitHub, redirect to a foreign host, draft or prerelease Release.
**Without an installed public key, MintMail only announces new versions** (no automatic installation).

Privacy: a single anonymous GET request to `api.github.com` (agent “MintMail/<version>”), at launch then hourly, can be turned off.

## Setup (once)

1. `tools/make-signing-key.sh`: creates the key pair (passphrase asked); copies the public key to `data/update-pubkey.pem`; **back up the private key offline**.
2. `git add data/update-pubkey.pem && git commit -m "Update signing public key"`.
3. `tools/release.sh`: tests, builds, signs, tags and publishes the Release.
4. Install this signed package **once by hand** (`sudo apt install ./dist/mintmail_X.Y.Z_all.deb`): it brings the public key to the machines. From then on, later versions install from the application. Machines without this package only receive announcements.

## Limits and risks (to know)

- **Stolen private key** = whoever holds it can have any program installed on all machines. Passphrase, offline backup, no CI that holds it.
- **Lost or replaced key**: no automatic rotation mechanism (deliberately: it would be a backdoor). A package containing the new public key must be reinstalled by hand.
- **Freeze attack**: someone controlling the network or GitHub can prevent learning that a new version exists (not forge it). This is not detected.
- **Downgrade**: refused below the installed version, but an authentic signed intermediate version older than the latest can be replayed as long as it is newer than the installed one.
- The check relies on the system's `openssl`, `dpkg` and `apt` (preferably up to date); the repository to query is a per-machine setting (Settings → Updates), **not synchronized** between machines.
- Not tested against a real GitHub nor with a real polkit window: tested with a fake GitHub server, real openssl signatures and a real `dpkg` (see `SECURITY.md`).

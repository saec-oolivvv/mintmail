# Publishing a version

The repository is **versioned**: a single number `X.Y.Z` (`VERSION` file, copied to `mintmail/VERSION`), a `CHANGELOG.md` journal, a git tag `vX.Y.Z` and a **signed** GitHub Release. MintMail compares its number with that of the latest Release.

## Numbering rules (SemVer)

- `X` (major): a breaking change (data formats, machine-to-machine sync protocol).
- `Y` (minor): a new feature. `Z` (patch): a fix without new features (security fixes included).
- All synced machines must share the same protocol version (`PROTOCOL` in `mintmail/p2p.py`): change it only if the exchange changes.

> **Signing key**: backup (`tools/backup-signing-key.sh`), loss, theft and rotation without reinstallation: [KEY-RECOVERY.md](KEY-RECOVERY.md).

## Updating the repository from a patch (`tools/mintmail-maj.sh`)

When a new version is delivered as a `mintmail-X.Y.Z….patch` file, a single script does the whole procedure:

```
sh tools/mintmail-maj.sh --dry-run     # checks everything without changing anything
sh tools/mintmail-maj.sh               # finds the right patch (Downloads…), applies it, changes the version, completes the journal, commits, publishes
```

- It reads the patch header (`# mintmail-patch`, `# version:`, `# base:` = versions it applies to, `# note:` = changelog lines) and picks **the right file from your current version**, not from its name.
- It refuses a dirty repository, a patch meant for another version, a GitHub ahead of your repository; it recognizes an already applied patch.
- If a step fails **before the commit**, everything is cancelled (the repository returns exactly to its previous state). If publishing fails, your code stays committed: fix the cause, then `tools/release.sh`.
- A `.patch` forgotten in the repository is moved to Downloads (it never enters a commit). Options: `--no-release`, `--yes`, `--repo FOLDER`, `--version X.Y.Z --note "…"` (patch without header).

## Steps

```
tools/bump-version.sh 1.12.0     # VERSION, mintmail/VERSION, new section in CHANGELOG.md
# ... development, then complete the "1.12.0" section of CHANGELOG.md ...
git add -A && git commit -m "MintMail 1.12.0"
tools/release.sh                 # checks version, clean repo, tests, package, signature, tag v1.12.0, push, GitHub Release
```

`tools/release.sh --dry-run` does everything except the tag, the push and the Release. It refuses: inconsistent version, empty `CHANGELOG` or “(à compléter)”, unsaved repository, existing tag, missing or uncommitted public key, missing private key, failing tests, a package that does not contain the repository's public key, a signature that does not match.

First setup (key generation): see `docs/UPDATES.md`. Releases must always come from `tools/release.sh`: a Release without a signature is ignored by installed MintMail (they announce it but refuse to install it). The GitHub Actions workflow publishes nothing itself on Linux: it builds and tests without ever holding the private key. When a Release is published, the **macOS** workflow (`.github/workflows/macos.yml`) builds the unsigned `.dmg` on a GitHub-hosted Mac and attaches it to that Release.

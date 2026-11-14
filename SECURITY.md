# MintMail security

> 🇫🇷 Version française : [SECURITY.fr.md](SECURITY.fr.md)

## Reporting a vulnerability

Write to **contact@saec.me** with a description, steps to reproduce and the version (`mintmail --version`). Please do not publish the problem before a fix is available. Only the **latest version** is maintained.

## What MintMail protects (threat model)

| Threat | Protection |
|---|---|
| Booby-trapped e-mail (active HTML, tracking, technical phishing) | HTML rebuilt from an allow-list, content security policy (CSP), JavaScript disabled in the reader, remote images blocked, hardened web view, ephemeral context |
| Malicious link or attachment | Only http / https / mailto open; programs and scripts are never opened; risky files ask for confirmation |
| Other accounts on the machine | Folders `0700`, files `0600` (mail, attachments, settings, log) |
| Eavesdropping / intrusion on the local network | Encrypted + authenticated sync, limited to the local network, bounded timeouts and tables, weak codes refused |
| Hostile content sent to the AI | No action without approval, escaped rendering, drafts never sent (but a model can be fooled: see R4) |
| Mail servers | TLS with certificate verification, mandatory STARTTLS, OAuth with PKCE |
| Booby-trapped update (hacked GitHub, hostile network, modified package) | RSA / SHA-256 signature checked with a public key installed with MintMail; downgrades refused; installation by a minimal administrator program, password asked (see `docs/UPDATES.md`) |

## Audit report — version 1.10.2

**Method.** Manual code review (~15,000 lines of Python) against the real risks of a mail client: hostile HTML, links and files, secret storage, network (sync, unsubscribe, OAuth, calendar), command execution, SQL, temporary files, installation. Every flaw found was fixed **and** covered by a regression test (`tests/test_security.py`: 19 tests, including 3,000 random HTML documents and 11 pathological inputs, plus ~70 classic attack payloads).
**Limits of the audit**: no penetration test on real systems, no fuzzing of MIME / IMAP parsing, no audit of third-party libraries (Qt, QtWebEngine, Python), no independent cryptographic review, Qt interface not tested automatically on a real screen. **This audit does not prove the absence of flaws.** The audit was carried out on version 1.10.2 (GTK / WebKit interface); the reader has since moved to QtWebEngine and has not been re-audited (see R7).

### Flaws found and fixed

| # | Severity | Problem | Fix |
|---|---|---|---|
| S1 | High | The HTML sanitizer (regular expressions) could be bypassed (`<scr<script>ipt>`, `<img/src=x/onerror=…>`, obfuscated schemes); the **composer ran JavaScript**: replying to a booby-trapped message could run code and exfiltrate the text being written | **Allow-list** sanitizer rebuilt with a parser (`htmlsafe.py`), editor CSP (only its own script, by hash), ephemeral view, validated links |
| S2 | High | The reader displayed unsanitized HTML; forms, redirects, frames, `<base>`, `ping`: tracking and bypass of remote-image blocking | Sanitizing + CSP, navigation policy (everything refused except our own load), hardened web view settings |
| S3 | Medium | A clicked link opened any scheme (`file:`, `smb:`, application handlers) | http / https / mailto only, address stripped of control characters |
| S4 | Medium | Mail (`cache.db`), attachments, log created with default permissions (readable by other accounts); `config.json` set to 0600 *after* being written | Created directly as 0600 / 0700, fixed at startup (older installations included), state shown by `--diagnose` |
| S5 | Medium | **Hijacking through the current directory**: launched from a folder containing a `mintmail/` directory, the program ran that code (demonstrated) | Launchers in isolated mode (`python3 -I`) |
| S6 | Medium | Sync: connections accepted from any address, no overall timeout (slot hogging), unbounded announcement ports and tables, weak code accepted; the first timeout fix did not really cut a blocked read (found by test) | Local network / VPN / loopback only, effective overall timeout (`shutdown`), ports 1024-65535, 64 peers maximum, weak codes refused, new generator (~120 bits) |
| S7 | Medium | Unsubscribe: request to any https host (internal network, cloud metadata) and redirect following; multi-recipient / Cc / Bcc `mailto:` taken from the message header | Non-public addresses refused (redirects included), single valid mailto address |
| S8 | Medium | Attachments: direct opening of scripts, executables, `.desktop`, active SVG / HTML; extension tricks (double extension, trailing dot, bidirectional characters) | Programs and scripts: save only; risky files: confirmation; no inline SVG preview; images > 15 MB not previewed |
| S9 | Low | IMAP folder names: control characters not refused (command injection) | Refused |
| S10 | Low | Code-strength estimate: 2.9% of the codes produced by the old “Generate” button were refused (defect of my own fix, found by test) | Estimate adjusted, new generator always accepted; ~0.5% of old random codes trigger a (non-blocking) warning |

### Examined, no flaw found

SQL queries (parameterized; only constants are concatenated) · command execution (argument lists, never a shell) · deserialization (JSON only, no `pickle` or `eval`) · TLS (verification by default, mandatory STARTTLS, no plaintext fallback) · constant-time HMAC comparisons · sync nonces, session binding and sequence numbers (altered byte, wrong code, replay: rejected) · OAuth (PKCE, state, 127.0.0.1 loopback, HTTPS required) · attachment file names (no directory traversal) · temporary files (`mkstemp`, 0600).

### Remaining risks (not fixed)

- **R1 — “Home-made” sync cryptography** (HMAC-SHA256 in counter mode): no external audit, no forward secrecy; a weak code allows an offline attack on a captured exchange. *Recommendation: independent cryptographic review, or replacement by a proven protocol (TLS-PSK, Noise, PAKE). Use sync only on a trusted network, with the generated code.*
- **R2 — Total trust between paired machines**: a compromised peer can push accounts, server addresses, the AI key.
- **R3 — Secrets in clear in `config.json` (0600)** when no system keyring is available (`--diagnose` reports it). On macOS the Keychain is used through Apple's `security` tool.
- **R4 — Prompt injection**: an e-mail can fool a model (distorted summary, sorting, filing). Mitigated: mandatory approval, drafts never sent.
- **R5 — DNS rebinding** (unsubscribe): the address is checked before the request, not between resolution and connection.
- **R6 — System libraries** (Qt / QtWebEngine, Python): inherited surface; keep the system up to date.
- **R7 — QtWebEngine reader not screen-tested by the automatic suite**: JavaScript off, navigation forbidden, links filtered; the HTML is rebuilt from an allow-list anyway. Please report unexpected behavior.
- **R8 — Visual phishing**: MintMail does not warn when a link's text shows an address different from its destination, and does not detect domains imitating a correspondent's.
- **R9 — Out of scope**: an administrator of the machine or malware running as the same user reads everything.

### Automatic updates (added in 1.11.0) — own design and risks

See `docs/UPDATES.md`. Checks tested (`tests/test_updater.py`, with a fake local GitHub and real openssl signatures): signature from another key, package modified by one byte, signature of another file, empty or missing signature, package that is not MintMail, same or older version, symbolic link or special file instead of the package, file swapped after verification (installation uses the verified copy), host or redirect outside GitHub, drafts and prereleases, size caps, wrong checksum, verification key writable by a non-administrator.

- **R10 — Private signing key**: its compromise would allow installing any program on all machines. Protected by a passphrase, kept out of the repository, never given to CI. An attacker must ALSO have write access to the GitHub repository to publish. Checked backup (`tools/backup-signing-key.sh`) and planned rotation without reinstallation (`tools/rotate-signing-key.sh`, `tools/release.sh --rotation`): see docs/KEY-RECOVERY.md. No automatic revocation (deliberate: it would open another risk).
- **R11 — Freeze attack** not detected (preventing learning of a new version); an authentic intermediate version older than the latest can be replayed.
- **R12 — Not tested end to end** against a real GitHub nor with a real polkit authentication window (tested: fake GitHub, real signatures, real `dpkg`).
- **R13 — macOS**: the `.dmg` is not signed or notarized by Apple and updates download the `.dmg` over HTTPS from github.com and check a SHA-256 published next to it, but there is no SAEC signature on that path (a compromised GitHub account could replace both).

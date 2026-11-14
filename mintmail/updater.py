"""Mises à jour de MintMail depuis les « Releases » d'un dépôt GitHub — sans jamais faire confiance à GitHub seul.

Principe (sécurité d'abord : un paquet installé avec les droits administrateur peut tout faire sur la machine) :
  • GitHub ne fournit que le TRANSPORT. Chaque version est signée (RSA 3072 / SHA-256) avec une clé privée qui reste chez SAEC ;
    la clé PUBLIQUE est installée avec MintMail (/usr/share/mintmail/update-pubkey.pem, propriété de root) et ne peut être remplacée
    ni par un réglage, ni par une « Release », ni par un compte GitHub piraté. Pas de signature valide = pas d'installation.
  • Sans clé publique installée, MintMail se contente d'ANNONCER les nouvelles versions (aucune installation automatique).
  • Connexions : HTTPS uniquement, vers api.github.com et les hôtes de téléchargement de GitHub ; redirections contrôlées ; tailles plafonnées.
  • L'installation passe par pkexec : mot de passe administrateur demandé à chaque mise à jour (polkit), puis apply_update.py (root) re-vérifie
    tout sur une copie privée (voir ce fichier). Retour en arrière interdit (version strictement plus récente exigée).
  • Aucune donnée personnelle n'est envoyée : seulement une requête GET anonyme avec « MintMail/<version> » comme agent.
Les fonctions renvoient des CODES (« ratelimit », « bad_signature »…) que l'interface traduit.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

from . import __version__
from .apply_update import PUBKEY, verify_signature          # noqa: F401  (même vérification côté utilisateur et côté root)
from .store import private_dir

DEFAULT_REPO = "saec-oolivvv/mintmail"
API = "https://api.github.com"
HELPER = "/usr/lib/mintmail/apply-update"
DOWNLOAD_HOSTS = ("github.com", "githubusercontent.com")
CHECK_INTERVAL = 55 * 60          # « toutes les heures » : un peu moins d'une heure, pour absorber le décalage entre la recherche du démarrage et la minuterie horaire ; pendant que MintMail tourne ; au DÉMARRAGE la recherche a lieu à chaque fois (requête conditionnelle ETag : 304, quasi gratuite)
MAX_JSON, MAX_DEB, MAX_SIG, MAX_SUMS = 2_000_000, 150_000_000, 8192, 65536
MAX_DMG = 900_000_000                                                  # image disque Mac (Qt WebEngine comprise)
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9._-]{1,100}")


class UpdateError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, detail


@dataclass
class Update:
    version: str
    deb_url: str
    deb_size: int
    sig_url: str
    sums_url: str
    notes: str
    page: str
    dmg_url: str = ""                                                      # Mac : image disque de la version pour CE processeur (joint par la CI) et sa somme de contrôle
    dmg_sum_url: str = ""
    dmg_size: int = 0


@dataclass
class Result:
    state: str                 # "uptodate" | "available" | "error"
    update: Optional[Update] = None
    code: str = ""
    etag: str = ""


def parse_version(v) -> Optional[Tuple[int, ...]]:
    m = re.fullmatch(r"v?(?:\d+:)?(\d+(?:\.\d+){1,3})", (v or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def is_newer(candidate, current) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def valid_repo(repo) -> bool:
    return bool(_REPO.fullmatch(repo or "")) and ".." not in repo


def due(now, last, interval=CHECK_INTERVAL) -> bool:
    return not last or now - float(last) >= interval or float(last) > now + 3600     # horloge reculée : on revérifie


def host_allowed(url, allow_loopback=False) -> bool:
    p = urllib.parse.urlparse(url or "")
    host = (p.hostname or "").lower()
    if p.username or p.password:
        return False
    if allow_loopback and p.scheme == "http" and host in ("127.0.0.1", "localhost"):
        return True
    return p.scheme == "https" and any(host == d or host.endswith("." + d) for d in DOWNLOAD_HOSTS)


class _Redirect(urllib.request.HTTPRedirectHandler):
    allow_loopback = False

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not host_allowed(newurl, self.allow_loopback):
            raise urllib.error.URLError("redirection vers un hôte non autorisé refusée")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener(allow_loopback):
    h = _Redirect()
    h.allow_loopback = allow_loopback
    return urllib.request.build_opener(h)


def _get(url, headers, limit, allow_loopback=False, timeout=30):
    """(statut, en-têtes, corps) ; les statuts d'erreur HTTP sont renvoyés, pas levés."""
    if not host_allowed(url, allow_loopback):
        raise UpdateError("badurl")
    req = urllib.request.Request(url, headers=headers)
    try:
        with _opener(allow_loopback).open(req, timeout=timeout) as r:
            body = r.read(limit + 1)
            if len(body) > limit:
                raise UpdateError("toobig")
            return r.status, r.headers, body
    except urllib.error.HTTPError as e:
        return e.code, e.headers, b""


def check(repo, current=__version__, etag="", api=API, allow_loopback=False) -> Result:
    if not valid_repo(repo):
        return Result("error", code="badrepo")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "MintMail/%s" % current, "X-GitHub-Api-Version": "2022-11-28"}
    if etag:
        headers["If-None-Match"] = etag
    try:
        status, hdrs, body = _get("%s/repos/%s/releases/latest" % (api, repo), headers, MAX_JSON, allow_loopback)
    except UpdateError as e:
        return Result("error", code=e.code)
    except (urllib.error.URLError, OSError, ValueError):
        return Result("error", code="network")
    new_etag = hdrs.get("ETag", "") if hdrs else ""
    if status == 304:
        return Result("uptodate", etag=etag)
    if status == 404:
        return Result("error", code="norelease")
    if status in (403, 429):
        return Result("error", code="ratelimit")
    if status != 200:
        return Result("error", code="http")
    try:
        data = json.loads(body.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        return Result("error", code="badjson")
    if data.get("draft") or data.get("prerelease"):
        return Result("uptodate", etag=new_etag)                       # brouillons et préversions : jamais proposés
    version = parse_version(data.get("tag_name"))
    if version is None or parse_version(current) is None:
        return Result("error", code="badversion")
    vtxt = ".".join(map(str, version))
    if not is_newer(vtxt, current):
        return Result("uptodate", etag=new_etag)
    assets = {a["name"]: a for a in (data.get("assets") or []) if isinstance(a, dict) and isinstance(a.get("name"), str)}
    deb = assets.get("mintmail_%s_all.deb" % vtxt)
    if not deb:
        return Result("error", code="noasset")
    urls = [deb.get("browser_download_url")]
    sig, sums = assets.get("mintmail_%s_all.deb.sig" % vtxt), assets.get("SHA256SUMS")
    for a in (sig, sums):
        if a:
            urls.append(a.get("browser_download_url"))
    if not all(isinstance(u, str) and host_allowed(u, allow_loopback) for u in urls):
        return Result("error", code="badurl")
    size = deb.get("size") if isinstance(deb.get("size"), int) else 0
    if size > MAX_DEB:
        return Result("error", code="toobig")
    page = data.get("html_url") if isinstance(data.get("html_url"), str) and host_allowed(data.get("html_url")) else "https://github.com/%s/releases" % repo
    dmg_name = mac_dmg_name(vtxt)
    dmg, dsum = assets.get(dmg_name), assets.get(dmg_name + ".sha256")
    dmg_url = dsum_url = ""
    dmg_size = 0
    if dmg and dsum and isinstance(dmg.get("browser_download_url"), str) and isinstance(dsum.get("browser_download_url"), str) \
            and host_allowed(dmg["browser_download_url"], allow_loopback) and host_allowed(dsum["browser_download_url"], allow_loopback) \
            and isinstance(dmg.get("size"), int) and 0 < dmg["size"] <= MAX_DMG:
        dmg_url, dsum_url, dmg_size = dmg["browser_download_url"], dsum["browser_download_url"], dmg["size"]
    return Result("available", Update(vtxt, deb["browser_download_url"], size, sig["browser_download_url"] if sig else "",
                                      sums["browser_download_url"] if sums else "", str(data.get("body") or "")[:2000], page,
                                      dmg_url, dsum_url, dmg_size))


def disk_version() -> str:
    """Version du programme INSTALLÉ sur le disque (peut être plus récente que celle qui tourne encore en mémoire après une mise à jour)."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def restart_pending(current=__version__) -> str:
    """Version installée si elle est plus récente que celle en cours d'exécution (il suffit alors de relancer MintMail), sinon ''."""
    d = disk_version()
    return d if d and is_newer(d, current) else ""


def update_to_dict(up: Update) -> dict:
    """Forme enregistrable (réglages) d'une mise à jour détectée : permet d'afficher le bandeau dès le lancement suivant."""
    return {"version": up.version, "deb_url": up.deb_url, "deb_size": up.deb_size, "sig_url": up.sig_url, "sums_url": up.sums_url,
            "notes": up.notes, "page": up.page, "dmg_url": up.dmg_url, "dmg_sum_url": up.dmg_sum_url, "dmg_size": up.dmg_size}


def update_from_dict(d, current=__version__, allow_loopback=False) -> Optional[Update]:
    """Relit une mise à jour enregistrée en la REVALIDANT entièrement (le fichier de réglages n'est pas digne de confiance) : types, version
    strictement plus récente que celle installée, adresses sur les hôtes GitHub autorisés. Tout écart : None (le bandeau n'apparaît pas)."""
    if not isinstance(d, dict):
        return None
    try:
        version, deb_url = d.get("version"), d.get("deb_url")
        sig_url, sums_url, notes, page = d.get("sig_url") or "", d.get("sums_url") or "", d.get("notes") or "", d.get("page") or ""
        size = d.get("deb_size") or 0
        if not all(isinstance(x, str) for x in (version, deb_url, sig_url, sums_url, notes, page)) or not isinstance(size, int) or not 0 <= size <= MAX_DEB:
            return None
        v = parse_version(version)
        if v is None or ".".join(map(str, v)) != version or not is_newer(version, current):
            return None
        if not host_allowed(deb_url, allow_loopback) or any(u and not host_allowed(u, allow_loopback) for u in (sig_url, sums_url)):
            return None
        if not page or not host_allowed(page, allow_loopback):
            page = ""
        dmg_url, dmg_sum_url, dmg_size = d.get("dmg_url") or "", d.get("dmg_sum_url") or "", d.get("dmg_size") or 0
        if not all(isinstance(x, str) for x in (dmg_url, dmg_sum_url)) or not isinstance(dmg_size, int) or not 0 <= dmg_size <= MAX_DMG \
                or any(u and not host_allowed(u, allow_loopback) for u in (dmg_url, dmg_sum_url)):
            dmg_url = dmg_sum_url = ""
            dmg_size = 0
        return Update(version, deb_url, size, sig_url, sums_url, notes[:2000], page, dmg_url, dmg_sum_url, dmg_size)
    except (TypeError, ValueError):
        return None


def short_notes(notes: str, limit: int = 120) -> str:
    """Première nouveauté d'une Release (première puce du journal des changements), raccourcie pour le bandeau."""
    lines = [l.strip() for l in (notes or "").splitlines() if l.strip()]
    bullets = [l.lstrip("-•* ").strip() for l in lines if l[:1] in "-•*"]
    text = (bullets or [l for l in lines if not l.startswith("#")] or [""])[0]
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _download(url, dest, limit, expected=0, allow_loopback=False, progress: Optional[Callable] = None):
    if not host_allowed(url, allow_loopback):
        raise UpdateError("badurl")
    tmp = str(dest) + ".part"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    total, h = 0, hashlib.sha256()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MintMail/%s" % __version__})
        with os.fdopen(fd, "wb") as f, _opener(allow_loopback).open(req, timeout=60) as r:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise UpdateError("toobig")
                h.update(chunk)
                f.write(chunk)
                if progress:
                    progress(total, expected)
        if expected and total != expected:
            raise UpdateError("badsize")
        os.replace(tmp, dest)
        return h.hexdigest()
    except urllib.error.HTTPError:
        raise UpdateError("http")
    except (urllib.error.URLError, OSError) as e:
        if isinstance(e, UpdateError):
            raise
        raise UpdateError("network")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def fetch(update: Update, dest_dir, allow_loopback=False, progress=None):
    """Télécharge le paquet (et sa signature) dans un dossier privé. Retourne (paquet, signature | None)."""
    d = private_dir(dest_dir)
    name = "mintmail_%s_all.deb" % update.version
    deb = d / name
    digest = _download(update.deb_url, deb, MAX_DEB, update.deb_size, allow_loopback, progress)
    if update.sums_url:                                                  # intégrité du téléchargement (la signature, elle, prouve la provenance)
        _s, _h, body = _get(update.sums_url, {"User-Agent": "MintMail/%s" % __version__}, MAX_SUMS, allow_loopback)
        want = None
        for line in body.decode("utf-8", "replace").splitlines():
            m = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(\S+)", line.strip())
            if m and os.path.basename(m.group(2)) == name:
                want = m.group(1).lower()
        if want is not None and want != digest:
            deb.unlink(missing_ok=True)
            raise UpdateError("checksum")
    sig = None
    if update.sig_url:
        sig = d / (name + ".sig")
        _download(update.sig_url, sig, MAX_SIG, 0, allow_loopback)
    return deb, sig


def mac_arch(machine=None) -> str:
    import platform
    m = (machine or platform.machine() or "").lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64"


def mac_dmg_name(version, arch=None) -> str:
    return "MintMail-%s-macos-%s.dmg" % (version, arch or mac_arch())


def fetch_dmg(update: Update, dest_dir, allow_loopback=False, progress=None):
    """Mac : télécharge l'image disque de la version et vérifie sa somme de contrôle (fichier .sha256 publié avec elle). Retourne le chemin.
    Pas de signature SAEC ici (l'image est construite par GitHub, qui n'a jamais la clé privée) : la protection est HTTPS vers GitHub + cette somme."""
    if not update.dmg_url or not update.dmg_sum_url:
        raise UpdateError("nodmg")
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    name = mac_dmg_name(update.version)
    path = dest / name
    digest = _download(update.dmg_url, path, MAX_DMG, update.dmg_size, allow_loopback, progress)
    _s, _h, body = _get(update.dmg_sum_url, {"User-Agent": "MintMail/%s" % __version__}, MAX_SUMS, allow_loopback)
    want = None
    for line in body.decode("utf-8", "replace").splitlines():
        m = re.fullmatch(r"([0-9a-fA-F]{64})(?:\s+\*?(\S+))?", line.strip())
        if m and (not m.group(2) or os.path.basename(m.group(2)) == name):
            want = m.group(1).lower()
    if want is None or want != digest:
        path.unlink(missing_ok=True)
        raise UpdateError("checksum")
    return path


def open_dmg(path, runner=subprocess.run) -> bool:
    """Mac : ouvre l'image disque dans le Finder (commande fixe)."""
    try:
        return runner(["/usr/bin/open", str(path)], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def can_install(pubkey=PUBKEY, helper=HELPER, which=shutil.which, platform=None) -> Tuple[bool, str]:
    """(possible, code de la raison) : installation automatique seulement si la clé publique, le programme root et pkexec sont présents.
    Sur Mac, l'installation du paquet .deb n'existe pas : on renvoie « macos » (mise à jour à la main avec le .dmg de la Release)."""
    import sys
    if (platform or sys.platform) == "darwin":
        return False, "macos"
    if not os.path.exists(pubkey):
        return False, "nokey"
    if not os.path.exists(helper) or not which("pkexec"):
        return False, "nohelper"
    return True, ""


def check_signature(deb, sig, pubkey=PUBKEY, run=subprocess.run) -> str:
    """'' si la signature est valide, sinon un code (nokey / unsigned / bad_signature) — vérification côté utilisateur avant de déranger l'administrateur."""
    if not os.path.exists(pubkey):
        return "nokey"
    if not sig or not os.path.exists(sig):
        return "unsigned"
    return "" if verify_signature(str(deb), str(sig), pubkey, run) else "bad_signature"


_ENV_KEEP = ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "LANG", "LC_ALL", "HOME", "PATH")


def install(deb, sig, runner=subprocess.run, which=shutil.which, helper=HELPER) -> Tuple[bool, str, str]:
    """Lance l'installation via pkexec. Retourne (réussi, code, détail)."""
    pk = which("pkexec")
    if not pk or not os.path.exists(helper):
        return False, "nohelper", ""
    env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
    try:
        r = runner([pk, helper, str(deb), str(sig)], capture_output=True, text=True, timeout=2400, env=env)
    except (OSError, subprocess.SubprocessError):
        return False, "internal", ""
    last = ((r.stdout or "").strip().splitlines() or [""])[-1]
    if r.returncode == 0 and last.startswith("OK:"):
        return True, "", last[3:]
    if last.startswith("ERR:"):
        parts = (last.split(":", 2) + ["", ""])[:3]
        return False, parts[1] or "internal", parts[2]
    if r.returncode in (126, 127):
        return False, "cancelled", ""                                     # authentification refusée ou annulée
    return False, "internal", ""


def downloads_dir():
    from .store import DATA_DIR
    return DATA_DIR / "updates"


def cleanup(keep_version="", base=None):
    """Supprime les anciens paquets téléchargés (garde éventuellement celui de keep_version)."""
    d = Path(base) if base else downloads_dir()
    if not d.is_dir():
        return
    for p in d.iterdir():
        if keep_version and ("_%s_" % keep_version) in p.name:
            continue
        try:
            p.unlink()
        except OSError:
            pass

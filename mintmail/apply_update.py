"""Installation d'une mise à jour — programme exécuté avec les droits ADMINISTRATEUR (via pkexec / polkit), volontairement minuscule.

Rien de ce que reçoit ce programme n'est cru sur parole :
  1. il s'exécute seulement en root, avec exactement deux arguments (paquet .deb, signature) ;
  2. la clé publique de vérification doit appartenir à root et n'être modifiable que par lui (elle est installée avec MintMail) ;
  3. les deux fichiers sont COPIÉS (sans suivre de lien symbolique, taille plafonnée) dans un dossier privé de root : ce qui est vérifié
     est exactement ce qui sera installé (pas de substitution entre la vérification et l'installation) ;
  4. la signature RSA / SHA-256 doit correspondre à la clé publique ; sinon : refus ;
  5. le paquet doit s'appeler « mintmail », être de type « all » et avoir une version STRICTEMENT plus récente que celle installée
     (pas de retour en arrière vers une ancienne version vulnérable) ;
  6. l'installation passe par apt (dépendances résolues) avec un environnement minimal ; le dossier privé est toujours supprimé ;
  7. filet de sécurité : les fichiers de la version installée sont copiés avant l'installation ; si la nouvelle version ne s'importe pas
     après installation, ils sont remis en place (« ERR:rolled_back »).
Sortie : « OK:<version> » ou « ERR:<code>:<détail> » (l'interface traduit le code). Aucun texte n'est destiné à être affiché tel quel.
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile

PUBKEY = "/usr/share/mintmail/update-pubkey.pem"
MAX_DEB = 150_000_000
MAX_SIG = 8192
SAFE_ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C.UTF-8", "DEBIAN_FRONTEND": "noninteractive"}


class Refuse(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, detail


def key_trusted(path):
    """Clé publique et son dossier : propriété de root, non modifiables par le groupe ni les autres."""
    for p in (path, os.path.dirname(path)):
        st = os.stat(p)
        if st.st_uid != 0 or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return False
    return stat.S_ISREG(os.stat(path).st_mode)


def copy_in(src, dest, limit):
    """Copie un fichier ordinaire (jamais un lien symbolique ni un périphérique) vers dest, en refusant tout ce qui dépasse la limite."""
    try:
        fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as e:
        raise Refuse("bad_file", os.path.basename(src) + ": " + e.strerror)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            raise Refuse("bad_file", "pas un fichier ordinaire ou trop gros")
        out = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        total = 0
        with os.fdopen(out, "wb") as w, os.fdopen(fd, "rb", closefd=False) as r:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise Refuse("bad_file", "trop gros")
                w.write(chunk)
    finally:
        os.close(fd)


def verify_signature(deb, sig, pubkey, run=subprocess.run):
    """Vrai seulement si openssl confirme la signature RSA / SHA-256 de deb avec la clé publique pinnée."""
    try:
        r = run(["openssl", "dgst", "-sha256", "-verify", pubkey, "-signature", sig, deb], capture_output=True, text=True, timeout=300, env=SAFE_ENV)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and "Verified OK" in (r.stdout or "")


def _out(run, cmd):
    r = run(cmd, capture_output=True, text=True, timeout=60, env=SAFE_ENV)
    return (r.stdout or "").strip() if r.returncode == 0 else ""


BACKUP_PREFIXES = ("/usr/lib/python3/dist-packages/mintmail/", "/usr/share/mintmail/", "/usr/bin/mintmail")
MAX_BACKUP = 200_000_000


def snapshot_installed(run, dest, root="/"):
    """Copie (sans suivre les liens) les fichiers de la version installée dans dest ; retourne la liste de leurs chemins."""
    r = run(["dpkg", "-L", "mintmail"], capture_output=True, text=True, timeout=60, env=SAFE_ENV)
    if r.returncode != 0:
        return []
    saved, total = [], 0
    for path in (r.stdout or "").splitlines():
        src = os.path.join(root, path.lstrip("/"))
        if not path.startswith(BACKUP_PREFIXES) or ".." in path.split("/") or os.path.islink(src) or not os.path.isfile(src):
            continue
        total += os.path.getsize(src)
        if total > MAX_BACKUP:
            return []                                        # trop gros : pas de filet plutôt qu'un disque plein
        target = os.path.join(dest, path.lstrip("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(src, target)
        saved.append(path)
    return saved


def restore_installed(saved, src_dir, root="/"):
    """Remet en place les fichiers sauvegardés ; retourne le nombre de fichiers restaurés."""
    n = 0
    for path in saved:
        shutil.copy2(os.path.join(src_dir, path.lstrip("/")), os.path.join(root, path.lstrip("/")))
        n += 1
    return n


def import_ok(run):
    """La version qui vient d'être installée s'importe-t-elle (modules sans interface graphique) ?"""
    try:
        r = run(["python3", "-I", "-c", "import mintmail.store, mintmail.syncdata, mintmail.updater, mintmail.backend"],
                capture_output=True, text=True, timeout=120, env=SAFE_ENV, cwd="/")
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def main(argv=None, *, euid=None, pubkey=PUBKEY, key_ok=key_trusted, run=subprocess.run, installer=None, tmp_root=None, out=print, guard=None, root="/"):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if (os.geteuid() if euid is None else euid) != 0:
            raise Refuse("not_root")
        if len(argv) != 2:
            raise Refuse("usage")
        if not os.path.exists(pubkey):
            raise Refuse("nokey")
        if not key_ok(pubkey):
            raise Refuse("key_untrusted")
        work = tempfile.mkdtemp(prefix="mintmail-update-", dir=tmp_root)
        try:
            deb, sig = os.path.join(work, "update.deb"), os.path.join(work, "update.sig")
            copy_in(argv[0], deb, MAX_DEB)
            copy_in(argv[1], sig, MAX_SIG)
            if not verify_signature(deb, sig, pubkey, run):
                raise Refuse("bad_signature")
            package, arch, version = (_out(run, ["dpkg-deb", "--field", deb, f]) for f in ("Package", "Architecture", "Version"))
            if package != "mintmail" or arch != "all" or not version:
                raise Refuse("bad_package", "%s/%s" % (package[:40], arch[:20]))
            current = _out(run, ["dpkg-query", "-W", "-f=${Version}", "mintmail"])
            if current and run(["dpkg", "--compare-versions", version, "gt", current], capture_output=True, text=True, timeout=60, env=SAFE_ENV).returncode != 0:
                raise Refuse("not_newer", "%s <= %s" % (version, current))
            guarded = (installer is None) if guard is None else guard      # filet de retour arrière : actif en production, à la demande dans les tests
            backup = os.path.join(work, "backup")
            saved = snapshot_installed(run, backup, root) if guarded and current else []
            cmd = installer(deb) if installer else ["apt-get", "install", "-y", "-o", "Dpkg::Options::=--force-confold", deb]
            r = run(cmd, cwd=work, capture_output=True, text=True, timeout=1800, env=SAFE_ENV)
            if r.returncode != 0:
                raise Refuse("install_failed", " | ".join(((r.stderr or r.stdout or "")[-300:]).splitlines()[-3:]))
            if guarded and saved and not import_ok(run):
                restore_installed(saved, backup, root)
                raise Refuse("rolled_back", "%s -> %s" % (version, current))
        finally:
            shutil.rmtree(work, ignore_errors=True)
        out("OK:%s" % version)
        return 0
    except Refuse as e:
        out("ERR:%s:%s" % (e.code, e.detail.replace("\n", " ")[:300]))
        return 3
    except Exception as e:                               # jamais de trace brute : un code d'erreur propre
        out("ERR:internal:%s" % type(e).__name__)
        return 4


if __name__ == "__main__":
    sys.exit(main())

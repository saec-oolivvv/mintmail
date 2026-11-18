"""Sauvegarde, restauration et réparation (sans Qt) : configuration + cache dans un seul zip, copie de sécurité avant toute restauration,
contrôle d'intégrité de la base, compteur de démarrages ratés (→ mode sans échec). Les mots de passe restent dans le trousseau : ils ne sont pas dans la sauvegarde."""
import json
import os
import sqlite3
import time
import zipfile
from pathlib import Path

MANIFEST = "manifest.json"
FILES = {"config.json": "config", "cache.db": "data"}
KEEP_SAFETY = 5


def _stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def default_dir(data_dir) -> Path:
    return Path(data_dir) / "backups"


def _db_copy(src: Path, dst: Path):
    """Copie cohérente d'une base SQLite ouverte (API de sauvegarde : pas de fichier à moitié écrit)."""
    a = sqlite3.connect(str(src), timeout=15)
    b = sqlite3.connect(str(dst))
    try:
        a.backup(b)
    finally:
        b.close()
        a.close()


def create(config_dir, data_dir, dest=None, version="", with_cache=True) -> Path:
    """Crée une sauvegarde .zip et retourne son chemin."""
    config_dir, data_dir = Path(config_dir), Path(data_dir)
    dest = Path(dest) if dest else default_dir(data_dir) / ("mintmail-backup-%s.zip" % _stamp())
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    names = []
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        cfg = config_dir / "config.json"
        if cfg.exists():
            z.write(cfg, "config.json")
            names.append("config.json")
        db = data_dir / "cache.db"
        if with_cache and db.exists():
            snap = data_dir / ("cache.snapshot-%d.db" % os.getpid())
            try:
                _db_copy(db, snap)
                z.write(snap, "cache.db")
                names.append("cache.db")
            finally:
                try:
                    snap.unlink()
                except OSError:
                    pass
        z.writestr(MANIFEST, json.dumps({"app": "MintMail", "version": version, "date": time.strftime("%Y-%m-%d %H:%M:%S"), "files": names}, indent=1))
    os.replace(tmp, dest)
    try:
        os.chmod(dest, 0o600)                       # contient tout votre courrier
    except OSError:
        pass
    return dest


def inspect(path) -> dict:
    """Lit le manifeste d'une sauvegarde ; ValueError si ce n'est pas une sauvegarde MintMail valide."""
    try:
        with zipfile.ZipFile(path) as z:
            man = json.loads(z.read(MANIFEST).decode("utf-8"))
            bad = z.testzip()
            names = set(z.namelist())
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as e:
        raise ValueError("not a MintMail backup: %s" % e)
    if man.get("app") != "MintMail" or bad:
        raise ValueError("not a MintMail backup")
    man["files"] = [f for f in man.get("files", []) if f in FILES and f in names]      # seuls nos deux fichiers, jamais un chemin libre
    return man


def restore(path, config_dir, data_dir, version="") -> dict:
    """Restaure une sauvegarde. Avant d'écraser quoi que ce soit, l'état actuel est sauvegardé (restauration annulable)."""
    man = inspect(path)
    config_dir, data_dir = Path(config_dir), Path(data_dir)
    safety = create(config_dir, data_dir, default_dir(data_dir) / ("before-restore-%s.zip" % _stamp()), version)
    with zipfile.ZipFile(path) as z:
        for name in man["files"]:
            target = (config_dir if FILES[name] == "config" else data_dir) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".restoring")
            tmp.write_bytes(z.read(name))
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            if name == "cache.db":
                for ext in ("-wal", "-shm"):             # anciens journaux : ils ne vont pas avec la base restaurée
                    try:
                        (data_dir / ("cache.db" + ext)).unlink()
                    except OSError:
                        pass
            os.replace(tmp, target)
    prune_safety(data_dir)
    return {"restored": man["files"], "safety": safety, "date": man.get("date", "")}


def prune_safety(data_dir, keep=KEEP_SAFETY):
    old = sorted(default_dir(data_dir).glob("before-restore-*.zip"))
    for p in old[:-keep] if keep else old:
        try:
            p.unlink()
        except OSError:
            pass


def list_backups(data_dir):
    return sorted(default_dir(data_dir).glob("*.zip"), reverse=True)


# ---------------------------------------------------------------- réparation
def check_db(path) -> bool:
    """Vrai si la base SQLite est saine (integrity_check) ; une base absente est saine (elle sera créée)."""
    p = Path(path)
    if not p.exists():
        return True
    try:
        con = sqlite3.connect(str(p), timeout=15)
        try:
            return con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return False


def check_config(path) -> bool:
    p = Path(path)
    if not p.exists():
        return True
    try:
        return isinstance(json.loads(p.read_text(encoding="utf-8")), dict)
    except (OSError, ValueError):
        return False


def repair(config_dir, data_dir) -> list:
    """Met de côté (jamais supprime) la base ou la configuration illisible ; retourne ce qui a été fait.
    Une base de cache écartée se reconstruit depuis le serveur ; une configuration écartée se remplace par une sauvegarde."""
    done = []
    for target, ok, what in ((Path(data_dir) / "cache.db", check_db, "cache"), (Path(config_dir) / "config.json", check_config, "config")):
        if ok(target):
            continue
        aside = target.with_name(target.name + ".corrupt-" + _stamp())
        try:
            os.replace(target, aside)
            for ext in ("-wal", "-shm"):
                try:
                    os.replace(str(target) + ext, str(aside) + ext)
                except OSError:
                    pass
            done.append((what, str(aside)))
        except OSError:
            pass
    return done


# ---------------------------------------------------------------- démarrages ratés → mode sans échec
CRASH_FILE = "starting.json"
CRASH_LIMIT = 3


def _crash_path(data_dir):
    return Path(data_dir) / CRASH_FILE


def note_start(data_dir) -> int:
    """Appelé au lancement : compte les démarrages qui n'ont pas atteint « tout va bien » ; retourne ce compteur (avant celui-ci)."""
    p = _crash_path(data_dir)
    try:
        n = int(json.loads(p.read_text(encoding="utf-8")).get("n", 0))
    except (OSError, ValueError, AttributeError):
        n = 0
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"n": n + 1}), encoding="utf-8")
    except OSError:
        pass
    return n


def note_ok(data_dir):
    """Appelé quelques secondes après l'ouverture de la fenêtre : le démarrage a réussi."""
    try:
        _crash_path(data_dir).unlink()
    except OSError:
        pass


def should_start_safe(previous_failures) -> bool:
    return previous_failures >= CRASH_LIMIT - 1


SAFE_OFF = {"p2p_enabled": False, "notifications": False, "sound_receive": False, "sound_send": False}


def apply_safe(config) -> dict:
    """Mode sans échec : désactive en mémoire ce qui tourne en arrière-plan (synchro P2P, alertes, absence) ; rien n'est enregistré."""
    config.read_only = True
    for k, v in SAFE_OFF.items():
        config.data[k] = v
    ab = dict(config.data.get("absence") or {})
    ab["enabled"] = False
    config.data["absence"] = ab
    return SAFE_OFF


def safe_message(safe, fixed) -> str:
    """Texte (traduit) affiché au démarrage quand le mode sans échec ou une réparation a eu lieu."""
    from .i18n import tr
    out = []
    if safe:
        out.append(tr("MintMail a démarré en mode sans échec : synchronisation entre machines, alertes, sons et absence sont désactivés pour cette session (rien n'est modifié dans vos réglages). Relancez normalement pour tout retrouver."))
    for what, aside in fixed:
        out.append((tr("La base de messages était endommagée : elle a été mise de côté (%s) et sera reconstruite depuis le serveur.") if what == "cache"
                    else tr("Le fichier de réglages était illisible : il a été mis de côté (%s). Restaurez une sauvegarde dans Réglages → Maintenance.")) % aside)
    return "\n\n".join(out)

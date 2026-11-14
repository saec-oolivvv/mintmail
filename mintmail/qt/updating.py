"""Mises à jour de l'interface Qt (logique pure, sans Qt ni GTK) : même règles que updates_ui.py de la version GTK.

UpdateState tient l'état (version annoncée, opération en cours, bandeau) ; l'interface lit `banner` et `status_lines()` et lance le réseau en fond.
Aucune règle de sécurité n'est réimplémentée ici : tout passe par `updater` (signature RSA vérifiée, retour en arrière refusé, hôtes autorisés)."""
import os
import subprocess
import sys
import time
from typing import Callable, Dict, List, Optional, Tuple

from .. import __version__, updater
from ..i18n import tr
from ..update_text import explain


class UpdateState:
    def __init__(self, config, upd=updater, version=__version__, now: Callable[[], float] = time.time):
        self.config, self.upd, self.version, self.now = config, upd, version, now
        self.update = None
        self.busy = False
        self.banner: Dict = {"state": "hidden"}
        self.chip = ""                       # texte de la pastille de la barre latérale ("" = cachée)
        self.restore()

    # -- état
    def restore(self):
        """Une mise à jour déjà connue s'affiche tout de suite, sans attendre le réseau."""
        stored = self.config.get("update_available")
        self.update = self.upd.update_from_dict(stored, self.version)
        if stored and self.update is None:                 # déjà installée depuis, ou enregistrement invalide : on l'oublie
            self.config["update_available"] = None
            self.config.save()
        self.refresh()

    def snoozed(self, up) -> bool:
        c = self.config
        return c.get("update_snooze_version") == up.version and self.now() < float(c.get("update_snooze_until") or 0)

    def _set(self, state, icon="", title="", sub="", notes="", fraction=None, buttons=()):
        self.banner = {"state": state, "icon": icon, "title": title, "sub": sub, "notes": notes, "fraction": fraction, "buttons": list(buttons)}

    def hide(self):
        self.banner = {"state": "hidden"}

    def show_available(self, up):
        n = self.upd.short_notes(up.notes)
        self._set("available", "⬆", tr("MintMail %s est disponible") % up.version,
                  tr("Vous utilisez la version %s. Installation sécurisée : signature vérifiée, puis mot de passe administrateur demandé.") % self.version,
                  tr("Nouveautés : %s") % n if n else "", None, ["install"] + (["notes"] if up.page else []) + ["later", "close"])

    def show_progress(self, version, text, fraction=None):
        self._set("progress", "⏳", tr("Mise à jour vers MintMail %s") % version, text, "", fraction, [])

    def show_done(self, version):
        self._set("done", "✔", tr("MintMail %s est installé") % version, tr("Relancez MintMail pour profiter de la nouvelle version."), "", None,
                  ["restart", "close"])

    def show_error(self, text, page=""):
        self._set("error", "⚠", tr("La mise à jour a échoué"), text, "", None, ["retry"] + (["notes"] if page else []) + ["close"])

    def refresh(self, force=False):
        up, pend = self.update, self.upd.restart_pending(self.version)
        if pend and (up is None or not self.upd.is_newer(up.version, pend)):
            # Déjà installée sur le disque (cette fenêtre tourne encore avec l'ancienne version) : il ne reste qu'à relancer.
            self.update, self.chip = None, ""
            if self.config.get("update_available"):
                self.config["update_available"] = None
                self.config.save()
            if not self.busy and self.banner["state"] != "progress":
                self.show_done(pend)
            return
        self.chip = (tr("⬆ Mise à jour %s") % up.version) if up is not None else ""
        if not self.busy and self.banner["state"] not in ("progress", "done", "error"):
            if up is not None and (force or not self.snoozed(up)):
                self.show_available(up)
            else:
                self.hide()

    def snooze(self):
        """« Plus tard » : le bandeau se cache 24 h pour cette version (la pastille reste)."""
        if self.update is not None:
            self.config["update_snooze_version"] = self.update.version
            self.config["update_snooze_until"] = self.now() + 24 * 3600
            self.config.save()
        self.hide()

    # -- recherche
    def should_check(self, manual=False, startup=False) -> bool:
        c = self.config
        if self.busy:
            return False
        if not manual and not c.get("update_check", True):
            return False
        if not manual and not startup and not self.upd.due(self.now(), c.get("update_last_check", 0)):
            return False
        return True

    def begin_check(self) -> Tuple[str, str]:
        """Marque la recherche en cours ; retourne (dépôt, etag) pour updater.check (réseau : en fond)."""
        self.busy = True
        c = self.config
        return c.get("update_repo") or self.upd.DEFAULT_REPO, (c.get("update_etag", "") if self.update is None else "")

    def finish_check(self, res, err, manual=False) -> Dict:
        """Range le résultat. Retourne {"toast": texte ou "", "notify": mise à jour à annoncer par une notification ou None}."""
        c, out = self.config, {"toast": "", "notify": None}
        self.busy = False
        if err or res is None:
            out["toast"] = explain("network") if manual else ""
            return out
        c["update_last_result"] = ("available:" + res.update.version) if res.state == "available" else ("error:" + res.code) if res.state == "error" else "uptodate"
        if res.state != "error":
            c["update_last_check"] = self.now()
            c["update_etag"] = res.etag if res.state == "uptodate" else ""
        if res.state == "available":
            is_new = c.get("update_seen") != res.update.version
            self.update = res.update
            c["update_available"] = self.upd.update_to_dict(res.update)
            c["update_seen"] = res.update.version
            if is_new and not manual:
                out["notify"] = res.update
            if manual:
                c["update_snooze_until"] = 0                # demande explicite : on montre le bandeau même s'il avait été repoussé
            c.save()
            self.refresh(force=manual)
            return out
        if res.state == "uptodate":
            self.update = None
            c["update_available"] = None
            out["toast"] = (tr("MintMail est à jour (version %s).") % self.version) if manual else ""
        elif manual:
            out["toast"] = explain(res.code)
        c.save()
        self.refresh()
        return out

    # -- installation
    def start_install(self) -> Optional[str]:
        """Contrôles avant l'installation. Retourne None si on peut y aller (l'état passe en « téléchargement »), sinon le texte à afficher
        (« » = rien à faire : la mise à jour est déjà sur le disque, il reste à relancer)."""
        up = self.update
        if up is None or self.busy:
            return ""
        pend = self.upd.restart_pending(self.version)
        if pend and not self.upd.is_newer(up.version, pend):
            self.update = None
            self.refresh()
            return ""
        ok, why = self.upd.can_install()
        if not ok and why == "nokey" and source_repo():                                  # lancé depuis les sources (venv, dépôt cloné) : mise à jour par git
            self.busy = True
            self.show_progress(up.version, tr("Mise à jour du dépôt…"), None)
            return None
        if not ok:
            text = explain(why)
            self.show_error(text, up.page)
            return text
        self.busy = True
        self.show_progress(up.version, tr("Téléchargement…"), 0.0)
        return None

    def install_work(self, stage: Callable[[str, str, Optional[float]], None]):
        """Téléchargement, vérification de la signature puis installation (réseau et mot de passe administrateur : EN FOND).
        Retourne (réussi, code, détail)."""
        up, last = self.update, {"pct": -1}
        if not self.upd.can_install()[0] and source_repo():
            stage(up.version, tr("Mise à jour du dépôt…"), None)
            return git_update(source_repo())

        def progress(done, total):
            pct = int(100 * done / total) if total else -1
            if pct != last["pct"]:
                last["pct"] = pct
                stage(up.version, tr("Téléchargement…"), (done / total) if total else None)
        deb, sig = self.upd.fetch(up, self.upd.downloads_dir(), progress=progress)
        stage(up.version, tr("Vérification de la signature…"), None)
        code = self.upd.check_signature(deb, sig)
        if code:
            return False, code, ""
        stage(up.version, tr("Installation… (votre mot de passe administrateur est demandé)"), None)
        return self.upd.install(deb, sig)

    def finish_install(self, res, err) -> str:
        """Range le résultat de install_work ; retourne un message d'état (« » si rien à dire)."""
        up, c = self.update, self.config
        self.busy = False
        if err is not None:
            text = explain(getattr(err, "code", "internal"))
            self.show_error(text, up.page if up else "")
            return text
        ok, code, detail = res
        if ok:
            self.update, c["update_available"], self.chip = None, None, ""
            c.save()
            self.upd.cleanup()
            self.show_done(detail or up.version)
            return ""
        pend = self.upd.restart_pending(self.version)
        if code == "not_newer" and pend and not self.upd.is_newer(up.version, pend):
            self.update, c["update_available"] = None, None            # « pas plus récente » = déjà installée : relancer suffit
            c.save()
            self.hide()
            self.refresh()
            return ""
        text = explain(code)
        self.show_error(text, up.page if up else "")
        return text

    # -- page de réglages
    def status_lines(self) -> List[str]:
        c = self.config
        last = c.get("update_last_check", 0)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(last)) if last else tr("jamais")
        pend = self.upd.restart_pending(self.version)
        if self.busy:
            lines = [tr("Opération en cours…")]
        elif pend:
            lines = ["✔ " + tr("MintMail %s est installé") % pend + " — " + tr("Relancez MintMail pour profiter de la nouvelle version.")]
        elif self.update is not None:
            lines = [tr("⬆ La version %s est disponible (dernière vérification : %s).") % (self.update.version, when)]
        else:
            lines = [tr("Aucune mise à jour connue (dernière vérification : %s).") % when]
        res = str(c.get("update_last_result") or "")
        if res.startswith("error:") and not self.busy:
            lines.append(explain(res[6:]))
        return lines

    def key_line(self) -> str:
        ok, why = self.upd.can_install()
        if not ok and why == "nokey" and source_repo():
            return tr("Mise à jour depuis le dépôt de sources (git) : prête, MintMail est lancé depuis les sources.")
        return tr("Installation automatique : prête (clé de vérification présente).") if ok else \
            tr("Installation automatique désactivée : %s Vous serez seulement informé des nouvelles versions.") % explain(why)


def source_repo() -> str:
    """Racine du dépôt git si MintMail est lancé depuis ses sources (venv + clone), sinon « »."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return root if os.path.isdir(os.path.join(root, ".git")) and os.path.isfile(os.path.join(root, "VERSION")) else ""


def git_update(repo: str, run=subprocess.run):
    """Met à jour un dépôt de sources : récupère GitHub puis avance sans conflit (--ff-only) ; commandes FIXES, aucun texte externe.
    Retourne (réussi, code, détail) comme l'installation du paquet."""
    try:
        for cmd in (["git", "fetch", "--tags", "origin"], ["git", "pull", "--ff-only"]):
            r = run(cmd, cwd=repo, capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                return False, "git", (r.stderr or r.stdout or "").strip()[-300:]
    except (OSError, subprocess.SubprocessError) as e:
        return False, "git", str(e)[:200]
    return True, "", ""


def restart_command() -> List[str]:
    """Commande FIXE de relance (aucun texte externe) : le même interpréteur, qui retrouve la version installée par le paquet."""
    return [sys.executable, "-m", "mintmail", "--qt"]

"""Synchronisation entre machines (P2P) pour l'interface Qt, SANS Qt : réglages (code de jumelage, pairs statiques), état, diagnostic, messages.
Les règles et les textes sont ceux de la page « Synchronisation P2P » de la version GTK ; le moteur est p2p.SyncEngine."""
from typing import List, Tuple

from ..i18n import tr
from ..p2p import MIN_SECRET, code_is_acceptable, code_strength

INTRO = tr("Tout est synchronisé automatiquement entre vos machines MintMail du même réseau dès qu'elles se voient : "
           "comptes (avec leurs mots de passe), signatures, IA (clé API), modèles de réponse rapide, règles, "
           "blocages, recherches enregistrées et apparence. Les suppressions sont propagées aussi. "
           "Les échanges sont authentifiés et chiffrés ; le courrier n'est pas échangé (chaque machine le "
           "télécharge depuis son serveur). Utilisez le même code de jumelage partout.")
FIREWALL = tr("Pare-feu : autoriser UDP 54321 et TCP 54322 entre les machines "
              "(ex. sudo ufw allow from 192.168.1.0/24 to any port 54322 proto tcp). "
              "Les échanges sont chiffrés et authentifiés par le code de jumelage.")


def parse_peers(text: str) -> List[str]:
    """Adresses IP (ou nom, port facultatif) séparées par des virgules / espaces ; entrées invalides ignorées."""
    out: List[str] = []
    for tok in (text or "").replace(",", " ").split():
        host, sep, port = tok.partition(":")
        if not host or any(c in host for c in "/\\"):
            continue
        if sep and (not port.isdigit() or not 0 < int(port) < 65536):
            continue
        if tok not in out:
            out.append(tok)
    return out


def apply_settings(config, code: str, want: bool) -> Tuple[bool, str]:
    """Enregistre code et activation. Retourne (activée, message) ; refuse un code faible ou trop court (la synchro reste coupée)."""
    code = (code or "").strip()
    note = ""
    if want and code != (config.get("p2p_secret") or "") and len(code) >= MIN_SECRET and not code_is_acceptable(code):
        return False, tr("Code trop faible (≈ %d bits) : il protège vos mots de passe sur le réseau. Cliquez « Générer » ou utilisez au moins "
                         "16 caractères variés (lettres, chiffres, symboles), sans mot courant.") % code_strength(code)
    if want and len(code) < MIN_SECRET:
        note, want = tr("Définissez d'abord un code de jumelage (%d caractères minimum)") % MIN_SECRET, False
    config["p2p_secret"], config["p2p_enabled"] = code, want
    config.save()
    return want, note


def save_peers(config, text: str) -> Tuple[List[str], str]:
    lst = parse_peers(text)
    config["p2p_static_peers"] = lst
    config.save()
    return lst, tr("%d pair(s) statique(s) enregistré(s)") % len(lst)


def sync_result_text(engine, res: dict) -> str:
    """Message après « Synchroniser maintenant »."""
    res = res or {}
    if not engine.can_run():
        return tr("Synchronisation inactive (code de jumelage requis)")
    if not res.get("peers_checked"):
        return tr("Aucune autre machine détectée")
    if res.get("failed") and not res.get("applied"):
        return tr("Échange impossible : %s") % (engine.last_error or tr("machine injoignable"))
    return (tr("%d élément(s) reçu(s) — %s") % (res["applied"], engine.last_summary)) if res.get("applied") else tr("Tout est à jour")


def peers_text(engine) -> str:
    return "\n".join("%s @ %s:%s (%s)" % (p["node_id"], p["host"], p["port"], p["via"]) for p in engine.peers()) \
        or tr("Aucune autre machine détectée pour l'instant.")


def diagnostic_text(engine) -> str:
    d = engine.diagnostics()
    out = []
    if not d["enabled"]:
        out.append(tr("⚠ Synchronisation désactivée sur CETTE machine (elle ne se voit pas elle-même ni les autres)."))
    if d["code_len"] and d["code_len"] < MIN_SECRET:
        out.append(tr("⚠ Code trop court : %d caractères (%d minimum). Cliquez « Générer », « Appliquer », puis "
                      "saisissez EXACTEMENT le même code sur chaque machine.") % (d["code_len"], MIN_SECRET))
    if d["code_len"] >= MIN_SECRET and d.get("code_bits", 99) < 64:
        out.append(tr("⚠ Code de jumelage faible (≈ %d bits) : un attaquant du réseau pourrait le deviner hors ligne. Générez-en un nouveau "
                      "(bouton « Générer ») puis saisissez-le sur chaque machine.") % d["code_bits"])
    if d["enabled"] and not d["code_ok"]:
        out.append(tr("⚠ Aucun code valide : la synchronisation ne démarre pas."))
    out.append(tr("• Adresses de cette machine : %s") % (", ".join(d["own_ips"]) or tr("aucune détectée (réseau déconnecté ?)")))
    if d["enabled"]:
        out.append(tr("• Écoute : UDP %d %s — TCP %d %s") % (d["disc_port"], "OK" if d["udp_bound"] else tr("✗ port occupé"),
                                                       d["tcp_port"], "OK" if d["tcp_bound"] else tr("✗ port occupé")))
        out.append(tr("• Annonces envoyées : %d (échecs : %d) — reçues d'autres machines : %d") % (d["sent"], d["send_errors"], d["received"]))
        if d["foreign_versions"]:
            out.append(tr("⚠ Une machine d'une AUTRE version (protocole %s) annonce sa présence : mettez MintMail à jour "
                          "partout (même version).") % ", ".join(d["foreign_versions"]))
        if d["filtered"]:
            out.append(tr("• Annonces ignorées (adresse publique) : %s") % ", ".join(d["filtered"][:4]))
        if d["scanned"]:
            out.append(tr("• Dernière recherche active : %d adresses sondées") % d["scanned"])
        if not d["received"] and d["sent"]:
            out.append(tr("→ Aucune annonce reçue : box ou pare-feu qui bloque UDP %d ? Essayez « Rechercher les machines ».") % d["disc_port"])
    return "\n".join(out)


def footer_label(engine, config) -> str:
    """Libellé du pied de barre latérale."""
    if engine is not None and engine.is_enabled():
        return "⇄ " + engine.short_label()
    secret = str(config.get("p2p_secret") or "")
    return (tr("⇄ désactivée : code < %d car.") % MIN_SECRET) if 0 < len(secret) < MIN_SECRET else ""

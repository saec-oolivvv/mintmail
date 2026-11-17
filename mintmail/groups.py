"""Groupes de la boîte de réception (comme les groupes de Spark) : épinglés, attribués à moi, invitations, réponses aux invitations,
notifications, newsletters. Chaque message appartient à UN groupe ; pour chaque groupe on choisit « grouper » (le groupe sort de la boîte
principale et s'ouvre par sa pastille) ou « afficher tout » (ses messages restent dans la boîte principale). Réglage général, avec
dérogation possible pour chaque boîte mail. Module SANS Qt, testable partout."""
from typing import Dict, Iterable, List, Optional, Set

from .i18n import tr
from .util import split_addresses

ORDER = ["pinned", "mine", "invite", "reply", "notif", "news"]
GROUP, ALL = "group", "inline"                     # modes d'un groupe
ROW_ORDER = ["pinned", "notif", "news", "invite", "reply", "mine"]      # ordre des rangées de groupes en haut de la boîte unifiée
DEFAULT_MODES = {"pinned": GROUP, "mine": ALL, "invite": GROUP, "reply": GROUP, "notif": GROUP, "news": GROUP}


def labels() -> Dict[str, str]:
    return {"pinned": tr("Épinglés"), "mine": tr("Attribués à moi"), "invite": tr("Invitations reçues"),
            "reply": tr("Réponses aux invitations"), "notif": tr("Notifications"), "news": tr("Newsletters")}


def label(key: str) -> str:
    return labels().get(key, key)


def my_addresses(account: Optional[dict], identities: Iterable[dict] = ()) -> Set[str]:
    """Adresses qui désignent « moi » pour ce compte : l'adresse du compte et ses identités d'envoi (alias)."""
    out = {((account or {}).get("email") or "").lower()}
    for i in identities or []:
        if isinstance(i, dict) and i.get("email") and (not i.get("account") or i.get("account") == (account or {}).get("id")):
            out.add(i["email"].lower())
    out.discard("")
    return out


def group_of(msg, mine_addrs: Set[str] = frozenset(), has_followup: bool = False) -> Optional[str]:
    """Groupe d'un message de la boîte de réception, ou None (boîte principale : les échanges ordinaires entre personnes).
    Priorité : épinglé, invitation, réponse à une invitation, attribué à moi, notification, newsletter."""
    if getattr(msg, "pinned", False):
        return "pinned"
    method = ((getattr(msg, "invite", None) or {}).get("method") or "").upper()
    if method in ("REPLY", "COUNTER"):
        return "reply"
    if method in ("REQUEST", "CANCEL", "PUBLISH", "ADD", "REFRESH"):
        return "invite"
    cat = getattr(msg, "category", "people")
    if has_followup or (cat == "people" and _addressed_to_me_alone(msg, mine_addrs)):
        return "mine"
    return cat if cat in ("notif", "news") else None


def _addressed_to_me_alone(msg, mine: Set[str]) -> bool:
    """Une vraie personne m'écrit à moi seul : je suis le seul destinataire direct et personne d'autre n'est en copie."""
    if not mine:
        return False
    to = [a.lower() for a in split_addresses(getattr(msg, "to", ""))]
    cc = [a.lower() for a in split_addresses(getattr(msg, "cc", ""))]
    return len(to) == 1 and to[0] in mine and not cc


def settings_for(config, account_id: str) -> Dict:
    """{'on': bool, 'modes': {groupe: 'group'|'inline'}} pour une boîte : réglage général, puis dérogations de la boîte."""
    on = config.get("inbox_grouping", True)
    modes = dict(DEFAULT_MODES)
    modes.update({k: v for k, v in (config.get("group_modes") or {}).items() if k in modes and v in (GROUP, ALL)})
    for a in config.get("accounts") or []:
        if a.get("id") == account_id:
            if isinstance(a.get("inbox_grouping"), bool):
                on = a["inbox_grouping"]
            modes.update({k: v for k, v in (a.get("group_modes") or {}).items() if k in modes and v in (GROUP, ALL)})
    return {"on": bool(on), "modes": modes}


class Grouper:
    """Classe les messages d'une liste selon les réglages de leur boîte (une instance par affichage)."""

    def __init__(self, config, cache=None, accounts: Optional[List[dict]] = None):
        self.config = config
        self.accounts = {a.get("id"): a for a in (accounts if accounts is not None else config.get("accounts") or [])}
        self.idents = config.get("identities") or []
        self._set: Dict[str, Dict] = {}
        self._mine: Dict[str, Set[str]] = {}
        self.followed = followed_ids(config)

    def settings(self, aid):
        if aid not in self._set:
            self._set[aid] = settings_for(self.config, aid)
        return self._set[aid]

    def group(self, msg) -> Optional[str]:
        aid = msg.account
        if aid not in self._mine:
            self._mine[aid] = my_addresses(self.accounts.get(aid), self.idents)
        return group_of(msg, self._mine[aid], msg.id in self.followed)

    def in_main(self, msg) -> bool:
        """Le message reste-t-il dans la boîte principale ? (groupes en mode « afficher tout », ou regroupement coupé)"""
        s = self.settings(msg.account)
        g = self.group(msg)
        return g is None or not s["on"] or s["modes"].get(g) == ALL

    def counts(self, msgs) -> Dict[str, int]:
        out = {k: 0 for k in ORDER}
        for m in msgs:
            g = self.group(m)
            if g:
                out[g] += 1
        return out

    def any_grouping(self) -> bool:
        ids = list(self.accounts) or [""]
        return any(self.settings(i)["on"] and GROUP in self.settings(i)["modes"].values() for i in ids)


def followed_ids(config) -> Set[str]:
    """Messages sur lesquels une tâche ou une relance est posée (attribués à moi)."""
    ids = {t.get("msg") for t in config.get("tasks") or [] if t.get("msg") and not t.get("done")}
    ids |= {f.get("id") for f in config.get("followups") or [] if f.get("id")}
    return {i for i in ids if i}


def filter_view(grouper: Grouper, msgs, key: Optional[str]) -> list:
    """Messages à afficher pour la pastille choisie : None = boîte principale, 'all' = tout, sinon le groupe."""
    if key == "all":
        return list(msgs)
    if key is None:
        return [m for m in msgs if grouper.in_main(m)]
    return [m for m in msgs if grouper.group(m) == key]


def digest(grouper: Grouper, msgs, per: int = 4) -> Dict[str, Dict]:
    """Rangées de groupes de la boîte unifiée : {groupe: {'n': messages, 'unread': non lus, 'senders': [noms]}} pour les groupes en mode « grouper ».
    Les noms des expéditeurs (sans doublon, non lus d'abord, puis les plus récents) sont tout ce que la rangée affiche."""
    out: Dict[str, Dict] = {}
    for m in msgs:
        g = grouper.group(m)
        if not g or grouper.in_main(m):
            continue
        d = out.setdefault(g, {"n": 0, "unread": 0, "new": [], "old": []})
        d["n"] += 1
        name = (getattr(m, "display_sender", "") or "").strip()
        if getattr(m, "unread", False):
            d["unread"] += 1
        bucket = d["new"] if getattr(m, "unread", False) else d["old"]
        if name and name not in bucket:
            bucket.append(name)
    for d in out.values():
        names = d.pop("new") + [n for n in d.pop("old")]
        seen, d["senders"] = set(), []
        for n in names:
            if n not in seen:
                seen.add(n)
                d["senders"].append(n)
        d["senders"] = d["senders"][:per]
    return out

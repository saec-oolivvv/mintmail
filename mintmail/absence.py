"""Absence du bureau / vacances : réponse automatique, SANS Qt. Un seul réglage (dates, objet, message) appliqué à UNE ou PLUSIEURS boîtes mail,
chaque réponse partant de la boîte qui a reçu le message, avec la signature de cette boîte (ou de l'alias auquel on a écrit).
MintMail doit être ouvert pour répondre : la réponse est envoyée à la synchronisation suivante, une seule fois par expéditeur et par absence."""
import datetime
import re
import time
from .i18n import tr

DEFAULTS = {"enabled": False, "kind": "office", "start": "", "end": "", "subject": "", "body": "", "accounts": [], "known_only": False}

KINDS = ("office", "vacation")


def default_subject(kind) -> str:
    if kind == "vacation":
        return tr("En vacances")
    return tr("Absence du bureau")


def default_body(kind) -> str:
    if kind == "vacation":
        return tr("Bonjour,\n\nJe suis en vacances du {debut} au {fin}. Je lirai votre message à mon retour, le {retour}.\n\nCordialement,")
    return tr("Bonjour,\n\nJe suis absent(e) du bureau du {debut} au {fin} et je n'ai qu'un accès limité à mes messages.\n"
              "Je vous répondrai à mon retour, le {retour}.\n\nCordialement,")


AUTO_SUBJECT = re.compile(r"^\s*(r[ée]ponse automatique|automatic reply|auto[- ]?reply|out of office|abwesenheit|afwezig|absence|fuera de la oficina|"
                          r"undeliverable|delivery status|mail delivery|failure notice|returned mail)", re.I)
MACHINE = re.compile(r"(^|[._+-])(no-?reply|do-?not-?reply|donotreply|mailer-daemon|postmaster|bounce[s]?|notifications?|newsletter|daemon|robot|automated?)([._+@-]|$)", re.I)


def settings(cfg) -> dict:
    """Réglage normalisé (valeurs inconnues ou invalides ignorées)."""
    raw = (cfg.get("absence") if hasattr(cfg, "get") else None) or {}
    a = dict(DEFAULTS)
    if isinstance(raw, dict):
        a.update({k: raw[k] for k in DEFAULTS if k in raw})
    a["enabled"], a["known_only"] = bool(a["enabled"]), bool(a["known_only"])
    a["kind"] = a["kind"] if a["kind"] in KINDS else "office"
    a["accounts"] = [x for x in a["accounts"] if isinstance(x, str)] if isinstance(a["accounts"], list) else []
    for k in ("start", "end", "subject", "body"):
        a[k] = a[k] if isinstance(a[k], str) else ""
    return a


def parse_date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def window(a):
    """(début, fin) en timestamps locaux : de 00:00 le premier jour à 23:59:59 le dernier ; None si les dates manquent ou sont à l'envers."""
    d1, d2 = parse_date(a.get("start")), parse_date(a.get("end"))
    if not d1 or not d2 or d2 < d1:
        return None
    return (time.mktime(d1.timetuple()), time.mktime((d2 + datetime.timedelta(days=1)).timetuple()) - 1)


def state(a, now=None) -> str:
    """off (désactivée ou dates invalides) · soon (programmée) · active · over (terminée)."""
    w = window(a)
    if not a.get("enabled") or not w:
        return "off"
    now = time.time() if now is None else now
    return "soon" if now < w[0] else ("over" if now > w[1] else "active")


def days_count(a) -> int:
    w = window(a)
    return (parse_date(a["end"]) - parse_date(a["start"])).days + 1 if w else 0


def _fmt(d):
    return d.strftime("%d/%m/%Y")


def expand(text, a) -> str:
    """Remplace {debut} {fin} {retour} {jours} dans l'objet ou le message."""
    d1, d2 = parse_date(a.get("start")), parse_date(a.get("end"))
    if not d1 or not d2:
        return text
    vals = {"debut": _fmt(d1), "fin": _fmt(d2), "retour": _fmt(d2 + datetime.timedelta(days=1)), "jours": str(days_count(a))}
    return re.sub(r"\{(debut|fin|retour|jours)\}", lambda m: vals[m.group(1)], text)


def subject_of(a) -> str:
    return expand(a.get("subject") or default_subject(a["kind"]), a)


def body_of(a) -> str:
    return expand(a.get("body") or default_body(a["kind"]), a)


def targets(a, accounts) -> list:
    """Boîtes concernées : celles cochées ; liste vide = toutes les boîtes réelles."""
    real = [x for x in accounts if x.get("id") and not x.get("demo")]
    return [x for x in real if not a["accounts"] or x["id"] in a["accounts"]]


def own_addresses(config, account) -> set:
    out = {str(account.get("email", "")).lower()}
    out |= {str(i.get("email", "")).lower() for i in (config.get("identities") or []) if i.get("account") == account.get("id")}
    return {x for x in out if x}


def skip_reason(msg, own, config=None) -> str:
    """Pourquoi on ne répond PAS à ce message (vide : on peut répondre). Jamais de réponse aux robots, listes, newsletters, ni en boucle."""
    sender = (msg.sender_email or "").lower()
    if not sender or "@" not in sender:
        return "sender"
    if sender in own:
        return "self"
    if msg.folder != "inbox":
        return "folder"
    if getattr(msg, "auto", False) or msg.unsubscribe or msg.category in ("news", "notif") or msg.invite or msg.receipt_for:
        return "automatic"
    if MACHINE.search(sender) or AUTO_SUBJECT.match(msg.subject or ""):
        return "automatic"
    cfg = config or {}
    if sender in {str(x).lower() for x in (cfg.get("blocked") or []) + (cfg.get("spam_senders") or [])}:
        return "blocked"
    to = ((msg.to or "") + " " + (msg.cc or "")).lower()
    if not any(o in to for o in own):
        return "not_addressed"                       # liste de diffusion, copie cachée : on ne répond pas
    return ""


def log_key(msg) -> str:
    return "%s|%s" % (msg.account, (msg.sender_email or "").lower())


def should_reply(a, msg, own, config, log, now=None) -> bool:
    """Vrai si ce message doit recevoir la réponse d'absence : absence active, boîte concernée, message reçu pendant l'absence,
    expéditeur légitime (voir skip_reason) et pas déjà prévenu pendant cette absence."""
    now = time.time() if now is None else now
    if state(a, now) != "active":
        return False
    w = window(a)
    if msg.date < w[0] or msg.date > w[1] or skip_reason(msg, own, config):
        return False
    if a["known_only"] and (msg.sender_email or "").lower() not in {str(k).lower() for k in (config.get("contacts") or {})}:
        return False
    return float((log or {}).get(log_key(msg), 0) or 0) < w[0]


def prune(log, a) -> dict:
    """Oublie les réponses des absences précédentes."""
    w = window(a)
    return {k: v for k, v in (log or {}).items() if w and float(v or 0) >= w[0]}


def update(config, **changes) -> dict:
    """Modifie le réglage (clés inconnues ignorées), l'enregistre et retourne la version normalisée."""
    cur = dict(settings(config))
    cur.update({k: v for k, v in changes.items() if k in DEFAULTS})
    config["absence"] = cur
    if hasattr(config, "save"):
        config.save()
    return settings(config)


def starting_today(days, today=None):
    """(début, fin) ISO pour une absence de `days` jours qui commence aujourd'hui."""
    d = today or datetime.date.today()
    return d.isoformat(), (d + datetime.timedelta(days=max(1, int(days)) - 1)).isoformat()

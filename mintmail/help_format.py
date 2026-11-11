"""Mise en forme de l'aide, SANS GTK (donc testable partout) : le texte brut des rubriques devient des blocs (paragraphes, puces, étapes, astuces,
avertissements, commandes) et du balisage Pango (touches de clavier, noms d'écrans en gras, commandes, liens), avec surlignage des recherches.

Conventions d'écriture des rubriques (français et anglais) :
  « • texte »            puce            « 1. texte »        étape numérotée
  « Astuce : texte »     encadré d'astuce (« Tip: » en anglais)   « Attention : texte »  encadré d'avertissement (« Warning: »)
  ligne entière commençant par « mintmail », « sudo », « python3 », « tools/ »  : bloc de commande
Dans une phrase : « ... » (nom d'un bouton ou d'une page) passe en gras ; (S), (touche T), Ctrl+K, F1… deviennent des touches ; `mintmail --reset` une commande.
"""
import html
import re
import unicodedata
from typing import List, Tuple

KEY_BG = "bgcolor='#808080' bgalpha='30%'"
HIT_BG = "bgcolor='#ffc83d' bgalpha='60%'"

_STEP = re.compile(r"^(\d{1,2})[.)]\s+(.*)$")
_TIP = re.compile(r"^(?:💡\s*)?(?:Astuce|Tip)\s*:\s*(.*)$")
_WARN = re.compile(r"^(?:⚠\s*)?(?:Attention|Important|Warning)\s*:\s*(.*)$")
_CMDLINE = re.compile(r"^(?:mintmail\b|/usr/bin/mintmail\b|sudo\s|python3\s|tools/|git\s|apt\s)")

_KEYS = (r"Ctrl\+Maj\+,|Ctrl\+Shift\+,|Ctrl\+[A-Za-z,.]|Alt\+[A-Za-z0-9]|F(?:1[0-2]|[1-9])|Échap|Esc(?:ape)?|Entrée|Enter|Suppr|Delete|Tab")          # i18n: skip  (expression régulière : jamais traduite)
_INLINE = re.compile(
    r"(?P<url>https?://[^\s<>«»]+)"
    r"|(?P<cmd>mintmail(?: (?:--?[\w-]+|[\w@:./-]+))+)"
    r"|(?P<quote>«[^»]{1,140}»)"
    r"|(?P<paren>\((?:touche |key )?(?P<pk>[A-Z!?#\\])(?: key)?\))"
    r"|(?P<touche>\b(?:touche|key) (?P<tk>[A-Z])\b)"
    r"|(?<!\w)(?P<key>" + _KEYS + r")(?!\w)")


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def keycap(k: str) -> str:
    return "<span font_family='monospace' weight='bold' %s> %s </span>" % (KEY_BG, esc(k))


def blocks(body: str) -> List[Tuple[str, str]]:
    """[(type, texte)] ; type ∈ p, bullet, step, tip, warn, code. Pour « step », le texte est « n|contenu »."""
    out = []
    for raw in (body or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = _STEP.match(line)
        if line.startswith("• "):
            out.append(("bullet", line[2:].strip()))
        elif m:
            out.append(("step", "%s|%s" % (m.group(1), m.group(2).strip())))
        elif _TIP.match(line):
            out.append(("tip", _TIP.match(line).group(1).strip()))
        elif _WARN.match(line):
            out.append(("warn", _WARN.match(line).group(1).strip()))
        elif _CMDLINE.match(line) and len(line) <= 160:
            out.append(("code", line))
        else:
            out.append(("p", line))
    return out


def markup(text: str) -> str:
    """Texte brut → balisage Pango sûr (tout est échappé d'abord ; seuls les liens http(s) deviennent cliquables)."""
    s = esc(text)

    def sub(m):
        if m.group("url"):
            url = m.group("url")
            tail = ""
            while url and url[-1] in ".,;:)!?":
                tail, url = url[-1] + tail, url[:-1]
            return "<a href=\"%s\">%s</a>%s" % (url.replace('"', "&quot;"), url, tail)
        if m.group("cmd"):
            return "<tt><b>%s</b></tt>" % m.group("cmd")
        if m.group("quote"):
            return "<b>%s</b>" % m.group("quote")
        if m.group("paren"):
            return keycap(html.unescape(m.group("pk")))
        if m.group("touche"):
            return m.group(0)[: -len(m.group("tk"))] + keycap(m.group("tk"))
        return keycap(html.unescape(m.group("key")))
    return _INLINE.sub(sub, s)


def norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _spans(text: str, query: str) -> List[Tuple[int, int]]:
    words = [w for w in re.split(r"\s+", norm(query).strip()) if w]
    n = norm(text)
    if not words or len(n) != len(text):
        return []
    found = sorted((m.start(), m.end()) for w in words for m in re.finditer(re.escape(w), n))
    merged = []
    for a, b in found:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def highlight(text: str, query: str) -> str:
    """Texte brut → balisage Pango avec les mots cherchés surlignés (sans accent ni casse)."""
    spans = _spans(text, query)
    if not spans:
        return esc(text)
    out, pos = [], 0
    for a, b in spans:
        out.append(esc(text[pos:a]))
        out.append("<span %s>%s</span>" % (HIT_BG, esc(text[a:b])))
        pos = b
    out.append(esc(text[pos:]))
    return "".join(out)


def plain(body: str) -> str:
    """Texte d'une rubrique sur une seule ligne, sans puces (pour les extraits de recherche)."""
    out = []
    for kind, t in blocks(body):
        out.append(t.split("|", 1)[1] if kind == "step" else t)
    return " · ".join(out)


def excerpt(text: str, query: str, width: int = 170) -> str:
    """Extrait d'environ `width` caractères centré sur la première occurrence (début du texte s'il n'y en a pas)."""
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    spans = _spans(text, query)
    start = max(0, (spans[0][0] if spans else 0) - 40)
    if start > 0:
        cut = text.rfind(" ", 0, start)
        start = cut + 1 if cut != -1 else start
    end = min(len(text), start + width)
    if end < len(text):
        cut = text.rfind(" ", start, end)
        end = cut if cut > start else end
    return ("… " if start > 0 else "") + text[start:end].strip() + (" …" if end < len(text) else "")


def tip_of_the_day(tips: List[str], ordinal: int, offset: int = 0) -> Tuple[int, str]:
    """Astuce stable pendant la journée (ordinal du jour) ; offset fait défiler (« Autre astuce »). Retourne (indice, texte)."""
    if not tips:
        return 0, ""
    i = (ordinal + offset) % len(tips)
    return i, tips[i]

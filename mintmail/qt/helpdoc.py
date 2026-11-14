"""Aide intégrée (F1) de l'interface Qt : pages HTML générées à partir du même contenu que la version GTK (help_content.py / help_format.py).
Logique pure, sans Qt : testable partout. Les couleurs viennent du thème courant (voir theme.resolve)."""
import datetime
import html
import re

from .. import APP_NAME, __version__
from .. import help_content as H
from .. import help_format as F
from ..i18n import tr
from ..store import CONFIG_DIR, DATA_DIR

HOME_ID = "home"
_KEY_SPLIT = re.compile(r"\s+(?:/|ou|or)\s+")


def ctx() -> dict:
    from ..log import LOG
    return {"version": __version__, "config": str(CONFIG_DIR), "data": str(DATA_DIR), "log": str(LOG)}


def nav(c=None):
    """Navigation : l'accueil puis chaque section [(id, icône, titre)]."""
    return [(HOME_ID, "🏠", tr("Accueil"))] + [(s["id"], s["icon"], s["title"]) for s in H.sections(c or ctx())]


def _e(s):
    return html.escape(s or "", quote=False)


def inline(text, t) -> str:
    """Texte brut → HTML sûr (tout est échappé ; seuls les liens http(s) deviennent cliquables ; touches, commandes et noms d'écrans mis en forme)."""
    key = "<span style='background:%s; color:%s; font-family:monospace; font-weight:600'>&nbsp;%%s&nbsp;</span>" % (t["hover"], t["text"])

    def sub(m):
        if m.group("url"):
            url, tail = m.group("url"), ""
            while url and url[-1] in ".,;:)!?":
                tail, url = url[-1] + tail, url[:-1]
            return "<a href=\"%s\" style='color:%s'>%s</a>%s" % (_e(url).replace('"', "&quot;"), t["accent"], _e(url), _e(tail))
        if m.group("cmd"):
            return "<tt><b>%s</b></tt>" % _e(m.group("cmd"))
        if m.group("quote"):
            return "<b>%s</b>" % _e(m.group("quote"))
        if m.group("paren"):
            return key % _e(m.group("pk"))
        if m.group("touche"):
            return _e(m.group(0)[: -len(m.group("tk"))]) + key % _e(m.group("tk"))
        return key % _e(m.group("key"))
    out, pos = [], 0
    for m in F._INLINE.finditer(text or ""):
        out.append(_e(text[pos:m.start()]))
        out.append(sub(m))
        pos = m.end()
    out.append(_e(text[pos:]))
    return "".join(out)


def _box(inner, colour, t):
    return ("<table width='100%%' cellspacing='0' cellpadding='9' style='margin:6px 0'><tr><td style='background:%s; border-left:3px solid %s'>%s</td></tr></table>"
            % (t["hover"], colour, inner))


def blocks_html(body, t) -> str:
    out, items = [], []

    def flush():
        if items:
            out.append("<ul style='margin:4px 0 4px 0'>%s</ul>" % "".join("<li>%s</li>" % i for i in items))
            items.clear()
    for kind, text in F.blocks(body):
        if kind == "bullet":
            items.append(inline(text, t))
            continue
        flush()
        if kind == "step":
            n, _, txt = text.partition("|")
            out.append("<p style='margin:4px 0'><b style='color:%s'>%s.</b>&nbsp; %s</p>" % (t["accent"], _e(n), inline(txt, t)))
        elif kind == "tip":
            out.append(_box("💡 " + inline(text, t), t["accent"], t))
        elif kind == "warn":
            out.append(_box("⚠ " + inline(text, t), "#d97706", t))
        elif kind == "code":
            out.append("<pre style='background:%s; padding:8px; margin:4px 0'>%s</pre>" % (t["field"], _e(text)))
        else:
            out.append("<p style='margin:4px 0'>%s</p>" % inline(text, t))
    flush()
    return "".join(out)


def _title(icon, title, tagline, t):
    return ("<h1 style='margin:0 0 2px 0; font-size:22px'>%s&nbsp; %s</h1><p style='color:%s; margin:0 0 10px 0'>%s</p>"
            % (_e(icon), _e(title), t["dim"], _e(tagline)))


def _shortcuts_table(keys, t):
    rows = "".join("<tr><td style='padding:3px 14px 3px 0; white-space:nowrap'>%s</td><td>%s</td></tr>" % (
        " ".join(inline("(%s)" % k, t) if len(k) == 1 else inline(k, t) for k in F_keys(k_)), _e(d)) for k_, d in keys)
    return "<table cellspacing='0'>%s</table>" % rows


def F_keys(keys):
    """« # / Suppr » → ['#', 'Suppr'] (même découpage que la version GTK)."""
    note = re.search(r"\(([^)]*)\)", keys)
    if note:
        keys = (keys[:note.start()] + keys[note.end():]).replace("…", "")
    return [p.strip() for p in _KEY_SPLIT.split(keys.strip()) if p.strip()] or [keys.strip()]


def home_html(t, c=None, ordinal=None, tip_offset=0) -> str:
    c = c or ctx()
    home, secs = H.home(), H.sections(c)
    ordinal = datetime.date.today().toordinal() if ordinal is None else ordinal
    idx, tip = F.tip_of_the_day(home["tips"], ordinal, tip_offset)
    title, lead = home["welcome"]
    out = [_title("📬", title, lead, t), "<h3>%s</h3>" % _e(tr("Bien démarrer en 4 étapes"))]
    for i, (st, tx, target) in enumerate(home["steps"], 1):
        out.append("<p style='margin:5px 0'><b style='color:%s'>%d.</b>&nbsp; <a href='sec:%s' style='color:%s'><b>%s</b></a> — %s</p>"
                   % (t["accent"], i, _e(target), t["accent"], _e(st), inline(tx, t)))
    out.append("<h3>%s</h3>%s" % (_e(tr("Astuce du jour")), _box("💡 " + inline(tip, t) + " &nbsp;<a href='tip:%d' style='color:%s'>%s</a>" % (
        tip_offset + 1, t["accent"], _e(tr("Autre astuce"))), t["accent"], t)))
    out.append("<h3>%s</h3>%s<p><a href='sec:shortcuts' style='color:%s'>%s</a></p>" % (
        _e(tr("Raccourcis essentiels")), _shortcuts_table(H.shortcuts()[:12], t), t["accent"], _e(tr("Tous les raccourcis →"))))
    out.append("<h3>%s</h3><table cellspacing='0' cellpadding='7'>" % _e(tr("Parcourir l'aide")))
    for i in range(0, len(secs), 2):
        out.append("<tr>")
        for s in secs[i:i + 2]:
            out.append("<td width='50%%'><a href='sec:%s' style='color:%s'><b>%s&nbsp; %s</b></a><br><span style='color:%s'>%s</span></td>"
                       % (_e(s["id"]), t["accent"], _e(s["icon"]), _e(s["title"]), t["dim"], _e(s["tagline"])))
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def section_html(sid, t, c=None) -> str:
    c = c or ctx()
    sec = next((s for s in H.sections(c) if s["id"] == sid), None)
    if sec is None:
        return home_html(t, c)
    out = [_title(sec["icon"], sec["title"], sec["tagline"], t)]
    for (title, body), kind in zip(sec["items"], sec["kinds"]):
        out.append("<h3 style='margin:14px 0 4px 0'>%s</h3>" % inline(title, t))
        if kind == "shortcuts":
            out.append(_shortcuts_table(H.shortcuts(), t))
        elif kind == "cli":
            out.append("".join("<pre style='background:%s; padding:6px; margin:2px 0'>%s</pre><p style='margin:0 0 6px 0; color:%s'>%s</p>"
                               % (t["field"], _e(cmd), t["dim"], _e(d)) for cmd, d in H.cli_options(c)))
        else:
            out.append(blocks_html(body, t))
    return "".join(out)


def results_html(query, t, c=None) -> str:
    c = c or ctx()
    hits = H.search_full(query, c)
    out = ["<h2>%s</h2>" % _e(tr("%d résultat%s pour « %s »") % (len(hits), "s" if len(hits) > 1 else "", query))]
    if not hits:
        return out[0] + "<p style='color:%s'>%s</p>" % (t["dim"], _e(tr("Aucun résultat : essayez un autre mot (sans accent, une partie de mot suffit).")))
    for h in hits:
        out.append("<p style='margin:10px 0 0 0'><span style='color:%s; font-size:11px'><b>%s</b></span><br><a href='sec:%s' style='color:%s'><b>%s</b></a><br>%s<br>"
                   "<a href='sec:%s' style='color:%s'>%s</a></p>" % (
                       t["dim"], _e(h["section"].upper()), _e(h["sid"]), t["accent"], _e(h["title"]),
                       _e(F.excerpt(F.plain(h["body"]), query)), _e(h["sid"]), t["accent"], _e(tr("Ouvrir la section"))))
    return "".join(out)


def page_html(target, t, c=None) -> str:
    """Page demandée par un lien : « sec:<id> », « tip:<n> » ou une recherche."""
    kind, _, arg = (target or "").partition(":")
    if kind == "sec":
        return home_html(t, c) if arg == HOME_ID else section_html(arg, t, c)
    if kind == "tip":
        return home_html(t, c, tip_offset=int(arg) if arg.isdigit() else 0)
    return results_html(arg or target, t, c)

"""Images en ligne des signatures (logos SVG, images « data: ») : l'éditeur Qt ne sait pas afficher un <svg> en ligne et les messagers
(Gmail, Outlook…) ne l'affichent pas non plus. On convertit donc :
  • pour l'AFFICHAGE (éditeur, aperçu) : <svg> → <img src="data:image/png;base64,…"> ;
  • pour l'ENVOI : <svg> et images « data: » → images PNG jointes « en ligne » (cid:), que tous les messagers affichent.
Le rendu SVG → PNG est fourni par l'interface (ui_svg.py) ; sans lui, rien n'est modifié. Logique pure, testée sans Qt."""
import base64
import hashlib
import html
import re

SVG_RE = re.compile(r"<svg\b.*?</svg\s*>", re.I | re.S)
DATA_IMG_RE = re.compile(r"""(<img\b[^>]*?\bsrc\s*=\s*)(["'])data:image/(png|jpeg|jpg|gif|webp);base64,([A-Za-z0-9+/=\s]+?)\2""", re.I | re.S)
MAX_SVG_BYTES = 300_000
MAX_IMAGES = 12
MAX_SIDE = 1200
_render = None


def set_renderer(fn) -> None:
    """fn(svg_text, largeur, hauteur) -> octets PNG (ou None si le SVG est illisible)."""
    global _render
    _render = fn


def has_renderer() -> bool:
    return _render is not None


def _num(v):
    m = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*(px)?\s*$", v or "")
    return float(m.group(1)) if m else None


def _attr(tag, name):
    m = re.search(r"""\b%s\s*=\s*(["'])(.*?)\1""" % name, tag, re.I | re.S)
    return m.group(2) if m else ""


def svg_size(svg):
    """(largeur, hauteur) en pixels logiques : attributs width/height, sinon viewBox, sinon 200×200 ; bornés."""
    tag = re.match(r"<svg\b[^>]*>", svg, re.I | re.S)
    tag = tag.group(0) if tag else ""
    w, h = _num(_attr(tag, "width")), _num(_attr(tag, "height"))
    vb = re.findall(r"[-0-9.]+", _attr(tag, "viewBox"))
    if (w is None or h is None) and len(vb) == 4 and float(vb[2]) > 0 and float(vb[3]) > 0:
        vw, vh = float(vb[2]), float(vb[3])
        w, h = (w, w * vh / vw) if w else (h * vw / vh, h) if h else (vw, vh)
    w, h = w or 200.0, h or 200.0
    k = min(1.0, MAX_SIDE / max(w, h))
    return max(1, round(w * k)), max(1, round(h * k))


def _alt(svg):
    tag = re.match(r"<svg\b[^>]*>", svg, re.I | re.S)
    return html.escape(_attr(tag.group(0), "aria-label") if tag else "", quote=True)


def _png_for(svg):
    if _render is None or len(svg) > MAX_SVG_BYTES:
        return None
    w, h = svg_size(svg)
    try:
        png = _render(svg, w, h)
    except Exception:
        return None
    return (png, w, h) if png else None


def _img_tag(src, w, h, alt):
    return '<img src="%s" width="%d" height="%d" alt="%s">' % (src, w, h, alt)


def to_display(html_text: str) -> str:
    """HTML prêt à être affiché par Qt : chaque <svg> devient une image PNG « data: » (un SVG illisible disparaît)."""
    if _render is None or not html_text or "<svg" not in html_text.lower():
        return html_text
    count = [0]

    def one(m):
        count[0] += 1
        got = _png_for(m.group(0)) if count[0] <= MAX_IMAGES else None
        if not got:
            return ""
        png, w, h = got
        return _img_tag("data:image/png;base64," + base64.b64encode(png).decode(), w, h, _alt(m.group(0)))
    return SVG_RE.sub(one, html_text)


def to_mail(html_text: str):
    """(html, images en ligne) pour l'envoi. Chaque <svg> et chaque image « data: » devient <img src="cid:…"> ;
    images = [[cid, sous-type, base64]] (sérialisable : l'envoi peut être différé)."""
    inline, seen = [], {}
    if not html_text:
        return html_text, inline

    def register(raw, subtype):
        digest = hashlib.sha256(raw).hexdigest()[:16]
        cid = "img%s@mintmail" % digest
        if cid not in seen:
            seen[cid] = True
            inline.append([cid, subtype, base64.b64encode(raw).decode()])
        return cid

    def svg_one(m):
        if len(inline) >= MAX_IMAGES:
            return ""
        got = _png_for(m.group(0))
        if not got:
            return m.group(0) if _render is None else ""
        png, w, h = got
        return _img_tag("cid:" + register(png, "png"), w, h, _alt(m.group(0)))

    def data_one(m):
        if len(inline) >= MAX_IMAGES:
            return m.group(0)
        try:
            raw = base64.b64decode(re.sub(r"\s+", "", m.group(4)))
        except Exception:
            return m.group(0)
        sub = "jpeg" if m.group(3).lower() == "jpg" else m.group(3).lower()
        return "%s%scid:%s%s" % (m.group(1), m.group(2), register(raw, sub), m.group(2))
    out = SVG_RE.sub(svg_one, html_text) if "<svg" in html_text.lower() else html_text
    out = DATA_IMG_RE.sub(data_one, out)
    return out, inline

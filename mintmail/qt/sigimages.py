"""Images en ligne des signatures (logos SVG, images « data: ») : l'éditeur Qt ne sait pas afficher un <svg> en ligne et les messagers
(Gmail, Outlook…) ne l'affichent pas non plus. On convertit donc :
  • pour l'AFFICHAGE (éditeur, aperçu) : <svg> → <img src="data:image/png;base64,…"> ;
  • pour l'ENVOI : <svg> et images « data: » → images PNG jointes « en ligne » (cid:), que tous les messagers affichent.
  • images DISTANTES (<img src="https://…">) : téléchargées une fois (réseau public seulement, taille bornée), gardées dans un cache local,
    puis traitées comme des images « data: » : visibles dans l'aperçu et l'éditeur (Qt n'en charge aucune seule) et jointes en ligne à l'envoi
    (la plupart des messageries bloquent les images distantes). La signature enregistrée garde l'adresse d'origine.
Le rendu SVG → PNG est fourni par l'interface (ui_svg.py) ; sans lui, rien n'est modifié. Logique pure, testée sans Qt."""
import base64
import hashlib
import html
import os
import re
import threading
import time

SVG_RE = re.compile(r"<svg\b.*?</svg\s*>", re.I | re.S)
DATA_IMG_RE = re.compile(r"""(<img\b[^>]*?\bsrc\s*=\s*)(["'])data:image/(png|jpeg|jpg|gif|webp);base64,([A-Za-z0-9+/=\s]+?)\2""", re.I | re.S)
REMOTE_IMG_RE = re.compile(r"""(<img\b[^>]*?\bsrc\s*=\s*)(["'])(https?://[^"'\s>]+)\2""", re.I | re.S)
MAX_REMOTE_BYTES = 2_000_000
FETCH_TIMEOUT = 8.0
MISS_SECONDS = 300
MAX_SVG_BYTES = 300_000
MAX_IMAGES = 12
MAX_SIDE = 1200
_render = None
FETCH = None             # remplaçable (tests) : fonction url -> octets


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
    if not html_text:
        return html_text
    html_text = _remote_sub(html_text, lambda raw, sub: "data:image/%s;base64,%s" % (sub, base64.b64encode(raw).decode()), False, None) \
        if "<img" in html_text.lower() else html_text
    if _render is None or "<svg" not in html_text.lower():
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
    if "<img" in html_text.lower():
        html_text = _remote_sub(html_text, lambda raw, sub: "cid:" + register(raw, sub), True, FETCH)
    out = SVG_RE.sub(svg_one, html_text) if "<svg" in html_text.lower() else html_text
    out = DATA_IMG_RE.sub(data_one, out)
    return out, inline



# ------------------------------------------------------------------ images distantes
_cache_dir = None
_mem = {}              # url -> (octets, sous-type) | None (échec récent) ; l'échec est retenu MISS_SECONDS secondes
_misses = {}
_lock = threading.Lock()


def set_cache_dir(path) -> None:
    global _cache_dir
    _cache_dir = str(path) if path else None


def _dir():
    if _cache_dir:
        return _cache_dir
    try:
        from ..store import DATA_DIR
        return os.path.join(str(DATA_DIR), "sigcache")
    except Exception:
        return None


def sniff(raw: bytes):
    """Sous-type d'une image reconnue à son contenu (jamais à son nom ni à l'en-tête du serveur) : png, jpeg, gif, webp, svg ; sinon None."""
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if raw[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    if b"<svg" in raw[:4096].lower():
        return "svg"
    return None


def http_fetch(url: str):
    """Télécharge une image distante : http(s) vers une adresse publique seulement (redirections revérifiées), au plus MAX_REMOTE_BYTES. None si échec."""
    import urllib.error
    import urllib.request
    from ..unsub import public_host

    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not newurl.lower().startswith(("http://", "https://")) or not public_host(newurl):
                raise urllib.error.URLError("redirection refusee")
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    if not public_host(url):
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MintMail", "Accept": "image/*"})
        with urllib.request.build_opener(Redirect).open(req, timeout=FETCH_TIMEOUT) as r:
            raw = r.read(MAX_REMOTE_BYTES + 1)
        return raw if 0 < len(raw) <= MAX_REMOTE_BYTES else None
    except Exception:
        return None


def _cache_path(url):
    d = _dir()
    return os.path.join(d, hashlib.sha256(url.encode()).hexdigest()[:40]) if d else None


def cached(url: str):
    """(octets, sous-type) déjà téléchargés, sans toucher au réseau ; None sinon."""
    with _lock:
        if url in _mem:
            return _mem[url]
    path = _cache_path(url)
    if path and os.path.isfile(path):
        try:
            raw = open(path, "rb").read()
            sub = sniff(raw)
            if sub:
                with _lock:
                    _mem[url] = (raw, sub)
                return raw, sub
        except OSError:
            pass
    return None


def get_remote(url: str, fetch=None, network=True):
    """(octets, sous-type) d'une image distante : cache, puis réseau si autorisé. None si indisponible (échec retenu 5 minutes)."""
    got = cached(url)
    if got or not network:
        return got
    with _lock:
        if time.time() - _misses.get(url, 0) < MISS_SECONDS:
            return None
    raw = (fetch or http_fetch)(url)
    sub = sniff(raw) if raw else None
    if not sub:
        with _lock:
            _misses[url] = time.time()
        return None
    with _lock:
        _mem[url] = (raw, sub)
    path = _cache_path(url)
    if path:
        try:
            os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
            with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
                f.write(raw)
        except OSError:
            pass
    return raw, sub


def remote_urls(html_text: str):
    return list(dict.fromkeys(html.unescape(m.group(3)) for m in REMOTE_IMG_RE.finditer(html_text or "")))[:MAX_IMAGES]


def prefetch(html_text: str, fetch=None) -> int:
    """Télécharge (et garde en cache) les images distantes d'une signature ; retourne le nombre d'images disponibles. À appeler hors du fil de l'interface."""
    return sum(1 for u in remote_urls(html_text) if get_remote(u, fetch))


def pending(html_text: str) -> bool:
    """Vrai s'il reste une image distante pas encore en cache (et pas en échec récent) : un téléchargement est à lancer."""
    with _lock:
        recent = {u for u, ts in _misses.items() if time.time() - ts < MISS_SECONDS}
    return any(u not in recent and cached(u) is None for u in remote_urls(html_text))


def _as_png(raw, sub):
    """Octets prêts pour Qt / un message : un SVG distant est rendu en PNG ; None si impossible."""
    if sub != "svg":
        return raw, sub
    svg = raw.decode("utf-8", "replace")
    got = _png_for(svg) if SVG_RE.search(svg) else None
    return (got[0], "png") if got else None


def _remote_sub(html_text, make, network, fetch):
    count = [0]

    def one(m):
        url = html.unescape(m.group(3))
        count[0] += 1
        if count[0] > MAX_IMAGES:
            return m.group(0)
        got = get_remote(url, fetch, network)
        got = _as_png(*got) if got else None
        if not got:
            return m.group(0)                      # indisponible : l'adresse d'origine reste (l'envoi n'est jamais bloqué)
        return "%s%s%s%s" % (m.group(1), m.group(2), make(*got), m.group(2))
    return REMOTE_IMG_RE.sub(one, html_text)

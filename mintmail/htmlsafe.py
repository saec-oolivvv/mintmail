"""Nettoyage du HTML reçu par e-mail : liste blanche de balises / attributs / schémas d'URL, reconstruction à partir d'un
analyseur (pas d'expressions régulières qui se contournent), + politique de sécurité de contenu (CSP) pour l'affichage.

Menaces visées : exécution de script (XSS) dans l'éditeur ou le lecteur, pistage par ressources distantes (pixels espions,
fonts, CSS, iframes), redirection / formulaires / ouverture de schémas dangereux (javascript:, file:, data:), usurpation
d'interface (position: fixed), contournement par imbrication (<scr<script>ipt>), entités ou caractères de contrôle.
"""
import base64
import hashlib
import html
import re
from html.parser import HTMLParser
from typing import List, Optional

MAX_INPUT = 30_000_000         # au-delà : tronqué (images intégrées comprises)

ALLOWED_TAGS = {
    "a", "abbr", "address", "article", "aside", "b", "bdi", "bdo", "big", "blockquote", "br", "caption", "center", "cite", "code",
    "col", "colgroup", "dd", "del", "dfn", "div", "dl", "dt", "em", "figcaption", "figure", "font", "footer", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "i", "img", "ins", "kbd", "li", "main", "mark", "nav", "ol", "p", "pre", "q", "s", "samp",
    "section", "small", "span", "strike", "strong", "sub", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "tt", "u",
    "ul", "var", "wbr",
}
VOID = {"br", "hr", "img", "wbr", "col"}
# balises supprimées AVEC leur contenu (scripts, cadres, objets, formulaires, vecteurs de mutation XSS : svg / math / template…)
DROP_WITH_CONTENT = {
    "script", "style", "iframe", "frame", "frameset", "object", "embed", "applet", "noscript", "template", "svg", "math", "head",
    "title", "textarea", "xmp", "plaintext", "noembed", "noframes", "select", "option", "button", "audio", "video", "canvas",
    "dialog", "marquee", "form", "input", "datalist", "portal", "slot", "map", "meta", "link", "base",
}
GLOBAL_ATTRS = {"title", "lang", "dir", "align", "style"}
TAG_ATTRS = {
    "a": {"href"}, "img": {"src", "alt", "width", "height", "border"}, "table": {"width", "height", "border", "cellpadding", "cellspacing", "bgcolor"},
    "td": {"colspan", "rowspan", "width", "height", "bgcolor", "valign", "nowrap"}, "th": {"colspan", "rowspan", "width", "height", "bgcolor", "valign", "nowrap"},
    "tr": {"bgcolor", "valign"}, "font": {"color", "size", "face"}, "col": {"span", "width"}, "colgroup": {"span", "width"},
    "ol": {"start", "type"}, "ul": {"type"}, "li": {"value"}, "hr": {"width", "size", "noshade"},
}
LINK_SCHEMES = {"http", "https", "mailto", "tel"}
CSS_PROPS = {
    "color", "background-color", "background", "font", "font-family", "font-size", "font-weight", "font-style", "text-align",
    "text-decoration", "text-indent", "text-transform", "line-height", "letter-spacing", "word-spacing", "margin", "margin-top",
    "margin-right", "margin-bottom", "margin-left", "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
    "border", "border-top", "border-right", "border-bottom", "border-left", "border-color", "border-style", "border-width",
    "border-radius", "border-collapse", "border-spacing", "width", "height", "max-width", "min-width", "max-height", "min-height",
    "display", "vertical-align", "white-space", "word-break", "word-wrap", "overflow-wrap", "list-style-type", "list-style",
    "table-layout", "direction", "text-shadow", "opacity", "clear",
}
_BAD_CSS = re.compile(r"url\s*\(|expression|javascript|vbscript|@import|behavior|binding|\\|<|>|/\*|image-set|attr\(|var\(", re.I)
_CTRL = re.compile(r"[\x00-\x20\x7f-\x9f\u200b-\u200f\u2028-\u202e\ufeff]")
_DATA_IMG = re.compile(r"^data:image/(png|gif|jpe?g|webp|bmp);base64,[A-Za-z0-9+/=\s]*$", re.I)


def clean_url(value: str, kind: str, allow_remote: bool) -> Optional[str]:
    """URL acceptée telle quelle, ou None. Les caractères de contrôle / espaces sont retirés avant l'examen du schéma
    (« java\\tscript: », « &#106;avascript: »…)."""
    v = (value or "").strip()
    probe = _CTRL.sub("", v).lower()
    if not probe:
        return None
    m = re.match(r"^([a-z][a-z0-9+.\-]*):", probe)
    if m is None:
        return v if kind == "link" and probe.startswith("#") else None   # relatif : refusé (sauf ancre) — pas de base d'URL
    scheme = m.group(1)
    if kind == "link":
        return v if scheme in LINK_SCHEMES else None
    if scheme == "cid":
        return v
    if scheme == "data":
        return v if _DATA_IMG.match(v) else None
    return v if scheme in ("http", "https") and allow_remote else None


def clean_style(value: str) -> str:
    """Déclarations CSS en liste blanche, sans url() ni construction dangereuse."""
    if _BAD_CSS.search(value or ""):
        value = ";".join(d for d in value.split(";") if not _BAD_CSS.search(d))
    out = []
    for decl in (value or "").split(";"):
        if ":" not in decl:
            continue
        prop, _, val = decl.partition(":")
        prop, val = prop.strip().lower(), val.strip()
        if prop in CSS_PROPS and val and len(val) <= 200 and not _BAD_CSS.search(val):
            out.append("%s:%s" % (prop, val))
    return ";".join(out)


def clean_css_block(css: str) -> str:
    """Contenu d'un <style> : retire @import / @font-face / commentaires, filtre toutes les déclarations (même dans @media)."""
    css = re.sub(r"/\*.*?\*/", "", css or "", flags=re.S)
    css = re.sub(r"@(import|charset|namespace)[^;{]*;", "", css, flags=re.I)
    css = re.sub(r"@(font-face|page|keyframes|-webkit-keyframes|document|supports)[^{}]*\{(?:[^{}]|\{[^{}]*\})*\}", "", css, flags=re.I)
    css = re.sub(r"\{([^{}]*)\}", lambda m: "{" + clean_style(m.group(1)) + "}", css)
    css = re.sub(r"[<>]", "", css)
    return css


class _Cleaner(HTMLParser):
    def __init__(self, keep_style: bool, allow_remote: bool, drop_ids: bool):
        super().__init__(convert_charrefs=True)
        self.keep_style, self.allow_remote, self.drop_ids = keep_style, allow_remote, drop_ids
        self.out: List[str] = []
        self.stack: List[str] = []
        self.skip: Optional[str] = None      # nom de la balise dont on ignore le contenu
        self.skip_depth = 0
        self.css: List[str] = []
        self.in_style = False

    # -- balises
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self.skip:
            if tag == self.skip:
                self.skip_depth += 1
            return
        if tag in DROP_WITH_CONTENT:
            if tag == "style" and self.keep_style:
                self.in_style = True
                return
            if tag not in VOID and tag not in ("meta", "link", "base", "input"):
                self.skip, self.skip_depth = tag, 1
            return
        if tag not in ALLOWED_TAGS:
            return                           # balise inconnue : supprimée, son texte est conservé
        keep = []
        allowed = GLOBAL_ATTRS | TAG_ATTRS.get(tag, set()) | ({"class"} if self.keep_style else set())
        for name, val in attrs:
            name = (name or "").lower()
            if name not in allowed or val is None and name not in ("nowrap", "noshade"):
                continue
            val = val or ""
            if name == "style":
                val = clean_style(val)
                if not val:
                    continue
            elif name == "href":
                val = clean_url(val, "link", False)
            elif name == "src":
                u = clean_url(val, "image", self.allow_remote)
                if u is None:
                    if clean_url(val, "image", True):          # image distante bloquée : on garde l'adresse, inerte
                        keep.append(' data-blocked-src="%s"' % html.escape(val.strip()[:500], quote=True))
                    continue
                val = u
            elif name == "class":
                val = re.sub(r"[^\w\- ]", "", val)[:100]
            else:
                val = _CTRL.sub(" ", val)[:300]
            if val is None:
                continue
            keep.append(' %s="%s"' % (name, html.escape(val, quote=True)))
        if tag == "a":
            keep.append(' rel="noopener noreferrer"')
        self.out.append("<%s%s>" % (tag, "".join(keep)))
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID and tag.lower() in ALLOWED_TAGS and not self.skip:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.skip:
            if tag == self.skip:
                self.skip_depth -= 1
                if self.skip_depth <= 0:
                    self.skip, self.skip_depth = None, 0
            return
        if tag == "style" and self.in_style:
            self.in_style = False
            return
        if tag in VOID or tag not in ALLOWED_TAGS or tag not in self.stack:
            return                           # fermeture orpheline : ignorée (pas de sortie du conteneur)
        while self.stack:
            top = self.stack.pop()
            self.out.append("</%s>" % top)
            if top == tag:
                break

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_style:
            self.css.append(data)
        else:
            self.out.append(html.escape(data, quote=False))

    def handle_comment(self, data):          # commentaires et conditionnels MSO : ignorés
        pass

    def handle_decl(self, decl):
        pass

    def handle_pi(self, data):
        pass

    def unknown_decl(self, data):
        pass

    def result(self) -> str:
        while self.stack:
            self.out.append("</%s>" % self.stack.pop())
        body = "".join(self.out)
        if self.keep_style and self.css:
            css = clean_css_block("".join(self.css))
            if css.strip():
                body = "<style>%s</style>%s" % (css, body)
        return body


def sanitize(h: str, keep_style: bool = False, allow_remote_images: bool = False, drop_ids: bool = True) -> str:
    """HTML nettoyé. keep_style : conserve les <style> filtrés (affichage des newsletters) ; faux pour l'éditeur."""
    h = (h or "")[:MAX_INPUT]
    c = _Cleaner(keep_style, allow_remote_images, drop_ids)
    try:
        c.feed(h)
        c.close()
    except Exception:                        # analyseur en difficulté : on retombe sur du texte brut échappé
        return "<pre>%s</pre>" % html.escape(re.sub(r"<[^>]*>", "", h)[:100000])
    return c.result()


# ------------------------------------------------------------------ politique de sécurité de contenu
def reader_csp(allow_remote_images: bool) -> str:
    img = "img-src data: cid:" + (" http: https:" if allow_remote_images else "")
    return ("default-src 'none'; %s; style-src 'unsafe-inline'; font-src data:; form-action 'none'; base-uri 'none'; "
            "frame-ancestors 'none'" % img)


def script_hash(js: str) -> str:
    return "'sha256-%s'" % base64.b64encode(hashlib.sha256(js.encode("utf-8")).digest()).decode()


def editor_csp(inline_script: str) -> str:
    """L'éditeur n'exécute QUE son propre script (empreinte), aucune ressource distante, aucun formulaire."""
    return ("default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src %s; form-action 'none'; base-uri 'none'"
            % script_hash(inline_script))


ALLOWED_OPEN_SCHEMES = ("http", "https", "mailto")


def safe_to_open(uri: str) -> Optional[str]:
    """Un lien cliqué ne peut ouvrir que http, https ou mailto (jamais file:, javascript:, smb:, ssh:, gestionnaires d'applications…).
    Retourne l'adresse débarrassée de ses caractères de contrôle (celle qu'il faut ouvrir), ou None si elle est refusée."""
    clean = _CTRL.sub("", uri or "")
    m = re.match(r"^([a-z][a-z0-9+.\-]*):", clean.lower())
    return clean if (m and m.group(1) in ALLOWED_OPEN_SCHEMES and len(clean) <= 4000) else None

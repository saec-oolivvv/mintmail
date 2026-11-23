"""Icônes vectorielles (traits fins, style « outline ») dessinées depuis du SVG intégré : aucune image à installer, couleur suivant le thème.
Sans QtSvg, `icon()` renvoie une icône vide et les boutons gardent leur texte."""
from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

try:
    from PySide6.QtSvg import QSvgRenderer
except ImportError:                                           # pragma: no cover
    QSvgRenderer = None

_L = lambda x1, y1, x2, y2: '<line x1="%s" y1="%s" x2="%s" y2="%s"/>' % (x1, y1, x2, y2)

PATHS = {
    "bold": '<path d="M6 4h8a4 4 0 0 1 0 8H6z"/><path d="M6 12h9a4 4 0 0 1 0 8H6z"/>',
    "italic": _L(19, 4, 10, 4) + _L(14, 20, 5, 20) + _L(15, 4, 9, 20),
    "underline": '<path d="M6 4v6a6 6 0 0 0 12 0V4"/>' + _L(4, 20, 20, 20),
    "strike": '<path d="M16 4H9a3 3 0 0 0-2.83 4"/><path d="M14 12a4 4 0 0 1 0 8H6"/>' + _L(4, 12, 20, 12),
    "bullets": _L(9, 6, 21, 6) + _L(9, 12, 21, 12) + _L(9, 18, 21, 18) + _L(4, 6, 4.01, 6) + _L(4, 12, 4.01, 12) + _L(4, 18, 4.01, 18),
    "numbered": _L(10, 6, 21, 6) + _L(10, 12, 21, 12) + _L(10, 18, 21, 18) + '<path d="M4 6h1v4"/><path d="M4 10h2"/><path d="M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"/>',
    "quote": _L(5, 5, 5, 19) + _L(10, 8, 20, 8) + _L(10, 12, 20, 12) + _L(10, 16, 16, 16),
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "clear": '<path d="M4 7V4h16v3"/><path d="M5 20h6"/><path d="M13 4 8 20"/><path d="m15 15 5 5"/><path d="m20 15-5 5"/>',
    "attach": '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
    "trash": '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>' + _L(10, 11, 10, 17) + _L(14, 11, 14, 17),
    "send": '<path d="m22 2-7 20-4-9-9-4z"/>' + _L(22, 2, 11, 13),
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "sign": '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "sparkles": '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 3v4"/><path d="M21 5h-4"/>',
    "template": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>' + _L(8, 13, 16, 13) + _L(8, 17, 14, 17),
    "chevron": '<polyline points="6 9 12 15 18 9"/>',
    "refresh": '<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/>',
    "eye": '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>',
    "print": '<polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
    "flag": '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/>' + _L(4, 22, 4, 15),
    "reply": '<polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/>',
    "replyall": '<polyline points="7 17 2 12 7 7"/><polyline points="12 17 7 12 12 7"/><path d="M22 18v-2a4 4 0 0 0-4-4H7"/>',
    "forward": '<polyline points="15 17 20 12 15 7"/><path d="M4 18v-2a4 4 0 0 1 4-4h12"/>',
    "archive": '<polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/>' + _L(10, 12, 14, 12),
    "spam": '<polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/>' + _L(12, 8, 12, 12) + _L(12, 16, 12.01, 16),
    "mail": '<path d="M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/><polyline points="22,6 12,13 2,6"/>',
    "star": '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    "pin": _L(12, 17, 12, 22) + '<path d="M9 3h6l-1 7 3 3v2H7v-2l3-3z"/>',
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    "checklist": '<polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    "user": '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "userplus": '<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/>' + _L(20, 8, 20, 14) + _L(23, 11, 17, 11),
    "more": _L(5, 12, 5.01, 12) + _L(12, 12, 12.01, 12) + _L(19, 12, 19.01, 12),
    "share": '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>' + _L(8.59, 13.51, 15.42, 17.49) + _L(15.41, 6.51, 8.59, 10.49),
    "ban": '<circle cx="12" cy="12" r="10"/>' + _L(4.93, 4.93, 19.07, 19.07),
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "search": '<circle cx="11" cy="11" r="8"/>' + _L(21, 21, 16.65, 16.65),
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "bell": '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/>' + _L(16, 2, 16, 6) + _L(8, 2, 8, 6) + _L(3, 10, 21, 10),
    "x": _L(18, 6, 6, 18) + _L(6, 6, 18, 18),
}

_cache = {}


def _pixmap(name, color, size, dpr):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="%s" stroke-width="2" '
           'stroke-linecap="round" stroke-linejoin="round">%s</svg>' % (color, PATHS[name]))
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    renderer.render(p)
    p.end()
    return pm


def icon(name, color="#6b7280", active=None, size=18, dpr=2.0):
    """QIcon du dessin `name` ; `active` : couleur quand le bouton est coché (sinon identique)."""
    if QSvgRenderer is None or name not in PATHS:
        return QIcon()
    key = (name, color, active, size, dpr)
    if key not in _cache:
        ic = QIcon()
        ic.addPixmap(_pixmap(name, color, size, dpr), QIcon.Normal, QIcon.Off)
        ic.addPixmap(_pixmap(name, active or color, size, dpr), QIcon.Normal, QIcon.On)
        ic.addPixmap(_pixmap(name, active or color, size, dpr), QIcon.Active, QIcon.On)
        _cache[key] = ic
    return _cache[key]


def icon_size(px=18):
    return QSize(px, px)

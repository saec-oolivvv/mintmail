"""Rendu SVG → PNG pour les signatures (QtSvg). Branché au démarrage de l'interface ; sans QtSvg, les logos SVG ne sont simplement pas affichés."""


def render_png(svg: str, w: int, h: int, scale: int = 2):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not r.isValid():
        return None
    img = QImage(max(1, w * scale), max(1, h * scale), QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p)
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def install() -> bool:
    try:
        import PySide6.QtSvg  # noqa: F401
    except Exception:
        return False
    from . import sigimages
    sigimages.set_renderer(render_png)
    return True

"""Pastille de messages non lus sur l'icône du programme, mise à jour en temps réel :
- fenêtre et barre des tâches / Alt-Tab : l'icône reçoit une pastille rouge avec le nombre (marche partout, y compris Cinnamon) ;
- zone de notification : même icône avec pastille ;
- bureau Linux compatible « Unity Launcher » (Plank, Dash to Dock, Ubuntu Dock, KDE Plasma) : compteur natif sur l'icône du lanceur ;
- macOS : pastille du Dock (Qt 6.5 ou plus)."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPixmap

from .. import notifyrules as NR
from . import ui_appicon as AI

_cache = {}
SIZES = (16, 22, 24, 32, 48, 64, 128)


def badge_icon(label: str) -> QIcon:
    """L'icône du programme avec une pastille rouge portant `label` (vide : icône normale)."""
    if not label:
        return AI.load()
    if label in _cache:
        return _cache[label]
    base, icon = AI.load(), QIcon()
    for s in SIZES:
        pm = base.pixmap(s, s)
        if pm.isNull():
            continue
        out = QPixmap(pm)
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        h = max(9.0, s * (0.5 if s >= 32 else 0.62))                      # petites tailles : pastille proportionnellement plus grande pour rester lisible
        w = h if len(label) == 1 else h * (1.35 if len(label) == 2 else 1.7)
        r = QRectF(out.width() - w - 0.5, 0.5, w, h)
        p.setPen(QColor("#ffffff"))
        p.setBrush(QColor("#e5322d"))
        p.drawRoundedRect(r, h / 2, h / 2)
        f = QFont()
        f.setBold(True)
        f.setPixelSize(max(6, int(h * (0.62 if len(label) == 1 else 0.52))))
        p.setFont(f)
        p.drawText(r, Qt.AlignCenter, label)
        p.end()
        icon.addPixmap(out)
    _cache[label] = icon if not icon.isNull() else base
    return _cache[label]


def _unity(count: int):
    """Signal « com.canonical.Unity.LauncherEntry.Update » : compteur natif du lanceur (sans effet si aucun bureau ne l'écoute)."""
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusMessage
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return
        msg = QDBusMessage.createSignal("/com/canonical/unity/launcherentry/mintmail", "com.canonical.Unity.LauncherEntry", "Update")
        msg.setArguments(["application://%s.desktop" % AI.DESKTOP_ID, {"count": int(count), "count-visible": count > 0}])
        bus.send(msg)
    except Exception:
        pass


def apply(window, unread: int):
    """Met à jour toutes les pastilles ; appelée à chaque changement du nombre de non lus."""
    label = NR.badge_label(unread)
    if getattr(window, "_badge_label", None) == label:
        return
    window._badge_label = label
    ic = badge_icon(label)
    try:
        window.setWindowIcon(ic)
        tray = getattr(window, "tray", None)
        if tray is not None:
            tray.setIcon(ic)
    except RuntimeError:
        pass
    _unity(int(unread or 0))
    setter = getattr(QGuiApplication, "setBadgeNumber", None)             # Qt 6.5+ : Dock de macOS
    if setter:
        try:
            setter(int(unread or 0))
        except Exception:
            pass

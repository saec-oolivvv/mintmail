"""Éléments visuels Qt : pastille d'initiales, lignes de la liste des messages, lignes de la barre latérale (peints à la main, aux couleurs du thème)."""
from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QListView, QListWidget, QStyle, QStyledItemDelegate, QWidget

from ..util import color_index, initials
from . import gestures as GS

InfoRole = Qt.UserRole + 2
KeyRole, LabelRole, CountRole, KindRole = Qt.UserRole, Qt.UserRole + 1, Qt.UserRole + 2, Qt.UserRole + 3
DepthRole, ToggleRole, FoldedRole, AccountRole, NameRole = (KindRole + n for n in (1, 2, 3, 4, 5))
CHEVRON_X = 8                                   # le chevron des dossiers occupe [CHEVRON_X, CHEVRON_X + 22] à droite de la marge de la ligne


class NavList(QListWidget):
    """Liste de la barre latérale : un clic sur le chevron (ou sur toute ligne de compte) plie / déplie sans changer de dossier."""
    toggled = Signal(str)

    def mousePressEvent(self, e):
        it = self.itemAt(e.position().toPoint())
        key = it.data(ToggleRole) if it is not None else ""
        if key:
            r = self.visualItemRect(it)
            left = r.left() + CHEVRON_X + 14 * min(int(it.data(DepthRole) or 0), 3)
            if it.data(KindRole) == "account" or left <= e.position().x() <= left + 24:
                self.toggled.emit(key)
                e.accept()
                return
        super().mousePressEvent(e)


def _c(hex_, alpha=None):
    c = QColor(hex_)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def draw_avatar(p: QPainter, rect: QRect, name: str, key: str, t: dict):
    """Disque coloré (couleur stable par expéditeur) avec les initiales."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(_c(t["avatars"][color_index(key or name or "?", len(t["avatars"]))]))
    p.drawEllipse(rect)
    f = QFont(p.font())
    f.setBold(True)
    f.setPixelSize(max(10, int(rect.height() * 0.38)))
    p.setFont(f)
    p.setPen(QColor("#ffffff"))
    p.drawText(rect, Qt.AlignCenter, initials(name or key or "?"))
    p.restore()


class AvatarWidget(QWidget):
    def __init__(self, t, size=44):
        super().__init__()
        self.t, self.name, self.key = t, "", ""
        self.setFixedSize(size, size)

    def set_sender(self, name, key):
        self.name, self.key = name, key
        self.setVisible(bool(name or key))
        self.update()

    def paintEvent(self, _e):
        if self.name or self.key:
            p = QPainter(self)
            draw_avatar(p, self.rect(), self.name, self.key, self.t)


class MessageList(QListView):
    """Liste des messages avec gestes : glisser à la souris (ou deux doigts sur le pavé tactile) vers la droite / la gauche ; court ou long = deux actions."""
    swiped = Signal(int, str)                        # (ligne, action)

    def __init__(self, delegate, cfg_fn):
        super().__init__()
        self._d, self._cfg, self._press, self._row, self._dx, self._wheel = delegate, cfg_fn, None, -1, 0.0, False
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self._finish)

    def _set(self, row, dx):
        self._row, self._dx = row, dx
        cfg, invert = self._cfg()
        self._d.swipe = (row, dx, GS.pick(dx, cfg, invert, self._wheel)[0]) if row >= 0 else None
        self.viewport().update()

    def _finish(self):
        row, dx, wheel = self._row, self._dx, self._wheel
        cfg, invert = self._cfg()
        act, _lvl = GS.pick(dx, cfg, invert, wheel)
        self._press, self._wheel = None, False
        self._set(-1, 0.0)
        if act and row >= 0:
            self.swiped.emit(row, act)

    def mousePressEvent(self, e):
        idx = self.indexAt(e.position().toPoint())
        self._press = (e.position().toPoint(), idx.row()) if idx.isValid() and e.button() == Qt.LeftButton else None
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press and (e.buttons() & Qt.LeftButton):
            d = e.position().toPoint() - self._press[0]
            if self._row >= 0 or (abs(d.x()) > 12 and abs(d.x()) > 2 * abs(d.y())):
                self._set(self._press[1], float(d.x()))
                e.accept()
                return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._row >= 0 and not self._wheel:
            self._finish()
            e.accept()
            return
        self._press = None
        super().mouseReleaseEvent(e)

    def wheelEvent(self, e):
        ax, ay = e.angleDelta().x(), e.angleDelta().y()
        if abs(ax) > abs(ay) and abs(ax) > 0:                    # défilement horizontal du pavé tactile
            if self._row < 0:
                idx = self.indexAt(e.position().toPoint())
                if not idx.isValid():
                    return super().wheelEvent(e)
                self._wheel, self._dx = True, 0.0
                self._row = idx.row()
            self._set(self._row, self._dx + ax * GS.WHEEL_GAIN * 0.5)
            self._idle.start(220)
            e.accept()
            return
        super().wheelEvent(e)


class MessageDelegate(QStyledItemDelegate):
    """Ligne de message : avatar, expéditeur + heure, objet (+ marques), extrait. Non lu : gras et pastille. Sélection et survol arrondis."""

    def __init__(self, t, height=78):
        super().__init__()
        self.t, self.h = t, height
        self.swipe = None                            # (ligne, décalage, action) pendant un geste

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.h)

    def paint(self, p, option, index):
        info, t = index.data(InfoRole), self.t
        p.save()
        sw = self.swipe
        if sw and sw[0] == index.row():
            self._paint_swipe(p, option.rect, sw[1], sw[2])
            p.translate(max(-option.rect.width(), min(option.rect.width(), sw[1])) * 0.9, 0)
        p.setRenderHint(QPainter.Antialiasing, True)
        card = QRectF(option.rect).adjusted(8, 2, -8, -2)
        selected, hover = bool(option.state & QStyle.State_Selected), bool(option.state & QStyle.State_MouseOver)
        if selected or hover:
            path = QPainterPath()
            path.addRoundedRect(card, t["rs"] + 4, t["rs"] + 4)
            p.fillPath(path, _c(t["accent"], 46) if selected else _c(t["hover"]))
        if selected:
            p.setPen(Qt.NoPen)
            p.setBrush(_c(t["accent"]))
            p.drawRoundedRect(QRectF(card.left(), card.top() + 14, 3, card.height() - 28), 1.5, 1.5)
        r = option.rect.adjusted(20, 0, -20, 0)
        av = QRect(r.left(), option.rect.top() + (self.h - 40) // 2, 40, 40)
        draw_avatar(p, av, info["sender"], info["email"] or info["sender"], t)
        x, w = av.right() + 13, r.right() - av.right() - 13
        top = option.rect.top() + 11
        unread = info["unread"]
        bold, plain = QFont(option.font), QFont(option.font)
        bold.setBold(True)
        bold.setPixelSize(14)
        plain.setPixelSize(13)
        small = QFont(plain)
        small.setPixelSize(12)
        # ligne 1 : expéditeur … heure
        p.setFont(small)
        tw = p.fontMetrics().horizontalAdvance(info["time"]) + 4
        p.setPen(_c(t["accent"]) if unread else _c(t["dim"]))
        p.drawText(QRect(x + w - tw, top, tw, 18), Qt.AlignRight | Qt.AlignVCenter, info["time"])
        p.setFont(bold if unread else plain)
        p.setPen(_c(t["text"]))
        p.drawText(QRect(x, top, w - tw - 6, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(info["sender"], Qt.ElideRight, w - tw - 6))
        # ligne 2 : objet + marques
        marks = ("📌 " if info["pinned"] else "") + ("★ " if info["starred"] else "") + ("📎" if info["attachments"] else "")
        p.setFont(small)
        mw = p.fontMetrics().horizontalAdvance(marks) + 4 if marks else 0
        if marks:
            p.setPen(_c("#f5b301") if info["starred"] else _c(t["dim"]))
            p.drawText(QRect(x + w - mw, top + 20, mw, 18), Qt.AlignRight | Qt.AlignVCenter, marks)
        sf = QFont(bold if unread else plain)
        sf.setBold(unread)
        p.setFont(sf)
        p.setPen(_c(t["text"]))
        p.drawText(QRect(x, top + 20, w - mw - 6, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(info["subject"] or "", Qt.ElideRight, w - mw - 6))
        # ligne 3 : extrait
        p.setFont(small)
        p.setPen(_c(t["dim"]))
        p.drawText(QRect(x, top + 40, w, 18), Qt.AlignLeft | Qt.AlignVCenter, p.fontMetrics().elidedText(info["snippet"], Qt.ElideRight, w))
        if unread:
            p.setPen(Qt.NoPen)
            p.setBrush(_c(t["accent"]))
            p.drawEllipse(QRectF(option.rect.left() + 8 + 3, option.rect.top() + self.h / 2 - 3.5, 7, 7))
        p.restore()


    def _paint_swipe(self, p, rect, dx, act):
        """Fond coloré de l'action visée sous la ligne qui glisse (gris tant que le seuil n'est pas atteint)."""
        label, color, glyph = GS.SWIPE_ACTIONS.get(act or "none", GS.SWIPE_ACTIONS["none"])
        p.fillRect(rect.adjusted(8, 2, -8, -2), _c(color if act else "#9ca3af", 255 if act else 120))
        p.setPen(_c("#ffffff"))
        f = QFont(p.font())
        f.setPixelSize(14)
        f.setBold(True)
        p.setFont(f)
        box = rect.adjusted(22, 0, -22, 0)
        p.drawText(box, (Qt.AlignLeft if dx > 0 else Qt.AlignRight) | Qt.AlignVCenter, ((glyph + "  ") if glyph else "") + (label if act else ""))


class NavDelegate(QStyledItemDelegate):
    """Barre latérale : intitulés de section, vues avec pastille de couleur, compteur en pilule."""

    def __init__(self, t):
        super().__init__()
        self.t = t

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 34 if index.data(KindRole) != "caption" else 34)

    def paint(self, p, option, index):
        t, kind = self.t, index.data(KindRole)
        label = index.data(LabelRole) or ""
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = option.rect
        if kind == "caption":
            f = QFont(option.font)
            f.setPixelSize(11)
            f.setBold(True)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)
            p.setFont(f)
            p.setPen(_c(t["dim"]))
            p.drawText(rect.adjusted(20, 10, -10, 0), Qt.AlignLeft | Qt.AlignVCenter, label.upper())
            p.restore()
            return
        if kind == "account":                                                            # section d'une boîte : pastille, nom, chevron, non lus repliés
            hover = bool(option.state & QStyle.State_MouseOver)
            if hover:
                path = QPainterPath()
                path.addRoundedRect(QRectF(rect).adjusted(10, 2, -10, -2), t["rs"] + 2, t["rs"] + 2)
                p.fillPath(path, _c(t["hover"]))
            p.setPen(Qt.NoPen)
            p.setBrush(_c(t["accent"]))
            p.drawEllipse(QRectF(rect.left() + 22, rect.center().y() - 4.5, 9, 9))
            f = QFont(option.font)
            f.setPixelSize(12)
            f.setBold(True)
            p.setFont(f)
            p.setPen(_c(t["dim"]))
            right = rect.right() - 34
            n = index.data(CountRole) or 0
            if n and bool(index.data(FoldedRole)):
                txt = str(n) if n < 1000 else "999+"
                w = p.fontMetrics().horizontalAdvance(txt) + 14
                pill = QRectF(right - w, rect.center().y() - 9, w, 18)
                p.setPen(Qt.NoPen)
                p.setBrush(_c(t["line"]))
                p.drawRoundedRect(pill, 9, 9)
                p.setPen(_c(t["dim"]))
                p.drawText(pill, Qt.AlignCenter, txt)
                right -= w + 8
            p.setPen(_c(t["text"]))
            tr_ = QRect(rect.left() + 40, rect.top(), right - rect.left() - 40, rect.height())
            p.drawText(tr_, Qt.AlignLeft | Qt.AlignVCenter, p.fontMetrics().elidedText(label, Qt.ElideRight, tr_.width()))
            cx, cy = rect.right() - 20, rect.center().y()
            path = QPainterPath()
            if bool(index.data(FoldedRole)):
                path.moveTo(cx - 2, cy - 4); path.lineTo(cx + 3, cy); path.lineTo(cx - 2, cy + 4)
            else:
                path.moveTo(cx - 4, cy - 2); path.lineTo(cx, cy + 3); path.lineTo(cx + 4, cy - 2)
            p.setPen(Qt.NoPen)
            p.setBrush(_c(t["dim"]))
            p.drawPath(path)
            p.restore()
            return
        selected, hover = bool(option.state & QStyle.State_Selected), bool(option.state & QStyle.State_MouseOver)
        card = QRectF(rect).adjusted(10, 2, -10, -2)
        if selected or hover:
            path = QPainterPath()
            path.addRoundedRect(card, t["rs"] + 2, t["rs"] + 2)
            p.fillPath(path, _c(t["accent"], 40) if selected else _c(t["hover"]))
        key, count, depth = index.data(KeyRole), index.data(CountRole) or 0, index.data(DepthRole) or 0
        toggle, folded = index.data(ToggleRole), bool(index.data(FoldedRole))
        left = rect.left() + 22 + 14 * min(int(depth), 3)
        if toggle and kind != "account":                                                # chevron « ▸ replié / ▾ déplié »
            cx, cy = rect.left() + CHEVRON_X + 14 * min(int(depth), 3) + 8, rect.center().y()
            path = QPainterPath()
            if folded:
                path.moveTo(cx - 2, cy - 4); path.lineTo(cx + 3, cy); path.lineTo(cx - 2, cy + 4)
            else:
                path.moveTo(cx - 4, cy - 2); path.lineTo(cx, cy + 3); path.lineTo(cx + 4, cy - 2)
            p.setPen(Qt.NoPen)
            p.setBrush(_c(t["dim"]))
            p.drawPath(path)
        tint = t["tints"].get(key) or t["dim"]
        p.setPen(Qt.NoPen)
        p.setBrush(_c(tint if selected or key in t["tints"] else t["dim"]))
        p.drawEllipse(QRectF(left, rect.center().y() - 4.5, 9, 9))
        f = QFont(option.font)
        f.setPixelSize(14)
        f.setBold(selected or bool(count) and key != "drafts")
        p.setFont(f)
        p.setPen(_c(t["accent"]) if selected else _c(t["text"]))
        pill_w = 0
        if count and key != "drafts":
            txt = str(count) if count < 1000 else "999+"
            pf = QFont(option.font)
            pf.setPixelSize(11)
            pf.setBold(True)
            p.setFont(pf)
            pill_w = p.fontMetrics().horizontalAdvance(txt) + 14
            pill = QRectF(rect.right() - 18 - pill_w, rect.center().y() - 9, pill_w, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(_c(t["accent"]) if key in ("inbox", "unread") else _c(t["line"]))
            p.drawRoundedRect(pill, 9, 9)
            p.setPen(QColor(t["on"]) if key in ("inbox", "unread") else _c(t["dim"]))
            p.drawText(pill, Qt.AlignCenter, txt)
            p.setFont(f)
            p.setPen(_c(t["accent"]) if selected else _c(t["text"]))
        p.setFont(f)
        p.setPen(_c(t["accent"]) if selected else _c(t["text"]))
        text_rect = QRect(left + 20, rect.top(), rect.right() - left - 20 - pill_w - 24, rect.height())
        p.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, p.fontMetrics().elidedText(label, Qt.ElideRight, text_rect.width()))
        p.restore()

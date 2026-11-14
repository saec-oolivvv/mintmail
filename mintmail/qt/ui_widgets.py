"""Éléments visuels Qt : pastille d'initiales, lignes de la liste des messages, lignes de la barre latérale (peints à la main, aux couleurs du thème)."""
from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QWidget

from ..util import color_index, initials

InfoRole = Qt.UserRole + 2
KeyRole, LabelRole, CountRole, KindRole = Qt.UserRole, Qt.UserRole + 1, Qt.UserRole + 2, Qt.UserRole + 3


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


class MessageDelegate(QStyledItemDelegate):
    """Ligne de message : avatar, expéditeur + heure, objet (+ marques), extrait. Non lu : gras et pastille. Sélection et survol arrondis."""

    def __init__(self, t, height=78):
        super().__init__()
        self.t, self.h = t, height

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.h)

    def paint(self, p, option, index):
        info, t = index.data(InfoRole), self.t
        p.save()
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
        selected, hover = bool(option.state & QStyle.State_Selected), bool(option.state & QStyle.State_MouseOver)
        card = QRectF(rect).adjusted(10, 2, -10, -2)
        if selected or hover:
            path = QPainterPath()
            path.addRoundedRect(card, t["rs"] + 2, t["rs"] + 2)
            p.fillPath(path, _c(t["accent"], 40) if selected else _c(t["hover"]))
        key, count, depth = index.data(KeyRole), index.data(CountRole) or 0, index.data(KindRole + 1) or 0
        left = rect.left() + 22 + 14 * min(int(depth), 3)
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

"""Éléments visuels Qt : pastille d'initiales, lignes de la liste des messages, lignes de la barre latérale (peints à la main, aux couleurs du thème)."""
from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QListView, QListWidget, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from ..util import color_index, initials
from ..i18n import tr
from . import gestures as GS

InfoRole = Qt.UserRole + 2
WIDE_MIN = 820                                   # liste plus large que ceci (disposition « liste seule ») : messages sur une ligne, comme Spark
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
            zone = 13 if it.data(KindRole) == "view" else 24          # vue (Boîte de réception, Envoyés) : seul le chevron plie, la pastille ouvre la vue
            if it.data(KindRole) == "account" or left <= e.position().x() <= left + zone:
                self.toggled.emit(key)
                e.accept()
                return
        super().mousePressEvent(e)


def _c(hex_, alpha=None):
    c = QColor(hex_)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def draw_avatar(p: QPainter, rect: QRect, name: str, key: str, t: dict, ring: bool = False):
    """Disque coloré (couleur stable par expéditeur) avec les initiales ; ring=True : cerclé d'un anneau, comme les avatars de Spark."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    color = _c(t["avatars"][color_index(key or name or "?", len(t["avatars"]))])
    if ring and rect.width() >= 24:
        p.setPen(QPen(color, 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(rect).adjusted(1, 1, -1, -1))
        rect = rect.adjusted(4, 4, -4, -4)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
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
    clickedRow = Signal(object)                      # clic simple terminé (bouton gauche relâché sans glissé) : QModelIndex à ouvrir

    def __init__(self, delegate, cfg_fn):
        super().__init__()
        self._d, self._cfg, self._press, self._row, self._dx, self._wheel = delegate, cfg_fn, None, -1, 0.0, False
        self.mouse_down = False                      # un bouton de la souris est enfoncé : la sélection ne doit PAS encore ouvrir le message (clic droit, glissé)
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

    def resizeEvent(self, e):
        super().resizeEvent(e)
        wide = self.viewport().width() >= WIDE_MIN
        if wide != self._d.wide:                                   # bascule ligne unique (large) / trois lignes (colonne étroite)
            self._d.wide = wide
            self.doItemsLayout()

    def mousePressEvent(self, e):
        idx = self.indexAt(e.position().toPoint())
        self._press = (e.position().toPoint(), idx.row()) if idx.isValid() and e.button() == Qt.LeftButton else None
        self.mouse_down = True
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
            self.mouse_down = False
            self._finish()                                           # glissé : l'action est décidée au relâchement, le message n'est jamais ouvert
            e.accept()
            return
        self._press = None
        super().mouseReleaseEvent(e)
        self.mouse_down = False
        if e.button() == Qt.LeftButton:
            idx = self.indexAt(e.position().toPoint())
            if idx.isValid():
                self.clickedRow.emit(idx)                            # vrai clic simple : c'est maintenant qu'on ouvre

    def leaveEvent(self, e):
        super().leaveEvent(e)
        if not (QApplication.mouseButtons() & (Qt.LeftButton | Qt.RightButton)):
            self.mouse_down = False

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.mouse_down = False

    IDLE_MS = 320                                    # pavé sans indication de phase (Linux) : le geste ne se termine qu'après ce silence
    IDLE_PHASE_MS = 500                             # avec les phases (macOS) : simple filet de sécurité, la fin vient de ScrollEnd

    def cancel_swipe(self):
        """Annule le geste en cours sans rien exécuter."""
        self._idle.stop()
        self._press, self._wheel = None, False
        self._set(-1, 0.0)

    def keyPressEvent(self, e):
        self.mouse_down = False                         # le clavier reprend la main : plus de clic en cours
        if e.key() == Qt.Key_Escape and self._row >= 0:
            self.cancel_swipe()
            e.accept()
            return
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        ax, ay = e.angleDelta().x(), e.angleDelta().y()
        phase = e.phase()
        horizontal = abs(ax) > abs(ay) and abs(ax) > 0
        if phase == Qt.ScrollMomentum and (horizontal or self._wheel):
            if self._wheel:
                self._finish()                                   # l'inertie commence = doigts levés : on décide tout de suite (sous le seuil = annulé)
            e.accept()                                           # l'inertie elle-même n'ajoute rien et ne lance jamais un nouveau geste
            return
        if phase == Qt.ScrollEnd and self._wheel:
            self._finish()                                       # doigts levés : on décide maintenant (sous le seuil = annulé)
            e.accept()
            return
        if horizontal:                                           # défilement horizontal du pavé tactile
            if self._row < 0:
                idx = self.indexAt(e.position().toPoint())
                if not idx.isValid():
                    return super().wheelEvent(e)
                self._wheel, self._dx = True, 0.0
                self._row = idx.row()
            self._set(self._row, self._dx + ax * GS.WHEEL_GAIN * 0.5)        # revenir vers l'origine réduit le glissement : sous le seuil, rien ne se passe
            self._idle.start(self.IDLE_PHASE_MS if phase != Qt.NoScrollPhase else self.IDLE_MS)
            e.accept()
            return
        super().wheelEvent(e)


class MessageDelegate(QStyledItemDelegate):
    """Ligne de message : avatar, expéditeur + heure, objet (+ marques), extrait. Non lu : gras et pastille. Sélection et survol arrondis."""

    def __init__(self, t, height=78):
        super().__init__()
        self.t, self.h = t, height
        self.select_mode = False
        self.wide = False                            # liste large : une ligne par message (expéditeur · objet — extrait · date)
        self.swipe = None                            # (ligne, décalage, action) pendant un geste

    def row_h(self):
        return max(48, self.h - 24) if self.wide else self.h

    HEAD = 30                                        # hauteur du titre de période (Aujourd'hui, Hier, mois…) au-dessus de la 1re ligne d'une période

    def _head(self, index):
        info = index.data(InfoRole)
        return info.get("section", "") if isinstance(info, dict) else ""

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.row_h() + (self.HEAD if self._head(index) else 0))

    def paint(self, p, option, index):
        head = self._head(index)
        if not head:
            return self._paint_row(p, option, index)
        p.save()
        f = QFont(option.font)
        f.setBold(True)
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(_c(self.t["dim"]))
        p.drawText(QRect(option.rect.left() + 20, option.rect.top() + 6, option.rect.width() - 30, self.HEAD - 8), Qt.AlignLeft | Qt.AlignVCenter, head)
        p.restore()
        opt = QStyleOptionViewItem(option)
        opt.rect = option.rect.adjusted(0, self.HEAD, 0, 0)
        self._paint_row(p, opt, index)

    def _background(self, p, option, selected, hover):
        """Fond d'une ligne : bulle arrondie avec filet (Aurora, Papier, Terminal) ou ligne à plat, sélection pleine (Ardoise)."""
        t = self.t
        rad = min(t["r"], 16) if t["r"] > 8 else t["rs"]
        if t.get("flat"):
            card = QRectF(option.rect).adjusted(8, 1, -8, -1)
            if selected or hover:
                path = QPainterPath()
                path.addRoundedRect(card, rad, rad)
                p.fillPath(path, _c(t["accent"], 70) if selected else _c(t["hover"]))
            return card
        card = QRectF(option.rect).adjusted(10, 3, -10, -3)
        path = QPainterPath()
        path.addRoundedRect(card, rad, rad)                                    # chaque message est une bulle : fond, filet, accent à la sélection
        p.fillPath(path, _c(t["hover"]) if hover and not selected else _c(t["card"]))
        if selected:
            p.fillPath(path, _c(t["accent"], 46))
        p.setPen(QPen(_c(t["accent"], 150) if selected else _c(t["line"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if selected:
            p.setPen(Qt.NoPen)
            p.setBrush(_c(t["accent"]))
            p.drawRoundedRect(QRectF(card.left(), card.top() + 14, 3, card.height() - 28), 1.5, 1.5)
        return card

    def _paint_row(self, p, option, index):
        info, t = index.data(InfoRole), self.t
        if self.wide:
            return self._paint_wide(p, option, index, info)
        p.save()
        sw = self.swipe
        if sw and sw[0] == index.row():
            self._paint_swipe(p, option.rect, sw[1], sw[2])
            p.translate(max(-option.rect.width(), min(option.rect.width(), sw[1])) * 0.9, 0)
        p.setRenderHint(QPainter.Antialiasing, True)
        selected, hover = bool(option.state & QStyle.State_Selected), bool(option.state & QStyle.State_MouseOver)
        self._background(p, option, selected, hover)
        r = option.rect.adjusted(20, 0, -20, 0)
        if self.select_mode:                                                   # case ronde à cocher, l'avatar se décale
            cy = option.rect.center().y()
            p.setPen(QPen(_c(t["accent"]) if selected else _c(t["dim"]), 1.6))
            p.setBrush(_c(t["accent"]) if selected else Qt.NoBrush)
            p.drawEllipse(QRectF(r.left() - 2, cy - 9, 18, 18))
            if selected:
                p.setPen(QPen(_c("#ffffff"), 2))
                p.drawLine(r.left() + 3, cy, r.left() + 6, cy + 4)
                p.drawLine(r.left() + 6, cy + 4, r.left() + 12, cy - 4)
            r = r.adjusted(26, 0, 0, 0)
        av = QRect(r.left(), option.rect.top() + (self.h - 40) // 2, 40, 40)
        draw_avatar(p, av, info["sender"], info["email"] or info["sender"], t, ring=bool(t.get("flat")))
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
        badge = (tr("⚠ Suspect") + "  ") if info.get("spam") else (tr("⚡ Important") + "  ") if info.get("prio") == 3 else ""
        marks = badge + ("%d✉  " % info["count"] if info.get("count") else "") + ("👁 " if info.get("read_by") else "") + ("📌 " if info["pinned"] else "") + ("★ " if info["starred"] else "") + ("📎" if info["attachments"] else "")
        p.setFont(small)
        mw = p.fontMetrics().horizontalAdvance(marks) + 4 if marks else 0
        if marks:
            p.setPen(_c("#dc2626") if info.get("spam") else _c(t["accent"]) if info.get("prio") == 3 else _c("#f5b301") if info["starred"] else _c(t["dim"]))
            p.drawText(QRect(x + w - mw, top + 20, mw, 18), Qt.AlignRight | Qt.AlignVCenter, marks)
        sf = QFont(bold if unread else plain)
        sf.setBold(unread)
        p.setFont(sf)
        p.setPen(_c(t["text"]))
        p.drawText(QRect(x, top + 20, w - mw - 6, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(info["subject"] or "", Qt.ElideRight, w - mw - 6))
        # ligne 3 : extrait
        p.setFont(small)
        ai = info.get("ai")
        p.setPen(_c(t["accent"]) if ai else _c(t["dim"]))                                  # résumé de l'IA en couleur d'accent
        line = ("✨ " + ai) if ai else info["snippet"]
        p.drawText(QRect(x, top + 40, w, 18), Qt.AlignLeft | Qt.AlignVCenter, p.fontMetrics().elidedText(line, Qt.ElideRight, w))
        if unread:
            p.setPen(Qt.NoPen)
            p.setBrush(_c(t["accent"]))
            p.drawEllipse(QRectF(option.rect.left() + 8 + 3, option.rect.top() + self.h / 2 - 3.5, 7, 7))
        p.restore()


    def _marks(self, info):
        badge = (tr("⚠ Suspect") + "  ") if info.get("spam") else (tr("⚡ Important") + "  ") if info.get("prio") == 3 else ""
        return badge + ("%d✉  " % info["count"] if info.get("count") else "") + ("👁 " if info.get("read_by") else "") + ("📌 " if info["pinned"] else "") \
            + ("★ " if info["starred"] else "") + ("📎" if info["attachments"] else "")

    def _paint_wide(self, p, option, index, info):
        """Liste large (comme Spark) : une ligne — avatar, expéditeur, objet suivi de l'extrait, marques, date."""
        t = self.t
        p.save()
        sw = self.swipe
        if sw and sw[0] == index.row():
            self._paint_swipe(p, option.rect, sw[1], sw[2])
            p.translate(max(-option.rect.width(), min(option.rect.width(), sw[1])) * 0.9, 0)
        p.setRenderHint(QPainter.Antialiasing, True)
        selected, hover = bool(option.state & QStyle.State_Selected), bool(option.state & QStyle.State_MouseOver)
        self._background(p, option, selected, hover)
        rect = option.rect
        h = rect.height()
        cy = rect.top() + h // 2
        unread = info["unread"]
        if unread:
            p.setPen(Qt.NoPen)
            p.setBrush(_c(t["accent"]))
            p.drawEllipse(QRectF(rect.left() + 11, cy - 3.5, 7, 7))
        x = rect.left() + 26
        if self.select_mode:
            p.setPen(QPen(_c(t["accent"]) if selected else _c(t["dim"]), 1.6))
            p.setBrush(_c(t["accent"]) if selected else Qt.NoBrush)
            p.drawEllipse(QRectF(x, cy - 9, 18, 18))
            x += 28
        draw_avatar(p, QRect(x, cy - 17, 34, 34), info["sender"], info["email"] or info["sender"], t, ring=bool(t.get("flat")))
        x += 34 + 14
        bold, plain, small = QFont(option.font), QFont(option.font), QFont(option.font)
        bold.setPixelSize(14)
        bold.setBold(True)
        plain.setPixelSize(14)
        small.setPixelSize(12)
        small.setBold(True)
        p.setFont(small)
        tw = p.fontMetrics().horizontalAdvance(info["time"]) + 6
        p.setPen(_c(t["accent"]) if unread else _c(t["dim"]))
        p.drawText(QRect(rect.right() - 24 - tw, rect.top(), tw, h), Qt.AlignRight | Qt.AlignVCenter, info["time"])
        end = rect.right() - 24 - tw - 12
        marks = self._marks(info)
        if marks:
            sm = QFont(option.font)
            sm.setPixelSize(12)
            p.setFont(sm)
            mw = p.fontMetrics().horizontalAdvance(marks) + 4
            p.setPen(_c("#dc2626") if info.get("spam") else _c("#f5b301") if info["starred"] else _c(t["dim"]))
            p.drawText(QRect(end - mw, rect.top(), mw, h), Qt.AlignRight | Qt.AlignVCenter, marks)
            end -= mw + 8
        p.setFont(bold if unread else plain)
        p.setPen(_c(t["text"]))
        sw_ = min(230, max(120, (end - x) // 4))
        p.drawText(QRect(x, rect.top(), sw_, h), Qt.AlignLeft | Qt.AlignVCenter, p.fontMetrics().elidedText(info["sender"], Qt.ElideRight, sw_))
        x += sw_ + 18
        if end - x > 40:
            subj = info["subject"] or ""
            p.setFont(bold if unread else plain)
            fm = p.fontMetrics()
            subj_t = fm.elidedText(subj, Qt.ElideRight, end - x)
            sw2 = fm.horizontalAdvance(subj_t)
            p.setPen(_c(t["text"]))
            p.drawText(QRect(x, rect.top(), sw2 + 2, h), Qt.AlignLeft | Qt.AlignVCenter, subj_t)
            rest = end - x - sw2 - 14
            ai = info.get("ai")
            line = ("✨ " + ai) if ai else info["snippet"]
            if rest > 40 and line:
                p.setFont(plain)
                p.setPen(_c(t["accent"]) if ai else _c(t["dim"]))
                p.drawText(QRect(x + sw2 + 14, rect.top(), rest, h), Qt.AlignLeft | Qt.AlignVCenter, p.fontMetrics().elidedText(line, Qt.ElideRight, rest))
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
        self.rail = False                                   # barre latérale réduite : pastilles seules

    def sizeHint(self, option, index):
        if self.rail and index.data(KindRole) == "caption":
            return QSize(option.rect.width(), 8)
        return QSize(option.rect.width(), 34 if index.data(KindRole) != "caption" else 34)

    def paint(self, p, option, index):
        t, kind = self.t, index.data(KindRole)
        label = index.data(LabelRole) or ""
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = option.rect
        if self.rail:
            if kind != "caption":
                selected, hover = bool(option.state & QStyle.State_Selected), bool(option.state & QStyle.State_MouseOver)
                if selected or hover:
                    path = QPainterPath()
                    path.addRoundedRect(QRectF(rect).adjusted(8, 2, -8, -2), t["rs"] + 2, t["rs"] + 2)
                    p.fillPath(path, _c(t["accent"], 40) if selected else _c(t["hover"]))
                key = index.data(KeyRole)
                p.setPen(Qt.NoPen)
                p.setBrush(_c((t["tints"].get(key) or t["dim"]) if key else t["dim"]))
                p.drawEllipse(QRectF(rect.center().x() - 5, rect.center().y() - 5, 10, 10))
                if (index.data(CountRole) or 0) and key != "drafts":
                    p.setBrush(_c(t["accent"]))
                    p.drawEllipse(QRectF(rect.center().x() + 7, rect.center().y() - 11, 7, 7))
            p.restore()
            return
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
        flat = bool(t.get("flat"))
        if selected or hover:
            path = QPainterPath()
            path.addRoundedRect(card, t["rs"] + 2, t["rs"] + 2)
            p.fillPath(path, (_c(t["accent"]) if flat else _c(t["accent"], 40)) if selected else _c(t["hover"]))   # Ardoise : sélection pleine
        sel_text = _c(t["on"]) if flat else _c(t["accent"])
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
        if kind == "acctview":                                                         # une boîte mail sous « Boîte de réception » / « Envoyés »
            draw_avatar(p, QRect(int(left) - 4, rect.center().y() - 9, 18, 18), label, label, t)
        else:
            tint = t["tints"].get(key) or t["dim"]
            p.setPen(Qt.NoPen)
            p.setBrush(_c(tint if selected or key in t["tints"] else t["dim"]))
            p.drawEllipse(QRectF(left, rect.center().y() - 4.5, 9, 9))
        f = QFont(option.font)
        f.setPixelSize(14)
        f.setBold(selected or bool(count) and key != "drafts" and kind != "acctview")
        p.setFont(f)
        p.setPen(sel_text if selected else _c(t["text"]))
        pill_w = 0
        if count and key != "drafts":
            txt = str(count) if count < 1000 else "999+"
            pf = QFont(option.font)
            pf.setPixelSize(11)
            pf.setBold(True)
            p.setFont(pf)
            pill_w = p.fontMetrics().horizontalAdvance(txt) + 14
            pill = QRectF(rect.right() - 18 - pill_w, rect.center().y() - 9, pill_w, 18)
            loud = key in ("inbox", "unread") and kind != "acctview"
            if not (flat and kind == "acctview"):
                p.setPen(Qt.NoPen)
                p.setBrush(_c(t["accent"]) if loud else _c(t["line"]))
                p.drawRoundedRect(pill, 9, 9)
            p.setPen(QColor(t["on"]) if loud or (flat and selected) else _c(t["dim"]))
            p.drawText(pill, Qt.AlignCenter, txt)
        p.setFont(f)
        p.setPen(sel_text if selected else _c(t["text"]))
        text_rect = QRect(left + 20, rect.top(), rect.right() - left - 20 - pill_w - 24, rect.height())
        p.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, p.fontMetrics().elidedText(label, Qt.ElideRight, text_rect.width()))
        p.restore()

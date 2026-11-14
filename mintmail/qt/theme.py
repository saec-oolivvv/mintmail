"""Thème de l'interface Qt SANS Qt : couleurs et feuille de style (QSS) construites à partir des mêmes styles que l'interface GTK
(Aurora, Papier, Terminal ; clair / sombre ; couleur d'accent). Testé partout : aucune couleur n'est laissée dans un format que Qt ne lit pas."""
import re

from ..themes import AVATARS, DEFAULT_STYLE, NAV_TINTS, STYLES

_RGBA = re.compile(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([0-9.]+)\s*\)")


def solid(c: str) -> str:
    """« rgba(255,255,255,0.055) » → « #0effffff » (#AARRGGBB, lu par Qt) ; « #rrggbb » inchangé."""
    m = _RGBA.fullmatch((c or "").strip())
    if not m:
        return c
    r, g, b = (int(m.group(i)) for i in (1, 2, 3))
    a = max(0, min(255, round(float(m.group(4)) * 255)))
    return "#%02x%02x%02x%02x" % (a, r, g, b)


def resolve(config, system_dark=False) -> dict:
    """Thème courant : couleurs (toutes en #rrggbb / #aarrggbb), arrondis, police, mode sombre."""
    style = config.get("style") or DEFAULT_STYLE
    style = style if style in STYLES else DEFAULT_STYLE
    mode = config.get("theme") or "system"
    dark = system_dark if mode == "system" else mode == "dark"
    meta = STYLES[style]
    t = {k: solid(v) for k, v in meta["dark" if dark else "light"].items() if k != "canvas"}
    t.update(accent=config.get("accent") or meta["accent"], style=style, dark=dark, r=meta["r"], rs=meta["rs"], rp=min(meta["rp"], 18),
             font=meta["font"], head=meta["head"], hw=meta["hw"], tints=dict(NAV_TINTS), avatars=list(AVATARS))
    # Qt ne superpose pas les teintes translucides sur un dégradé : on les compose sur le fond pour obtenir des aplats lisibles
    t["canvas"] = t["bg"]
    for k in ("side", "card", "panel", "hover", "field"):
        t[k] = _over(t[k], t["bg"])
    t["line"] = _over(t["line"], t["bg"])
    return t


def _over(fg: str, bg: str) -> str:
    """Compose une couleur #aarrggbb sur un fond #rrggbb → #rrggbb."""
    if len(fg) != 9 or not fg.startswith("#"):
        return fg
    a = int(fg[1:3], 16) / 255
    f = [int(fg[i:i + 2], 16) for i in (3, 5, 7)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(f[i] * a + b[i] * (1 - a)) for i in range(3))


def row_height(density="comfortable") -> int:
    return {"compact": 62, "comfortable": 78, "spacious": 90}.get(density, 78)


def build_qss(t: dict) -> str:
    r, rs, rp = t["r"], t["rs"], t["rp"]
    return """
* { font-family: %(font)s; }
QMainWindow, QDialog, QMessageBox { background: %(bg)s; color: %(text)s; }
QWidget { color: %(text)s; font-size: 14px; }
QLabel { background: transparent; }
#root { background: %(bg)s; }
#sidebar, #listcol, #readerwrap, #assistant { background: %(panel)s; border: 1px solid %(line)s; border-radius: %(rc)dpx; }
#sidebar { background: %(side)s; }
#readerhead { background: transparent; border: none; border-bottom: 1px solid %(line)s; border-radius: 0; }
#brand { font-size: 18px; font-weight: 800; color: %(text)s; }
#caption { color: %(dim)s; font-size: 11px; font-weight: 700; }
#dim { color: %(dim)s; }
#subject { font-size: 18px; font-weight: %(hw)s; }
#footer { color: %(dim)s; font-size: 12px; }
#updatebanner { background: %(card)s; border-bottom: 1px solid %(line)s; }
QProgressBar { background: %(line)s; border: none; border-radius: 3px; }
QProgressBar::chunk { background: %(accent)s; border-radius: 3px; }
#aicard { background: %(card)s; border: 1px solid %(line)s; border-radius: %(rc)dpx; margin: 8px 16px 0 16px; }
#aiwarn { color: #dc2626; font-weight: 700; }
#assistanthead { background: transparent; border: none; border-bottom: 1px solid %(line)s; border-radius: 0; }
#bubble_user { background: %(accent)s; color: %(on)s; border-radius: 16px; border-bottom-right-radius: 4px; padding: 10px 14px; }
#bubble_ai { background: %(card)s; border: 1px solid %(line)s; border-radius: 16px; border-bottom-left-radius: 4px; padding: 10px 14px; }
#planrow { background: %(hover)s; border-radius: %(rs)dpx; }
QListView, QListWidget { background: transparent; border: none; outline: 0; }
QListView::item, QListWidget::item { border: none; }
QDialog QListWidget::item { padding: 6px 10px; border-radius: %(rs)dpx; }
QDialog QListWidget::item:hover { background: %(hover)s; }
QDialog QListWidget::item:selected, QDialog QListWidget::item:selected:active, QDialog QListWidget::item:selected:!active { background: %(accent)s; color: %(on)s; }
QLineEdit, QTextEdit, QComboBox, QSpinBox, QPlainTextEdit {
    background: %(field)s; border: 1px solid %(line)s; border-radius: %(rs)dpx; padding: 7px 10px; selection-background-color: %(accent)s; selection-color: %(on)s; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid %(accent)s; }
QLineEdit#search { border-radius: %(rp)dpx; padding: 9px 16px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: %(card)s; border: 1px solid %(line)s; selection-background-color: %(accent)s; selection-color: %(on)s; }
QPushButton { background: %(card)s; border: 1px solid %(line)s; border-radius: %(rs)dpx; padding: 7px 14px; }
QPushButton:hover { background: %(hover)s; }
QPushButton:pressed { background: %(line)s; }
QPushButton#primary { background: %(accent)s; color: %(on)s; border: none; border-radius: %(rp)dpx; padding: 12px 18px; font-weight: 700; }
QPushButton#primary:hover { background: %(accent)s; }
QPushButton#flat, QToolButton#flat { background: transparent; border: none; border-radius: %(rs)dpx; padding: 7px 10px; color: %(dim)s; }
QPushButton#flat:hover, QToolButton#flat:hover { background: %(hover)s; color: %(text)s; }
QPushButton#flat:checked { background: %(hover)s; color: %(accent)s; }
QPushButton#flat:disabled { color: %(line)s; }
QPushButton#chip { background: %(hover)s; border: none; border-radius: %(rp)dpx; padding: 6px 14px; color: %(accent)s; font-weight: 600; }
QMenu { background: %(card)s; border: 1px solid %(line)s; border-radius: %(rc)dpx; padding: 8px; }
QMenu::item { padding: 8px 24px; border-radius: %(rs)dpx; margin: 1px 0; }
QMenu::item:selected { background: %(accent)s; color: %(on)s; }
QMenu::separator { height: 1px; background: %(line)s; margin: 5px 8px; }
QToolTip { background: %(card)s; color: %(text)s; border: 1px solid %(line)s; border-radius: %(rs)dpx; padding: 6px 10px; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 4px 2px; }
QScrollBar::handle:vertical { background: %(line)s; border-radius: 4px; min-height: 36px; }
QScrollBar::handle:vertical:hover { background: %(dim)s; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { background: none; height: 0; width: 0; border: none; }
QScrollBar:horizontal { height: 0; }
QSplitter::handle { background: transparent; }
QTabWidget::pane { border: 1px solid %(line)s; border-radius: %(rc)dpx; top: -1px; }
QTabBar::tab { background: transparent; padding: 9px 16px; color: %(dim)s; border: none; }
QTabBar::tab:selected { color: %(accent)s; border-bottom: 2px solid %(accent)s; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid %(dim)s; border-radius: 4px; background: %(field)s; }
QCheckBox::indicator:checked { background: %(accent)s; border-color: %(accent)s; }
QCalendarWidget QWidget { background: %(card)s; }
QToolBar { background: transparent; border: none; spacing: 4px; padding: 6px 10px; }
QStatusBar { background: transparent; color: %(dim)s; }
QStatusBar::item { border: none; }
""" % dict(t, r=r, rs=rs, rp=rp, rc=min(r, 18) + (4 if r > 8 else 0))

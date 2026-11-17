"""Réglages → Groupes : pour chaque groupe de la boîte de réception, « grouper » ou « afficher tout », en général et pour chaque boîte mail."""
from PySide6.QtWidgets import QCheckBox, QComboBox

from .. import groups as G
from ..i18n import tr
from .ui_cards import Page

INHERIT = "inherit"


def _mode_combo(current, inherit_label=None):
    c = QComboBox()
    if inherit_label:
        c.addItem(inherit_label, INHERIT)
    c.addItem(tr("Grouper (pastille à part)"), G.GROUP)
    c.addItem(tr("Afficher tout dans la boîte principale"), G.ALL)
    c.setCurrentIndex(max(0, c.findData(current)))
    return c


def groups_tab(win):
    cfg = win.cfg
    page = Page(tr("Groupes"), tr("Comme dans Spark : les notifications, newsletters, invitations… peuvent être regroupées sous une pastille au-dessus de la liste au lieu d'encombrer la boîte principale. Choisissez pour chaque groupe de le grouper ou d'afficher tous ses messages, en général puis, si besoin, boîte par boîte."))
    form = page.card(tr("Réglage général")).form()
    master = QCheckBox(tr("Regrouper les messages de la boîte de réception"))
    master.setChecked(bool(cfg.get("inbox_grouping", True)))
    master.toggled.connect(lambda v: _save_general(win, "inbox_grouping", bool(v)))
    form.addRow("", master)
    current = G.settings_for({"inbox_grouping": True, "group_modes": cfg.get("group_modes") or {}, "accounts": []}, "")["modes"]
    for key in G.ORDER:
        c = _mode_combo(current[key])
        c.currentIndexChanged.connect(lambda _i, c=c, k=key: _save_mode(win, None, k, c.currentData()))
        form.addRow(G.label(key), c)
    help_ = page.card(tr("Ce que contient chaque groupe"))
    for line in (tr("Épinglés : les messages que vous avez épinglés."),
                 tr("Attribués à moi : vous êtes le seul destinataire d'une vraie personne, ou une tâche ou une relance est posée dessus."),
                 tr("Invitations : invitations à un événement (agenda)."),
                 tr("Réponses aux invitations : accepté, refusé, peut-être."),
                 tr("Notifications : services, factures, alertes automatiques."),
                 tr("Newsletters : messages d'information avec lien de désabonnement.")):
        from PySide6.QtWidgets import QLabel
        lab = QLabel(line)
        lab.setWordWrap(True)
        help_.addWidget(lab)
    for acct in cfg.get("accounts") or []:
        if acct.get("demo") or not acct.get("id"):
            continue
        form = page.card(tr("Boîte mail : %s") % (acct.get("email") or acct.get("name") or acct["id"])).form()
        on = QComboBox()
        on.addItem(tr("Comme le réglage général"), INHERIT)
        on.addItem(tr("Regrouper cette boîte"), True)
        on.addItem(tr("Tout afficher, sans groupes"), False)
        v = acct.get("inbox_grouping")
        on.setCurrentIndex(0 if not isinstance(v, bool) else (1 if v else 2))
        on.currentIndexChanged.connect(lambda _i, on=on, a=acct["id"]: _save_account_on(win, a, on.currentData()))
        form.addRow(tr("Regroupement"), on)
        own = acct.get("group_modes") or {}
        for key in G.ORDER:
            c = _mode_combo(own.get(key, INHERIT), tr("Comme le réglage général"))
            c.currentIndexChanged.connect(lambda _i, c=c, a=acct["id"], k=key: _save_mode(win, a, k, c.currentData()))
            form.addRow(G.label(key), c)
    return page.finish()


def _save_general(win, key, value):
    win.cfg[key] = value
    win.cfg.save()
    win.main.reload()


def _account(win, aid):
    return next((a for a in win.cfg.get("accounts") or [] if a.get("id") == aid), None)


def _save_mode(win, aid, group, mode):
    if aid is None:
        modes = dict(win.cfg.get("group_modes") or {})
        modes[group] = mode
        win.cfg["group_modes"] = modes
    else:
        a = _account(win, aid)
        if a is None:
            return
        modes = dict(a.get("group_modes") or {})
        if mode == INHERIT:
            modes.pop(group, None)
        else:
            modes[group] = mode
        if modes:
            a["group_modes"] = modes
        else:
            a.pop("group_modes", None)
    win.cfg.save()
    win.main.reload()


def _save_account_on(win, aid, value):
    a = _account(win, aid)
    if a is None:
        return
    if isinstance(value, bool):
        a["inbox_grouping"] = value
    else:
        a.pop("inbox_grouping", None)
    win.cfg.save()
    win.main.reload()

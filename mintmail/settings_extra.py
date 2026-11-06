"""Pages de réglages : gestes & disposition, filtres & blocage, modèles de réponse."""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from .widgets import SWIPE_ACTIONS, icon

LAYOUTS = [("columns", "Colonnes : liste | lecture"), ("bottom", "Lecture en bas"), ("list", "Liste seule (lecture plein écran)")]
RULE_FIELDS = [("from", "L'expéditeur contient"), ("subject", "L'objet contient"), ("to", "Les destinataires contiennent")]
RULE_ACTIONS = [("archive", "Archiver"), ("trash", "Supprimer"), ("spam", "Mettre en spam"),
                ("read", "Marquer comme lu"), ("star", "Ajouter aux favoris"), ("pin", "Épingler")]


def _combo(options, active):
    c = Gtk.ComboBoxText()
    for k, v in options:
        c.append(k, v)
    c.set_active_id(active)
    return c


def _scrolled(widget):
    sw = Gtk.ScrolledWindow()
    sw.add(widget)
    return sw


# ------------------------------------------------------------------ gestes
def gestures_page(win):
    cfg = win.config
    grid = Gtk.Grid(column_spacing=14, row_spacing=10)
    grid.set_border_width(18)
    intro = Gtk.Label(xalign=0, label="Faites glisser un message vers la droite ou la gauche (souris, pavé tactile à deux "
                                      "doigts, écran tactile). Un glissement court déclenche l'action principale, un "
                                      "glissement long l'action secondaire.")
    intro.set_line_wrap(True)
    intro.get_style_context().add_class("dim")
    grid.attach(intro, 0, 0, 2, 1)
    lay = _combo(LAYOUTS, cfg["layout"])
    lay.connect("changed", lambda c: win.set_layout(c.get_active_id()))
    grid.attach(Gtk.Label(label="Disposition", xalign=1), 0, 1, 1, 1)
    grid.attach(lay, 1, 1, 1, 1)
    opts = [(k, v[0]) for k, v in SWIPE_ACTIONS.items()]
    for i, (key, label) in enumerate((("right", "Glisser vers la droite"), ("right_long", "… jusqu'au bout (droite)"),
                                      ("left", "Glisser vers la gauche"), ("left_long", "… jusqu'au bout (gauche)"))):
        c = _combo(opts, cfg["swipe"].get(key, "none"))

        def changed(combo, k=key):
            cfg["swipe"][k] = combo.get_active_id()
            cfg.save()
            win.reload_list()
        c.connect("changed", changed)
        grid.attach(Gtk.Label(label=label, xalign=1), 0, 2 + i, 1, 1)
        grid.attach(c, 1, 2 + i, 1, 1)
    inv = Gtk.Switch()
    inv.set_active(cfg["swipe_invert"])
    inv.set_halign(Gtk.Align.START)

    def inv_changed(sw, _p):
        cfg["swipe_invert"] = sw.get_active()
        cfg.save()
        win.reload_list()
    inv.connect("notify::active", inv_changed)
    grid.attach(Gtk.Label(label="Inverser le sens au pavé tactile", xalign=1), 0, 6, 1, 1)
    grid.attach(inv, 1, 6, 1, 1)
    return _scrolled(grid)


# ----------------------------------------------------------------- filtres
def _list_editor(win, title, key, placeholder, hint):
    cfg = win.config
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    head = Gtk.Label(xalign=0)
    head.set_markup("<b>%s</b>" % title)
    box.pack_start(head, False, False, 0)
    h = Gtk.Label(label=hint, xalign=0)
    h.set_line_wrap(True)
    h.get_style_context().add_class("dim")
    box.pack_start(h, False, False, 0)
    lb = Gtk.ListBox()
    lb.set_selection_mode(Gtk.SelectionMode.NONE)
    box.pack_start(lb, False, False, 0)
    add = Gtk.Box(spacing=6)
    entry = Gtk.Entry()
    entry.set_placeholder_text(placeholder)
    entry.set_hexpand(True)
    btn = Gtk.Button(label="Ajouter")
    add.pack_start(entry, True, True, 0)
    add.pack_start(btn, False, False, 0)
    box.pack_start(add, False, False, 0)

    def refresh():
        for ch in lb.get_children():
            lb.remove(ch)
        for v in cfg[key]:
            row = Gtk.Box(spacing=8)
            row.set_border_width(4)
            row.pack_start(Gtk.Label(label=v, xalign=0), True, True, 0)
            rm = Gtk.Button()
            rm.set_image(icon("list-remove-symbolic"))
            rm.set_relief(Gtk.ReliefStyle.NONE)
            rm.set_tooltip_text("Retirer")
            rm.connect("clicked", lambda _b, val=v: (cfg[key].remove(val), cfg.save(), refresh()))
            row.pack_end(rm, False, False, 0)
            lb.add(row)
        lb.show_all()

    def add_item(*_):
        v = entry.get_text().strip().lower()
        if v and v not in cfg[key]:
            cfg[key].append(v)
            cfg.save()
            entry.set_text("")
            refresh()
    btn.connect("clicked", add_item)
    entry.connect("activate", add_item)
    refresh()
    return box


def filters_page(win):
    cfg = win.config
    page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
    page.set_border_width(18)
    page.pack_start(_list_editor(
        win, "Expéditeurs bloqués", "blocked", "adresse@exemple.com ou @domaine.com",
        "Leurs messages vont directement à la corbeille (marqués comme lus)."), False, False, 0)
    page.pack_start(_list_editor(
        win, "Expéditeurs envoyés en spam", "spam_senders", "adresse@exemple.com ou @domaine.com",
        "Leurs messages vont directement dans le dossier Spam."), False, False, 0)

    head = Gtk.Label(xalign=0)
    head.set_markup("<b>Règles automatiques</b>")
    page.pack_start(head, False, False, 0)
    hint = Gtk.Label(xalign=0, label="Appliquées à chaque nouveau message de la boîte de réception.")
    hint.get_style_context().add_class("dim")
    page.pack_start(hint, False, False, 0)
    lb = Gtk.ListBox()
    lb.set_selection_mode(Gtk.SelectionMode.NONE)
    page.pack_start(lb, False, False, 0)
    form = Gtk.Box(spacing=6)
    f_field = _combo(RULE_FIELDS, "from")
    f_text = Gtk.Entry()
    f_text.set_placeholder_text("texte…")
    f_text.set_hexpand(True)
    f_act = _combo(RULE_ACTIONS, "archive")
    add = Gtk.Button(label="Ajouter la règle")
    for w in (f_field, f_text, f_act, add):
        form.pack_start(w, w is f_text, True, 0)
    page.pack_start(form, False, False, 0)
    apply_btn = Gtk.Button(label="Appliquer maintenant à la boîte de réception")
    apply_btn.set_halign(Gtk.Align.START)
    apply_btn.connect("clicked", lambda *_: win.apply_rules_now())
    page.pack_start(apply_btn, False, False, 0)
    names = dict(RULE_FIELDS)
    anames = dict(RULE_ACTIONS)

    def refresh():
        for ch in lb.get_children():
            lb.remove(ch)
        for r in cfg["rules"]:
            row = Gtk.Box(spacing=8)
            row.set_border_width(4)
            row.pack_start(Gtk.Label(xalign=0, label="%s « %s » → %s" % (
                names.get(r["field"], r["field"]), r["text"], anames.get(r["action"], r["action"]))), True, True, 0)
            rm = Gtk.Button()
            rm.set_image(icon("list-remove-symbolic"))
            rm.set_relief(Gtk.ReliefStyle.NONE)
            rm.connect("clicked", lambda _b, rule=r: (cfg["rules"].remove(rule), cfg.save(), refresh()))
            row.pack_end(rm, False, False, 0)
            lb.add(row)
        lb.show_all()

    def add_rule(*_):
        t = f_text.get_text().strip()
        if t:
            cfg["rules"].append({"field": f_field.get_active_id(), "text": t, "action": f_act.get_active_id()})
            cfg.save()
            f_text.set_text("")
            refresh()
    add.connect("clicked", add_rule)
    f_text.connect("activate", add_rule)
    refresh()
    return _scrolled(page)


# ----------------------------------------------------------------- modèles
def templates_page(win):
    cfg = win.config
    page = Gtk.Box(spacing=12)
    page.set_border_width(14)
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    lb = Gtk.ListBox()
    sw = Gtk.ScrolledWindow()
    sw.set_size_request(200, -1)
    sw.add(lb)
    left.pack_start(sw, True, True, 0)
    new = Gtk.Button(label="＋ Nouveau modèle")
    left.pack_start(new, False, False, 0)
    page.pack_start(left, False, False, 0)
    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    name = Gtk.Entry()
    name.set_placeholder_text("Nom du modèle")
    tv = Gtk.TextView()
    tv.set_monospace(True)
    tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    tsw = Gtk.ScrolledWindow()
    tsw.add(tv)
    btns = Gtk.Box(spacing=6)
    save = Gtk.Button(label="Enregistrer")
    save.get_style_context().add_class("suggested-action")
    rm = Gtk.Button(label="Supprimer")
    btns.pack_start(save, False, False, 0)
    btns.pack_start(rm, False, False, 0)
    hint = Gtk.Label(xalign=0, label="Contenu HTML. Insertion depuis le bouton « Modèles » de la fenêtre de rédaction.")
    hint.get_style_context().add_class("dim")
    for w, ex in ((name, False), (hint, False), (tsw, True), (btns, False)):
        right.pack_start(w, ex, ex, 0)
    page.pack_start(right, True, True, 0)
    state = {"i": None}
    buf = tv.get_buffer()

    def refresh(select=None):
        for ch in lb.get_children():
            lb.remove(ch)
        for i, t in enumerate(cfg["templates"]):
            r = Gtk.ListBoxRow()
            r.idx = i
            l = Gtk.Label(label=t["name"], xalign=0)
            l.set_border_width(8)
            r.add(l)
            lb.add(r)
        lb.show_all()
        if select is not None and cfg["templates"]:
            lb.select_row(lb.get_row_at_index(min(select, len(cfg["templates"]) - 1)))

    def selected(_lb, row):
        if row is None:
            return
        state["i"] = row.idx
        t = cfg["templates"][row.idx]
        name.set_text(t["name"])
        buf.set_text(t["html"])

    def on_new(*_):
        cfg["templates"].append({"name": "Nouveau modèle", "html": "<p>Bonjour,</p>"})
        cfg.save()
        refresh(len(cfg["templates"]) - 1)

    def on_save(*_):
        i = state["i"]
        if i is None or i >= len(cfg["templates"]):
            return
        cfg["templates"][i] = {"name": name.get_text().strip() or "Sans titre",
                               "html": buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)}
        cfg.save()
        refresh(i)
        win.toast.popup("Modèle enregistré", timeout=2)

    def on_rm(*_):
        i = state["i"]
        if i is not None and i < len(cfg["templates"]):
            del cfg["templates"][i]
            cfg.save()
            state["i"] = None
            name.set_text("")
            buf.set_text("")
            refresh(0)
    lb.connect("row-selected", selected)
    new.connect("clicked", on_new)
    save.connect("clicked", on_save)
    rm.connect("clicked", on_rm)
    refresh(0)
    return page

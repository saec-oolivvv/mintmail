"""Pages de réglages : gestes & disposition, filtres & blocage, modèles de réponse, aide & synchronisation."""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from . import APP_NAME, __version__
from .widgets import SWIPE_ACTIONS, icon

LAYOUTS = [("columns", "Colonnes : liste | lecture"), ("bottom", "Lecture en bas"), ("list", "Liste seule (lecture plein écran)")]
RULE_FIELDS = [("from", "L'expéditeur contient"), ("subject", "L'objet contient"), ("to", "Les destinataires contiennent")]
RULE_ACTIONS = [("archive", "Archiver"), ("trash", "Supprimer"), ("spam", "Mettre en spam"),
                ("read", "Marquer comme lu"), ("star", "Ajouter aux favoris"), ("pin", "Épingler"),
                ("move", "Ranger dans le dossier →")]


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
    thr = Gtk.Switch()
    thr.set_active(bool(cfg.get("threads", True)))
    thr.set_halign(Gtk.Align.START)

    def thr_changed(sw, _p):
        cfg["threads"] = sw.get_active()
        cfg.save()
        win.reload_list(full=True)
    thr.connect("notify::active", thr_changed)
    grid.attach(Gtk.Label(label="Regrouper en conversations", xalign=1), 0, 7, 1, 1)
    grid.attach(thr, 1, 7, 1, 1)
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
    f_folder = Gtk.Entry()
    f_folder.set_placeholder_text("dossier (pour « Ranger »)")
    f_folder.set_width_chars(16)
    add = Gtk.Button(label="Ajouter la règle")
    for w in (f_field, f_text, f_act, f_folder, add):
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
                names.get(r["field"], r["field"]), r["text"], anames.get(r["action"], r["action"]) + ((" « %s »" % r["folder"]) if r.get("folder") else ""))), True, True, 0)
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
            rule = {"field": f_field.get_active_id(), "text": t, "action": f_act.get_active_id()}
            if rule["action"] == "move":
                from .ai_engine import sanitize_folder_name
                rule["folder"] = sanitize_folder_name(f_folder.get_text())
                if not rule["folder"]:
                    win.toast.popup("Indiquez le dossier de destination", timeout=3)
                    return
            cfg["rules"].append(rule)
            cfg.save()
            f_text.set_text("")
            f_folder.set_text("")
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
            r.set_border_width(8)
            l = Gtk.Label(label=t["name"], xalign=0)
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


# ------------------------------------------------------------------ synchronisation
_SYNC_NOUNS = {"rules": "règles", "templates": "modèles", "blocked": "expéditeurs bloqués",
               "spam_senders": "expéditeurs en spam", "saved_searches": "recherches", "signatures": "signatures"}


def p2p_page(win):
    """Synchronisation des préférences entre machines du même réseau (code de jumelage obligatoire)."""
    import secrets
    import socket
    import threading
    from .p2p import MIN_SECRET, local_ip
    cfg = win.config
    grid = Gtk.Grid(column_spacing=14, row_spacing=10)
    grid.set_border_width(18)
    alive = {"v": True}

    def label(text, dim=True, wrap=True):
        l = Gtk.Label(xalign=0, label=text)
        l.set_line_wrap(wrap)
        if dim:
            l.get_style_context().add_class("dim")
        return l
    title = label("Synchronisation entre machines", dim=False)
    title.get_style_context().add_class("list-title")
    grid.attach(title, 0, 0, 2, 1)
    grid.attach(label("Tout est synchronisé automatiquement entre vos machines MintMail du même réseau dès qu'elles se voient : "
                      "comptes (avec leurs mots de passe), signatures, IA (clé API), modèles de réponse rapide, règles, "
                      "blocages, recherches enregistrées et apparence. Les suppressions sont propagées aussi. "
                      "Les échanges sont authentifiés et chiffrés ; le courrier n'est pas échangé (chaque machine le "
                      "télécharge depuis son serveur). Utilisez le même code de jumelage partout."),
                0, 1, 2, 1)

    # --- code de jumelage
    secret = Gtk.Entry()
    secret.set_visibility(False)
    secret.set_hexpand(True)
    secret.set_text(cfg.get("p2p_secret") or "")
    secret.set_placeholder_text("%d caractères minimum, identique sur les deux machines" % MIN_SECRET)
    show = Gtk.CheckButton(label="Afficher")
    show.connect("toggled", lambda b: secret.set_visibility(b.get_active()))
    gen = Gtk.Button(label="Générer")
    apply_btn = Gtk.Button(label="Appliquer")
    srow = Gtk.Box(spacing=6)
    for w, ex in ((secret, True), (show, False), (gen, False), (apply_btn, False)):
        srow.pack_start(w, ex, ex, 0)
    grid.attach(Gtk.Label(label="Code de jumelage", xalign=1), 0, 2, 1, 1)
    grid.attach(srow, 1, 2, 1, 1)

    def on_generate(_b):
        secret.set_text(secrets.token_urlsafe(12))
        show.set_active(True)
    gen.connect("clicked", on_generate)

    # --- activation
    enabled = Gtk.Switch()
    enabled.set_active(bool(cfg["p2p_enabled"]))
    enabled.set_halign(Gtk.Align.START)
    guard = {"busy": False}

    def apply_settings(*_):
        code = secret.get_text().strip()
        want = enabled.get_active()
        if want and len(code) < MIN_SECRET:
            win.toast.popup("Définissez d'abord un code de jumelage (%d caractères minimum)" % MIN_SECRET, timeout=4)
            guard["busy"] = True
            enabled.set_active(False)
            guard["busy"] = False
            want = False
        cfg["p2p_secret"], cfg["p2p_enabled"] = code, want
        cfg.save()
        win._init_sync()
        refresh()

    def on_switch(sw, _p):
        if not guard["busy"]:
            apply_settings()
    enabled.connect("notify::active", on_switch)
    apply_btn.connect("clicked", apply_settings)
    secret.connect("activate", apply_settings)
    grid.attach(Gtk.Label(label="Synchronisation activée", xalign=1), 0, 3, 1, 1)
    grid.attach(enabled, 1, 3, 1, 1)

    # --- état, identifiant, pairs
    state_lbl = label("")
    id_lbl = Gtk.Label(xalign=0)
    id_lbl.set_selectable(True)
    peers_lbl = label("")
    grid.attach(Gtk.Label(label="État", xalign=1), 0, 4, 1, 1)
    grid.attach(state_lbl, 1, 4, 1, 1)
    grid.attach(Gtk.Label(label="Cet appareil", xalign=1), 0, 5, 1, 1)
    grid.attach(id_lbl, 1, 5, 1, 1)
    grid.attach(Gtk.Label(label="Pairs détectés", xalign=1), 0, 6, 1, 1)
    grid.attach(peers_lbl, 1, 6, 1, 1)

    sync_btn = Gtk.Button(label="↔ Synchroniser maintenant")
    sync_btn.set_halign(Gtk.Align.START)

    def do_sync(_b):
        sync_btn.set_sensitive(False)

        def work():
            res = win.sync_engine.sync_now() or {}

            def done():
                sync_btn.set_sensitive(True)
                if not win.sync_engine.can_run():
                    msg = "Synchronisation inactive (code de jumelage requis)"
                elif not res.get("peers_checked"):
                    msg = "Aucune autre machine détectée"
                elif res.get("failed") and not res.get("applied"):
                    msg = "Échange impossible : %s" % (win.sync_engine.last_error or "machine injoignable")
                else:
                    msg = ("%d élément(s) reçu(s) — %s" % (res["applied"], win.sync_engine.last_summary)) if res["applied"] else "Tout est à jour"
                win.toast.popup(msg, timeout=3)
                refresh()
                return False
            GLib.idle_add(done)
        threading.Thread(target=work, daemon=True).start()
    sync_btn.connect("clicked", do_sync)
    scan_btn = Gtk.Button(label="🔍 Rechercher les machines")
    scan_btn.set_tooltip_text("Sonde le réseau local (utile si la détection automatique est bloquée par la box ou un VPN)")

    def do_scan(_b):
        scan_btn.set_sensitive(False)
        win.toast.popup("Recherche des machines sur le réseau local…", timeout=3)

        def work():
            n = win.sync_engine.scan_now()

            def done():
                scan_btn.set_sensitive(True)
                win.toast.popup("%d machine(s) trouvée(s)" % n if win.sync_engine.can_run()
                                else "Synchronisation inactive (code de jumelage requis)", timeout=4)
                refresh()
                return False
            GLib.idle_add(done)
        threading.Thread(target=work, daemon=True).start()
    scan_btn.connect("clicked", do_scan)
    brow = Gtk.Box(spacing=8)
    brow.pack_start(sync_btn, False, False, 0)
    brow.pack_start(scan_btn, False, False, 0)
    grid.attach(brow, 1, 7, 1, 1)

    # --- pairs statiques (secours si la découverte automatique est bloquée)
    grid.attach(label("Secours si la découverte automatique est bloquée (isolation Wi-Fi de certaines box) : "
                      "adresse IP de l'autre machine. Votre adresse : %s" % local_ip()), 0, 8, 2, 1)
    peer_entry = Gtk.Entry()
    peer_entry.set_placeholder_text("192.168.1.42 ou 192.168.1.42:54322")
    peer_entry.set_text(", ".join(cfg.get("p2p_static_peers") or []))
    peer_entry.set_hexpand(True)
    save_peers_btn = Gtk.Button(label="Enregistrer")
    test_peer_btn = Gtk.Button(label="Tester")

    def parse_peers(text):
        out = []
        for tok in text.replace(",", " ").split():
            host, sep, port = tok.partition(":")
            if not host or any(c in host for c in "/\\"):
                continue
            if sep and (not port.isdigit() or not 0 < int(port) < 65536):
                continue
            if tok not in out:
                out.append(tok)
        return out

    def save_peers(_b):
        lst = parse_peers(peer_entry.get_text())
        cfg["p2p_static_peers"] = lst
        cfg.save()
        win._init_sync()
        win.toast.popup("%d pair(s) statique(s) enregistré(s)" % len(lst), timeout=3)
    save_peers_btn.connect("clicked", save_peers)

    def test_peer(_b):
        lst = parse_peers(peer_entry.get_text())
        if not lst:
            return
        host, _, port = lst[0].partition(":")
        port = int(port) if port else int(cfg.get("p2p_port", 54322))

        def work():
            try:
                socket.create_connection((host, port), timeout=3).close()
                msg = "Connexion TCP vers %s:%d : OK" % (host, port)
            except OSError as e:
                msg = "Impossible de joindre %s:%d (%s)" % (host, port, e.strerror or e)
            GLib.idle_add(lambda: (win.toast.popup(msg, timeout=4), False)[1])
        threading.Thread(target=work, daemon=True).start()
    test_peer_btn.connect("clicked", test_peer)
    prow = Gtk.Box(spacing=6)
    prow.pack_start(peer_entry, True, True, 0)
    prow.pack_start(save_peers_btn, False, False, 0)
    prow.pack_start(test_peer_btn, False, False, 0)
    grid.attach(prow, 0, 9, 2, 1)
    grid.attach(label("Pare-feu : autoriser UDP 54321 et TCP 54322 entre les machines "
                      "(ex. sudo ufw allow from 192.168.1.0/24 to any port 54322 proto tcp). "
                      "Les échanges sont chiffrés et authentifiés par le code de jumelage."), 0, 10, 2, 1)
    diag_lbl = label("")
    diag_lbl.set_selectable(True)
    grid.attach(Gtk.Label(label="Diagnostic réseau", xalign=1, yalign=0), 0, 11, 1, 1)
    grid.attach(diag_lbl, 1, 11, 1, 1)

    def diag_text():
        d = win.sync_engine.diagnostics()
        out = []
        if not d["enabled"]:
            out.append("⚠ Synchronisation désactivée sur CETTE machine (elle ne se voit pas elle-même ni les autres).")
        if d["code_len"] and d["code_len"] < MIN_SECRET:
            out.append("⚠ Code trop court : %d caractères (%d minimum). Cliquez « Générer », « Appliquer », puis "
                       "saisissez EXACTEMENT le même code sur chaque machine." % (d["code_len"], MIN_SECRET))
        if d["enabled"] and not d["code_ok"]:
            out.append("⚠ Aucun code valide : la synchronisation ne démarre pas.")
        out.append("• Adresses de cette machine : %s" % (", ".join(d["own_ips"]) or "aucune détectée (réseau déconnecté ?)"))
        if d["enabled"]:
            out.append("• Écoute : UDP %d %s — TCP %d %s" % (d["disc_port"], "OK" if d["udp_bound"] else "✗ port occupé",
                                                           d["tcp_port"], "OK" if d["tcp_bound"] else "✗ port occupé"))
            out.append("• Annonces envoyées : %d (échecs : %d) — reçues d'autres machines : %d" % (
                d["sent"], d["send_errors"], d["received"]))
            if d["foreign_versions"]:
                out.append("⚠ Une machine d'une AUTRE version (protocole %s) annonce sa présence : mettez MintMail à jour "
                           "partout (même version)." % ", ".join(d["foreign_versions"]))
            if d["filtered"]:
                out.append("• Annonces ignorées (adresse publique) : %s" % ", ".join(d["filtered"][:4]))
            if d["scanned"]:
                out.append("• Dernière recherche active : %d adresses sondées" % d["scanned"])
            if not d["received"] and d["sent"]:
                out.append("→ Aucune annonce reçue : box ou pare-feu qui bloque UDP %d ? Essayez « Rechercher les machines »." % d["disc_port"])
        return "\n".join(out)

    def refresh(*_):
        eng = win.sync_engine
        state_lbl.set_text(eng.state_label())
        id_lbl.set_markup("<b>%s</b>" % GLib.markup_escape_text(eng.node_id() or "—"))
        peers_lbl.set_text("\n".join("%s @ %s:%s (%s)" % (p["node_id"], p["host"], p["port"], p["via"]) for p in eng.peers())
                           or "Aucune autre machine détectée pour l'instant.")
        diag_lbl.set_text(diag_text())

    sw = _scrolled(grid)
    sw.connect("destroy", lambda *_: alive.update(v=False))

    def tick():
        if alive["v"]:
            refresh()
        return alive["v"]
    GLib.timeout_add_seconds(5, tick)
    refresh()
    return sw


# ------------------------------------------------------------------ aide
def help_page():
    """Aide intégrée complète : sections à gauche, recherche instantanée, contenu sélectionnable (voir help_content.py)."""
    from . import help_content as H
    from .log import LOG
    from .store import CONFIG_DIR, DATA_DIR
    ctx = {"version": __version__, "config": str(CONFIG_DIR), "data": str(DATA_DIR), "log": str(LOG)}
    secs = H.sections(ctx)
    mono = ("Tous les raccourcis clavier", "Options de la commande mintmail")

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    top = Gtk.Box(spacing=12)
    top.set_border_width(12)
    title = Gtk.Label(label="Aide — %s %s" % (APP_NAME, __version__), xalign=0)
    title.get_style_context().add_class("list-title")
    search = Gtk.SearchEntry()
    search.set_placeholder_text("Rechercher dans l'aide (ex. OAuth, spam, hors ligne, raccourcis)")
    search.set_hexpand(True)
    top.pack_start(title, False, False, 0)
    top.pack_start(search, True, True, 0)
    root.pack_start(top, False, False, 0)

    body = Gtk.Box(spacing=0)
    lb = Gtk.ListBox()
    lb.set_selection_mode(Gtk.SelectionMode.SINGLE)
    for s in secs:
        row = Gtk.ListBoxRow()
        row.sec = s
        lab = Gtk.Label(label=s["title"], xalign=0)
        lab.set_line_wrap(True)
        row.set_border_width(8)
        row.add(lab)
        lb.add(row)
    lsw = Gtk.ScrolledWindow()
    lsw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    lsw.set_size_request(230, -1)
    lsw.add(lb)
    body.pack_start(lsw, False, False, 0)
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
    content.set_border_width(18)
    csw = Gtk.ScrolledWindow()
    csw.add(content)
    body.pack_start(csw, True, True, 0)
    root.pack_start(body, True, True, 0)

    def render(entries, heading=None, show_section=False):
        for ch in content.get_children():
            content.remove(ch)
        if heading:
            h = Gtk.Label(xalign=0)
            h.set_markup("<span size='x-large' weight='bold'>%s</span>" % GLib.markup_escape_text(heading))
            h.set_line_wrap(True)
            content.pack_start(h, False, False, 0)
        for sec, t, text in entries:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            if show_section:
                sl = Gtk.Label(label=sec.upper(), xalign=0)
                sl.get_style_context().add_class("dim")
                box.pack_start(sl, False, False, 0)
            tl = Gtk.Label(xalign=0)
            tl.set_markup("<b>%s</b>" % GLib.markup_escape_text(t))
            tl.set_line_wrap(True)
            tl.set_selectable(True)
            box.pack_start(tl, False, False, 0)
            bl = Gtk.Label(xalign=0)
            esc = GLib.markup_escape_text(text)
            bl.set_markup("<tt>%s</tt>" % esc if t in mono else esc)
            bl.set_line_wrap(True)
            bl.set_selectable(True)
            bl.get_style_context().add_class("dim" if False else "help-body")
            box.pack_start(bl, False, False, 0)
            content.pack_start(box, False, False, 0)
        if not entries:
            content.pack_start(Gtk.Label(label="Aucun résultat : essayez un autre mot (sans accent, une partie de mot suffit).", xalign=0), False, False, 0)
        content.show_all()
        vadj = csw.get_vadjustment()
        if vadj is not None:
            vadj.set_value(0)

    def picked(_lb, row):
        if row is not None and not search.get_text().strip():
            render([(row.sec["title"], t, b) for t, b in row.sec["items"]], heading=row.sec["title"])
    lb.connect("row-selected", picked)

    def changed(entry):
        q = entry.get_text().strip()
        if len(q) >= 2:
            lb.unselect_all()
            hits = H.search(q, ctx)
            render(hits, heading="%d résultat%s pour « %s »" % (len(hits), "s" if len(hits) > 1 else "", q), show_section=True)
        elif not q:
            lb.select_row(lb.get_row_at_index(0))
    search.connect("search-changed", changed)
    lb.select_row(lb.get_row_at_index(0))
    root.show_all()
    return root
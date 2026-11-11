"""Page d'aide : accueil (démarrage en 4 étapes, cartes, astuce du jour), sections illustrées, raccourcis en touches, commandes en blocs,
recherche avec extraits surlignés. Le contenu vient de help_content.py ; la mise en forme de help_format.py.

Deux couches : les « plans » (plan_home, plan_section, plan_results) décrivent chaque page en données simples — testables sans écran —,
puis les fonctions _make_* les transforment en widgets GTK stylés par les classes .help-* de style.py (thèmes Aurora, Papier, Terminal)."""
import datetime
import re

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from . import help_content as H
from . import help_format as F
from . import __version__, APP_NAME
from .i18n import tr

HOME_ID = "home"
_KEY_SPLIT = re.compile(r"\s+(?:/|ou|or)\s+")


def key_parts(keys: str):
    """« # / Suppr » → (['#', 'Suppr'], '') ; « ? … (recherche) » → (['?'], '(recherche)')."""
    note = ""
    m = re.search(r"\(([^)]*)\)", keys)
    if m:
        note = m.group(0)
        keys = (keys[:m.start()] + keys[m.end():]).replace("…", "")
    parts = [p.strip() for p in _KEY_SPLIT.split(keys.strip()) if p.strip()]
    return parts or [keys.strip()], note


# ============================================================================== plans (données)
def nav_entries(ctx):
    """Entrées de la navigation : l'accueil puis chaque section (id, icône, titre)."""
    return [(HOME_ID, "🏠", tr("Accueil"))] + [(s["id"], s["icon"], s["title"]) for s in H.sections(ctx)]


def plan_home(ctx, ordinal=None, tip_offset=0):
    home, secs = H.home(), H.sections(ctx)
    ordinal = datetime.date.today().toordinal() if ordinal is None else ordinal
    idx, tip = F.tip_of_the_day(home["tips"], ordinal, tip_offset)
    title, lead = home["welcome"]
    return [
        {"t": "welcome", "icon": "📬", "title": title, "lead": lead},
        {"t": "steps", "title": tr("Bien démarrer en 4 étapes"),
         "steps": [{"n": i + 1, "title": t, "text": x, "target": tgt} for i, (t, x, tgt) in enumerate(home["steps"])]},
        {"t": "tip", "title": tr("Astuce du jour"), "text": tip, "index": idx, "count": len(home["tips"])},
        {"t": "keys", "title": tr("Raccourcis essentiels"), "keys": [k for k in H.shortcuts()][:12], "more": tr("Tous les raccourcis →"), "target": "context"},
        {"t": "tiles", "title": tr("Parcourir l'aide"),
         "tiles": [{"id": s["id"], "icon": s["icon"], "title": s["title"], "tagline": s["tagline"]} for s in secs]},
    ]


def plan_section(sec, ctx):
    items = []
    for (title, body), kind in zip(sec["items"], sec["kinds"]):
        if kind == "shortcuts":
            items.append({"t": "shortcuts", "title": title, "keys": H.shortcuts()})
        elif kind == "cli":
            items.append({"t": "cli", "title": title, "options": H.cli_options(ctx)})
        else:
            items.append({"t": "card", "title": title, "blocks": F.blocks(body)})
    return [{"t": "hero", "icon": sec["icon"], "title": sec["title"], "tagline": sec["tagline"]}] + items


def plan_results(query, ctx):
    hits = H.search_full(query, ctx)
    head = {"t": "heading", "text": tr("%d résultat%s pour « %s »") % (len(hits), "s" if len(hits) > 1 else "", query)}
    if not hits:
        return [head, {"t": "empty", "text": tr("Aucun résultat : essayez un autre mot (sans accent, une partie de mot suffit).")}]
    return [head] + [{"t": "result", "sid": h["sid"], "chip": h["section"].upper(), "title": h["title"], "title_markup": F.highlight(h["title"], query),
                      "excerpt_markup": F.highlight(F.excerpt(F.plain(h["body"]), query), query), "open": tr("Ouvrir la section")} for h in hits]


# ============================================================================== widgets
def _label(markup="", css=None, selectable=False, wrap=True, text=None):
    lab = Gtk.Label(xalign=0)
    if text is not None:
        lab.set_text(text)
    else:
        lab.set_markup(markup)
    lab.set_line_wrap(wrap)
    if wrap:
        lab.set_max_width_chars(96)
    if selectable:
        lab.set_selectable(True)
    if css:
        for c in css.split():
            lab.get_style_context().add_class(c)
    return lab


def _box(css=None, vertical=True, spacing=6):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)
    if css:
        for c in css.split():
            b.get_style_context().add_class(c)
    return b


def _flat_button(label, cb, css="help-open"):
    b = Gtk.Button(label=label)
    b.set_relief(Gtk.ReliefStyle.NONE)
    b.get_style_context().add_class(css)
    b.connect("clicked", lambda *_: cb())
    return b


def _flow(columns):
    f = Gtk.FlowBox()
    f.set_selection_mode(Gtk.SelectionMode.NONE)
    f.set_homogeneous(True)
    f.set_min_children_per_line(1)
    f.set_max_children_per_line(columns)
    f.set_row_spacing(10)
    f.set_column_spacing(10)
    return f


def _keys_row(keys, note=""):
    row = _box(vertical=False, spacing=4)
    for k in keys:
        row.pack_start(_label(text=k, css="help-key", wrap=False), False, False, 0)
    if note:
        row.pack_start(_label(text=note, css="dim", wrap=False), False, False, 0)
    return row


def _pair(keys_text, desc):
    keys, note = key_parts(keys_text)
    box = _box(vertical=False, spacing=10)
    kb = _keys_row(keys, note)
    kb.set_size_request(170, -1)
    box.pack_start(kb, False, False, 0)
    box.pack_start(_label(text=desc, wrap=True), True, True, 0)
    return box


def _block(kind, text):
    if kind == "bullet":
        row = _box(vertical=False, spacing=8)
        dot = _label(text="•", css="help-bullet-dot", wrap=False)
        dot.set_valign(Gtk.Align.START)
        row.pack_start(dot, False, False, 0)
        row.pack_start(_label(F.markup(text), "help-body", True), True, True, 0)
        return row
    if kind == "step":
        n, content = text.split("|", 1)
        row = _box(vertical=False, spacing=10)
        num = _label(text=n, css="help-step-num help-step-small", wrap=False)
        num.set_valign(Gtk.Align.START)
        row.pack_start(num, False, False, 0)
        row.pack_start(_label(F.markup(content), "help-body", True), True, True, 0)
        return row
    if kind in ("tip", "warn"):
        row = _box("help-tip" if kind == "tip" else "help-warn", vertical=False, spacing=10)
        ic = _label(text="💡" if kind == "tip" else "⚠", wrap=False)
        ic.set_valign(Gtk.Align.START)
        row.pack_start(ic, False, False, 0)
        row.pack_start(_label(F.markup(text), "help-body", True), True, True, 0)
        return row
    if kind == "code":
        return _label(text=text, css="help-code", selectable=True)
    return _label(F.markup(text), "help-body", True)


def _make(spec, goto, state, refresh_tip):
    t = spec["t"]
    if t == "hero":
        box = _box("help-hero", vertical=False, spacing=16)
        icon = _label(text=spec["icon"], css="help-hero-icon", wrap=False)
        icon.set_valign(Gtk.Align.CENTER)
        box.pack_start(icon, False, False, 0)
        col = _box(spacing=2)
        col.pack_start(_label(text=spec["title"], css="help-hero-title", selectable=True), False, False, 0)
        col.pack_start(_label(text=spec["tagline"], css="help-hero-sub"), False, False, 0)
        box.pack_start(col, True, True, 0)
        return box
    if t == "welcome":
        box = _box("help-welcome", vertical=False, spacing=18)
        icon = _label(text=spec["icon"], css="help-hero-icon", wrap=False)
        icon.set_valign(Gtk.Align.CENTER)
        box.pack_start(icon, False, False, 0)
        col = _box(spacing=4)
        col.pack_start(_label(text=spec["title"], css="help-hero-title"), False, False, 0)
        col.pack_start(_label(text=spec["lead"], css="help-hero-sub"), False, False, 0)
        box.pack_start(col, True, True, 0)
        return box
    if t in ("steps", "tiles", "keys", "tip"):
        box = _box(spacing=8)
        if t == "tip":
            box.get_style_context().add_class("help-tipday")
            head = _box(vertical=False, spacing=8)
            head.pack_start(_label(text="💡  " + spec["title"].upper(), css="help-chip", wrap=False), True, True, 0)
            head.pack_start(_flat_button(tr("Autre astuce"), refresh_tip), False, False, 0)
            box.pack_start(head, False, False, 0)
            state["tip_label"] = _label(F.markup(spec["text"]), "help-body", True)
            box.pack_start(state["tip_label"], False, False, 0)
            return box
        box.pack_start(_label(text=spec["title"], css="help-section-title", wrap=False), False, False, 0)
        if t == "steps":
            for st in spec["steps"]:
                row = _box("help-step", vertical=False, spacing=12)
                num = _label(text=str(st["n"]), css="help-step-num", wrap=False)
                num.set_valign(Gtk.Align.START)
                row.pack_start(num, False, False, 0)
                col = _box(spacing=2)
                col.pack_start(_label(text=st["title"], css="help-card-title"), False, False, 0)
                col.pack_start(_label(F.markup(st["text"]), "help-body", True), False, False, 0)
                row.pack_start(col, True, True, 0)
                row.pack_start(_flat_button("→", lambda tg=st["target"]: goto(tg)), False, False, 0)
                box.pack_start(row, False, False, 0)
        elif t == "keys":
            fl = _flow(2)
            for k, d in spec["keys"]:
                fl.add(_pair(k, d))
            box.pack_start(fl, False, False, 0)
            more = _flat_button(spec["more"], lambda: goto(spec["target"]))
            more.set_halign(Gtk.Align.START)
            box.pack_start(more, False, False, 0)
        else:
            fl = _flow(3)
            for tile in spec["tiles"]:
                b = Gtk.Button()
                b.set_relief(Gtk.ReliefStyle.NONE)
                b.get_style_context().add_class("help-tile")
                inner = _box(spacing=4)
                head = _box(vertical=False, spacing=8)
                head.pack_start(_label(text=tile["icon"], css="help-tile-icon", wrap=False), False, False, 0)
                head.pack_start(_label(text=tile["title"], css="help-tile-title"), True, True, 0)
                inner.pack_start(head, False, False, 0)
                inner.pack_start(_label(text=tile["tagline"], css="help-tile-sub"), False, False, 0)
                b.add(inner)
                b.connect("clicked", lambda *_, sid=tile["id"]: goto(sid))
                fl.add(b)
            box.pack_start(fl, False, False, 0)
        return box
    if t in ("card", "shortcuts", "cli"):
        box = _box("help-card", spacing=8)
        box.pack_start(_label(text=spec["title"], css="help-card-title", selectable=True), False, False, 0)
        if t == "card":
            for kind, text in spec["blocks"]:
                box.pack_start(_block(kind, text), False, False, 0)
        elif t == "shortcuts":
            fl = _flow(2)
            for k, d in spec["keys"]:
                fl.add(_pair(k, d))
            box.pack_start(fl, False, False, 0)
        else:
            for cmd, desc in spec["options"]:
                box.pack_start(_label(text=cmd, css="help-code", selectable=True), False, False, 0)
                box.pack_start(_label(text=desc, css="help-body", selectable=True), False, False, 0)
        return box
    if t == "heading":
        return _label(text=spec["text"], css="help-hero-title")
    if t == "empty":
        return _label(text=spec["text"], css="help-body")
    if t == "result":
        box = _box("help-card", spacing=6)
        box.pack_start(_label(text=spec["chip"], css="help-chip", wrap=False), False, False, 0)
        box.pack_start(_label(spec["title_markup"], "help-card-title"), False, False, 0)
        box.pack_start(_label(spec["excerpt_markup"], "help-body"), False, False, 0)
        b = _flat_button(spec["open"] + " →", lambda sid=spec["sid"]: goto(sid))
        b.set_halign(Gtk.Align.START)
        box.pack_start(b, False, False, 0)
        return box
    return _label(text="")


def build(ctx):
    """Page d'aide complète (navigation à gauche, recherche, contenu à droite)."""
    entries = nav_entries(ctx)
    secs = {s["id"]: s for s in H.sections(ctx)}
    state = {"page": HOME_ID, "tip_offset": 0, "guard": False}

    root = _box(spacing=0)
    top = _box("help-top", vertical=False, spacing=14)
    titles = _box(spacing=0)
    titles.pack_start(_label(text="📖  " + tr("Aide — %s %s") % (APP_NAME, __version__), css="help-title", wrap=False), False, False, 0)
    top.pack_start(titles, False, False, 0)
    search = Gtk.SearchEntry()
    search.set_placeholder_text(tr("Rechercher dans l'aide (ex. OAuth, spam, hors ligne, raccourcis)"))
    search.get_style_context().add_class("help-search")
    search.set_hexpand(True)
    top.pack_start(search, True, True, 0)
    root.pack_start(top, False, False, 0)

    body = Gtk.Box(spacing=0)
    nav = Gtk.ListBox()
    nav.set_selection_mode(Gtk.SelectionMode.SINGLE)
    nav.get_style_context().add_class("help-nav")
    rows = {}
    for pid, icon, title in entries:
        row = Gtk.ListBoxRow()
        row.pid = pid
        row.get_style_context().add_class("help-nav-row")
        line = _box(vertical=False, spacing=10)
        line.set_border_width(6)
        line.pack_start(_label(text=icon, css="help-nav-icon", wrap=False), False, False, 0)
        line.pack_start(_label(text=title, css="help-nav-title"), True, True, 0)
        row.add(line)
        nav.add(row)
        rows[pid] = row
    nsw = Gtk.ScrolledWindow()
    nsw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    nsw.set_size_request(250, -1)
    nsw.add(nav)
    body.pack_start(nsw, False, False, 0)
    content = _box(spacing=14)
    content.set_border_width(18)
    csw = Gtk.ScrolledWindow()
    csw.add(content)
    body.pack_start(csw, True, True, 0)
    root.pack_start(body, True, True, 0)

    def render(plan):
        for ch in content.get_children():
            content.remove(ch)
        for spec in plan:
            content.pack_start(_make(spec, goto, state, refresh_tip), False, False, 0)
        content.show_all()
        vadj = csw.get_vadjustment()
        if vadj is not None:
            vadj.set_value(0)

    def refresh_tip():
        state["tip_offset"] += 1
        spec = [p for p in plan_home(ctx, tip_offset=state["tip_offset"]) if p["t"] == "tip"][0]
        if state.get("tip_label") is not None:
            state["tip_label"].set_markup(F.markup(spec["text"]))

    def show(pid):
        state["page"] = pid
        if pid == HOME_ID or pid not in secs:
            render(plan_home(ctx, tip_offset=state["tip_offset"]))
        else:
            render(plan_section(secs[pid], ctx))

    def goto(pid):
        if search.get_text():
            state["guard"] = True
            search.set_text("")
            state["guard"] = False
        row = rows.get(pid)
        if row is not None and nav.get_selected_row() is not row:
            nav.select_row(row)
        else:
            show(pid)

    def picked(_lb, row):
        if row is not None and not search.get_text().strip():
            show(row.pid)
    nav.connect("row-selected", picked)

    def changed(entry):
        if state["guard"]:
            return
        q = entry.get_text().strip()
        if len(q) >= 2:
            nav.unselect_all()
            render(plan_results(q, ctx))
        elif not q:
            goto(state["page"])
    search.connect("search-changed", changed)

    nav.select_row(rows[HOME_ID])
    if not content.get_children():           # la sélection affiche déjà l'accueil ; sinon (signal non émis) on l'affiche ici
        show(HOME_ID)
    root.help_show = show              # utilisé par les tests
    root.help_goto = goto
    root.show_all()
    return root

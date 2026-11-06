AVATARS = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#8b5cf6", "#ec4899"]
DEFAULT_ACCENT = "#1a73ff"


def _palette(dark):
    if dark:
        return dict(bg="#12141a", side="#171a21", card="#1c2028", hover="#232833", text="#e9ebf0",
                    dim="#8f97a6", line="#2a2f3a", field="#232833")
    return dict(bg="#f1f3f7", side="#f7f8fb", card="#ffffff", hover="#f3f6fc", text="#1c1f26",
                dim="#7a8190", line="#e6e9ef", field="#ffffff")


def build_css(dark, accent=DEFAULT_ACCENT, density="comfortable"):
    """Retourne (css_de_base, css_raffiné) : le second utilise dégradés / ombres / alpha()."""
    c = _palette(dark)
    pad = {"compact": 6, "comfortable": 11, "spacious": 15}.get(density, 11)
    base = """
@define-color accent %(accent)s;
* { font-family: "Inter", "Cantarell", "Ubuntu", "Segoe UI", sans-serif; }
window, .mm-root { background: %(bg)s; color: %(text)s; font-size: 14px; }
headerbar, .titlebar { background: %(bg)s; border: none; box-shadow: none; min-height: 54px; padding: 4px 10px; }
headerbar button.titlebutton { background: transparent; box-shadow: none; border: none; }
.mm-search { border-radius: 999px; padding: 7px 16px; background: %(field)s; border: 1px solid %(line)s;
             box-shadow: none; min-width: 160px; }
button.flat-btn { border-radius: 999px; background-image: none; background: transparent; border: none;
                  box-shadow: none; padding: 7px 9px; color: %(dim)s; }
button.flat-btn:hover { background: %(hover)s; color: %(text)s; }
button.flat-btn:checked { background: %(hover)s; color: @accent; }
button.round-accent { border-radius: 999px; background-image: none; background: @accent; color: #fff;
                      border: none; box-shadow: none; padding: 8px 10px; }
.compose-btn { border-radius: 999px; background-image: none; background: @accent; color: #fff; border: none;
               box-shadow: none; padding: 11px 18px; font-weight: 700; margin: 12px 12px 4px 12px; }
.compose-btn:hover { background: %(accent)s; opacity: 0.92; }
.mm-sidebar { background: %(side)s; border-right: 1px solid %(line)s; }
.mm-sidebar combobox, .mm-sidebar button.combo { border-radius: 12px; }
.mm-list { background: %(bg)s; }
.mm-list viewport, .mm-list scrolledwindow, .mm-list list { background: transparent; }
.mm-reader, .mm-reader-head { background: %(card)s; }
.mm-reader-head { border-bottom: 1px solid %(line)s; padding: 4px 6px; }
.mm-toolbar { background: %(card)s; padding: 6px 10px; }
.mm-listbar { background: %(bg)s; padding: 10px 14px 6px 14px; }
.list-title { font-size: 24px; font-weight: 800; }
.cat-tab { border-radius: 999px; padding: 4px 14px; background-image: none; background: transparent;
           border: 1px solid transparent; box-shadow: none; color: %(dim)s; font-weight: 600; }
.cat-tab:hover { background: %(hover)s; }
.cat-tab:checked { background: %(hover)s; color: @accent; border-color: @accent; }
.pill-toggle { border-radius: 999px; padding: 2px 12px; background-image: none; background: %(field)s;
               border: 1px solid %(line)s; box-shadow: none; color: %(dim)s; font-size: 12px; }
.pill-toggle:checked { color: @accent; border-color: @accent; }
.msg-row { background: %(card)s; border: 1px solid %(line)s; border-radius: 14px; margin: 3px 12px; }
.msg-row:hover { background: %(card)s; border-color: %(dim)s; }
.msg-row:selected, .msg-row:selected:hover { background: %(hover)s; border-color: @accent; color: %(text)s; }
.msg-row:selected label { color: %(text)s; }
.msg-row:selected .dim { color: %(dim)s; }
.msg-row .pad { padding: %(pad)dpx 14px; }
.msg-row .sender { font-size: 15px; }
.msg-row.unread .sender, .msg-row.unread .subject { font-weight: 700; }
.msg-row .dim, .dim { color: %(dim)s; }
.msg-row .unread-dot { background: @accent; border-radius: 999px; min-width: 9px; min-height: 9px; }
.group-header { background: transparent; color: %(dim)s; font-size: 13px; font-weight: 700; padding: 14px 20px 4px 20px; }
.avatar { border-radius: 999px; color: #fff; font-weight: 700; font-size: 15px; }
.nav-row { padding: 9px 14px; border-radius: 12px; margin: 2px 10px; font-weight: 500; color: %(text)s; }
.nav-row:hover { background: %(hover)s; }
.nav-row:selected { background: %(card)s; color: @accent; font-weight: 700; }
.nav-row:selected label, .nav-row:selected image { color: @accent; }
.badge { background: @accent; color: #fff; border-radius: 999px; padding: 0 8px; font-size: 11px; font-weight: 700; }
.subject-big { font-size: 22px; font-weight: 800; }
.pill { border-radius: 999px; padding: 4px 14px; background-image: none; background: %(field)s;
        border: 1px solid %(line)s; box-shadow: none; }
.pill:hover { border-color: @accent; color: @accent; }
.chip { border-radius: 10px; padding: 6px 10px; background-image: none; background: %(hover)s;
        border: 1px solid %(line)s; box-shadow: none; }
.banner { background: %(hover)s; border: 1px solid %(line)s; border-radius: 12px; padding: 8px 12px; margin: 8px 14px; }
.toast { background: #111827; color: #fff; border-radius: 12px; padding: 10px 18px; margin: 18px; }
.toast button { color: #93c5fd; background: transparent; background-image: none; border: none; box-shadow: none; font-weight: 700; }
.bulkbar { background: @accent; color: #fff; padding: 6px 12px; border-radius: 12px; margin: 6px 12px; }
.bulkbar button { color: #fff; background-image: none; background: rgba(255,255,255,0.18); border: none; box-shadow: none; }
.suggested-action { background-image: none; background: @accent; color: #fff; border: none; box-shadow: none;
                    text-shadow: none; border-radius: 999px; padding: 6px 18px; font-weight: 600; }
.quick-reply { background: %(card)s; border-top: 1px solid %(line)s; }
.quick-reply entry { border-radius: 999px; padding: 8px 16px; }
.empty-state { color: %(dim)s; }
.settings-page { background: %(bg)s; }
.settings-page stacksidebar { background: %(side)s; border-right: 1px solid %(line)s; }
.settings-page stacksidebar row { padding: 10px 16px; margin: 2px 8px; border-radius: 10px; }
.settings-page stacksidebar row:selected { background: %(card)s; color: @accent; font-weight: 700; }
.settings-page stack { background: %(card)s; }
entry, textview text { background: %(field)s; color: %(text)s; }
paned > separator { background-image: none; background-color: %(line)s; min-width: 6px; }
paned.vertical > separator { min-width: 0; min-height: 6px; }
paned > separator:hover { background-color: @accent; }
.msg-card { background: transparent; border-radius: 14px; }
.msg-card.swiping { background: %(card)s; }
.swipe-bg { color: #fff; font-weight: 700; border-radius: 14px; }
.swipe-green { background: #16a34a; } .swipe-red { background: #dc2626; }
.swipe-orange { background: #ea580c; } .swipe-blue { background: #2563eb; }
.swipe-yellow { background: #ca8a04; } .swipe-purple { background: #7c3aed; }
.swipe-grey { background: #6b7280; }
""" % dict(c, accent=accent, pad=pad)
    for i, col in enumerate(AVATARS):
        base += ".avatar-%d { background: %s; }\n" % (i, col)
    fancy = """
.compose-btn { background-image: linear-gradient(to bottom right, shade(@accent, 1.25), @accent);
               box-shadow: 0 6px 16px alpha(@accent, 0.38); }
.msg-row { box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05); }
.msg-row:hover { box-shadow: 0 4px 14px rgba(16, 24, 40, 0.10); }
.msg-row:selected, .msg-row:selected:hover { background: alpha(@accent, 0.10); }
.cat-tab:checked { background: alpha(@accent, 0.12); }
.nav-row:selected { background: alpha(@accent, 0.12); box-shadow: none; }
.toast { box-shadow: 0 8px 28px rgba(0, 0, 0, 0.35); }
.mm-search:focus { border-color: @accent; box-shadow: 0 0 0 3px alpha(@accent, 0.18); }
"""
    return base.encode(), fancy.encode()

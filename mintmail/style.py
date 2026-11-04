AVATARS = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#8b5cf6", "#ec4899"]


def build_css(dark, accent="#3b82f6", density="comfortable"):
    if dark:
        c = dict(bg="#16181d", side="#1d2027", card="#1f2229", hover="#262a33", sel="#2a3140",
                 text="#e8eaed", dim="#9aa0ab", line="#2c303a", field="#262a33")
    else:
        c = dict(bg="#f4f5f7", side="#eceef2", card="#ffffff", hover="#f0f3f8", sel="#e3ecfd",
                 text="#1f2328", dim="#6b7280", line="#e2e5ea", field="#ffffff")
    pad = {"compact": 6, "comfortable": 10, "spacious": 14}.get(density, 10)
    css = """
@define-color accent %(accent)s;
window, .mm-root { background: %(bg)s; color: %(text)s; }
.mm-sidebar { background: %(side)s; border-right: 1px solid %(line)s; }
.mm-list { background: %(card)s; }
.mm-reader, .mm-reader-head { background: %(card)s; }
.mm-reader-head { border-bottom: 1px solid %(line)s; }
.mm-toolbar { background: %(card)s; border-bottom: 1px solid %(line)s; padding: 4px 8px; }
.mm-listbar { background: %(card)s; border-bottom: 1px solid %(line)s; padding: 8px 10px; }
.msg-row { background: %(card)s; border-bottom: 1px solid %(line)s; }
.msg-row:hover { background: %(hover)s; }
.msg-row:selected, .msg-row:selected:hover { background: %(sel)s; color: %(text)s; }
.msg-row .pad { padding: %(pad)dpx 12px; }
.msg-row.unread .sender, .msg-row.unread .subject { font-weight: 700; }
.msg-row .dim, .dim { color: %(dim)s; }
.msg-row .unread-dot { background: @accent; border-radius: 999px; min-width: 9px; min-height: 9px; }
.group-header { background: %(bg)s; color: %(dim)s; font-size: 11px; font-weight: 700;
                padding: 6px 14px; letter-spacing: 1px; }
.avatar { border-radius: 999px; color: #fff; font-weight: 700; }
.nav-row { padding: 8px 12px; border-radius: 8px; margin: 1px 8px; }
.nav-row:hover { background: %(hover)s; }
.nav-row:selected { background: %(sel)s; color: @accent; font-weight: 600; }
.badge { background: @accent; color: #fff; border-radius: 999px; padding: 0 7px; font-size: 11px; font-weight: 700; }
.subject-big { font-size: 20px; font-weight: 700; }
.pill { border-radius: 999px; padding: 3px 12px; background: %(field)s; border: 1px solid %(line)s; }
.chip { border-radius: 8px; padding: 6px 10px; background: %(hover)s; border: 1px solid %(line)s; }
.banner { background: %(sel)s; border-radius: 8px; padding: 8px 12px; margin: 8px 16px; }
.toast { background: #111827; color: #fff; border-radius: 10px; padding: 10px 16px; margin: 18px;
         box-shadow: 0 6px 24px rgba(0,0,0,0.35); }
.toast button { color: #93c5fd; background: transparent; border: none; box-shadow: none; font-weight: 700; }
.bulkbar { background: @accent; color: #fff; padding: 6px 12px; }
.bulkbar button { color: #fff; background: rgba(255,255,255,0.18); border: none; box-shadow: none; }
.suggested-action { background: @accent; color: #fff; border: none; box-shadow: none; text-shadow: none; }
.quick-reply entry { border-radius: 999px; padding: 6px 14px; }
.empty-state { color: %(dim)s; }
entry, textview text { background: %(field)s; color: %(text)s; }
""" % dict(c, accent=accent, pad=pad)
    for i, col in enumerate(AVATARS):
        css += ".avatar-%d { background: %s; }\n" % (i, col)
    return css.encode()

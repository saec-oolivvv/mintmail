"""Identités visuelles de MintMail.

Trois styles, chacun en clair et en sombre :
- Aurora   : verre dépoli sur dégradé nuit, lueurs de l'IA, formes très arrondies (par défaut)
- Papier   : éditorial, encre sur papier chaud, titres en empattement, filets fins, aucune carte
- Terminal : monospace, angles droits, vert phosphore, densité maximale
"""
AVATARS = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#8b5cf6", "#ec4899"]
NAV_TINTS = {"inbox": "#4f8cff", "unread": "#a78bfa", "starred": "#fbbf24", "pinned": "#f87171",
             "snoozed": "#fb923c", "drafts": "#94a3b8", "sent": "#2dd4bf", "archive": "#4ade80",
             "spam": "#ef4444", "trash": "#94a3b8"}

STYLES = {
    "aurora": {
        "label": "Aurora — verre et lueurs", "accent": "#7c8cff", "r": 16, "rs": 10, "rp": 999, "ra": 999,
        "font": '"Inter", "Cantarell", "Ubuntu", "Segoe UI", sans-serif',
        "head": '"Inter", "Cantarell", "Ubuntu", sans-serif', "hw": 800,
        "dark": dict(bg="#0a0e1a", side="rgba(255,255,255,0.035)", card="rgba(255,255,255,0.055)",
                     panel="rgba(255,255,255,0.03)", hover="rgba(255,255,255,0.10)", text="#e9edfb",
                     dim="#8a96b8", line="rgba(255,255,255,0.10)", field="rgba(255,255,255,0.07)",
                     ai1="#b79cff", ai2="#4cc9f0", on="#ffffff",
                     canvas="linear-gradient(to bottom right, #0a0e1a, #111a33 48%, #1b1039)"),
        "light": dict(bg="#eef1fb", side="rgba(255,255,255,0.55)", card="rgba(255,255,255,0.82)",
                      panel="rgba(255,255,255,0.55)", hover="rgba(255,255,255,0.97)", text="#1a1f36",
                      dim="#6b7592", line="rgba(30,40,90,0.11)", field="rgba(255,255,255,0.92)",
                      ai1="#7c5cff", ai2="#2f80ff", on="#ffffff",
                      canvas="linear-gradient(to bottom right, #eaf0ff, #f6efff 50%, #e6f6ff)"),
    },
    "papier": {
        "label": "Papier — éditorial", "accent": "#b4472f", "r": 4, "rs": 3, "rp": 4, "ra": 999,
        "font": '"Source Sans 3", "Source Sans Pro", "Cantarell", "Ubuntu", sans-serif',
        "head": '"Source Serif 4", "Source Serif Pro", "Georgia", "DejaVu Serif", serif', "hw": 700,
        "dark": dict(bg="#1b1814", side="#15120f", card="#241f1a", panel="#201c17", hover="#2e2822",
                     text="#efe7d8", dim="#a39880", line="#3a3329", field="#241f1a", ai1="#d98cb3",
                     ai2="#e0795c", on="#ffffff", canvas="#1b1814"),
        "light": dict(bg="#f4efe6", side="#ece5d6", card="#fffdf8", panel="#faf6ee", hover="#f1e9d8",
                      text="#2b2620", dim="#8a7f6c", line="#ddd2bb", field="#fffdf8", ai1="#8b3a62",
                      ai2="#b4472f", on="#ffffff", canvas="#f4efe6"),
    },
    "terminal": {
        "label": "Terminal — phosphore", "accent": "#3dff8a", "r": 2, "rs": 2, "rp": 2, "ra": 2,
        "font": '"JetBrains Mono", "Fira Code", "DejaVu Sans Mono", "Ubuntu Mono", monospace',
        "head": '"JetBrains Mono", "Fira Code", "DejaVu Sans Mono", "Ubuntu Mono", monospace', "hw": 700,
        "dark": dict(bg="#050d08", side="#07140c", card="#0a1a10", panel="#08150d", hover="#0f2617",
                     text="#bff5cd", dim="#5f9a74", line="#14402a", field="#0a1a10", ai1="#7dffb0",
                     ai2="#3dff8a", on="#03120a", canvas="#050d08"),
        "light": dict(bg="#eef5ee", side="#e2ece2", card="#f8fcf8", panel="#f3f9f3", hover="#dcebdc",
                      text="#10301c", dim="#4f7a5f", line="#b9d2bf", field="#f8fcf8", ai1="#0b8f45",
                      ai2="#0a6b8f", on="#ffffff", canvas="#eef5ee"),
    },
}
DEFAULT_STYLE = "aurora"
DEFAULT_ACCENT = STYLES[DEFAULT_STYLE]["accent"]
ACCENTS = [("Indigo", "#7c8cff"), ("Cyan", "#22b8f0"), ("Menthe", "#2fd6a1"), ("Vert", "#16a34a"),
           ("Orange", "#f97316"), ("Rose", "#ec4899"), ("Terracotta", "#b4472f"), ("Phosphore", "#3dff8a")]

BASE = """
@define-color accent %(accent)s;
@define-color ai1 %(ai1)s;
@define-color ai2 %(ai2)s;
* { font-family: %(font)s; }
window, .mm-root { background: %(bg)s; color: %(text)s; font-size: 14px; }
.mm-root viewport, .mm-root scrolledwindow, .mm-root list, .mm-root flowbox { background: transparent; }
headerbar, .titlebar { background: transparent; border: none; box-shadow: none; min-height: 54px; padding: 4px 10px; }
headerbar button.titlebutton { background: transparent; background-image: none; box-shadow: none; border: none;
                               border-radius: %(rp)dpx; padding: 6px; color: %(dim)s; }
headerbar button.titlebutton:hover { background: %(hover)s; color: %(text)s; }
headerbar button.titlebutton.close:hover { background: #dc2626; color: #fff; }
.mm-search { border-radius: %(rp)dpx; padding: 8px 18px; background: %(field)s; border: 1px solid %(line)s;
             box-shadow: none; min-width: 160px; color: %(text)s; }
button.flat-btn { border-radius: %(rp)dpx; background-image: none; background: transparent; border: none;
                  box-shadow: none; padding: 7px 9px; color: %(dim)s; }
button.flat-btn:hover { background: %(hover)s; color: %(text)s; }
button.flat-btn:checked { background: %(hover)s; color: @accent; }
button.round-accent { border-radius: %(rp)dpx; background-image: none; background: @accent; color: %(on)s;
                      border: none; box-shadow: none; padding: 8px 10px; }
button.ai-btn { border-radius: %(rp)dpx; background-image: none; background: @ai1; color: %(on)s; border: none;
                box-shadow: none; padding: 7px 14px; font-weight: 700; }
button.ai-btn:hover { opacity: 0.9; }
.compose-btn { border-radius: %(rp)dpx; background-image: none; background: @accent; color: %(on)s; border: none;
               box-shadow: none; padding: 11px 18px; font-weight: 700; margin: 8px 12px 4px 12px; }
.compose-btn:hover { opacity: 0.92; }
.ai-nav-btn { border-radius: %(r)dpx; background-image: none; background: %(card)s; border: 1px solid %(line)s;
              box-shadow: none; padding: 9px 14px; margin: 4px 12px; font-weight: 700; color: @ai1; }
.ai-nav-btn:hover { border-color: @ai1; }
.wordmark { padding: 16px 18px 6px 18px; font-size: 19px; }
.wm-dot { color: @ai1; font-size: 15px; }
.wm-a { font-family: %(head)s; font-weight: %(hw)d; }
.wm-b { font-family: %(head)s; font-weight: 300; color: %(dim)s; }
.orb { border-radius: %(ra)dpx; padding: 2px; background-image: none; background: transparent; border: 2px solid transparent;
       box-shadow: none; min-width: 0; min-height: 0; }
.orb:hover { border-color: %(line)s; }
.orb-active, .orb-active:hover { border-color: @accent; }
.mm-sidebar { background: %(side)s; border-right: 1px solid %(line)s; }
.mm-list { background: %(panel)s; }
.mm-list viewport, .mm-list scrolledwindow, .mm-list list { background: transparent; }
.mm-reader, .mm-reader-head { background: %(card)s; }
.mm-reader-head { border-bottom: 1px solid %(line)s; padding: 4px 6px; }
.mm-toolbar { background: %(card)s; padding: 6px 10px; }
.mm-listbar { background: transparent; padding: 10px 14px 6px 14px; }
.list-title { font-family: %(head)s; font-size: 25px; font-weight: %(hw)d; }
.count-lbl { color: %(dim)s; font-size: 12px; }
.cat-tab { border-radius: %(rp)dpx; padding: 4px 14px; background-image: none; background: transparent;
           border: 1px solid transparent; box-shadow: none; color: %(dim)s; font-weight: 600; }
.cat-tab:hover { background: %(hover)s; }
.cat-tab:checked { background: %(hover)s; color: @accent; border-color: @accent; }
.pill-toggle { border-radius: %(rp)dpx; padding: 2px 12px; background-image: none; background: %(field)s;
               border: 1px solid %(line)s; box-shadow: none; color: %(dim)s; font-size: 12px; }
.pill-toggle:checked { color: @accent; border-color: @accent; }
.msg-row { background: %(card)s; border: 1px solid %(line)s; border-radius: %(r)dpx; margin: 3px 12px; }
.msg-row:hover { border-color: %(dim)s; }
.msg-row:selected, .msg-row:selected:hover { background: %(hover)s; border-color: @accent; color: %(text)s; }
.msg-row:selected label { color: %(text)s; }
.msg-row:selected .dim { color: %(dim)s; }
.msg-row .pad { padding: %(pad)dpx 14px 14px 10px; }
.msg-row .sender { font-size: 15px; }
.msg-row.unread .sender, .msg-row.unread .subject { font-weight: 700; }
.msg-row .dim, .dim { color: %(dim)s; }
.msg-row .ai-line { color: @ai1; }
.msg-row .unread-dot { background: @accent; border-radius: 999px; min-width: 9px; min-height: 9px; }
.rail { min-width: 4px; border-radius: 4px; background: transparent; margin: 2px 0; }
.rail-unread { background: @accent; }
.rail-news { background: #a78bfa; } .rail-notif { background: #2dd4bf; }
.rail-p3 { background: #ef4444; } .rail-spam { background: #ef4444; }
.hover-actions { background: %(card)s; border: 1px solid %(line)s; border-radius: %(rp)dpx; padding: 2px 4px; margin: 0 8px; }
.hover-actions button { padding: 4px 6px; }
.badge-important { background: #ef4444; color: #fff; border-radius: %(rp)dpx; padding: 0 8px; font-size: 11px; font-weight: 700; }
.badge-suspect { background: #7f1d1d; color: #fff; border-radius: %(rp)dpx; padding: 0 8px; font-size: 11px; font-weight: 700; }
.group-header { background: transparent; color: %(dim)s; font-size: 12px; font-weight: 700; padding: 14px 20px 4px 20px; }
.avatar { border-radius: %(ra)dpx; color: #fff; font-weight: 700; font-size: 15px; }
.nav-row { padding: 8px 12px; border-radius: %(rs)dpx; margin: 1px 10px; font-weight: 500; color: %(text)s; }
.nav-row:hover { background: %(hover)s; }
.nav-row:selected { background: %(hover)s; color: @accent; font-weight: 700; }
.nav-row:selected label { color: @accent; }
.folder-row { padding: 5px 8px 5px 4px; font-size: 13px; }
.nav-caption-row { margin: 10px 10px 2px 10px; }
.nav-caption { color: %(dim)s; font-size: 11px; font-weight: 800; letter-spacing: 1px; padding: 0 4px; }
.badge { background: @accent; color: %(on)s; border-radius: %(rp)dpx; padding: 0 8px; font-size: 11px; font-weight: 700; }
.subject-big { font-family: %(head)s; font-size: 24px; font-weight: %(hw)d; }
.pill { border-radius: %(rp)dpx; padding: 4px 14px; background-image: none; background: %(field)s;
        border: 1px solid %(line)s; box-shadow: none; color: %(text)s; }
.pill:hover { border-color: @accent; color: @accent; }
.chip { border-radius: %(rs)dpx; padding: 6px 10px; background-image: none; background: %(hover)s;
        border: 1px solid %(line)s; box-shadow: none; }
.ai-chip { border-radius: %(rp)dpx; padding: 5px 14px; background-image: none; background: transparent;
           border: 1px solid @ai1; color: @ai1; box-shadow: none; font-weight: 600; }
.ai-chip:hover { background: @ai1; color: %(on)s; }
.ai-card { background: %(hover)s; border: 1px solid @ai1; border-radius: %(r)dpx; margin: 10px 16px; padding: 12px 14px; }
.ai-title { color: @ai1; font-weight: 800; font-size: 12px; letter-spacing: 1px; }
.ai-text { font-size: 14px; }
.ai-warn { background: rgba(239,68,68,0.14); border: 1px solid #ef4444; color: #ef4444; border-radius: %(rs)dpx; padding: 6px 10px; }
.digest-card { background: %(card)s; border: 1px solid @ai1; border-radius: %(r)dpx; margin: 6px 12px 4px 12px; padding: 10px 14px; }
.welcome-card { background: %(card)s; border: 1px solid %(line)s; border-radius: %(r)dpx; margin: 14px; padding: 18px; }
.banner { background: %(hover)s; border: 1px solid %(line)s; border-radius: %(rs)dpx; padding: 8px 12px; margin: 8px 14px; }
.toast { background: #0b1020; color: #fff; border-radius: %(r)dpx; padding: 10px 18px; margin: 18px; border: 1px solid rgba(255,255,255,0.14); }
.toast button { color: #8fb8ff; background: transparent; background-image: none; border: none; box-shadow: none; font-weight: 700; }
.bulkbar { background: @accent; color: %(on)s; padding: 6px 12px; border-radius: %(rs)dpx; margin: 6px 12px; }
.bulkbar button { color: %(on)s; background-image: none; background: rgba(255,255,255,0.18); border: none; box-shadow: none; }
.suggested-action { background-image: none; background: @accent; color: %(on)s; border: none; box-shadow: none;
                    text-shadow: none; border-radius: %(rp)dpx; padding: 6px 18px; font-weight: 600; }
.quick-reply { background: %(card)s; border-top: 1px solid %(line)s; }
.quick-reply entry { border-radius: %(rp)dpx; padding: 8px 16px; }
.empty-state { color: %(dim)s; }
.assistant { background: %(side)s; border-left: 1px solid %(line)s; }
.assistant-head { padding: 12px 14px; }
.bubble-user { background: @accent; color: %(on)s; border-radius: %(r)dpx; padding: 8px 12px; margin: 4px 10px 4px 40px; }
.bubble-ai { background: %(card)s; border: 1px solid %(line)s; border-radius: %(r)dpx; padding: 8px 12px; margin: 4px 40px 4px 10px; }
.plan-row { background: %(hover)s; border: 1px solid %(line)s; border-radius: %(rs)dpx; padding: 6px 10px; margin: 3px 10px; }
.settings-page { background: %(bg)s; }
.settings-page stacksidebar { background: %(side)s; border-right: 1px solid %(line)s; }
.settings-page stacksidebar row { padding: 10px 16px; margin: 2px 8px; border-radius: %(rs)dpx; }
.settings-page stacksidebar row:selected { background: %(card)s; color: @accent; font-weight: 700; }
.settings-page stack { background: %(card)s; }
entry, textview text { background: %(field)s; color: %(text)s; }
paned > separator { background-image: none; background-color: %(line)s; min-width: 6px; }
paned.vertical > separator { min-width: 0; min-height: 6px; }
paned > separator:hover { background-color: @accent; }
.msg-card { background: transparent; border-radius: %(r)dpx; }
.msg-card.swiping { background: %(card)s; }
.swipe-bg { color: #fff; font-weight: 700; border-radius: %(r)dpx; }
.swipe-green { background: #16a34a; } .swipe-red { background: #dc2626; }
.swipe-orange { background: #ea580c; } .swipe-blue { background: #2563eb; }
.swipe-yellow { background: #ca8a04; } .swipe-purple { background: #7c3aed; }
.swipe-grey { background: #6b7280; }
.aurora-line { min-height: 0; }
"""

STYLE_BLOCKS = {
    "aurora": """
.mm-toolbar { border-radius: 999px; margin: 8px 14px; background: %(hover)s; }
.mm-reader-head { background: transparent; }
.mm-reader { background: %(card)s; }
.nav-row:selected { border-left: 3px solid @accent; }
""",
    "papier": """
window, .mm-root { font-size: 15px; }
.msg-row { background: transparent; border: none; border-bottom: 1px solid %(line)s; border-radius: 0; margin: 0 16px; }
.msg-row:hover { background: %(hover)s; }
.msg-row:selected, .msg-row:selected:hover { background: %(hover)s; border-bottom-color: %(line)s; border-left: 3px solid @accent; }
.msg-row .sender { font-family: %(head)s; font-size: 16px; }
.msg-row .subject { font-style: italic; }
.group-header { font-family: %(head)s; font-style: italic; font-size: 14px; padding: 16px 22px 4px 22px; border-bottom: 1px solid %(line)s; margin: 0 16px; }
.nav-row:selected { background: transparent; border-left: 3px solid @accent; border-radius: 0; }
.list-title, .subject-big { font-style: normal; }
.wordmark { border-bottom: 1px solid %(line)s; margin: 0 14px 8px 14px; padding: 16px 4px 8px 4px; }
.mm-toolbar { background: transparent; border-bottom: 1px solid %(line)s; border-radius: 0; margin: 0 14px; }
.ai-card, .digest-card { border-radius: 0; border-left: 4px solid @ai1; border-top: none; border-right: none; border-bottom: 1px solid %(line)s; }
.compose-btn { margin: 8px 14px 4px 14px; }
""",
    "terminal": """
window, .mm-root { font-size: 13px; }
.msg-row { background: transparent; border: none; border-left: 2px solid %(line)s; border-radius: 0; margin: 1px 10px; }
.msg-row:hover { background: %(hover)s; border-left-color: @accent; }
.msg-row:selected, .msg-row:selected:hover { background: %(hover)s; border-left: 2px solid @accent; }
.msg-row .sender { font-size: 13px; font-weight: 700; }
.msg-row .pad { padding: 5px 10px 5px 8px; }
.nav-caption { letter-spacing: 3px; }
.nav-row:selected { border-left: 2px solid @accent; border-radius: 0; background: %(hover)s; }
.wordmark { font-size: 16px; }
.list-title { font-size: 20px; }
.subject-big { font-size: 20px; }
.mm-toolbar { border-bottom: 1px solid %(line)s; }
.group-header { letter-spacing: 3px; }
.suggested-action, .compose-btn, button.ai-btn, button.round-accent { font-weight: 700; }
""",
}

FANCY = {
    "aurora": """
window { background-image: %(canvas)s; }
.aurora-line { min-height: 2px; background-image: linear-gradient(to right, @ai2, @ai1, @accent); }
.compose-btn { background-image: linear-gradient(to bottom right, shade(@accent, 1.25), @accent);
               box-shadow: 0 6px 18px alpha(@accent, 0.45); }
button.ai-btn { background-image: linear-gradient(to bottom right, @ai1, @ai2); }
.ai-card { background-image: linear-gradient(to bottom right, alpha(@ai1, 0.14), alpha(@ai2, 0.08));
           border-color: alpha(@ai1, 0.55); box-shadow: 0 0 28px alpha(@ai1, 0.14); }
.digest-card { background-image: linear-gradient(to bottom right, alpha(@ai1, 0.12), alpha(@ai2, 0.06));
               border-color: alpha(@ai1, 0.5); }
.msg-row { box-shadow: 0 1px 2px rgba(0, 0, 0, 0.18); }
.msg-row:hover { box-shadow: 0 6px 20px rgba(0, 0, 0, 0.22); }
.msg-row:selected, .msg-row:selected:hover { background-image: linear-gradient(to right, alpha(@accent, 0.22), alpha(@accent, 0.06));
                                             box-shadow: 0 0 18px alpha(@accent, 0.25); }
.hover-actions { box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25); }
.cat-tab:checked { background: alpha(@accent, 0.18); }
.nav-row:selected { background-image: linear-gradient(to right, alpha(@accent, 0.22), alpha(@accent, 0)); }
.orb-active, .orb-active:hover { box-shadow: 0 0 14px alpha(@accent, 0.7); }
.wm-dot { text-shadow: 0 0 10px alpha(@ai1, 0.9); }
.toast { box-shadow: 0 10px 34px rgba(0, 0, 0, 0.5); }
.mm-search:focus { border-color: @accent; box-shadow: 0 0 0 3px alpha(@accent, 0.22); }
.assistant { box-shadow: -10px 0 30px rgba(0, 0, 0, 0.25); }
.mm-toolbar { box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18); }
.welcome-card { box-shadow: 0 10px 34px rgba(0, 0, 0, 0.25); }
""",
    "papier": """
.ai-card { background-image: none; }
.compose-btn { box-shadow: 0 2px 0 shade(@accent, 0.75); }
""",
    "terminal": """
.msg-row:selected, .msg-row:selected:hover { box-shadow: inset 0 0 12px alpha(@accent, 0.18); }
.compose-btn, button.ai-btn { box-shadow: 0 0 12px alpha(@accent, 0.45); }
.wm-dot { text-shadow: 0 0 8px alpha(@accent, 0.9); }
.ai-card { box-shadow: 0 0 14px alpha(@ai1, 0.2); }
""",
}


def build_css(dark, accent=None, density="comfortable", style=DEFAULT_STYLE):
    """Retourne (css_de_base, css_raffiné) : le second utilise dégradés / ombres / alpha(), avec repli."""
    st = STYLES.get(style, STYLES[DEFAULT_STYLE])
    style = style if style in STYLES else DEFAULT_STYLE
    ctx = dict(st["dark" if dark else "light"])
    ctx.update(accent=accent or st["accent"], r=st["r"], rs=st["rs"], rp=st["rp"], ra=st["ra"], font=st["font"],
               head=st["head"], hw=st["hw"], pad={"compact": 6, "comfortable": 11, "spacious": 15}.get(density, 11))
    base = (BASE + STYLE_BLOCKS[style]) % ctx
    for i, col in enumerate(AVATARS):
        base += ".avatar-%d { background: %s; }\n" % (i, col)
    for view, col in NAV_TINTS.items():
        base += ".nav-%s image { color: %s; }\n" % (view, col)
    fancy = FANCY[style] % ctx
    if style == "aurora":
        for i, col in enumerate(AVATARS):
            fancy += ".avatar-%d { background-image: linear-gradient(to bottom right, %s, shade(%s, 0.7)); }\n" % (i, col, col)
    return base.encode(), fancy.encode()

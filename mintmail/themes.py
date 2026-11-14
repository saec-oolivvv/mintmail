"""Identités visuelles de MintMail (données seules : l'interface Qt les traduit en feuille de style, voir qt/theme.py).

Trois styles, chacun en clair et en sombre :
- Aurora   : verre dépoli sur dégradé nuit, lueurs de l'IA, formes très arrondies (par défaut)
- Papier   : éditorial, encre sur papier chaud, titres en empattement, filets fins, aucune carte
- Terminal : monospace, angles droits, vert phosphore, densité maximale
"""
from .i18n import tr

AVATARS = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#14b8a6", "#3b82f6", "#8b5cf6", "#ec4899"]
NAV_TINTS = {"inbox": "#4f8cff", "unread": "#a78bfa", "starred": "#fbbf24", "pinned": "#f87171",
             "snoozed": "#fb923c", "drafts": "#94a3b8", "sent": "#2dd4bf", "archive": "#4ade80",
             "spam": "#ef4444", "trash": "#94a3b8"}

STYLES = {
    "aurora": {
        "label": tr("Aurora — verre et lueurs"), "accent": "#7c8cff", "r": 16, "rs": 10, "rp": 999, "ra": 999,
        "font": '"Inter", "Cantarell", "Ubuntu", "Helvetica Neue", "Segoe UI", sans-serif',
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
        "label": tr("Papier — éditorial"), "accent": "#b4472f", "r": 4, "rs": 3, "rp": 4, "ra": 999,
        "font": '"Source Sans 3", "Source Sans Pro", "Cantarell", "Ubuntu", "Helvetica Neue", "Segoe UI", sans-serif',
        "head": '"Source Serif 4", "Source Serif Pro", "Georgia", "DejaVu Serif", serif', "hw": 700,
        "dark": dict(bg="#1b1814", side="#15120f", card="#241f1a", panel="#201c17", hover="#2e2822",
                     text="#efe7d8", dim="#a39880", line="#3a3329", field="#241f1a", ai1="#d98cb3",
                     ai2="#e0795c", on="#ffffff", canvas="#1b1814"),
        "light": dict(bg="#f4efe6", side="#ece5d6", card="#fffdf8", panel="#faf6ee", hover="#f1e9d8",
                      text="#2b2620", dim="#8a7f6c", line="#ddd2bb", field="#fffdf8", ai1="#8b3a62",
                      ai2="#b4472f", on="#ffffff", canvas="#f4efe6"),
    },
    "terminal": {
        "label": tr("Terminal — phosphore"), "accent": "#3dff8a", "r": 2, "rs": 2, "rp": 2, "ra": 2,
        "font": '"JetBrains Mono", "Fira Code", "DejaVu Sans Mono", "Ubuntu Mono", "Menlo", "Consolas", monospace',
        "head": '"JetBrains Mono", "Fira Code", "DejaVu Sans Mono", "Ubuntu Mono", "Menlo", "Consolas", monospace', "hw": 700,
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
ACCENTS = [(tr("Indigo"), "#7c8cff"), (tr("Cyan"), "#22b8f0"), (tr("Menthe"), "#2fd6a1"), (tr("Vert"), "#16a34a"),
           (tr("Orange"), "#f97316"), (tr("Rose"), "#ec4899"), (tr("Terracotta"), "#b4472f"), (tr("Phosphore"), "#3dff8a")]

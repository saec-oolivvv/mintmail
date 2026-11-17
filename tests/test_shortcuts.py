"""Raccourcis clavier configurables : catalogue complet, personnalisation, conflits, retour à l'origine."""
import os
import re

from mintmail import shortcuts as SC

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Cfg(dict):
    saved = 0

    def save(self):
        self.saved += 1


def test_every_shortcut_wired_in_the_windows_is_in_the_catalog():
    win = open(os.path.join(ROOT, "mintmail", "qt", "window.py"), encoding="utf-8").read()
    wired = set(re.findall(r'self\._act\(None, (?:tr\("[^"]*"\)|""), "((?:[^"\\]|\\\\)+)"', win))
    wired |= set(re.findall(r'self\._tool\("[^"]+", tr\("[^"]*"\), "((?:[^"\\]|\\\\)+)"', win))
    wired = {w.replace("\\\\", "\\") for w in wired}
    assert len(wired) >= 28, wired
    missing = [w for w in wired if SC.action_of(w, SC.MAIN) is None]
    assert not missing, "raccourcis du code absents du catalogue : %s" % missing


def test_catalog_has_unique_ids_and_no_default_clash_inside_a_scope():
    cat = SC.catalog()
    assert len({a[0] for a in cat}) == len(cat)
    for scope in (SC.MAIN, SC.COMPOSE):
        keys = [k.lower() for a in cat if a[1] == scope for k in a[4]]
        assert len(keys) == len(set(keys)), scope


def test_defaults_resolve_unchanged_without_customisation():
    cfg = Cfg()
    assert SC.resolve(cfg, "R") == "R" and SC.resolve(cfg, "Ctrl+=") == "Ctrl+=" and SC.resolve(cfg, "Ctrl+Return", SC.COMPOSE) == "Ctrl+Return"
    assert SC.resolve(cfg, "Inconnu") == "Inconnu"                                  # un raccourci hors catalogue n'est jamais perdu


def test_custom_key_replaces_every_default_of_the_action_and_can_be_disabled_or_reset():
    cfg = Cfg()
    assert SC.set_key(cfg, "zoom_in", "Ctrl+Shift+Z") is None
    assert SC.resolve(cfg, "Ctrl++") == "Ctrl+Shift+Z" and SC.resolve(cfg, "Ctrl+=") == ""        # une seule touche active
    assert SC.keys_of(cfg, "zoom_in") == ("Ctrl+Shift+Z",)
    assert SC.set_key(cfg, "reply", "") is None and SC.resolve(cfg, "R") == "" and SC.keys_of(cfg, "reply") == ()
    SC.reset(cfg, "reply")
    assert SC.resolve(cfg, "R") == "R"
    SC.reset(cfg)
    assert cfg["shortcuts"] == {} and cfg.saved >= 3


def test_conflicts_are_refused_inside_a_scope_only():
    cfg = Cfg()
    other = SC.set_key(cfg, "reply", "A")                                           # « A » = Répondre à tous
    assert other and other == next(a[3] for a in SC.catalog() if a[0] == "reply_all")
    assert "reply" not in (cfg.get("shortcuts") or {})
    assert SC.set_key(cfg, "compose_ai", "Ctrl+J") is None                          # même touche que l'assistant, mais autre fenêtre
    assert SC.set_key(cfg, "reply", "F") is not None                                # « F » = Transférer
    assert SC.set_key(cfg, "reply_all", "R") is not None and SC.set_key(cfg, "forward", "Z") is None
    assert SC.set_key(cfg, "reply", "F") is None                                    # « F » libéré par Transférer
    assert SC.conflict(cfg, "reply_all", "z") is not None                           # insensible à la casse


def test_setting_back_the_default_removes_the_override_and_bad_ids_are_rejected():
    cfg = Cfg()
    SC.set_key(cfg, "reply", "Z")
    SC.set_key(cfg, "reply", "R")
    assert cfg["shortcuts"] == {}
    try:
        SC.set_key(cfg, "n_existe_pas", "Z")
        assert False
    except KeyError:
        pass
    assert SC.overrides({"shortcuts": "nimporte quoi"}) == {} and SC.overrides({"shortcuts": {"a": 3, "b": "X"}}) == {"b": "X"}

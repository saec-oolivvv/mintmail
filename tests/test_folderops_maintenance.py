"""Fonctions portées de l'ancienne interface (1.35.0) : dossiers, épingles, recherche sur le serveur, langue — logique pure, sans Qt."""
import os, sys, time, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail.models import Message
from mintmail.qt import folderops as FO, maintenance as MT
from mintmail.qt.viewmodel import Engine
from mintmail.store import Cache, Config


class Be:
    def __init__(self):
        self.calls, self.acc = [], {"pin_server": True}
        self._pin_dirty = True

    def create_folder(self, path): self.calls.append(("create", path))
    def rename_folder(self, old, new): self.calls.append(("rename", old, new))
    def delete_folder(self, raw): self.calls.append(("delete", raw))
    def list_folders(self): return []
    def search_server(self, text, logicals, known): self.calls.append(("search", text, tuple(logicals))); return [self.msg]


def engine(tag):
    cfg = Config(os.path.join(testenv.tmp, "fo%s.json" % tag))
    cfg.data["accounts"] = [{"id": "a1", "email": "a@x.be", "name": "A"}]
    cfg.data["folders"] = {"a1": [{"name": "INBOX", "label": "INBOX", "path": "INBOX", "special": "inbox", "selectable": True, "delim": "/", "depth": 0},
                                  {"name": "Clients", "label": "Clients", "path": "Clients", "special": "", "selectable": True, "delim": "/", "depth": 0}]}
    e = Engine(cfg, Cache(os.path.join(testenv.tmp, "fo%s.db" % tag)))
    be = Be()
    be.msg = Message(id="s1", account="a1", folder="inbox", uid=5, real_folder="INBOX", sender_name="S", sender_email="s@x.be", subject="Trouvé",
                     date=time.time(), snippet="x", text="x", html="", unread=True)
    e._backends["a1"] = be
    return e, be


def test_menu_plan_never_offers_rename_or_delete_on_special_folders():
    assert FO.menu_plan(None) == ["new", "refresh"]
    assert FO.menu_plan({"special": "inbox", "selectable": True}) == ["sync", "sub", "refresh"]
    assert FO.menu_plan({"special": "", "selectable": True}) == ["sync", "sub", "rename", "delete", "refresh"]
    assert all(FO.label_of(k) for k in ("sync", "new", "sub", "rename", "delete", "refresh"))


def test_create_rename_delete_folder_update_server_and_local_tree():
    e, be = engine(1)
    assert FO.check_name("a/b", None)[1] and FO.check_name("  ", None) == ("", "")
    assert "créé" in FO.create(e, "a1", "Factures")
    assert ("create", "Factures") in be.calls and any(x["label"] == "Factures" for x in e.folder_entries("a1"))
    entry = FO.entry_of(e, "a1", "Clients")
    assert "renommé" in FO.rename(e, "a1", entry, "Anciens clients") and ("rename", "Clients", "Anciens clients") in be.calls
    assert FO.rename(e, "a1", entry, "Clients") == ""                                                   # même nom : rien à faire
    e.cache.upsert_many([Message(id="d1", account="a1", folder="f:Clients", uid=9, real_folder="Clients", sender_name="S", sender_email="s@x.be",
                                 subject="x", date=time.time(), snippet="x", text="x", html="", unread=False)])
    assert FO.delete(e, "a1", entry) and ("delete", "Clients") in be.calls and e.cache.get("d1") is None


def test_pins_are_pushed_once_and_server_search_adds_messages():
    e, be = engine(2)
    m = Message(id="p1", account="a1", folder="inbox", uid=3, real_folder="INBOX", sender_name="S", sender_email="s@x.be", subject="Épinglé",
                date=time.time(), snippet="x", text="x", html="", unread=False, pinned=True)
    e.cache.upsert_many([m])
    assert MT.save_pin_states(e) == ["a1"] and e.config["pins_pushed"] == ["a1"]
    assert MT.save_pin_states(e) == []                                                                  # une seule fois par compte
    assert MT.push_pins(e) == 1 and e.cache.ops_count() >= 0
    assert MT.pins_text(0) and MT.pins_text(2)
    assert MT.server_search_logicals("f:Clients") == ["inbox", "sent", "archive", "f:Clients"] and MT.server_search_logicals("inbox") == ["inbox", "sent", "archive"]
    assert MT.search_server(e, "Trouvé", "inbox") == 1 and e.cache.get("s1") is not None
    assert MT.server_search_text(0) != MT.server_search_text(3)


def test_language_choice_is_saved_and_validated():
    e, _ = engine(3)
    codes = [c for c, _l in MT.languages()]
    assert codes[0] == "auto" and "fr" in codes and "en" in codes
    assert MT.set_language(e.config, "en") and e.config["ui_lang"] == "en"
    assert MT.set_language(e.config, "xx") == "" and e.config["ui_lang"] == "en"                        # code inconnu : refusé

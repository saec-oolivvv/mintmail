"""Test de fumée sans interface : charge tous les modules purs (moteur et logique de l'interface Qt) et exécute les fonctions qui fabriquent des textes
(aide, menus, palette, thème, agenda, tâches). Sert à vérifier qu'aucune logique ne dépend du texte français affiché (voir test_i18n). Affiche « SMOKE OK »."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv  # noqa: F401
from mintmail import help_content as H, tasks, slots, util
from mintmail.models import Message
from mintmail.qt import accounts, aiwork, automation, calendars, folderops, gestures, imagetrust, maintenance, menus, navtree, organizer, personal, savedsearch, syncing, theme, viewmodel  # noqa: F401

CTX = {"version": "9.9.9", "config": "/c", "data": "/d", "log": "/d/mintmail.log"}
assert len(H.full_text(CTX)) > 20000
assert H.search("signature", CTX)
msg = Message(id="m1", account="a", folder="inbox", uid=1, sender_name="Marie", sender_email="marie@x.be", subject="Sujet", date=time.time(),
              snippet="x", text="x", html="<p>x</p>", unread=True)
assert menus.context_items(msg) and menus.palette_commands(msg) and menus.palette_commands(None)
from mintmail.store import Config
assert theme.build_qss(theme.resolve(Config()))
assert tasks.due_label({"due": "2026-11-09"}, __import__("datetime").date(2026, 11, 10))
assert util.human_size(3 * 1024 * 1024)
assert [label for _code, label in maintenance.languages()][0]
assert folderops.menu_plan(None) == ["new", "refresh"] and "rename" in folderops.menu_plan({"special": "", "selectable": True})
assert "rename" not in folderops.menu_plan({"special": "inbox", "selectable": True})
print("SMOKE OK")

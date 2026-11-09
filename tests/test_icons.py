"""Icône et lanceur : fichiers présents, tailles exactes, association fenêtre / entrée de menu."""
import os, re, sys, xml.dom.minidom
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_icon_files():
    from PIL import Image
    d = os.path.join(ROOT, "mintmail", "icons")
    for size in (16, 22, 24, 32, 48, 64, 96, 128, 192, 256, 512):
        im = Image.open(os.path.join(d, "mintmail-%d.png" % size))
        assert im.size == (size, size) and im.mode == "RGBA" and im.getpixel((size // 2, size // 2))[3] == 255
    assert im.getpixel((0, 0))[3] == 0                                      # coins transparents (carré arrondi)
    doc = xml.dom.minidom.parse(os.path.join(d, "mintmail.svg"))
    assert doc.documentElement.getAttribute("viewBox") == "0 0 256 256"
    assert open(os.path.join(d, "mintmail.svg")).read() == open(os.path.join(ROOT, "data", "mintmail.svg")).read()


def test_desktop_entry_matches_the_window_class_and_app_id():
    from mintmail import APP_ID
    path = os.path.join(ROOT, "data", APP_ID + ".desktop")                  # nom = identifiant de l'application (GNOME / Wayland)
    text = open(path, encoding="utf-8").read()
    kv = dict(l.split("=", 1) for l in text.splitlines() if "=" in l and not l.startswith("["))
    assert kv["Icon"] == "mintmail" and kv["Exec"].endswith("%U") and "mailto" in kv["MimeType"]
    assert kv["StartupWMClass"] == "mintmail" and kv["Terminal"] == "false" and kv["Type"] == "Application"
    app = open(os.path.join(ROOT, "mintmail", "app.py"), encoding="utf-8").read()
    assert 'GLib.set_prgname("mintmail")' in app and 'Gdk.set_program_class("mintmail")' in app     # même classe que le lanceur
    assert "set_default_icon_list" in app                                   # repli si l'icône n'est pas dans le thème
    for f in ("install.sh", "uninstall.sh"):
        assert APP_ID + ".desktop" in open(os.path.join(ROOT, f), encoding="utf-8").read()

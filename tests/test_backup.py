"""Sauvegarde / restauration / réparation / démarrages ratés."""
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail import backup as BK


def mk():
    t = Path(tempfile.mkdtemp())
    c, d = t / "cfg", t / "data"
    c.mkdir(), d.mkdir()
    (c / "config.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    con = sqlite3.connect(str(d / "cache.db"))
    con.execute("create table messages(id text)")
    con.execute("insert into messages values('m1')")
    con.commit()
    con.close()
    return c, d


def rows(d):
    con = sqlite3.connect(str(d / "cache.db"))
    try:
        return [r[0] for r in con.execute("select id from messages")]
    finally:
        con.close()


def test_create_and_inspect():
    c, d = mk()
    z = BK.create(c, d, version="9.9")
    man = BK.inspect(z)
    assert set(man["files"]) == {"config.json", "cache.db"} and man["version"] == "9.9"
    assert (os.stat(z).st_mode & 0o077) == 0
    assert not list(d.glob("cache.snapshot-*"))


def test_restore_roundtrip_with_safety_copy():
    c, d = mk()
    z = BK.create(c, d, d / "b.zip")
    (c / "config.json").write_text(json.dumps({"theme": "light"}), encoding="utf-8")
    con = sqlite3.connect(str(d / "cache.db"))
    con.execute("delete from messages")
    con.commit()
    con.close()
    res = BK.restore(z, c, d)
    assert json.loads((c / "config.json").read_text())["theme"] == "dark" and rows(d) == ["m1"]
    safe = BK.inspect(res["safety"])                      # l'état d'avant (écrasé) est gardé
    assert "config.json" in safe["files"]
    with zipfile.ZipFile(res["safety"]) as zz:
        assert json.loads(zz.read("config.json"))["theme"] == "light"


def test_rejects_foreign_and_traversal():
    c, d = mk()
    bad = d / "x.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("a.txt", "x")
    for p in (bad, d / "absent.zip"):
        try:
            BK.inspect(p)
            assert False
        except ValueError:
            pass
    evil = d / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("../../evil.txt", "x")
        z.writestr("config.json", "{}")
        z.writestr(BK.MANIFEST, json.dumps({"app": "MintMail", "files": ["../../evil.txt", "config.json"]}))
    assert BK.inspect(evil)["files"] == ["config.json"]
    BK.restore(evil, c, d)
    assert not (d.parent / "evil.txt").exists() and not (d.parent.parent / "evil.txt").exists()


def test_repair_sets_aside_corrupt_files():
    c, d = mk()
    assert BK.repair(c, d) == [] and BK.check_db(d / "cache.db") and BK.check_config(c / "config.json")
    (d / "cache.db").write_bytes(b"ceci n'est pas une base" * 50)
    (c / "config.json").write_text("{pas du json", encoding="utf-8")
    done = BK.repair(c, d)
    assert {w for w, _ in done} == {"cache", "config"}
    assert not (d / "cache.db").exists() and list(d.glob("cache.db.corrupt-*")) and list(c.glob("config.json.corrupt-*"))
    assert BK.check_db(d / "cache.db") and BK.check_config(c / "config.json")        # absents = sains (recréés)


def test_crash_counter_and_safe_mode():
    _, d = mk()
    assert BK.note_start(d) == 0 and BK.note_start(d) == 1 and BK.note_start(d) == 2
    assert BK.should_start_safe(2) and not BK.should_start_safe(1)
    BK.note_ok(d)
    assert BK.note_start(d) == 0


def test_apply_safe_is_not_saved():
    from mintmail.store import Config
    c, _ = mk()
    cfg = Config(c / "config.json")
    cfg.data["p2p_enabled"], cfg.data["absence"] = True, {"enabled": True}
    BK.apply_safe(cfg)
    assert cfg.data["p2p_enabled"] is False and cfg.data["absence"]["enabled"] is False
    cfg.save()
    assert "p2p_enabled" not in json.loads((c / "config.json").read_text()) or json.loads((c / "config.json").read_text())["p2p_enabled"] is not False

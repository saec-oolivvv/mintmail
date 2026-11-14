"""Mise à jour sur Mac : image disque (.dmg) téléchargée, somme de contrôle vérifiée, ouverte dans le Finder ; mêmes états que sous Linux."""
import hashlib, os, sys, tempfile, types
import testenv  # noqa: F401
from mintmail import updater as U
from mintmail.qt import updating as UP

DATA = b"dmg-bytes" * 100
GOOD = hashlib.sha256(DATA).hexdigest()


def up(**kw):
    d = dict(version="9.9.9", deb_url="https://github.com/o/r/a.deb", deb_size=1, sig_url="", sums_url="", notes="", page="https://github.com/o/r/releases/tag/v9.9.9",
             dmg_url="https://github.com/o/r/MintMail-9.9.9-macos-x86_64.dmg", dmg_sum_url="https://github.com/o/r/MintMail-9.9.9-macos-x86_64.dmg.sha256", dmg_size=len(DATA))
    d.update(kw)
    return U.Update(**d)


def patched(sum_line):
    old = U._download, U._get
    U._download = lambda url, dest, limit, expected=0, allow_loopback=False, progress=None: (open(dest, "wb").write(DATA), progress and progress(len(DATA), expected), GOOD)[2]
    U._get = lambda url, headers, limit, allow_loopback=False, timeout=30: (200, {}, sum_line.encode())
    return old


def test_arch_and_names():
    assert U.mac_arch("arm64") == "arm64" and U.mac_arch("x86_64") == "x86_64" and U.mac_arch("AMD64") == "x86_64"
    assert U.mac_dmg_name("1.2.3", "arm64") == "MintMail-1.2.3-macos-arm64.dmg"


def test_fetch_dmg_verifies_the_checksum_and_refuses_anything_else():
    d = tempfile.mkdtemp()
    name = U.mac_dmg_name("9.9.9")
    old = patched("%s  %s\n" % (GOOD, name))
    try:
        seen = []
        p = U.fetch_dmg(up(), d, progress=lambda a, b: seen.append(a))
        assert os.path.basename(str(p)) == name and open(p, "rb").read() == DATA and seen
        U._get = lambda *a, **k: (200, {}, ("%s  %s\n" % ("0" * 64, name)).encode())
        try:
            U.fetch_dmg(up(), d)
            assert False
        except U.UpdateError as e:
            assert e.code == "checksum" and not os.path.exists(os.path.join(d, name))             # image refusée ET supprimée
        U._get = lambda *a, **k: (200, {}, b"rien d'utile\n")
        try:
            U.fetch_dmg(up(), d)
            assert False
        except U.UpdateError as e:
            assert e.code == "checksum"
        try:
            U.fetch_dmg(up(dmg_sum_url=""), d)
            assert False
        except U.UpdateError as e:
            assert e.code == "nodmg"
    finally:
        U._download, U._get = old


def test_update_dict_roundtrip_keeps_the_dmg_only_on_allowed_hosts():
    back = U.update_from_dict(U.update_to_dict(up()), current="1.0.0")
    assert back and back.dmg_url.endswith(".dmg") and back.dmg_size == len(DATA)
    evil = U.update_to_dict(up(dmg_url="https://evil.example/x.dmg"))
    back = U.update_from_dict(evil, current="1.0.0")
    assert back and back.dmg_url == "" and back.dmg_sum_url == ""                                   # état falsifié : l'annonce reste, pas le téléchargement


def test_mac_install_flow_downloads_opens_and_reports():
    class Cfg(dict):
        def save(self): pass
    calls, log = [], []
    fake = types.SimpleNamespace(can_install=lambda: (False, "macos"), update_from_dict=lambda d, v: None, restart_pending=lambda v: "", is_newer=U.is_newer,
                                 fetch_dmg=lambda u, d, progress=None: (log.append("fetch"), progress and progress(5, 10), "/tmp/x.dmg")[2],
                                 open_dmg=lambda p: log.append(("open", p)) or True, cleanup=lambda: None)
    old = UP._mac
    UP._mac = lambda: True
    try:
        st = UP.UpdateState(Cfg(), upd=fake, version="1.0.0")
        st.update = up()
        st.show_progress = lambda *a: calls.append(("progress",) + a)
        st.show_error = lambda text, page="": calls.append(("error", text))
        st.show_mac_done = lambda v: calls.append(("done", v))
        st.refresh = lambda force=False: None
        assert st.start_install() is None and st.busy and calls[-1][0] == "progress"
        stages = []
        res = st.install_work(lambda v, t, f: stages.append((t, f)))
        assert res == (True, "", "/tmp/x.dmg") and log == ["fetch", ("open", "/tmp/x.dmg")] and stages
        st.finish_install(res, None)
        assert calls[-1] == ("done", "9.9.9") and not st.busy and st.update is None
        st2 = UP.UpdateState(Cfg(), upd=fake, version="1.0.0")                      # image pas encore publiée : message clair, rien n'est téléchargé
        st2.update = up(dmg_url="", dmg_sum_url="")
        st2.show_error = lambda text, page="": calls.append(("error", text))
        text = st2.start_install()
        assert text and "dmg" in text and calls[-1][0] == "error" and not st2.busy
        assert "dmg" in st2.key_line() or "image disque" in st2.key_line()
    finally:
        UP._mac = old

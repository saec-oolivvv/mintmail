"""Réplication entre postes : création de dossier sans double CREATE (« créer » + « déplacer » validés d'un coup), dossier visible
tout de suite, relecture des dossiers coalescée et espacée, et IDLE qui réagit aux changements de drapeaux faits ailleurs (épingles)."""
import os, sys, time, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtkstub   # noqa: F401
from test_listing import make_window
from mintmail import backend as B


def _win(tag, server_lists_new_folder=True):
    w = make_window(30 + tag)
    w._init_folders()
    w.folder_tree = {}
    w.accounts = lambda: [{"id": "a1"}]
    w._rebuild_nav_dynamic = lambda: None
    w.refresh_folder_counts = lambda: None
    w.run_bg = lambda fn, done=None: (lambda r: done(*r) if done else None)(_call(fn))
    srv = types.SimpleNamespace(created=[], listed=0, folders=[])

    def create(path):
        if path in srv.folders:
            raise B.BackendError("[ALREADYEXISTS] Duplicate folder name")
        srv.created.append(path)
        if server_lists_new_folder:
            srv.folders.append(path)

    def list_folders():
        srv.listed += 1
        return [{"name": f, "path": f, "label": f, "depth": 0, "delim": "/", "special": "", "selectable": True} for f in srv.folders]
    be = types.SimpleNamespace(demo=False, create_folder=create, list_folders=list_folders)
    w.backend = lambda aid: be
    return w, srv


def _call(fn):
    try:
        return fn(), None
    except Exception as e:
        return None, e


def test_two_requests_for_the_same_new_folder_create_it_once_and_both_continue():
    w, srv = _win(1)
    got = []
    w.run_bg = lambda fn, done=None: got.append((fn, done))          # création « en vol » : la 2e demande arrive avant la fin de la 1re
    w.create_folder_named("a1", "LTD", None, lambda e: got.append(("cb1", e["path"])))
    w.create_folder_named("a1", "LTD", None, lambda e: got.append(("cb2", e["path"])))
    assert len(got) == 1, "une seule création lancée"
    fn, done = got.pop()
    w.run_bg = lambda fn, done=None: (lambda r: done(*r) if done else None)(_call(fn))
    done(*_call(fn))
    assert srv.created == ["LTD"] and ("cb1", "LTD") in got and ("cb2", "LTD") in got, (srv.created, got)


def test_already_exists_is_not_an_error_and_the_move_continues():
    w, srv = _win(2)
    srv.folders.append("LTD")                                        # créé entre-temps depuis un autre poste
    w.folder_tree = {"a1": []}                                       # mais notre arbre ne le connaît pas encore
    got = []
    w.create_folder_named("a1", "LTD", None, lambda e: got.append(e["path"]))
    assert got == ["LTD"] and not [t for t in getattr(w, "toasts", []) if "impossible" in t[0]]


def test_the_new_folder_is_usable_even_if_the_server_list_does_not_show_it_yet():
    w, srv = _win(3, server_lists_new_folder=False)
    got = []
    w.create_folder_named("a1", "Factures", None, lambda e: got.append(e))
    assert got and got[0]["path"] == "Factures" and got[0]["name"] == "Factures" and got[0]["selectable"]
    assert any(e["path"] == "Factures" for e in w.folder_tree["a1"])   # et visible dans la barre latérale


def test_a_real_creation_error_is_reported_and_forgotten():
    w, srv = _win(4)
    w.backend = lambda aid: types.SimpleNamespace(demo=False, list_folders=lambda: [], create_folder=lambda p: (_ for _ in ()).throw(B.BackendError("quota")))
    got = []
    w.create_folder_named("a1", "X", None, lambda e: got.append(e))
    assert not got and w.toasts[-1][0].startswith("Création du dossier impossible") and not w._folder_creating


def test_folder_refresh_is_throttled_and_coalesced():
    w, srv = _win(5)
    srv.folders.append("Clients")
    w.refresh_folders()
    assert srv.listed == 1 and w.folder_tree["a1"][0]["path"] == "Clients"       # un dossier créé ailleurs apparaît
    w.refresh_folders_soon(20)
    assert srv.listed == 1                                                       # trop tôt : pas de nouvelle commande
    w._folders_ts -= 30
    w.refresh_folders_soon(20)
    assert srv.listed == 2
    pend = []
    w.run_bg = lambda fn, done=None: pend.append((fn, done))
    w.refresh_folders(); w.refresh_folders(after=lambda: pend.append("after"))
    assert len(pend) == 1                                                        # 2e demande pendant la 1re : mise en attente
    fn, done = pend.pop(); done(*_call(fn))
    assert len(pend) == 1 and w._folders_again is False                          # une relecture de plus est lancée (elle verra les créations récentes)


def test_idle_wakes_up_on_flag_changes_made_by_another_machine():
    class Sock:
        def __init__(s): s.out, s.q = [], [b"+ idling\r\n", b"* 7 FETCH (FLAGS (\\Flagged $MintMailPinned))\r\n", b"A1 OK Idle completed\r\n"]
        def sendall(s, b): s.out.append(b)
        def recv(s, n): return s.q.pop(0)
        def pending(s): return True
    imap = types.SimpleNamespace(sock=Sock(), _new_tag=lambda: b"A1")
    stop = types.SimpleNamespace(is_set=lambda: False)
    assert B.IMAPBackend._idle_once(imap, stop, max_wait=5) is True
    assert imap.sock.out[-1] == b"DONE\r\n"

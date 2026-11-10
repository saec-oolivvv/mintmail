"""tools/translate_catalog.py : pré-traduction par un service d'IA compatible OpenAI, testée contre un FAUX serveur local."""
import io, contextlib, json, os, shutil, sys, tempfile, threading, importlib.util
from http.server import BaseHTTPRequestHandler, HTTPServer
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TOOL = os.path.join(ROOT, "tools", "translate_catalog.py")


class Fake(BaseHTTPRequestHandler):
    seen = {}          # texte français -> nombre de demandes
    auth = []
    requests = 0

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.requests += 1
        Fake.auth.append(self.headers.get("Authorization"))
        user = body["messages"][1]["content"]
        payload = json.loads(user.split("\n\nPREVIOUS ANSWER")[0])
        out = {}
        for i, d in payload.items():
            fr, en = d["fr"], d["en"]
            Fake.seen[fr] = Fake.seen.get(fr, 0) + 1
            if fr == "Annuler":
                out[i] = ""                                                    # le « modèle » refuse toujours cette entrée
            elif "%d" in fr and Fake.seen[fr] == 1:
                out[i] = "[xx] sans marqueurs"                                  # 1re réponse fautive (marqueur perdu) : doit être redemandée
            else:                                                              # un bon modèle conserve espaces et retours à la ligne de début / fin
                lead, trail = fr[:len(fr) - len(fr.lstrip())], fr[len(fr.rstrip()):]
                out[i] = lead + "[xx] " + en.strip() + trail
        text = "```json\n" + json.dumps(out, ensure_ascii=False) + "\n```"      # le modèle entoure sa réponse de balises : l'outil doit s'y retrouver
        data = json.dumps({"choices": [{"message": {"content": text}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def load_tool():
    spec = importlib.util.spec_from_file_location("translate_catalog", TOOL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_translation_tool_validates_retries_resumes_and_produces_loadable_catalogs():
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/v1" % srv.server_port
    d = tempfile.mkdtemp()
    for f in ("en.json", "help_en.json"):
        shutil.copy(os.path.join(ROOT, "mintmail", "locale", f), d)
    tool = load_tool()
    os.environ["TEST_TRANSLATE_KEY"] = "sk-secret-do-not-print"
    out, err = io.StringIO(), io.StringIO()
    args = ["--lang", "xx", "--base-url", url, "--model", "fake", "--batch", "40", "--limit", "130", "--locale-dir", d, "--key-env", "TEST_TRANSLATE_KEY", "--help-too", "--lang-name", "Testish"]
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = tool.main(args)
    shown = out.getvalue() + err.getvalue()
    assert code == 1 and "TRADUCTION AUTOMATIQUE" in shown and "sk-secret" not in shown               # entrée refusée -> code 1 ; la clé n'est jamais affichée
    assert set(Fake.auth) == {"Bearer sk-secret-do-not-print"}                                          # la clé part seulement en en-tête
    cat = json.load(open(os.path.join(d, "xx.json"), encoding="utf-8"))
    from mintmail import i18n
    ids = json.load(open(os.path.join(ROOT, "tools", "i18n_msgids.json"), encoding="utf-8"))
    n_expected = min(130, len(ids)) - 1                                                                  # les 130 premières entrées, moins la refusée
    assert len(cat) == n_expected and "Annuler" not in cat, len(cat)
    assert all(not i18n.check_entry(k, v) for k, v in cat.items())                                      # tout ce qui est écrit est valide
    percent = [k for k in cat if "%d" in k]
    assert percent and all("%d" in cat[k] for k in percent)                                             # les réponses fautives ont été redemandées puis corrigées
    assert all(Fake.seen[k] == 2 for k in percent) and all(Fake.seen[k] == 1 for k in cat if "%d" not in k)
    st = json.load(open(os.path.join(d, "xx.status.json"), encoding="utf-8"))
    assert st["machine_translated"] is True and st["reviewed_by_human"] is False and st["rejected"] == 1 and st["strings"] == n_expected
    h = json.load(open(os.path.join(d, "help_xx.json"), encoding="utf-8"))
    he = json.load(open(os.path.join(d, "help_en.json"), encoding="utf-8"))
    assert [s["id"] for s in h["sections"]] == [s["id"] for s in he["sections"]] and h["sections"][0]["title"].startswith("[xx] ")
    assert h["sections"][0]["items"][0][1].count("\n") == he["sections"][0]["items"][0][1].count("\n")
    # reprise : seules les entrées manquantes sont redemandées
    before = Fake.requests
    with contextlib.redirect_stdout(io.StringIO()):
        tool.main(["--lang", "xx", "--base-url", url, "--model", "fake", "--limit", "1", "--locale-dir", d])
    assert Fake.requests - before == 3, Fake.requests - before                                          # 1 entrée restante (la refusée) : 1 essai + 2 reprises, rien d'autre
    assert len(json.load(open(os.path.join(d, "xx.json"), encoding="utf-8"))) == n_expected
    out2 = io.StringIO()
    with contextlib.redirect_stdout(out2):
        assert tool.main(["--lang", "xx", "--check", "--locale-dir", d]) == 1
    assert ("%d / %d" % (n_expected, len(ids))) in out2.getvalue(), out2.getvalue()
    # le catalogue produit se charge réellement
    old = i18n.LOCALE_DIR
    i18n.LOCALE_DIR = type(old)(d)
    try:
        assert "xx" in i18n.available() and i18n.set_language("xx") == "xx"
        sample = sorted(cat)[0]
        assert i18n.tr(sample).strip().startswith("[xx] ") and i18n.tr("Annuler") == "Annuler"                # entrée refusée : retombe sur le français
    finally:
        i18n.LOCALE_DIR = old
        i18n.set_language("fr")
    srv.shutdown()


def test_translation_tool_refuses_unsafe_or_pointless_requests():
    tool = load_tool()
    for argv in (["--lang", "fr"], ["--lang", "en"], ["--lang", "de", "--base-url", "http://exemple.org/v1", "--model", "m"],
                 ["--lang", "de", "--base-url", "http://8.8.8.8/v1", "--model", "m"], ["--lang", "de"]):
        try:
            tool.main(argv)
            raise AssertionError("accepté : %r" % argv)
        except SystemExit as e:
            assert e.code not in (0, None)
    tool.check_base_url("https://api.exemple.be/v1")
    tool.check_base_url("http://localhost:11434/v1")
    tool.check_base_url("http://192.168.1.20:8080/v1")

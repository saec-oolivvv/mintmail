"""IA locale (Ollama), clé facultative, habitudes de rangement dans le classement, résumé de conversation."""
import json, os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ["XDG_DATA_HOME"] = tmp
os.environ["XDG_CONFIG_HOME"] = tmp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_modules import Server
from mintmail import ai_service as S
from mintmail.ai_engine import AIEngine
from mintmail.models import Message
from mintmail.store import Cache, Config


def engine(name, **cfg):
    c = Config(os.path.join(tmp, name + ".json"))
    c.data.update(cfg)
    return AIEngine(c, Cache(os.path.join(tmp, name + ".db"))), c


def msg(i, subject="S", sender="a@x.be", thread="t1"):
    return Message(id="m%d" % i, account="acc", folder="inbox", uid=i, sender_name="A", sender_email=sender, subject=subject,
                   date=1000 + i, text="corps %d" % i, snippet="x", thread_id=thread)


def test_local_provider_needs_no_key_and_sends_no_authorization_header():
    srv = Server(lambda m, path, h, b: (200, "application/json", json.dumps({"choices": [{"message": {"content": "Bonjour local"}}]}), {}))
    try:
        eng, c = engine("p1", ai_enabled=True, ai_provider="ollama", nvidia_api_base=srv.url + "/v1")
        svc = eng.service()
        assert svc is not None and svc.local and svc.api_key == ""
        assert svc.call([{"role": "user", "content": "salut"}]) == "Bonjour local"
        method, path, headers, body = srv.requests[0]
        assert path == "/v1/chat/completions" and "Authorization" not in headers and json.loads(body)["model"] == "llama3.2"
        assert eng.enabled() is True
        eng2, _ = engine("p2", ai_enabled=True, ai_provider="nvidia")                  # NVIDIA : la clé reste obligatoire
        assert eng2.service() is None and eng2.enabled() is False
        eng3, _ = engine("p3", ai_enabled=True, ai_provider="custom", nvidia_api_base="http://exemple.com/v1")
        assert eng3.service() is None or not eng3.service().is_configured() or eng3.service() is None   # HTTP public : refusé
        svc3 = S.AIService("", "http://exemple.com/v1")
        try:
            svc3.call([{"role": "user", "content": "x"}]); raise SystemExit("HTTP public accepté")
        except S.AIServiceError:
            pass
        eng4, _ = engine("p4", ai_enabled=True, ai_provider="custom", nvidia_api_base="http://192.168.1.50:8080/v1", ai_model="mon-modele")
        assert eng4.service() is not None and eng4.service().model == "mon-modele"      # serveur du réseau local compatible OpenAI
    finally:
        srv.close()


def test_model_listing_openai_style_and_ollama_tags():
    def route(m, path, h, b):
        if path == "/v1/models":
            return 404, "text/plain", "", {}
        if path == "/api/tags":
            return 200, "application/json", json.dumps({"models": [{"name": "llama3.2:latest"}, {"name": "mistral:7b"}]}), {}
        return 404, "text/plain", "", {}
    srv = Server(route)
    srv2 = Server(lambda m, p, h, b: (200, "application/json", json.dumps({"data": [{"id": "gpt-x"}, {"id": "gpt-y"}]}), {}))
    try:
        assert S.list_models(srv.url + "/v1") == ["llama3.2:latest", "mistral:7b"]      # repli sur /api/tags d'Ollama
        assert S.list_models(srv2.url + "/v1") == ["gpt-x", "gpt-y"]
        try:
            S.list_models("http://127.0.0.1:9/v1", timeout=1); raise SystemExit("service injoignable")
        except S.AIServiceError as e:
            assert "Aucun modèle" in str(e)
    finally:
        srv.close(); srv2.close()


def test_classification_prompt_contains_user_habits_and_thread_summary_is_cached():
    prompts = []

    def route(m, path, h, b):
        prompts.append(json.loads(b)["messages"][-1]["content"])
        content = "[]" if "tu ranges" in prompts[-1].lower() else "Décision : go. Reste : devis."
        return 200, "application/json", json.dumps({"choices": [{"message": {"content": content}}]}), {}
    srv = Server(route)
    try:
        eng, c = engine("p5", ai_enabled=True, ai_provider="ollama", nvidia_api_base=srv.url + "/v1")
        eng.cache.learn_record("acc", "compta@x.be", "Factures"); eng.cache.learn_record("acc", "compta@x.be", "Factures")
        eng.cache.learn_record("acc", "x@y.be", "Disparu"); eng.cache.learn_record("acc", "x@y.be", "Disparu")
        eng.classify([msg(1, sender="compta@x.be")], ["Factures", "Clients"], account="acc")
        p = prompts[-1]
        assert "Habitudes de rangement" in p and "compta@x.be → Factures" in p
        assert "Disparu" not in p                                                      # dossier supprimé : habitude ignorée
        eng.classify([msg(1)], ["Factures"])                                           # sans compte : pas d'habitudes
        assert "Habitudes" not in prompts[-1]
        ms = [msg(1, "Devis"), msg(2, "Re: Devis")]
        assert eng.summarize_thread(ms) == "Décision : go. Reste : devis."
        n = len(prompts)
        assert eng.summarize_thread(ms) == "Décision : go. Reste : devis." and len(prompts) == n   # mis en cache
        eng.summarize_thread(ms + [msg(3, "Re: Devis")])
        assert len(prompts) == n + 1                                                   # un message de plus : nouveau résumé
    finally:
        srv.close()

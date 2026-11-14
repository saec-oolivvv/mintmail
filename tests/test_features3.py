"""Tâches, page « Aujourd'hui », créneaux libres, brouillons de réponse préparés."""
import datetime, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from test_modules import Server
from mintmail.models import Message
from mintmail import gcal, oauth, slots, syncdata, tasks
from mintmail.ai_engine import AIEngine
from mintmail.store import Cache, Config


def real_msg(i, subject, folder="inbox", account="acc", sender="a@x.be"):
    return Message(id="r%d" % i, account=account, folder=folder, uid=i + 1, real_folder="INBOX", sender_name="A", sender_email=sender, subject=subject,
                   date=time.time() - i, snippet=subject, text=subject + " : pouvez-vous me répondre ?", html="", unread=True)


def test_triage_reads_reply_needed_from_the_model_and_defaults_to_false_locally():
    def route(m, path, h, b):
        return 200, "application/json", json.dumps({"choices": [{"message": {"content": json.dumps(
            [{"i": 0, "summary": "Demande de devis", "priority": 3, "spam": False, "category": "people", "reply": True},
             {"i": 1, "summary": "Promo", "priority": 1, "spam": False, "category": "news"}])}}]}), {}
    srv = Server(route)
    try:
        c = Config(os.path.join(testenv.tmp, "tri.json"))
        c.data.update(ai_enabled=True, ai_provider="ollama", nvidia_api_base=srv.url + "/v1")
        eng = AIEngine(c, Cache(os.path.join(testenv.tmp, "tri.db")))
        ms = [real_msg(1, "Devis ?"), real_msg(2, "Promo")]
        out = eng.triage(ms)
        assert out["r1"]["reply_needed"] is True and out["r2"]["reply_needed"] is False and out["r1"]["priority"] == 3
        c.data["ai_enabled"] = False
        local = eng.triage([real_msg(3, "Autre")])
        assert local["r3"]["reply_needed"] is False and local["r3"]["local"] is True
    finally:
        srv.close()

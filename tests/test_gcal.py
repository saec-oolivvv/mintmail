"""Google Agenda : API (serveur local simulé), autorisation supplémentaire OAuth, routage des événements, conflits, agenda."""
import datetime, json, os, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from test_modules import Server
from mintmail import caldav, gcal, oauth, syncdata


def google(store, mode="ok"):
    def route(method, path, headers, body):
        if headers.get("Authorization") != "Bearer TOK":
            return 401, "application/json", json.dumps({"error": {"message": "Invalid Credentials"}}), {}
        if mode == "scope":
            return 403, "application/json", json.dumps({"error": {"message": "Request had insufficient authentication scopes."}}), {}
        if mode == "disabled":
            return 403, "application/json", json.dumps({"error": {"message": "Google Calendar API has not been used in project 123 before or it is disabled."}}), {}
        if method == "POST":
            ev = json.loads(body)
            if ev.get("id") in store:
                return 409, "application/json", json.dumps({"error": {"message": "duplicate"}}), {}
            store[ev["id"] if "id" in ev else "x%d" % len(store)] = ev
            return 200, "application/json", json.dumps({"id": "ok"}), {}
        loc = lambda h, m: datetime.datetime(2026, 11, 12, h, m).astimezone().isoformat()      # indépendant du fuseau de la machine
        items = [{"summary": "Réunion équipe", "start": {"dateTime": loc(13, 30)}, "end": {"dateTime": loc(14, 30)}, "location": "Salle B"},
                 {"summary": "Congé", "start": {"date": "2026-11-12"}, "end": {"date": "2026-11-13"}},
                 {"summary": "Annulé", "status": "cancelled", "start": {"dateTime": loc(14, 0)}, "end": {"dateTime": loc(15, 0)}},
                 {"summary": "cassé"}]
        return 200, "application/json", json.dumps({"items": items}), {}
    return Server(route)


def test_insert_is_idempotent_and_formats_the_event():
    store = {}
    srv = google(store)
    try:
        ev = {"title": "Point projet", "start": "2026-11-12T14:00", "end": "2026-11-12T15:30", "location": "Salle A", "description": "Ordre du jour"}
        assert gcal.insert_event("TOK", ev, "uid-1@x", base=srv.url + "/calendar/v3") == (True, "ajouté")
        m, path, headers, body = srv.requests[0]
        sent = json.loads(body)
        assert path == "/calendar/v3/calendars/primary/events" and sent["summary"] == "Point projet" and sent["location"] == "Salle A"
        assert sent["start"]["dateTime"].startswith("2026-11-12T14:00:00") and sent["end"]["dateTime"].startswith("2026-11-12T15:30:00")
        assert len(sent["id"]) == 40 and set(sent["id"]) <= set("0123456789abcdef")                     # identifiant accepté par Google
        assert gcal.insert_event("TOK", ev, "uid-1@x", base=srv.url + "/calendar/v3") == (True, "déjà dans votre agenda")   # pas de doublon
        assert gcal.to_google_event({"title": "x", "start": "2026-11-12T14:00"})["end"]["dateTime"].startswith("2026-11-12T15:00")   # durée 1 h par défaut
        assert gcal.to_google_event({"title": "x", "start": "2026-11-12T14:00", "end": "2026-11-12T13:00"})["end"]["dateTime"].startswith("2026-11-12T15:00")
        assert gcal.insert_event("MAUVAIS", ev, base=srv.url + "/calendar/v3") == (False, "jeton refusé : reconnectez le compte (Paramètres → Comptes)")
        assert gcal.insert_event("TOK", ev, base="http://exemple.com/calendar/v3") == (False, "HTTPS obligatoire")
    finally:
        srv.close()


def test_errors_are_explained_in_plain_language():
    for mode, expected in (("scope", gcal.NEED_SCOPE), ("disabled", "Google Calendar API")):
        srv = google({}, mode)
        try:
            ok, msg = gcal.insert_event("TOK", {"title": "x", "start": "2026-11-12T14:00"}, base=srv.url + "/calendar/v3")
            assert not ok and expected in msg, (mode, msg)
        finally:
            srv.close()


def test_listing_parsing_and_conflicts():
    srv = google({})
    try:
        ok, events = gcal.list_events("TOK", datetime.datetime(2026, 11, 12), datetime.datetime(2026, 11, 13), base=srv.url + "/calendar/v3")
        assert ok and [e["title"] for e in events] == ["Congé", "Réunion équipe"] or [e["title"] for e in events] == ["Réunion équipe", "Congé"]
        assert all(e["title"] not in ("Annulé", "cassé") for e in events)                         # annulés et illisibles ignorés
        q = urllib.parse.parse_qs(urllib.parse.urlparse(srv.requests[0][1]).query)
        assert q["singleEvents"] == ["true"] and q["orderBy"] == ["startTime"] and "timeMin" in q
        meeting = [e for e in events if e["title"] == "Réunion équipe"][0]
        assert meeting["location"] == "Salle B" and not meeting["all_day"]
        s, e = meeting["start"], meeting["end"]
        assert gcal.conflicts(events, s + datetime.timedelta(minutes=10), s + datetime.timedelta(minutes=70))[0]["title"] == "Réunion équipe"
        assert gcal.conflicts(events, e, e + datetime.timedelta(hours=1)) == []                   # bout à bout : pas de conflit
        assert all(c["title"] != "Congé" for c in gcal.conflicts(events, s, e))                   # journée entière : jamais un conflit
    finally:
        srv.close()


def test_extra_calendar_scope_is_added_not_replaced():
    url = oauth.build_auth_url("google", "CID", "http://127.0.0.1:1/", "ST", "CH", "moi@gmail.com", extra_scopes=[gcal.SCOPE])
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert "mail.google.com" in q["scope"][0] and gcal.SCOPE in q["scope"][0] and q["include_granted_scopes"] == ["true"]
    q0 = urllib.parse.parse_qs(urllib.parse.urlparse(oauth.build_auth_url("google", "CID", "http://127.0.0.1:1/", "ST", "CH")).query)
    assert gcal.SCOPE not in q0["scope"][0] and "include_granted_scopes" not in q0                  # Gmail seul : rien de plus demandé


def test_gcal_setting_syncs_with_strict_validation():
    ok = syncdata.SYNC_SETTINGS["gcal"]
    assert ok({"account": "acc12345", "enabled": True}) and ok({}) and ok({"enabled": False})
    assert not ok({"account": "x", "enabled": True}) and not ok({"account": "acc12345", "enabled": "oui"}) and not ok({"evil": 1})
    assert not ok({"account": "../../etc", "enabled": True}) and not ok("google")

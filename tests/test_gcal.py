"""Google Agenda : API (serveur local simulé), autorisation supplémentaire OAuth, routage des événements, conflits, agenda."""
import datetime, json, os, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gtkstub   # noqa: F401
from test_modules import Server
from test_features2 import real_msg, win_with, FakeBackend
from mintmail import caldav, extras, gcal, oauth, syncdata


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


def with_google(w, store=None):
    acc = {"id": "acc12345", "name": "Moi", "email": "moi@gmail.com", "auth": "oauth2", "oauth_provider": "google"}
    w.accounts = lambda: [acc]
    w.config["gcal"] = {"account": "acc12345", "enabled": True}
    tm = type("TM", (), {"access_token": lambda self, a: "TOK"})()
    orig = oauth.manager_for
    oauth.manager_for = lambda cfg: tm
    return orig


def test_events_go_to_google_agenda_first_then_caldav_then_ics():
    w, be = win_with()
    store, orig_mgr = {}, None
    srv = google(store)
    orig_api = gcal.API
    gcal.API = srv.url + "/calendar/v3"
    orig_mgr = with_google(w)
    try:
        inv = {"method": "REQUEST", "uid": "u1@x", "title": "Point projet", "start": "2026-11-12T14:00", "end": "2026-11-12T15:00",
               "location": "Salle A", "organizer": "marie@y.be", "raw": "BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nEND:VCALENDAR\r\n"}
        w._full = lambda m: m
        w.invite_add(real_msg(1, "Invitation", invite=inv))
        assert len(store) == 1 and list(store.values())[0]["summary"] == "Point projet"
        assert any("Google Agenda : ajouté" in t[0] for t in w.toasts)
        w.invite_add(real_msg(1, "Invitation", invite=inv))                                       # 2e fois : pas de doublon
        assert len(store) == 1 and any("déjà dans votre agenda" in t[0] for t in w.toasts)
        # événement détecté par l'IA
        w.calendar_add_event({"title": "Déjeuner client", "start": "2026-11-13T12:00", "end": "", "location": "Resto"}, uid="mintmail-x")
        assert len(store) == 2
        # Google désactivé : CalDAV
        w.config["gcal"] = {"account": "acc12345", "enabled": False}
        puts = []
        orig_put = caldav.put_event
        caldav.put_event = lambda url, user, pw, ics, uid: (puts.append((url, "METHOD:PUBLISH" in ics or "BEGIN:VCALENDAR" in ics)), (True, "ok"))[1]
        w.config["caldav"] = {"url": "https://cal.x.be/dav/", "user": "moi"}
        w.calendar_add_event({"title": "CalDAV", "start": "2026-11-14T10:00", "end": ""}, uid="u2")
        assert puts == [("https://cal.x.be/dav/", True)] and len(store) == 2
        caldav.put_event = orig_put
        # ni l'un ni l'autre : fichier .ics ouvert dans l'agenda du système
        w.config["caldav"] = {}
        opened = []
        orig_launch = extras.Gio.AppInfo.launch_default_for_uri
        extras.Gio.AppInfo.launch_default_for_uri = staticmethod(lambda uri, ctx: opened.append(uri))
        w.calendar_add_event({"title": "Fichier", "start": "2026-11-15T10:00", "end": ""}, uid="u3")
        assert opened and opened[0].startswith("file://") and opened[0].endswith(".ics")
        extras.Gio.AppInfo.launch_default_for_uri = orig_launch
    finally:
        gcal.API = orig_api
        oauth.manager_for = orig_mgr
        srv.close()


def test_invitation_conflict_note_and_agenda_events():
    w, be = win_with()
    srv = google({})
    orig_api = gcal.API
    gcal.API = srv.url + "/calendar/v3"
    orig_mgr = with_google(w)
    try:
        notes = []
        w.reader.set_invite_note = lambda n: notes.append(n)
        w.reader.msg = real_msg(1, "Invitation")
        inv = {"uid": "u1", "title": "Point", "start": "2026-11-12T14:00", "end": "2026-11-12T15:00"}
        m = real_msg(1, "Invitation", invite=inv)
        w._invite_conflicts(m)
        assert notes and notes[-1].startswith("⚠ Conflit avec « Réunion équipe »")
        inv_free = {"uid": "u2", "title": "Tard", "start": "2026-11-12T18:00", "end": "2026-11-12T19:00"}
        w._invite_conflicts(real_msg(1, "Invitation", invite=inv_free))
        assert "libre sur ce créneau" in notes[-1]
        w.reader.msg = real_msg(99, "Autre message")                                              # message changé entre-temps : pas de note tardive
        n = len(notes)
        w._invite_conflicts(m)
        assert len(notes) == n
        w.config["gcal"] = {}
        w._invite_conflicts(m)
        assert len(notes) == n                                                                    # Google Agenda inactif : aucune requête
        w.config["gcal"] = {"account": "acc12345", "enabled": True}
        ok, events = w.agenda_events(14)
        assert ok and any(e["title"] == "Réunion équipe" for e in events)
    finally:
        gcal.API = orig_api
        oauth.manager_for = orig_mgr
        srv.close()


def test_gcal_setting_syncs_with_strict_validation():
    ok = syncdata.SYNC_SETTINGS["gcal"]
    assert ok({"account": "acc12345", "enabled": True}) and ok({}) and ok({"enabled": False})
    assert not ok({"account": "x", "enabled": True}) and not ok({"account": "acc12345", "enabled": "oui"}) and not ok({"evil": 1})
    assert not ok({"account": "../../etc", "enabled": True}) and not ok("google")

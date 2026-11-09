"""Échéances en français, tri des tâches, créneaux libres."""
import datetime as D, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mintmail import slots, tasks

TODAY = D.date(2026, 11, 9)         # lundi


def test_parse_due_french_expressions():
    cases = {
        "Envoyer le devis avant vendredi": D.date(2026, 11, 13), "Rappeler le client demain": D.date(2026, 11, 10),
        "à faire après-demain": D.date(2026, 11, 11), "Payer la facture aujourd'hui": TODAY, "Répondre ce soir": TODAY,
        "Réunion dans 3 jours": D.date(2026, 11, 12), "Point dans 2 semaines": D.date(2026, 11, 23),
        "Rendre le dossier le 15/11": D.date(2026, 11, 15), "Pour le 3/12/2026": D.date(2026, 12, 3), "Échéance 05-12-26": D.date(2026, 12, 5),
        "Signer le contrat avant le 20 novembre": D.date(2026, 11, 20), "Livraison 1er décembre": D.date(2026, 12, 1),
        "Congé du 24 déc. 2026": D.date(2026, 12, 24), "à rendre pour la fin du mois": D.date(2026, 11, 30),
        "pour la fin de la semaine": D.date(2026, 11, 13), "à voir la semaine prochaine": D.date(2026, 11, 16),
        "Appeler lundi": D.date(2026, 11, 16),                      # aujourd'hui exclu : lundi prochain
        "À faire ce lundi": TODAY, "Facture à payer avant le 5": D.date(2026, 12, 5),      # le 5 est passé : mois suivant
        "Payer avant le 5 novembre": D.date(2026, 11, 5),             # dépassée récemment : reste en retard, pas l'an prochain
        "Fête du 12 mars": D.date(2027, 3, 12),                       # passée depuis longtemps : année suivante
    }
    for text, want in cases.items():
        assert tasks.parse_due(text, TODAY) == want, (text, tasks.parse_due(text, TODAY), want)
    for none in ("Rien de daté ici", "", "Appeler à 14h30", "Réunion à 10:00", "Le 31/02 impossible", "budget 2026"):
        assert tasks.parse_due(none, TODAY) is None, none
    assert tasks.parse_due("fin de semaine", D.date(2026, 11, 14)) == D.date(2026, 11, 20)         # un samedi : vendredi suivant
    assert tasks.parse_due("le 10", D.date(2026, 12, 20)) == D.date(2027, 1, 10)                   # passage d'année


def test_sorting_and_labels():
    ts = [{"id": "c", "due": "", "created": 1}, {"id": "b", "due": "2026-11-12", "created": 2}, {"id": "a", "due": "2026-11-08", "created": 3}]
    assert [t["id"] for t in sorted(ts, key=tasks.sort_key)] == ["a", "b", "c"]
    assert tasks.is_overdue(ts[2], TODAY) and not tasks.is_overdue(ts[1], TODAY) and not tasks.is_overdue(dict(ts[2], done=True), TODAY)
    assert tasks.due_label(ts[2], TODAY) == "en retard de 1 j" and tasks.due_label({"due": "2026-11-10"}, TODAY) == "demain"
    assert tasks.due_label({"due": "2026-11-09"}, TODAY) == "aujourd'hui" and tasks.due_label(ts[0], TODAY) == ""


def ev(d, h1, m1, h2, m2, **kw):
    return dict({"title": "x", "start": D.datetime(2026, 11, d, h1, m1), "end": D.datetime(2026, 11, d, h2, m2), "all_day": False, "busy": True}, **kw)


def test_free_slots_skip_busy_weekends_past_and_spread_over_days():
    now = D.datetime(2026, 11, 9, 8, 0)                                        # lundi 8 h
    got = slots.free_slots([], now)
    assert [(s.day, s.hour, s.minute) for s, e in got] == [(9, 10, 0), (10, 9, 0), (11, 9, 0)]      # 8 h + 2 h = dès 10 h aujourd'hui ; un jour différent chaque fois
    busy = [ev(10, 9, 0, 12, 0), ev(9, 10, 0, 11, 0)]
    got = slots.free_slots(busy, now)
    assert (got[0][0].day, got[0][0].hour, got[0][0].minute) == (9, 11, 0)                         # 10-11 occupé : 11 h
    assert (got[1][0].day, got[1][0].hour) == (10, 12)                                             # 9-12 occupé : 12 h
    fri = D.datetime(2026, 11, 13, 16, 0)
    got = slots.free_slots([], fri, count=3)
    assert [s.day for s, e in got] == [16, 17, 18]                                                 # fin de journée + week-end : lundi suivant
    allday = [dict(ev(10, 0, 0, 0, 0), all_day=True, start=D.datetime(2026, 11, 10), end=D.datetime(2026, 11, 11))]
    assert 10 not in [s.day for s, e in slots.free_slots(allday, now, count=4)]                    # journée entière occupée : jour exclu
    free_all_day = [dict(allday[0], busy=False)]
    assert 10 in [s.day for s, e in slots.free_slots(free_all_day, now, count=4)]                  # « disponible » (férié, anniversaire) : ne bloque pas
    long = slots.free_slots([], now, duration=90)
    assert all((e - s) == D.timedelta(minutes=90) and e.time() <= D.time(17, 30) for s, e in long)
    assert slots.free_slots([ev(d, 0, 0, 23, 59) for d in range(9, 31)], now, days=14) == []       # rien de libre : liste vide, pas de faux créneau


def test_proposal_text_is_french_and_complete():
    got = slots.free_slots([], D.datetime(2026, 11, 9, 8, 0))
    text = slots.proposal_text(got)
    assert text.startswith("Je vous propose les créneaux suivants :") and "- lundi 9 novembre, de 10h00 à 11h00" in text
    assert "mardi 10 novembre, de 9h00 à 10h00" in text and text.endswith("Dites-moi celui qui vous convient.")

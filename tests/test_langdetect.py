"""Détection locale de la langue d'un message."""
from types import SimpleNamespace as NS

from mintmail import langdetect as L

SAMPLES = {
    "fr": "Bonjour, merci pour votre message. Nous sommes très heureux de vous annoncer que votre commande est prête et que vous pouvez la retirer dans nos locaux.",
    "en": "Hello, thank you for your message. We are very happy to tell you that your order is ready and that you can pick it up at our office when you want.",
    "nl": "Hallo, bedankt voor uw bericht. Wij zijn blij u te laten weten dat uw bestelling klaar is en dat u deze graag kunt ophalen op ons kantoor.",
    "de": "Hallo, danke für Ihre Nachricht. Wir freuen uns Ihnen mitzuteilen, dass Ihre Bestellung bereit ist und Sie sie in unserem Büro abholen können.",
    "es": "Hola, gracias por su mensaje. Estamos muy contentos de comunicarle que su pedido está listo y que usted puede recogerlo en nuestra oficina.",
}


def test_five_languages_are_recognised():
    for code, text in SAMPLES.items():
        got = L.detect(text)
        assert got and got[0] == code, (code, got)


def test_short_or_ambiguous_text_gives_no_answer():
    assert L.detect("Ok merci") is None and L.detect("") is None and L.detect("123 456 789 !!!") is None
    assert L.detect("Invoice 2024-11 ref ABC XYZ total amount paid net gross tax code id no") is None


def test_quoted_lines_are_ignored_when_judging_a_message():
    m = NS(subject="Re: commande", text="> " + SAMPLES["en"] + "\n> " + SAMPLES["en"] + "\n" + SAMPLES["fr"], html="", snippet="")
    assert L.language_of(m) == "fr"
    assert L.language_of(NS(subject="", text="", html="<p>%s</p>" % SAMPLES["de"], snippet="")) == "de"
    assert L.name("nl") == "néerlandais" and L.name("zz") == "zz"

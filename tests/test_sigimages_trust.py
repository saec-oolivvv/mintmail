"""Signatures à logo SVG (affichage Qt + envoi en image jointe cid:) et images distantes toujours chargées pour un expéditeur."""
import base64, email, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mintmail import syncdata
from mintmail.backend import IMAPBackend
from mintmail.models import Outgoing
from mintmail.qt import composing as C, imagetrust as IT, personal as P, sigimages as SI
from mintmail.store import Config

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50" width="200" aria-label="Logo Web"><circle cx="5" cy="5" r="4"/></svg>'
SIG = '<table style="background-color:#2d1b2e;border-radius:16px"><tr><td>%s</td><td><a href="tel:1">0484</a></td></tr></table>' % SVG


def fake(svg, w, h):
    return b"PNG%d,%d" % (w, h)


def with_renderer(fn):
    def run():
        SI.set_renderer(fake)
        try:
            fn()
        finally:
            SI.set_renderer(None)
    run.__name__ = fn.__name__
    return run


def test_svg_size_uses_attributes_then_viewbox_and_is_bounded():
    assert SI.svg_size(SVG) == (200, 100)
    assert SI.svg_size('<svg viewBox="0 0 30 10"></svg>') == (30, 10)
    assert SI.svg_size("<svg></svg>") == (200, 200)
    assert max(SI.svg_size('<svg width="9000" height="3000"></svg>')) == SI.MAX_SIDE


def test_without_renderer_nothing_changes():
    SI.set_renderer(None)
    assert SI.to_display(SIG) == SIG and SI.to_mail(SIG) == (SIG, [])


@with_renderer
def test_display_replaces_svg_by_png_data_image_and_mail_by_cid_image():
    d = SI.to_display(SIG)
    assert "<svg" not in d and 'src="data:image/png;base64,' in d and 'width="200" height="100"' in d and 'alt="Logo Web"' in d
    html, inline = SI.to_mail(SIG)
    assert "<svg" not in html and "cid:" in html and len(inline) == 1 and inline[0][1] == "png"
    assert base64.b64decode(inline[0][2]) == b"PNG200,100"
    assert "border-radius:16px" in html                                  # le reste de la signature est intact
    html2, inline2 = SI.to_mail(d)                                       # une image « data: » (venue de l'éditeur) devient aussi une pièce en ligne
    assert "data:" not in html2 and len(inline2) == 1


@with_renderer
def test_same_logo_twice_is_attached_once_and_images_are_capped():
    html, inline = SI.to_mail(SVG + SVG)
    assert html.count("cid:") == 2 and len(inline) == 1
    many = "".join('<svg width="%d" height="5"></svg>' % (i + 1) for i in range(SI.MAX_IMAGES + 5))
    assert len(SI.to_mail(many)[1]) == SI.MAX_IMAGES
    assert SI.to_display("<svg>" + "x" * (SI.MAX_SVG_BYTES + 1) + "</svg>") == ""      # trop gros : ignoré


@with_renderer
def test_preview_keeps_colours_and_shows_the_logo():
    pv = P.signature_preview(SIG)
    assert "<img" in pv and "background-color" in pv and "<svg" not in pv


@with_renderer
def test_sent_signature_is_the_original_not_the_qt_version():
    acc = {"id": "a1", "email": "o@x.be", "signature_html": SIG}
    qt_body = "<p>Bonjour</p><p>%s-- <br>[version abîmée par Qt]%s</p>" % (C.SIG_MARK, C.SIG_MARK)
    out = C.build_outgoing(acc, None, "a@b.be", "", "", "S", qt_body, [])
    assert "abîmée" not in out.html and "border-radius:16px" in out.html and "cid:" in out.html and C.SIG_MARK not in out.html
    assert len(out.inline) == 1
    assert C.restore_signature("<p>pas de signature</p>", acc, None) == "<p>pas de signature</p>"      # signature effacée : rien n'est ajouté


@with_renderer
def test_backend_sends_inline_images_as_related_part():
    acc = {"id": "a1", "email": "o@x.be", "imap_host": "imap.gmail.com"}
    out = C.build_outgoing(acc, None, "a@b.be", "", "", "S", "<p>x</p>" + C.signature_html({"signature_html": SIG}, None), [])
    box = []

    class S:
        def send_message(self, em, **kw): box.append(em)
        def quit(self): pass
    be = object.__new__(IMAPBackend)
    be.acc = acc
    be._smtp = lambda: S()
    be.send(out)
    types = [p.get_content_type() for p in email.message_from_bytes(box[0].as_bytes()).walk()]
    assert "multipart/related" in types and "image/png" in types and "text/html" in types
    assert "Content-ID" in box[0].as_string()
    Outgoing.from_dict(out.to_dict())                                    # l'envoi différé (file d'attente JSON) garde les images


def test_image_trust_by_address_or_domain_and_validation():
    d = tempfile.mkdtemp()
    cfg = Config(os.path.join(d, "c.json"))
    assert not IT.trusted(cfg, "a@news.com")
    assert IT.trust(cfg, "A@News.com") and IT.trusted(cfg, "a@news.com") and not IT.trusted(cfg, "b@news.com")
    assert IT.trust(cfg, "@shop.be") and IT.trusted(cfg, "x@shop.be") and not IT.trusted(cfg, "x@shop.com")
    assert not IT.trust(cfg, "pas une adresse") and not IT.trust(cfg, "") and not IT.trusted(cfg, "")
    IT.trust(cfg, "a@news.com")
    assert cfg["image_senders"].count("a@news.com") == 1
    IT.untrust(cfg, "A@NEWS.com")
    assert not IT.trusted(cfg, "a@news.com")


def test_image_trust_list_is_synchronised_between_machines():
    d = tempfile.mkdtemp()
    a, b = Config(os.path.join(d, "a.json")), Config(os.path.join(d, "b.json"))
    IT.trust(a, "@shop.be")
    items = syncdata.collect(a)
    assert "imgs:@shop.be" in items
    item = {"ts": 5, "v": "@shop.be", "del": False}
    assert syncdata.valid_item("imgs:@shop.be", item) and not syncdata.valid_item("imgs:@shop.be", {"ts": 5, "v": "pas bon", "del": False})
    syncdata._apply_list_item(b, "imgs", "@shop.be", "@shop.be", False)
    assert IT.trusted(b, "x@shop.be")
    syncdata._apply_list_item(b, "imgs", "@shop.be", None, True)
    assert not IT.trusted(b, "x@shop.be")
    assert "1 expéditeur(s) aux images chargées" in syncdata.describe({"kinds": {"imgs": 1}})


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("ok")

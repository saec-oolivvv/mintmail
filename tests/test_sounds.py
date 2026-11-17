"""Sons (réception / envoi) et notifications émises par l'application."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import testenv
from mintmail import sysdeps as S


def test_sound_commands_per_system():
    have = lambda f: True
    assert S.sound_command("received", "macos", have, lambda c: "/usr/bin/" + c) == ["afplay", "/System/Library/Sounds/Glass.aiff"]
    assert S.sound_command("sent", "macos", have, lambda c: "/usr/bin/" + c)[1].endswith("Hero.aiff")           # son d'envoi différent du son de réception
    assert S.sound_command("received", "macos", have, lambda c: None) is None
    assert S.sound_command("sent", "linux", lambda f: False, lambda c: c if c == "canberra-gtk-play" else None) == ["canberra-gtk-play", "-i", "message-sent-instant"]
    assert S.sound_command("received", "linux", have, lambda c: c if c == "paplay" else None)[0] == "paplay"
    assert S.sound_command("received", "linux", lambda f: False, lambda c: None) is None


def test_notification_goes_through_the_app_hook_first():
    got = []
    old = S.NOTIFIER
    S.NOTIFIER = lambda t, b: got.append((t, b)) or True
    try:
        assert S.notify("Titre", "Corps") is True and got == [("Titre", "Corps")]
        S.NOTIFIER = lambda t, b: (_ for _ in ()).throw(RuntimeError("pas de zone de notification"))   # une panne ne casse rien : on retombe sur la commande système
        S.notify("x", "y", timeout=0)
    finally:
        S.NOTIFIER = old

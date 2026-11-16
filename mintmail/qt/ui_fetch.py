"""Téléchargement en arrière-plan des images distantes des signatures (le fil de l'interface n'attend jamais le réseau)."""
import threading

from PySide6.QtCore import QObject, Signal

from . import sigimages as SI


class _Done(QObject):
    done = Signal()


_running = set()
_alive = set()          # un « messager » par appel, gardé en vie jusqu'à la fin du téléchargement (aucune connexion ne s'accumule)


def prefetch_async(html_text, on_done=None):
    """Lance le téléchargement des images distantes pas encore en cache ; `on_done()` est appelé (dans le fil de l'interface) à la fin."""
    if not html_text or not SI.pending(html_text):
        return False
    key = tuple(SI.remote_urls(html_text))
    if key in _running:
        return False
    _running.add(key)
    hub = _Done()
    _alive.add(hub)

    def finished():
        _alive.discard(hub)
        if on_done:
            try:
                on_done()
            except RuntimeError:                      # la fenêtre a été fermée entre-temps
                pass
        hub.deleteLater()
    hub.done.connect(finished)

    def work():
        try:
            SI.prefetch(html_text)
        finally:
            _running.discard(key)
            hub.done.emit()
    threading.Thread(target=work, daemon=True).start()
    return True

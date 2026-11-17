"""IMAP IDLE contre un faux serveur local : l'arrivée d'un message (« * n EXISTS ») doit déclencher on_change() dans la seconde."""
import imaplib
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mintmail import backend


class FakeServer(threading.Thread):
    """Serveur IMAP minimal : LOGIN, SELECT, IDLE (annonce 1 nouveau message après `delay` s), DONE, LOGOUT."""

    def __init__(self, delay=0.4):
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.delay, self.idles = delay, 0
        self.start()

    def run(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(c,), daemon=True).start()

    def handle(self, c):
        f = c.makefile("rwb", buffering=0)
        f.write(b"* OK fake\r\n")
        while True:
            line = f.readline()
            if not line:
                return
            tag, _, rest = line.decode().strip().partition(" ")
            cmd = rest.split(" ")[0].upper()
            if cmd == "IDLE":
                self.idles += 1
                f.write(b"+ idling\r\n")
                time.sleep(self.delay)
                f.write(b"* 7 EXISTS\r\n")
                done = f.readline()
                f.write(("%s OK IDLE terminated\r\n" % tag).encode())
            elif cmd == "CAPABILITY":
                f.write(("* CAPABILITY IMAP4rev1 IDLE\r\n%s OK done\r\n" % tag).encode())
            elif cmd == "SELECT":
                f.write(b"* 6 EXISTS\r\n" + ("%s OK [READ-ONLY] done\r\n" % tag).encode())
            elif cmd == "LOGOUT":
                f.write(("* BYE\r\n%s OK bye\r\n" % tag).encode())
                return
            else:
                f.write(("%s OK %s done\r\n" % (tag, cmd)).encode())


def test_idle_calls_back_when_the_server_announces_a_message_and_survives_a_cycle():
    srv = FakeServer()
    acc = {"id": "t", "email": "a@x.be", "imap_host": "127.0.0.1", "imap_port": srv.port, "imap_ssl": False}
    be = backend.IMAPBackend(acc, "pw")

    def connect():
        c = imaplib.IMAP4("127.0.0.1", srv.port)
        c.login("a@x.be", "pw")
        return c
    be._connect = connect
    got, stop = [], threading.Event()
    t = threading.Thread(target=be.watch, args=(lambda *a: got.append(time.time()), stop), daemon=True)
    t0 = time.time()
    t.start()
    while len(got) < 2 and time.time() - t0 < 6:                         # deux annonces de suite : la boucle IDLE redémarre bien
        time.sleep(0.05)
    stop.set()
    t.join(5)
    assert len(got) >= 2, got
    assert got[0] - t0 < 2.5
    assert srv.idles >= 2

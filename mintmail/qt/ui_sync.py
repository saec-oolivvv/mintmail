"""Onglet « Synchronisation P2P » des réglages Qt. Logique et textes : syncing.py (testé sans Qt)."""
import socket
import threading

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..i18n import tr
from ..p2p import MIN_SECRET, generate_code, local_ip
from . import syncing as SY


class _Say(QObject):
    text = Signal(str)
    done = Signal()


def p2p_tab(dlg):
    main, cfg = dlg.main, dlg.cfg
    page = QWidget()
    lay = QVBoxLayout(page)
    title = QLabel("<b>%s</b>" % tr("Synchronisation entre machines"))
    lay.addWidget(title)
    intro = QLabel(SY.INTRO)
    intro.setWordWrap(True)
    intro.setEnabled(False)
    lay.addWidget(intro)
    form = QFormLayout()
    lay.addLayout(form)
    secret = QLineEdit(cfg.get("p2p_secret") or "")
    secret.setEchoMode(QLineEdit.Password)
    secret.setPlaceholderText(tr("%d caractères minimum, identique sur les deux machines") % MIN_SECRET)
    show, gen, apply_btn = QCheckBox(tr("Afficher")), QPushButton(tr("Générer")), QPushButton(tr("Appliquer"))
    srow = QHBoxLayout()
    for w in (secret, show, gen, apply_btn):
        srow.addWidget(w, 1 if w is secret else 0)
    form.addRow(tr("Code de jumelage"), srow)
    enabled = QCheckBox(tr("Synchronisation activée"))
    enabled.setChecked(bool(cfg["p2p_enabled"]))
    form.addRow("", enabled)
    state, ident, peers = QLabel(), QLabel(), QLabel()
    ident.setTextInteractionFlags(Qt.TextSelectableByMouse)
    for w in (state, peers):
        w.setWordWrap(True)
    form.addRow(tr("État"), state)
    form.addRow(tr("Cet appareil"), ident)
    form.addRow(tr("Pairs détectés"), peers)
    sync_btn, scan_btn = QPushButton(tr("↔ Synchroniser maintenant")), QPushButton(tr("🔍 Rechercher les machines"))
    scan_btn.setToolTip(tr("Sonde le réseau local (utile si la détection automatique est bloquée par la box ou un VPN)"))
    brow = QHBoxLayout()
    brow.addWidget(sync_btn)
    brow.addWidget(scan_btn)
    brow.addStretch(1)
    form.addRow("", brow)
    hint = QLabel(tr("Secours si la découverte automatique est bloquée (isolation Wi-Fi de certaines box) : "
                     "adresse IP de l'autre machine. Votre adresse : %s") % local_ip())
    hint.setWordWrap(True)
    hint.setEnabled(False)
    lay.addWidget(hint)
    peer_entry = QLineEdit(", ".join(cfg.get("p2p_static_peers") or []))
    peer_entry.setPlaceholderText(tr("192.168.1.42 ou 192.168.1.42:54322"))
    save_peers, test_peer = QPushButton(tr("Enregistrer")), QPushButton(tr("Tester"))
    prow = QHBoxLayout()
    prow.addWidget(peer_entry, 1)
    prow.addWidget(save_peers)
    prow.addWidget(test_peer)
    lay.addLayout(prow)
    fw = QLabel(SY.FIREWALL)
    fw.setWordWrap(True)
    fw.setEnabled(False)
    lay.addWidget(fw)
    diag = QLabel()
    diag.setWordWrap(True)
    diag.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lay.addWidget(QLabel("<b>%s</b>" % tr("Diagnostic réseau")))
    lay.addWidget(diag)
    lay.addStretch(1)
    say = _Say()
    say.text.connect(lambda t: main.status.setText(t))
    say.done.connect(lambda: (sync_btn.setEnabled(True), scan_btn.setEnabled(True), refresh()))

    def engine():
        return main.sync_engine

    def refresh():
        e = engine()
        state.setText(e.state_label())
        ident.setText("<b>%s</b>" % (e.node_id() or "—"))
        peers.setText(SY.peers_text(e))
        diag.setText(SY.diagnostic_text(e))

    def do_apply():
        want, note = SY.apply_settings(cfg, secret.text(), enabled.isChecked())
        enabled.blockSignals(True)
        enabled.setChecked(want)
        enabled.blockSignals(False)
        if note:
            main.status.setText(note)
        main.init_sync()
        refresh()

    def do_generate():
        secret.setText(generate_code())
        show.setChecked(True)

    def do_sync():
        sync_btn.setEnabled(False)

        def work():
            res = engine().sync_now() or {}
            say.text.emit(SY.sync_result_text(engine(), res))
        threading.Thread(target=lambda: (work(), say.done.emit()), daemon=True).start()

    def do_scan():
        scan_btn.setEnabled(False)
        main.status.setText(tr("Recherche des machines sur le réseau local…"))

        def work():
            n = engine().scan_now()
            say.text.emit(tr("%d machine(s) trouvée(s)") % n if engine().can_run() else tr("Synchronisation inactive (code de jumelage requis)"))
        threading.Thread(target=lambda: (work(), say.done.emit()), daemon=True).start()

    def do_save_peers():
        _lst, msg = SY.save_peers(cfg, peer_entry.text())
        main.init_sync()
        main.status.setText(msg)

    def do_test():
        lst = SY.parse_peers(peer_entry.text())
        if not lst:
            return
        host, _, port = lst[0].partition(":")
        port = int(port) if port else int(cfg.get("p2p_port", 54322))

        def work():
            try:
                socket.create_connection((host, port), timeout=3).close()
                say.text.emit(tr("Connexion TCP vers %s:%d : OK") % (host, port))
            except OSError as e:
                say.text.emit(tr("Impossible de joindre %s:%d (%s)") % (host, port, e.strerror or e))
        threading.Thread(target=work, daemon=True).start()
    show.toggled.connect(lambda on: secret.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
    gen.clicked.connect(do_generate)
    apply_btn.clicked.connect(do_apply)
    secret.returnPressed.connect(do_apply)
    enabled.toggled.connect(lambda _on: do_apply())
    sync_btn.clicked.connect(do_sync)
    scan_btn.clicked.connect(do_scan)
    save_peers.clicked.connect(do_save_peers)
    test_peer.clicked.connect(do_test)
    timer = QTimer(page)
    timer.timeout.connect(refresh)
    timer.start(5000)
    refresh()
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setWidget(page)
    return sc

"""Intégration de l'IA dans toute l'application : analyse de message, tri, assistant, résumé, recherche, actions."""
import datetime
import os
import tempfile
import time

import gi
from .i18n import tr
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib

from .ai_engine import AIEngine, describe_action, local_analysis, make_ics
from .assistant import AssistantPanel
from .folders import dest_of
from .util import text_to_html, normalize_subject


class AIMixin:
    # ------------------------------------------------------------------ init
    def _init_ai(self):
        self.engine = AIEngine(self.config, self.cache)
        self._ai_hist, self._ai_token, self._digest_key, self._digest_hidden = [], 0, None, False

    def _get_ai_service(self):
        return self.engine.service()

    def refresh_ai(self):
        on = self.engine.enabled()
        self.reader.ai_enabled = on
        self.reader.ai_reply_btn.set_visible(on)
        self.ai_btn.set_tooltip_text(tr("Assistant IA (Ctrl+J)") if on else tr("Assistant IA — non configuré (Ctrl+J)"))
        self._digest_key = None
        self.refresh_digest_visibility()
        if self.reader.msg is not None:
            self.ai_open_message(self.reader.msg)

    def build_digest_box(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.get_style_context().add_class("digest-card")
        head = Gtk.Box(spacing=6)
        t = Gtk.Label(xalign=0)
        t.set_markup(tr("<b>✨ En bref</b>"))
        t.get_style_context().add_class("ai-title")
        head.pack_start(t, True, True, 0)
        refresh = Gtk.Button(label=tr("Actualiser"))
        refresh.get_style_context().add_class("pill")
        refresh.connect("clicked", lambda *_: self._maybe_digest(force=True))
        hide = Gtk.Button(label="✕")
        hide.get_style_context().add_class("flat-btn")
        hide.connect("clicked", self._hide_digest)
        head.pack_end(hide, False, False, 0)
        head.pack_end(refresh, False, False, 0)
        self.digest_lbl = Gtk.Label(xalign=0)
        self.digest_lbl.set_line_wrap(True)
        self.digest_lbl.set_selectable(True)
        self.digest_lbl.get_style_context().add_class("ai-text")
        box.pack_start(head, False, False, 0)
        box.pack_start(self.digest_lbl, False, False, 0)
        box.set_no_show_all(True)
        self.digest_box = box
        return box

    def _hide_digest(self, *_):
        self._digest_hidden = True
        self.digest_box.hide()

    def refresh_digest_visibility(self):
        if not hasattr(self, "digest_box"):
            return
        show = (self.view == "inbox" and not self._effective_search() and not self._digest_hidden
                and self.config.get("ai_digest", True))
        if show:
            self.digest_box.show_all()
            self._maybe_digest()
        else:
            self.digest_box.hide()

    def _maybe_digest(self, force=False):
        msgs = self.cache.query("unread", self.account, limit=25)
        key = (len(msgs), datetime.date.today().isoformat(), self.account)
        if key == self._digest_key and not force:
            return
        self._digest_key = key
        if not msgs:
            self.digest_lbl.set_text(tr("Boîte à jour : aucun message non lu 🎉"))
            return
        self.digest_lbl.set_text(self.engine.local_digest(self.cache.counts(self.account), msgs))
        if not self.engine.enabled():
            return
        self.digest_lbl.set_text(tr("✨ Analyse de votre boîte…"))

        def done(text, err):
            if self._digest_key != key:
                return
            if err:
                self.digest_lbl.set_text(self.engine.local_digest(self.cache.counts(self.account), msgs)
                                         + tr("  (IA : %s)") % str(err)[:60])
            else:
                self.digest_lbl.set_text(text)
        self.run_bg(lambda: self.engine.digest(msgs, force=force), done)

    # ------------------------------------------------------------ analyse du message ouvert
    def ai_open_message(self, msg):
        """Prépare la carte IA du lecteur : cache immédiat, sinon analyse (légèrement temporisée)."""
        hit = self.cache.ai_get(msg.id, "analysis")
        if hit:
            self.reader.ai_show(hit)
            return
        if not self.engine.enabled():
            self.reader.ai_show(local_analysis(msg, self.engine.lang), cta=True)
            return
        if not self.config.get("ai_auto", True):
            self.reader.ai_idle()
            return
        self.reader.ai_loading()
        self._ai_token += 1
        token = self._ai_token

        def go():
            if token == self._ai_token and self.reader.msg is not None and self.reader.msg.id == msg.id:
                self.ai_fetch(msg)
            return False
        GLib.timeout_add(350, go)   # évite un appel par message quand on parcourt la liste rapidement

    def _folder_names(self):
        return [e["path"] for a in self.accounts() for e in self.tree_of(a["id"]) if e["selectable"] and not e["special"]]

    def _prime_engine(self):
        self.engine.folder_names = self._folder_names()

    def ai_fetch(self, msg, force=False):
        self._prime_engine()
        self.reader.ai_loading()

        def done(res, err):
            if self.reader.msg is None or self.reader.msg.id != msg.id:
                return
            if err:
                self.reader.ai_show(local_analysis(msg, self.engine.lang), error=str(err)[:120])
            else:
                self.reader.ai_show(res)
                self._refresh_row_ai([msg.id])
        self.run_bg(lambda: self.engine.analyze(msg, force=force), done)

    def _refresh_row_ai(self, ids):
        meta = self.cache.ai_meta(ids)
        for mid in ids:
            row = self.rows.get(mid)
            if row is not None:
                row.update_msg(row.msg, meta.get(mid, {}))

    def _on_ai_action(self, reader, act, payload):
        msg = reader.msg
        if act == "toast":
            self.toast.popup(payload, timeout=4)
            return
        if msg is None and act != "enable_ai":
            return
        if act in ("analyze", "regen"):
            self.ai_fetch(msg, force=(act == "regen"))
        elif act == "translate":
            reader.ai_working(tr("Traduction…"))
            self.run_bg(lambda: self.engine.translate_message(msg),
                        lambda t, e: reader.ai_text(tr("Traduction"), (tr("Erreur IA : %s") % str(e)[:100]) if e else t)
                        if reader.msg is not None and reader.msg.id == msg.id else None)
        elif act == "ask":
            reader.ai_working(tr("Réflexion…"))
            self.run_bg(lambda: self.engine.ask(msg, payload),
                        lambda t, e: reader.ai_text(payload[:60], (tr("Erreur IA : %s") % str(e)[:100]) if e else t)
                        if reader.msg is not None and reader.msg.id == msg.id else None)
        elif act == "reply_ai":
            self.ai_reply_with_ai(msg)
        elif act == "event":
            self._add_to_calendar(msg)
        elif act == "snooze":
            self.run_action("snooze", [msg])
        elif act == "archive":
            self.run_action("archive", [msg])
        elif act == "block":
            self.block_sender(msg)
        elif act == "spam":
            self.move_messages([msg], "spam")
        elif act == "not_spam":
            self.not_spam(msg)
        elif act == "not_spam_file":
            self.not_spam(msg, folder=payload)
        elif act == "enable_ai":
            self.show_settings("ai")
        elif act == "quick_expand":
            reader.ai_working(tr("Rédaction de votre réponse…"))
            self.run_bg(lambda: self.engine.write_from_prompt(payload, "Re: " + normalize_subject(msg.subject),
                                                              msg.sender_email, self.engine._msg_block(msg, 1200)),
                        lambda t, e: self._quick_expand_done(msg, t, e))

    def _quick_expand_done(self, msg, text, err):
        if self.reader.msg is None or self.reader.msg.id != msg.id:
            return
        self.reader.ai_spinner.stop()
        if err:
            self.toast.popup(tr("Erreur IA : %s") % str(err)[:90], timeout=5)
        else:
            self.reader.quick.set_text(text.replace("\n", " ").strip())
            self.reader.quick.grab_focus()
            self.reader.quick.set_position(-1)

    def _add_to_calendar(self, msg):
        res = self.cache.ai_get(msg.id, "analysis") or {}
        ev = res.get("event")
        if not ev:
            self.toast.popup(tr("Aucun rendez-vous détecté dans ce message."), timeout=3)
            return
        self.calendar_add_event(ev, uid="mintmail-" + msg.id)

    def ai_reply_with_ai(self, msg, idea=tr("Réponds de façon appropriée à ce message.")):
        """Rédige une réponse avec l'IA puis ouvre le composeur prérempli (à relire avant envoi)."""
        if not self.engine.enabled():
            self.toast.popup(tr("IA non configurée : Paramètres → IA."), timeout=4)
            self.show_settings("ai")
            return
        full = self._full(msg)
        self.toast.popup(tr("✨ Rédaction de la réponse…"), timeout=3)

        def work():
            return self.engine.write_from_prompt(idea,
                                                 "Re: " + normalize_subject(full.subject), full.sender_email,
                                                 context=self.engine._msg_block(full, 1500))

        def done(text, err):
            if err:
                self.toast.popup(tr("Erreur IA : %s") % str(err)[:90], timeout=6)
            else:
                self.reply(full, ai_text=text)
        self.run_bg(work, done)

    # ------------------------------------------------ classement et menu clic droit IA
    def _file_into(self, msgs, e):
        self.move_messages(msgs, dest_of(e), label=tr("rangé dans « %s »") % e["path"])
        self._learn_move(msgs, dest_of(e), e["path"])

    def _apply_group(self, aid, folder, group):
        self.ensure_folder(aid, folder, lambda e: self._file_into(group, e))

    def ai_file_message(self, msg, spec):
        self.ensure_folder(msg.account, spec, lambda e: self._file_into([msg], e))

    def ai_classify(self, msgs):
        """Classe des messages dans des dossiers (existants ou à créer). Propose, puis exécute seulement ce que vous validez."""
        msgs = [m for m in msgs if m.folder in ("inbox", "archive")][:100]
        if not self.engine.enabled():
            self.toast.popup(tr("IA non configurée : Paramètres → IA."), timeout=4)
            self.show_settings("ai")
            return
        if not msgs:
            self.toast.popup(tr("Aucun message à classer ici."), timeout=3)
            return
        self._prime_engine()
        p = self.assistant
        self.toggle_assistant(True)
        p.add_ai(tr("Je classe %d message(s)… Rien n'est déplacé ni créé avant votre accord.") % len(msgs))
        p.set_busy(True)
        groups = {}
        for m in msgs:
            groups.setdefault(m.account, []).append(m)

        def work():
            out = {}
            for aid, lst in groups.items():
                existing = [e["path"] for e in self.tree_of(aid) if e["selectable"] and not e["special"]]
                out[aid] = self.engine.classify(lst, existing, account=aid)
            return out

        def done(res, err):
            p.set_busy(False)
            if err:
                p.add_ai(tr("Désolé, le classement a échoué : %s") % str(err)[:160])
                return
            by_id, items, total, stay = {m.id: m for m in msgs}, [], 0, 0
            for aid, r in res.items():
                stay += r["stay"]
                for folder, ids in r["moves"].items():
                    grp = [by_id[i] for i in ids if i in by_id]
                    total += len(grp)
                    items.append((tr("%d message(s) → « %s »%s") % (len(grp), folder, tr(" (nouveau dossier)") if folder in r["new"] else ""),
                                  lambda aid=aid, f=folder, g=grp: self._apply_group(aid, f, g)))
            if not items:
                p.add_ai(tr("Rien à ranger : ces messages restent dans la boîte de réception."))
                return
            p.add_ai(tr("Voici ma proposition : %d message(s) rangés dans %d dossier(s)%s. Validez ligne par ligne ou tout d'un coup.")
                     % (total, len(items), (tr(", %d restent dans la boîte") % stay) if stay else ""))
            p.add_plan(items, lambda: [fn() for _d, fn in items])
        self.run_bg(work, done)

    def ai_suggest_folder(self, msg):
        if not self.engine.enabled():
            self.toast.popup(tr("IA non configurée : Paramètres → IA."), timeout=4)
            self.show_settings("ai")
            return
        self._prime_engine()
        self.toast.popup(tr("✨ Recherche du meilleur dossier…"), timeout=3)
        existing = [e["path"] for e in self.tree_of(msg.account) if e["selectable"] and not e["special"]]

        def done(r, err):
            if err:
                self.toast.popup(tr("Erreur IA : %s") % str(err)[:90], timeout=6)
                return
            if not r["moves"]:
                self.toast.popup(tr("✨ Cette conversation peut rester dans la boîte de réception."), timeout=5)
                return
            f = next(iter(r["moves"]))
            self.toast.popup(tr("✨ Suggestion : « %s »%s") % (f, tr(" (nouveau dossier)") if f in r["new"] else ""), tr("Ranger"),
                             lambda: self.ai_file_message(msg, f), timeout=12)
        self.run_bg(lambda: self.engine.classify([msg], existing), done)

    def ai_rule_move(self, msg, folder):
        rule = {"field": "from", "text": msg.sender_email.lower(), "action": "move", "folder": folder}
        if rule not in self.config["rules"]:
            self.config["rules"].append(rule)
            self.config.save()
        self.toast.popup(tr("Règle créée : les messages de %s iront dans « %s »") % (msg.sender_email, folder),
                         tr("Appliquer maintenant"), self.apply_rules_now, timeout=8)

    def _focus_message(self, msg):
        if self.reader.msg is None or self.reader.msg.id != msg.id:
            self.open_message(msg, force=True)

    def assistant_about(self, msg):
        self._focus_message(msg)
        self.toggle_assistant(True)
        self.assistant.entry.set_text(tr("À propos de ce message : "))
        self.assistant.entry.set_position(-1)
        self.assistant.focus_entry()

    def ai_menu_items(self, msg):
        """Entrées IA du menu clic droit : (libellé, action) | (\"sous-menu\", libellé, [(libellé, action)…]) | None."""
        if not self.engine.enabled():
            return [(tr("✨ Activer l'IA : classement, résumés, réponses…"), lambda: self.show_settings("ai"))]
        ana = self.cache.ai_get(msg.id, "analysis") or {}
        sug, who = ana.get("folder") or "", msg.sender_email
        key = who.lower()
        items = []
        if msg.folder == "spam":                                    # faux positif probable : l'IA propose de le sortir du Spam
            suspect = bool(ana.get("suspicious"))
            items.append((tr("✨ Ce n'est pas du spam (remettre en boîte de réception)") if not suspect
                          else tr("✔ Ce n'est pas du spam (malgré l'avis de l'IA)"), lambda: self.not_spam(msg)))
            if ana.get("folder") and not suspect:
                items.append((tr("✨ Pas du spam, ranger dans « %s »") % ana["folder"], lambda: self.not_spam(msg, folder=ana["folder"])))
        habit = "" if sug else (self.cache.learn_best(msg.account, who) or "")      # ce que l'utilisateur fait déjà
        if habit:
            sug = habit
            items.append((tr("✨ Ranger dans « %s » (selon vos habitudes)") % sug, lambda: self.ai_file_message(msg, sug)))
        elif sug:
            items.append((tr("✨ Ranger dans « %s » (suggéré)") % sug, lambda: self.ai_file_message(msg, sug)))
        else:
            items.append((tr("✨ Suggérer un dossier…"), lambda: self.ai_suggest_folder(msg)))
        items.append((tr("✨ Classer tous les messages de %s") % who,
                      lambda: self.ai_classify(self.cache.by_sender(key, ("inbox", "archive")) or [msg])))
        items.append((tr("✨ Classer ma boîte de réception (60 derniers)"),
                      lambda: self.ai_classify(self.cache.query("inbox", self.account, limit=60))))
        if sug:
            items.append((tr("✨ Toujours ranger %s dans « %s »") % (who, sug), lambda: self.ai_rule_move(msg, sug)))
        if ana.get("tasks"):
            items.append((tr("✨ Ajouter les %d tâche(s) détectée(s)") % len(ana["tasks"]), lambda: self.tasks_from_message(msg)))
        items.append(None)
        replies = [(tr("Réponse adaptée"), tr("Réponds de façon appropriée à ce message.")), (tr("Accepter"), tr("Accepte poliment la proposition.")),
                   (tr("Refuser poliment"), tr("Refuse poliment la demande.")), (tr("Demander plus d'informations"), tr("Demande des précisions.")),
                   (tr("Proposer un autre créneau"), tr("Propose un autre créneau.")), (tr("Ton formel"), tr("Réponds sur un ton formel.")),
                   (tr("Ton amical"), tr("Réponds sur un ton amical.")), (tr("Très courte"), tr("Réponds en une ou deux phrases."))]
        items.append(("sous-menu", tr("✨ Répondre avec l'IA"), [(lab, lambda i=idea: self.ai_reply_with_ai(msg, i)) for lab, idea in replies]))
        if getattr(msg, "thread_count", 1) > 1:
            items.append((tr("✨ Résumer la conversation (%d messages)") % msg.thread_count, lambda: self.ai_summarize_thread(msg)))
        items.append((tr("✨ Résumer / analyser ce message"), lambda: (self._focus_message(msg), self.ai_fetch(self._full(msg), force=True))))
        items.append((tr("✨ Traduire ce message"), lambda: (self._focus_message(msg), self._on_ai_action(self.reader, "translate", ""))))
        if ana.get("event"):
            items.append((tr("✨ Ajouter à l'agenda : %s") % ana["event"]["title"][:30], lambda: self._add_to_calendar(msg)))
        items.append((tr("✨ Demander à l'assistant à propos de ce message…"), lambda: self.assistant_about(msg)))
        return items

    # ------------------------------------------------------------------ tri
    def ai_triage(self, msgs):
        if not msgs:
            return

        def done(res, err):
            if err or not res:
                return
            by = {}
            for mid, v in res.items():
                if v.get("category"):
                    by.setdefault(v["category"], []).append(mid)
            for cat, ids in by.items():
                self.cache.update_many(ids, category=cat)
            self._refresh_row_ai(list(res))
            self._maybe_prepare_drafts(msgs, res)
            urgent = [m for m in msgs if res.get(m.id, {}).get("priority") == 3 and not res[m.id].get("local")]
            if urgent and self.config["notifications"]:
                n = Gio.Notification.new(tr("✨ %d message(s) important(s)") % len(urgent))
                n.set_body("\n".join("%s — %s" % (m.display_sender, m.subject) for m in urgent[:3]))
                self.get_application().send_notification("ai-urgent", n)
        use_ai = bool(self.config.get("ai_triage", True))
        self.run_bg(lambda: self.engine.triage(msgs, use_ai=use_ai), done)

    # ---------------------------------------------------------------- recherche IA
    def ai_search(self, text):
        text = text.lstrip("?✨ ").strip()
        if not text:
            return
        if not self.engine.enabled():
            self.toast.popup(tr("IA non configurée : Paramètres → IA."), timeout=3)
            return
        self.toast.popup(tr("✨ Recherche : « %s »") % text[:50], timeout=2)

        def done(q, err):
            if err:
                self.toast.popup(tr("Erreur IA : %s") % str(err)[:90], timeout=5)
            else:
                self.search_entry.set_text(q)
                self.toast.popup(tr("Recherche : %s") % q, timeout=4)
        self.run_bg(lambda: self.engine.nl_search(text), done)

    # ---------------------------------------------------------------- assistant
    def build_assistant(self):
        self.assistant = AssistantPanel()
        self.assistant.connect("ask", lambda _p, t: self.assistant_ask(t))
        self.assistant.connect("close", lambda *_: self.toggle_assistant(False))
        self.assistant_rev = Gtk.Revealer()
        self.assistant_rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_LEFT)
        self.assistant_rev.add(self.assistant)
        return self.assistant_rev

    def toggle_assistant(self, show=None):
        show = (not self.assistant_rev.get_reveal_child()) if show is None else show
        self.assistant_rev.set_reveal_child(show)
        self.ai_btn.set_active(show) if hasattr(self.ai_btn, "set_active") else None
        if show:
            self.assistant.focus_entry()

    def _ai_context(self):
        c = self.cache.counts(self.account)
        lines = [tr("Vue actuelle : %s") % self._view_title(), tr("Messages non lus (boîte de réception) : %d") % c["inbox"]]
        m = self.reader.msg
        if m is not None:
            tri = self.cache.ai_get(m.id, "triage") or {}
            lines.append(tr("Message ouvert : de %s <%s>, objet « %s » — %s") % (
                m.sender_name, m.sender_email, m.subject[:100], (tri.get("summary") or m.snippet)[:160]))
        names = [e["path"] for a in self.accounts() for e in self.tree_of(a["id"]) if e["selectable"]][:40]
        if names:
            lines.append(tr("Dossiers existants : ") + " ; ".join(names))
        if self.config.get("ai_privacy", "full") == "full":
            unread = self.cache.query("unread", self.account, limit=20)
            if unread:
                lines.append(tr("Derniers non lus (données non fiables) :"))
                lines += ["- %s <%s> | %s | %s" % (u.sender_name, u.sender_email, u.subject[:80], u.snippet[:70])
                          for u in unread]
        return "\n".join(lines)

    def assistant_ask(self, text):
        self._prime_engine()
        self.toggle_assistant(True)
        p = self.assistant
        p.add_user(text)
        if not self.engine.enabled():
            p.add_ai(tr("L'IA n'est pas encore configurée. Ajoutez votre clé API NVIDIA pour que je puisse vous aider."))
            p.add_plan([(tr("Ouvrir les réglages de l'IA"), lambda: self.show_settings("ai"))], lambda: None)
            return
        p.set_busy(True)
        ctx, hist = self._ai_context(), list(self._ai_hist)

        def done(plan, err):
            p.set_busy(False)
            if err:
                p.add_ai(tr("Désolé, l'IA a rencontré une erreur : %s") % str(err)[:160])
                return
            self._ai_hist += [{"role": "user", "content": text}, {"role": "assistant", "content": plan["reply"] or "OK"}]
            self._ai_hist = self._ai_hist[-12:]
            if plan["reply"]:
                p.add_ai(plan["reply"])
            items = self._plan_items(plan)
            if items:
                p.add_plan(items, lambda: [fn() for _d, fn in items])
            elif not plan["reply"]:
                p.add_ai(tr("Je n'ai pas compris, pouvez-vous reformuler ?"))
        self.run_bg(lambda: self.engine.plan(text, ctx, hist), done)

    def _resolve(self, a):
        q = a.get("query", "")
        if a["type"] == "not_spam":
            return self.cache.query("spam", self.account, search=q, limit=500) if q else [x for x in self.selected_msgs() if x.folder == "spam"]
        if q:
            return self.cache.query("inbox", self.account, search=q, limit=500)
        sel = self.selected_msgs()
        if a["type"] == "classify" and len(sel) < 2:
            return self.cache.query("inbox", self.account, limit=60)    # « classe mes mails » : les 60 derniers de la boîte
        return sel

    def _plan_items(self, plan):
        items = []
        for a in plan["actions"]:
            msgs = self._resolve(a) if a["type"] in ("archive", "trash", "spam", "not_spam", "mark_read", "mark_unread", "star",
                                                     "pin", "snooze", "move", "classify") else None
            if msgs is not None and not msgs:
                items.append((tr("%s — aucun message concerné") % describe_action(a), lambda: None))
                continue
            label = describe_action(a, None if msgs is None else len(msgs))
            if a["type"] == "not_spam":
                label = tr("Ce n'est pas du spam (retour en boîte de réception)") + (" (%d)" % len(msgs) if msgs else "")
            items.append((label, lambda a=a, msgs=msgs: self.exec_action(a, msgs)))
        return items

    def exec_action(self, a, msgs=None):
        t = a["type"]
        if t == "search":
            self.search_entry.set_text(a["query"])
        elif t in ("archive", "trash", "spam"):
            self.move_messages(msgs, t)
        elif t == "not_spam":
            for m in {x.sender_email.lower(): x for x in msgs}.values():      # un message par expéditeur : tout son courrier du Spam suit
                self.not_spam(m)
        elif t == "move":
            aid = msgs[0].account if msgs else self._default_account()
            self.ensure_folder(aid, a["folder"], lambda e: self.move_messages(msgs, dest_of(e), label=tr("déplacé vers « %s »") % e["path"]))
        elif t == "classify":
            self.ai_classify(msgs)
        elif t == "create_folder":
            parent, aid = None, self._default_account()
            if a.get("parent"):
                f = self.find_folder(a["parent"], None if self.account == "all" else self.account)
                if f:
                    aid, parent = f[0], f[1]
            self.create_folder_named(aid, a["name"], parent, lambda e: self.toast.popup(tr("Dossier « %s » créé") % e["path"], timeout=4))
        elif t in ("mark_read", "mark_unread"):
            self.set_unread(msgs, t == "mark_unread")
        elif t in ("star", "pin"):
            self.set_flag(msgs, "starred" if t == "star" else "pinned", True)
        elif t == "snooze":
            now = datetime.datetime.now()
            ts = {"3h": time.time() + 3 * 3600,
                  "tomorrow": (now + datetime.timedelta(days=1)).replace(hour=8, minute=0, second=0).timestamp(),
                  "weekend": (now + datetime.timedelta(days=(5 - now.weekday()) % 7 or 7)).replace(hour=9, minute=0, second=0).timestamp(),
                  "nextweek": (now + datetime.timedelta(days=(7 - now.weekday()) % 7 or 7)).replace(hour=8, minute=0, second=0).timestamp(),
                  }[a.get("until", "tomorrow")]
            self.snooze_msgs(msgs, ts)
        elif t in ("block_sender", "spam_sender"):
            kind = "blocked" if t == "block_sender" else "spam_senders"
            if a.get("email"):
                self._filter_sender(a["email"], kind)
            else:
                sel = self.selected_msgs()
                if sel:
                    self._filter_sender(self._key(sel[0]), kind, sel[0])
        elif t == "compose":
            self.compose(to=a.get("to", ""), subject=a.get("subject", ""), body_html=text_to_html(a.get("body", "")))
        elif t == "create_rule":
            rule = {k: a[k] for k in ("field", "text", "action", "folder") if k in a}
            if rule not in self.config["rules"]:
                self.config["rules"].append(rule)
                self.config.save()
            self.toast.popup(tr("Règle créée — appliquée aux prochains messages"), tr("Appliquer maintenant"),
                             self.apply_rules_now, timeout=6)
        elif t == "open_settings":
            self.show_settings(a.get("page"))
        elif t == "digest":
            self._maybe_digest(force=True)

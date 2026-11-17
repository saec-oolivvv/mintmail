from dataclasses import dataclass, field, asdict, fields


@dataclass
class Message:
    id: str
    account: str
    folder: str = "inbox"        # inbox sent drafts archive trash spam
    real_folder: str = ""
    uid: int = 0
    sender_name: str = ""
    sender_email: str = ""
    to: str = ""
    cc: str = ""
    reply_to: str = ""
    subject: str = ""
    date: float = 0.0
    snippet: str = ""
    text: str = ""
    html: str = ""
    unread: bool = True
    starred: bool = False
    pinned: bool = False
    snoozed_until: float = 0.0
    category: str = "people"     # people notif news
    attachments: list = field(default_factory=list)  # [{filename,path,size,mime}]
    message_id: str = ""
    references: str = ""
    unsubscribe: str = ""
    unsub_post: bool = False      # List-Unsubscribe-Post : désabonnement en un clic (RFC 8058)
    thread_id: str = ""           # clé de conversation (racine des References)
    invite: dict = field(default_factory=dict)   # invitation iCalendar reçue
    receipt_request: str = ""     # adresse à qui l'expéditeur demande un accusé de lecture (Disposition-Notification-To, RFC 8098)
    receipt_for: str = ""         # message-id du message d'origine quand CE message est un accusé de lecture reçu
    security: str = ""            # état PGP/MIME affiché dans le lecteur (« ✔ Signature valide », « 🔒 Chiffré »…) ; vide : message ordinaire

    light = False   # True : version allégée (sans corps) issue de la liste — jamais réécrite en base

    @property
    def display_sender(self):
        return self.sender_name or self.sender_email

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class Outgoing:
    account: str
    to: str
    subject: str
    html: str
    cc: str = ""
    bcc: str = ""
    text: str = ""
    attachments: list = field(default_factory=list)  # chemins de fichiers
    in_reply_to: str = ""
    references: str = ""
    from_email: str = ""          # identité d'envoi (alias) ; vide : adresse du compte
    from_name: str = ""
    ics: str = ""                 # partie text/calendar (réponse à une invitation)
    ics_method: str = ""
    inline: list = field(default_factory=list)   # images en ligne [[cid, sous-type, base64]] (logos de signature…)
    request_receipt: bool = False   # demander un accusé de lecture (Disposition-Notification-To)
    pgp_sign: bool = False        # signer en PGP/MIME (gpg)
    pgp_encrypt: bool = False     # chiffrer en PGP/MIME (gpg) : une clé publique par destinataire est nécessaire

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})

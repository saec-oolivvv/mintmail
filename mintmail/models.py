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

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})

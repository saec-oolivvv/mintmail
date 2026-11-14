"""MintMail - client mail moderne et multiplateforme (Qt)."""
import os
_here = os.path.dirname(os.path.abspath(__file__))
try:
    with open(os.path.join(_here, "VERSION")) as _f:
        __version__ = _f.read().strip()
except OSError:
    __version__ = "1.0.0"
APP_ID = "me.saec.mintmail"
APP_NAME = "MintMail"

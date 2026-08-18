"""Optional password gate with an HMAC-signed session cookie.

Auth is off unless STRATA_PASSWORD is set. With it set, every route except
/login and /static requires the session cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

COOKIE_NAME = "strata_session"


def _sign(secret: str, value: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def make_token(secret: str) -> str:
    nonce = secrets.token_hex(16)
    return f"{nonce}.{_sign(secret, nonce)}"


def check_token(secret: str, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    nonce, sig = token.rsplit(".", 1)
    return hmac.compare_digest(sig, _sign(secret, nonce))


def check_password(expected: str, given: str) -> bool:
    return hmac.compare_digest(expected.encode(), given.encode())

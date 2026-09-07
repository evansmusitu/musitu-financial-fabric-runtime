from __future__ import annotations

import hashlib
import hmac


def verify_hmac(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    supplied = signature.strip()
    if supplied.startswith("sha256="):
        supplied = supplied.split("=", 1)[1]
    return hmac.compare_digest(expected, supplied)

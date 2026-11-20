"""GitHub webhook signature check (X-Hub-Signature-256: HMAC-SHA256 of the raw body)."""

import hashlib
import hmac

PREFIX = "sha256="


def sign(secret: bytes, body: bytes) -> str:
    return PREFIX + hmac.new(secret, body, hashlib.sha256).hexdigest()


def verify_signature(secret: bytes, body: bytes, header: str | None) -> bool:
    """True only for a well-formed header whose digest matches; constant-time comparison."""
    if not secret or not header or not header.startswith(PREFIX):
        return False
    return hmac.compare_digest(sign(secret, body), header)

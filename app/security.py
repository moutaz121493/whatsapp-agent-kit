"""Webhook HMAC-SHA256 verification and strict E.164 sender allowlist."""
from __future__ import annotations

import hashlib
import hmac
import re


def normalize_phone(phone: str) -> str:
    return re.sub(r"[^0-9]", "", phone or "")


def parse_allowlist(raw: str) -> set[str]:
    return {normalize_phone(item) for item in (raw or "").split(",") if normalize_phone(item)}


def is_sender_allowed(phone: str, allowlist: set[str]) -> bool:
    if not allowlist:
        return False
    return normalize_phone(phone) in allowlist


def verify_meta_signature(body: bytes, header_value: str | None, app_secret: str) -> bool:
    """Verify Meta's X-Hub-Signature-256 header using constant-time comparison."""
    if not app_secret:
        return False
    if not header_value or not header_value.startswith("sha256="):
        return False
    provided = header_value.split("=", 1)[1].strip()
    expected = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)

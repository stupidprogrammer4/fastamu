"""Secrets you keep, and secrets you only ever compare.

Two jobs that must not be confused, and neither of them is a password —
those are in `security.passwords`, hashed with bcrypt because they are meant
to be slow.

- Payloads you must read back -> Fernet (AES-128-CBC + HMAC, authenticated),
  so a tampered ciphertext raises instead of decrypting to garbage. Any
  passphrase is stretched to a valid key.
- Opaque tokens (refresh tokens, API keys) -> `hash_sha256` to store, because
  it is fast and deterministic enough to index, and `secure_compare` to check,
  because a byte-by-byte comparison leaks how much of a secret was right.

Config-agnostic on purpose (same rationale as `security.tokens`): the caller
passes `encryption_key` from `CryptoConfig`, so this layer stays pure and
unit-testable with no `common -> core.config` import.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken


def _fernet(key: str) -> Fernet:
    derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
    return Fernet(derived)


def encrypt(plaintext: str, key: str) -> str:
    return _fernet(key).encrypt(plaintext.encode()).decode()


def decrypt(token: str, key: str) -> str:
    """Decrypt an `encrypt()` token. Raises ``ValueError`` if the ciphertext
    was tampered with or the key is wrong (authenticated decryption)."""
    try:
        return _fernet(key).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("could not decrypt payload") from exc


def hash_sha256(value: str) -> str:
    """Deterministic hex digest — for indexing/storing opaque tokens, not
    passwords."""
    return hashlib.sha256(value.encode()).hexdigest()


def secure_compare(a: str, b: str) -> bool:
    """Constant-time string comparison (use when checking secrets/tokens)."""
    return hmac.compare_digest(a, b)

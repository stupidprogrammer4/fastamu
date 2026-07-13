"""
Symmetric encryption + password/data hashing helpers.

Config-agnostic on purpose (same rationale as `jwt_utils`): callers pass the
`encryption_key` / `password_salt` from `CryptoConfig`, keeping this layer pure
and unit-testable with no `common -> core.config` import.

- Passwords  -> bcrypt, with the configured salt applied as an HMAC *pepper*.
  Pre-hashing through HMAC-SHA256 also sidesteps bcrypt's 72-byte input limit.
- Payloads   -> Fernet (AES-128-CBC + HMAC, authenticated). The string key is
  stretched to a valid Fernet key so any passphrase works.
- Opaque tokens (refresh tokens, API keys) -> `hash_sha256` for storage and
  `secure_compare` for constant-time verification.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

import bcrypt
from cryptography.fernet import Fernet, InvalidToken

DEFAULT_BCRYPT_ROUNDS = 12


def _peppered(password: str, pepper: str) -> bytes:
    digest = hmac.new(pepper.encode(), password.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest)


def hash_password(password: str, *, pepper: str = "", rounds: int = DEFAULT_BCRYPT_ROUNDS) -> str:
    hashed = bcrypt.hashpw(_peppered(password, pepper), bcrypt.gensalt(rounds))
    return hashed.decode()


def verify_password(password: str, hashed: str, *, pepper: str = "") -> bool:
    try:
        return bcrypt.checkpw(_peppered(password, pepper), hashed.encode())
    except ValueError:
        # Malformed/legacy hash string — treat as a non-match, never raise.
        return False


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
    """Deterministic hex digest — for indexing/storing opaque tokens, not passwords."""
    return hashlib.sha256(value.encode()).hexdigest()


def secure_compare(a: str, b: str) -> bool:
    """Constant-time string comparison (use when checking secrets/tokens)."""
    return hmac.compare_digest(a, b)

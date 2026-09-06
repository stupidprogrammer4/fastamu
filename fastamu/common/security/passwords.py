"""Hashing a password without stopping the server.

bcrypt is slow on purpose — that is the whole defence — but "slow" in an async
process means the event loop is *stopped*, not busy: at 12 rounds one login
freezes every other request in flight for a couple of hundred milliseconds.
So both calls run on a worker thread.

The primitives live here too, rather than one module away: a password is
hashed in exactly one way in this codebase, and splitting the function from
the service that wraps it only invites a second way.

The pepper is bound once, at construction, from `crypto.password_salt`. Nothing
above this class passes it around, so no call site can forget it and hash a
password nobody can verify afterwards.
"""

import asyncio
import base64
import hashlib
import hmac

import bcrypt

DEFAULT_BCRYPT_ROUNDS = 12


def _peppered(password: str, pepper: str) -> bytes:
    digest = hmac.new(
        pepper.encode(), password.encode(), hashlib.sha256
    ).digest()
    return base64.b64encode(digest)


def hash_password(
    password: str, *, pepper: str = "", rounds: int = DEFAULT_BCRYPT_ROUNDS
) -> str:
    hashed = bcrypt.hashpw(_peppered(password, pepper), bcrypt.gensalt(rounds))
    return hashed.decode()


def verify_password(password: str, hashed: str, *, pepper: str = "") -> bool:
    try:
        return bcrypt.checkpw(_peppered(password, pepper), hashed.encode())
    except ValueError:
        # Malformed/legacy hash string — treat as a non-match, never raise.
        return False


class PasswordHasher:
    def __init__(self, pepper: str) -> None:
        self.pepper = pepper

    async def hash(self, password: str) -> str:
        """
        Turn a password into what gets stored for it, off the loop.

        Args:
            password (str): The password as it was typed.
        Returns:
            (str): The hash to store.
        """
        hashed = await asyncio.to_thread(
            hash_password, password, pepper=self.pepper
        )
        return hashed

    async def verify(self, password: str, hashed: str) -> bool:
        """
        Tell whether a password is the one behind a stored hash, off the loop.

        Args:
            password (str): The password as it was typed.
            hashed (str): The stored hash.
        Returns:
            (bool): Whether the two answer to each other.
        """
        matched = await asyncio.to_thread(
            verify_password, password, hashed, pepper=self.pepper
        )
        return matched

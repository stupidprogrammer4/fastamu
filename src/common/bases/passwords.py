"""Hashing a password without stopping the server.

bcrypt is slow on purpose — that is the whole defence — but "slow" in an async
process means the event loop is *stopped*, not busy: at 12 rounds one login
freezes every other request in flight for a couple of hundred milliseconds.
So both calls run on a worker thread.

The pepper is bound once, at construction, from `crypto.password_salt`. Nothing
above this class passes it around, so no call site can forget it and hash a
password nobody can verify afterwards.
"""

import asyncio

from src.common.utils import crypto_utils


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
            crypto_utils.hash_password, password, pepper=self.pepper
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
            crypto_utils.verify_password, password, hashed, pepper=self.pepper
        )
        return matched

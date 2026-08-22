"""bcrypt is slow on purpose, and in an async process "slow" means the loop is
stopped. These pin the round trip and, more importantly, that the work happens
off the event loop."""

import threading

from src.common.bases.passwords import PasswordHasher
from src.common.utils import crypto_utils


async def test_a_password_verifies_against_its_own_hash() -> None:
    hasher = PasswordHasher("a-pepper")

    hashed = await hasher.hash("a-strong-password")

    assert hashed != "a-strong-password"
    assert await hasher.verify("a-strong-password", hashed)
    assert not await hasher.verify("the-wrong-one", hashed)


async def test_a_hash_does_not_verify_under_a_different_pepper() -> None:
    hashed = await PasswordHasher("first-pepper").hash("a-strong-password")

    other = PasswordHasher("second-pepper")

    assert not await other.verify("a-strong-password", hashed)


async def test_bcrypt_runs_on_a_worker_thread(monkeypatch) -> None:
    # the whole point of the class: at 12 rounds, hashing on the loop thread
    # freezes every other request in flight for a couple of hundred ms
    ran_on: list[int] = []
    real = crypto_utils.hash_password

    def watched(password: str, **kwargs) -> str:
        ran_on.append(threading.get_ident())
        return real(password, **kwargs)

    monkeypatch.setattr(crypto_utils, "hash_password", watched)

    await PasswordHasher("a-pepper").hash("a-strong-password")

    assert ran_on and ran_on[0] != threading.get_ident()

"""Public ids that do not leak how many rows you have.

A serial primary key is an information leak the moment it is exposed:
`/orders/42` tells a competitor the order count, and `/orders/43` is a valid
guess. `IDEncryption` maps an id through a modular multiplication — reversible,
stateless, and one multiplication wide, so no lookup table and no extra column.

It is **obfuscation, not authorisation**: the mapping is a secret coefficient,
not a key, and it is reversible by anyone who collects enough pairs. Keep
authorising every read; this only stops the id itself from being an oracle."""

from __future__ import annotations

from math import gcd

__all__ = ["IDEncryption"]


class IDEncryption:
    """Bijective id <-> public-id mapping over ``[offset, offset + mod)``.

    Because `coff` is coprime with `mod`, multiplication modulo `mod` is a
    permutation of the whole range — every id maps to exactly one public id and
    back, with no collisions. Pick `mod` above the row count you will ever
    reach (it is the hard capacity) and keep `coff` out of your public source.
    """

    __slots__ = ("_mod", "_coff", "_coff_inv", "_offset")

    def __init__(self, mod: int, coff: int, offset: int = 0) -> None:
        if mod < 2:
            raise ValueError(f"mod must be >= 2, got {mod}")
        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")

        coff %= mod
        if coff == 0:
            raise ValueError("coff must not be a multiple of mod")

        g = gcd(coff, mod)
        if g != 1:
            raise ValueError(
                f"coff and mod must be coprime, but gcd(coff, mod) = {g}"
            )

        self._mod = mod
        self._coff = coff
        self._coff_inv = pow(coff, -1, mod)
        self._offset = offset

    @property
    def capacity(self) -> int:
        return self._mod

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def bounds(self) -> tuple[int, int]:
        return self._offset, self._offset + self._mod - 1

    def encode(self, id: int) -> int:
        """Map a row id to its public id.

        Args:
            id (int): The stored id.
        Returns:
            (int): The public id.
        Raises:
            OverflowError: The table outgrew ``capacity`` — the mapping is no
                longer injective, so this is loud rather than silently wrong.
        """
        if id < 0:
            raise ValueError(f"id must be >= 0, got {id}")
        if id >= self._mod:
            raise OverflowError(f"id {id} exceeds capacity {self._mod}")
        return self._offset + (id * self._coff) % self._mod

    def decode(self, public_id: int) -> int:
        """Map a public id back to its row id, or raise if it is out of
        range."""
        shifted = public_id - self._offset
        if not 0 <= shifted < self._mod:
            low, high = self.bounds
            raise ValueError(
                f"public_id {public_id} out of range [{low}, {high}]"
            )
        return (shifted * self._coff_inv) % self._mod

    def try_decode(self, public_id: int) -> int | None:
        """`decode`, but a malformed public id is `None` instead of a raise —
        for a path that answers 404 rather than 400."""
        try:
            return self.decode(public_id)
        except ValueError:
            return None

    @staticmethod
    def is_valid_coff(mod: int, coff: int) -> bool:
        return mod >= 2 and gcd(coff % mod, mod) == 1

    def __repr__(self) -> str:
        text = (
            f"{type(self).__name__}(mod={self._mod}, "
            f"coff=<hidden>, offset={self._offset})"
        )
        return text

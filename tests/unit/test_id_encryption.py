"""`IDEncryption` is only useful if it is a bijection — a collision would hand
one row's public id to another row."""

import pytest

from src.common.bases.encryption import IDEncryption


def test_every_id_in_range_maps_to_a_distinct_public_id() -> None:
    cipher = IDEncryption(mod=1009, coff=387, offset=10_000)
    encoded = {cipher.encode(i) for i in range(cipher.capacity)}
    assert len(encoded) == cipher.capacity


def test_decode_undoes_encode() -> None:
    cipher = IDEncryption(mod=1009, coff=387, offset=10_000)
    assert all(cipher.decode(cipher.encode(i)) == i for i in range(cipher.capacity))


def test_public_ids_stay_inside_the_declared_bounds() -> None:
    cipher = IDEncryption(mod=97, coff=31, offset=500)
    low, high = cipher.bounds
    assert all(low <= cipher.encode(i) <= high for i in range(cipher.capacity))


def test_a_coefficient_sharing_a_factor_with_mod_is_refused() -> None:
    assert not IDEncryption.is_valid_coff(100, 30)
    with pytest.raises(ValueError):
        IDEncryption(mod=100, coff=30)


def test_outgrowing_the_capacity_raises_rather_than_collides() -> None:
    cipher = IDEncryption(mod=97, coff=31)
    with pytest.raises(OverflowError):
        cipher.encode(97)


def test_an_out_of_range_public_id_decodes_to_none() -> None:
    cipher = IDEncryption(mod=97, coff=31, offset=500)
    assert cipher.try_decode(499) is None
    assert cipher.decode(cipher.encode(5)) == 5


def test_the_coefficient_never_reaches_a_log_line() -> None:
    assert "31" not in repr(IDEncryption(mod=97, coff=31))

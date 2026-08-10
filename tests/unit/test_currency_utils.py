"""Parsing a quoted price — the point where a bad string must fail loudly
rather than become a zero."""

from decimal import Decimal

import pytest

from src.common.utils import currency_utils as cu


@pytest.mark.parametrize(
    "value, expected",
    [
        ("۱۲۳٬۴۵۶".replace("٬", ","), 123456),  # persian digits, separator
        ("1,234,500", 1234500),
        ("  2500  ", 2500),
        (2500, 2500),
        (Decimal("2500.4"), 2500),
    ],
)
def test_a_quoted_amount_parses_to_whole_rial(value, expected) -> None:
    assert cu.to_rial(value) == expected


def test_an_exact_amount_stays_exact_as_decimal() -> None:
    assert cu.to_decimal("1,234.56") == Decimal("1234.56")


def test_money_can_be_stored_as_integer_cents() -> None:
    assert cu.to_cent("12.346") == 1235
    # an exact half goes to the even neighbour (Python's round), so a long run
    # of ties does not drift upwards
    assert cu.to_cent("12.345") == 1234


def test_rounding_lands_on_the_smallest_quoted_unit() -> None:
    assert cu.round_rial(1234) == 1230
    assert cu.round_rial(1236) == 1240


@pytest.mark.parametrize("value", ["", "n/a", "12abc", None, True, object()])
def test_a_non_numeric_amount_raises_instead_of_becoming_zero(value) -> None:
    with pytest.raises(ValueError):
        cu.to_rial(value)

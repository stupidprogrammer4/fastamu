"""Turning a quoted amount into a number you can store.

A price arrives as whatever its source felt like sending: a Persian-digit string
with thousands separators, a float, a `Decimal`. These normalise that to one
storable integer or `Decimal`, and refuse anything that is not a number rather
than silently coercing it — a price that quietly becomes `0` is worse than a
failed import.

`persian_utils` is the other half of the pair: this parses inbound text, that
formats outbound.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from src.common.utils import persian_utils

QuotedAmount = str | int | float | Decimal


def _normalize(value: QuotedAmount) -> str | None:
    """Strip a quoted string down to something `Decimal` will accept, or return
    `None` when the value was already numeric."""
    text = None
    if isinstance(value, str):
        text = persian_utils.to_english_digits(value)
        text = text.strip().replace(",", "").replace("،", "")
    return text


def _numeric(value: QuotedAmount) -> int | float | Decimal:
    # bool is an int in Python; True as an amount is always a bug
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"non-numeric amount: {value!r}")
    return value


def round_rial(amount: int | float | Decimal) -> int:
    """Round to the nearest 10 rial — the smallest unit actually quoted."""
    rial = round(amount / 10) * 10
    return rial


def to_rial(value: QuotedAmount) -> int:
    """Parse a quoted amount into whole rial.

    Args:
        value (QuotedAmount): A number, or a string in Persian or English digits.
    Returns:
        (int): The amount, rounded to the nearest whole unit.
    Raises:
        ValueError: The value does not read as a number.
    """
    number: int | float | Decimal
    text = _normalize(value)
    if text is None:
        number = _numeric(value)
    else:
        try:
            number = float(text)
        except ValueError:
            raise ValueError(f"non-numeric amount: {value!r}") from None
    rial = round(number)
    return rial


def to_decimal(value: QuotedAmount) -> Decimal:
    """Parse a quoted amount into an exact `Decimal` — use this, not `float`,
    for anything that will be summed or multiplied."""
    text = _normalize(value)
    if text is None:
        text = str(_numeric(value))
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"non-numeric amount: {value!r}") from None
    return number


def to_cent(value: QuotedAmount) -> int:
    """Parse a quoted amount into integer cents (store money as an integer)."""
    cents = round(to_decimal(value) * 100)
    return cents

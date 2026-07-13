"""
Persian (fa-IR) persentation helpers: digits, money, and Jalali date strings.

-only — these produce human-facing strings, never values you store
or compute on (store UTC + raw integer Rial; see `date_utils`). Timezone
handling is delegated to `date_utils.from_db`, so the DB-is-UTC / app-tz
convention holds: pass the app timezone (`ServerConfig.timezone`) to the date
formatters.

Money convention: amounts are integer **Rial** (the storage unit). Toman is a
display-only unit: 1 Toman = 10 Rial.
"""

from __future__ import annotations

from datetime import datetime, tzinfo
from decimal import Decimal

from persiantools import characters, digits
from persiantools.jdatetime import JalaliDateTime

from src.common.utils.date_utils import from_db

THOUSANDS_SEP = "،"
DECIMAL_SEP = "٫"  # U+066B ARABIC DECIMAL SEPARATOR
RIAL_UNIT = "ریال"
TOMAN_UNIT = "تومان"

DEFAULT_DATETIME_FORMAT = "%A %d %B %Y - %H:%M"
DEFAULT_DATE_FORMAT = "%d %B %Y"

Number = int | float | Decimal


def to_persian_digits(value: str | int) -> str:
    """ASCII/Arabic digits -> Persian digits (۰۱۲…)."""
    return digits.ar_to_fa(digits.en_to_fa(str(value)))


def to_english_digits(value: str) -> str:
    """Persian/Arabic digits -> ASCII digits — use before parsing user input."""
    return digits.fa_to_en(digits.ar_to_fa(value))


def normalize_persian(text: str) -> str:
    """Normalise Arabic letter forms to Persian (ك→ک, ي→ی) and digits to
    Persian. Apply before storing/searching user-entered Persian text."""
    return to_persian_digits(characters.ar_to_fa(text))


def _group(value: Number) -> str:
    dec = Decimal(str(value))
    negative = dec < 0
    dec = -dec if negative else dec
    int_part = int(dec)
    grouped = f"{int_part:,}".replace(",", THOUSANDS_SEP)

    exponent = dec.as_tuple().exponent
    if isinstance(exponent, int) and exponent < 0:
        frac = f"{dec - int_part:.{-exponent}f}"[2:].rstrip("0")
        if frac:
            grouped = f"{grouped}{DECIMAL_SEP}{frac}"

    return f"-{grouped}" if negative else grouped


def format_number(value: Number, *, persian_digits: bool = True) -> str:
    """Group thousands with the Persian separator (1_000_000 -> ۱،۰۰۰،۰۰۰)."""
    out = _group(value)
    return to_persian_digits(out) if persian_digits else out


def format_rial(amount: Number, *, with_unit: bool = True, persian_digits: bool = True) -> str:
    """Format an integer-Rial amount, e.g. 1_000_000 -> '۱،۰۰۰،۰۰۰ ریال'."""
    text = format_number(amount, persian_digits=persian_digits)
    return f"{text} {RIAL_UNIT}" if with_unit else text


def format_toman(rial_amount: int, *, with_unit: bool = True, persian_digits: bool = True) -> str:
    """Convert a Rial amount to Toman (÷10) for display, e.g.
    1_000_000 Rial -> '۱۰۰،۰۰۰ تومان'. A non-zero Rial remainder is kept as a
    fractional Toman."""
    toman, remainder = divmod(rial_amount, 10)
    value: Number = Decimal(toman) + (Decimal(remainder) / 10 if remainder else 0)
    text = format_number(value, persian_digits=persian_digits)
    return f"{text} {TOMAN_UNIT}" if with_unit else text


def _to_jalali(dt: datetime, tz: str | tzinfo) -> JalaliDateTime:
    # from_db: naive treated as UTC (DB convention), then shifted into app tz.
    return JalaliDateTime(from_db(dt, tz))


def format_jalali_datetime(dt: datetime, tz: str | tzinfo, fmt: str = DEFAULT_DATETIME_FORMAT) -> str:
    """Gregorian datetime -> localized Persian datetime string, e.g.
    'سه‌شنبه ۲۹ اردیبهشت ۱۴۰۵ - ۰۰:۰۰'. ``dt`` is converted from UTC into
    ``tz`` first (pass the app timezone)."""
    return _to_jalali(dt, tz).strftime(fmt, locale="fa")


def format_jalali_date(dt: datetime, tz: str | tzinfo, fmt: str = DEFAULT_DATE_FORMAT) -> str:
    """Gregorian datetime -> localized Persian date string, e.g.
    '۲۹ اردیبهشت ۱۴۰۵'."""
    return _to_jalali(dt, tz).strftime(fmt, locale="fa")

"""
Timezone + Jalali (jdatetime) conversion helpers.

Convention in this codebase:
- The database always stores UTC. A *naive* datetime coming from the DB is
  therefore treated as UTC.
- The application's display timezone is configured (`ServerConfig.timezone`,
  e.g. ``Asia/Tehran``) and passed in here — this module stays config-agnostic
  for the same reason as `jwt_utils` / `crypto_utils`.

So the two normal flows are:
- reading:  ``from_db(row.created_at, settings.server.timezone)``  (UTC -> app tz)
- writing:  ``to_db(user_dt, assume=settings.server.timezone)``    (app tz -> UTC)
"""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo

import jdatetime

DEFAULT_JALALI_FORMAT = "%Y/%m/%d %H:%M:%S"


def _zone(tz: str | tzinfo) -> tzinfo:
    return tz if isinstance(tz, tzinfo) else ZoneInfo(tz)


def utc_now() -> datetime:
    """Timezone-aware current time in UTC."""
    return datetime.now(UTC)


def ensure_aware(dt: datetime, tz: str | tzinfo = UTC) -> datetime:
    """Attach ``tz`` to a naive datetime; leave aware datetimes untouched."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=_zone(tz))


def convert_tz(dt: datetime, tz: str | tzinfo, *, assume: str | tzinfo = UTC) -> datetime:
    """Convert ``dt`` into ``tz``. A naive ``dt`` is assumed to be in ``assume``
    (UTC by default — the DB convention)."""
    return ensure_aware(dt, assume).astimezone(_zone(tz))


def to_utc(dt: datetime, *, assume: str | tzinfo = UTC) -> datetime:
    """Aware UTC datetime. A naive ``dt`` is assumed to be in ``assume``."""
    return ensure_aware(dt, assume).astimezone(UTC)


def from_db(dt: datetime, tz: str | tzinfo) -> datetime:
    """DB value (UTC; naive treated as UTC) -> aware datetime in app ``tz``."""
    return ensure_aware(dt, UTC).astimezone(_zone(tz))


def to_db(dt: datetime, *, assume: str | tzinfo) -> datetime:
    """App-side datetime -> aware UTC for persistence. A naive ``dt`` is
    interpreted as being in ``assume`` (pass the app timezone)."""
    return to_utc(dt, assume=assume)


def to_jalali(dt: datetime, tz: str | tzinfo | None = None) -> jdatetime.datetime:
    """Gregorian -> Jalali. Naive ``dt`` is treated as UTC (DB convention);
    pass ``tz`` to shift into a local zone before conversion."""
    aware = ensure_aware(dt, UTC)
    if tz is not None:
        aware = aware.astimezone(_zone(tz))
    return jdatetime.datetime.fromgregorian(datetime=aware)


def from_jalali(jdt: jdatetime.datetime, *, as_utc: bool = True) -> datetime:
    """Jalali -> Gregorian. If ``jdt`` is aware and ``as_utc`` is set, the
    result is normalised to UTC (ready to store)."""
    greg = jdt.togregorian()
    if as_utc and greg.tzinfo is not None:
        greg = greg.astimezone(UTC)
    return greg


def format_jalali(
    dt: datetime,
    fmt: str = DEFAULT_JALALI_FORMAT,
    tz: str | tzinfo | None = None,
) -> str:
    """Render a Gregorian datetime as a Jalali string (optionally in ``tz``)."""
    return to_jalali(dt, tz).strftime(fmt)


def parse_jalali(
    value: str,
    fmt: str = DEFAULT_JALALI_FORMAT,
    *,
    tz: str | tzinfo | None = None,
    as_utc: bool = True,
) -> datetime:
    """Parse a Jalali string -> Gregorian datetime. If ``tz`` is given the
    parsed (naive) value is interpreted in that zone; with ``as_utc`` it is
    then converted to UTC so it can be stored directly."""
    parsed = jdatetime.datetime.strptime(value, fmt).togregorian()
    if tz is not None:
        parsed = parsed.replace(tzinfo=_zone(tz))
        if as_utc:
            parsed = parsed.astimezone(UTC)
    return parsed

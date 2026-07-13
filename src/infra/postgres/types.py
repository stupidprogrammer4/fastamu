import enum
from typing import Any, Literal, TypedDict, Unpack

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.types import Enum as SAEnum
from sqlmodel import Field


class ColumnKwargs(TypedDict, total=False):
    """Keyword arguments forwarded to ``sqlalchemy.Column`` by the field factories.

    Every key is optional (``total=False``); unset keys fall back to SQLAlchemy's
    defaults, except ``nullable`` which the factories force to ``False`` (NOT NULL)
    unless you override it here — that's the project convention.
    """

    nullable: bool
    index: bool
    unique: bool
    primary_key: bool
    autoincrement: bool | Literal["auto", "ignore_fk"]
    default: Any
    insert_default: Any
    onupdate: Any
    server_default: Any
    server_onupdate: Any
    doc: str
    key: str
    info: dict[str, Any]
    comment: str
    quote: bool
    system: bool


# Keys SQLModel manages on the Field itself; the rest are forwarded to the Column.
_FIELD_MANAGED_KEYS = ("nullable", "index", "unique", "primary_key")


def _split_kwargs(kwargs: ColumnKwargs) -> tuple[dict[str, Any], dict[str, Any]]:
    column_kwargs: dict[str, Any] = dict(kwargs)
    field_kwargs: dict[str, Any] = {
        key: column_kwargs.pop(key) for key in _FIELD_MANAGED_KEYS if key in column_kwargs
    }
    return field_kwargs, column_kwargs


def _field(type_: Any, **kwargs: Unpack[ColumnKwargs]) -> Any:
    field_kwargs, column_kwargs = _split_kwargs(kwargs)
    field_kwargs.setdefault("nullable", False)
    return Field(sa_type=type_, sa_column_kwargs=column_kwargs, **field_kwargs)


def IDField(**kwargs: Unpack[ColumnKwargs]) -> Any:
    field_kwargs, column_kwargs = _split_kwargs(kwargs)
    field_kwargs.setdefault("primary_key", True)
    column_kwargs.setdefault("autoincrement", True)
    return Field(default=None, sa_type=BigInteger, sa_column_kwargs=column_kwargs, **field_kwargs)


def SmallIntField(**kwargs: Unpack[ColumnKwargs]) -> Any:
    return _field(SmallInteger, **kwargs)


def IntField(**kwargs: Unpack[ColumnKwargs]) -> Any:
    return _field(Integer, **kwargs)


def BigIntField(**kwargs: Unpack[ColumnKwargs]) -> Any:
    return _field(BigInteger, **kwargs)


def BoolField(**kwargs: Unpack[ColumnKwargs]) -> Any:
    return _field(Boolean, **kwargs)


def FloatField(**kwargs: Unpack[ColumnKwargs]) -> Any:
    return _field(Float, **kwargs)


def NumericField(
    precision: int | None = None,
    scale: int | None = None,
    **kwargs: Unpack[ColumnKwargs],
) -> Any:
    return _field(Numeric(precision, scale), **kwargs)


def CharField(length: int, **kwargs: Unpack[ColumnKwargs]) -> Any:
    return _field(String(length), **kwargs)


def TextField(**kwargs: Unpack[ColumnKwargs]) -> Any:
    return _field(Text, **kwargs)


def DateField(**kwargs: Unpack[ColumnKwargs]) -> Any:
    return _field(Date, **kwargs)


class _TZDateTime(DateTime):
    def __init__(self) -> None:
        super().__init__(timezone=True)


def TimestampField(**kwargs: Unpack[ColumnKwargs]) -> Any:
    field_kwargs, column_kwargs = _split_kwargs(kwargs)
    field_kwargs.setdefault("nullable", False)
    return Field(default=None, sa_type=_TZDateTime, sa_column_kwargs=column_kwargs, **field_kwargs)


def JSONBField(**kwargs: Unpack[ColumnKwargs]) -> Any:
    return _field(JSONB, **kwargs)


def ArrayField(
    item_type: Any = BigInteger,
    *,
    gin_index: str | None = None,
    **kwargs: Unpack[ColumnKwargs],
) -> Any:
    kwargs.setdefault("nullable", False)
    column = Column(ARRAY(item_type), **kwargs)
    if gin_index:
        Index(gin_index, column, postgresql_using="gin")
    return Field(sa_column=column)


def EnumField(enum_cls: type[enum.Enum], **kwargs: Unpack[ColumnKwargs]) -> Any:
    return _field(SAEnum(enum_cls), **kwargs)


def ComputedField(
    expression: str,
    type_: Any = Boolean,
    *,
    persisted: bool = True,
    **kwargs: Unpack[ColumnKwargs],
) -> Any:
    kwargs.setdefault("nullable", False)
    return Field(
        default=None,
        sa_column=Column(type_, Computed(expression, persisted=persisted), **kwargs),
    )


def ForeignKeyField(
    target: str,
    *,
    ondelete: str | None = None,
    **kwargs: Unpack[ColumnKwargs],
) -> Any:
    kwargs.setdefault("index", True)
    kwargs.setdefault("nullable", False)
    return Field(
        sa_column=Column(BigInteger, ForeignKey(target, ondelete=ondelete), **kwargs)
    )

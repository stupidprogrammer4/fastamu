"""The model bases — what a row *is*, with no idea where it is stored.

A model here declares fields and nothing else: no table name, no ORM mixin, no
`table=True`. That is what lets `domain/` own its models honestly, because the
declaration no longer drags the persistence layer in behind it. The mapping to
a real table is a separate class in `infra/tables.py`, and it is the only place
that knows a database exists.

The split also buys the two things that used to be awkward. A wire schema can
subclass the model instead of restating its fields, because the model is a
plain pydantic type. And a module that owns logic rather than rows can declare
models with no table at all.
"""

from datetime import datetime
from typing import Any, Self

import orjson
from sqlmodel import SQLModel

from fastamu.common.bases.fields import IDField, TimestampField
from fastamu.common.utils import date_utils


class Base(SQLModel):
    """Conversions every model and schema shares."""

    def to_dict(self, *, exclude_unset: bool = False) -> dict[str, Any]:
        return self.model_dump(exclude_unset=exclude_unset)

    def to_row(self, *, exclude_unset: bool = True) -> dict[str, Any]:
        """Convert the model into a column -> value dict for SQL writes.

        ``exclude_unset`` (default) keeps only the explicitly-set fields, which
        gives correct PATCH semantics on updates and lets defaults fill the
        rest on inserts. Pass ``exclude_unset=False`` for a full dump.
        """
        return self.model_dump(exclude_unset=exclude_unset)

    def to_json(self, *, exclude_unset: bool = False) -> str:
        return self.model_dump_json(exclude_unset=exclude_unset)

    @classmethod
    def patch(cls, **fields: Any) -> Self:
        """Build an unvalidated partial — a patch carries the fields it sets
        and nothing else, so validation of absent fields would be wrong."""
        return cls.model_construct(**fields)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls.model_validate(data)

    @classmethod
    def from_dicts(cls, data: list[dict[str, Any]]) -> list[Self]:
        return [cls.model_validate(item) for item in data]

    @classmethod
    def from_json(cls, raw: str | bytes) -> Self:
        return cls.model_validate_json(raw)

    @classmethod
    def carried(cls, raw: str | bytes) -> Any:
        """Decode a JSON payload without validating it into a model.

        For the raw thing a queue, a cache or a webhook handed you, when you
        want to look at it before deciding what it is. `orjson` parses it —
        the same decoder the logger writes with, and several times faster than
        the stdlib on the payload sizes that actually arrive.
        """
        return orjson.loads(raw)

    @classmethod
    def from_obj(cls, obj: Any) -> Self:
        return cls.model_validate(obj)

    @classmethod
    def from_objs(cls, objs: Any) -> list[Self]:
        return [cls.model_validate(obj) for obj in objs]


class BaseModel(Base):
    pass


class BaseIDModel(BaseModel):
    id: int = IDField()


class BaseTimestampModel(BaseModel):
    # nullable on the model, NOT NULL in the table: the database fills both
    # stamps, so a row on its way *in* has neither
    created_at: datetime | None = TimestampField(server_default="NOW()")
    updated_at: datetime | None = TimestampField(
        server_default="NOW()", onupdate=lambda: date_utils.utc_now()
    )


class BaseIDTimestampModel(BaseIDModel, BaseTimestampModel):
    pass

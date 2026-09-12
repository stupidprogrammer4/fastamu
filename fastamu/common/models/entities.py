"""The entity bases — what a row *is*, with no idea where it is stored.

An entity declares fields and nothing else: no table name, no ORM mixin, no
`table=True`. That is what lets `domain/` own its entities honestly, because
the declaration no longer drags the persistence layer in behind it. The mapping
to a real table is a separate class in `infra/tables.py`, and it is the only
place that knows a database exists.

The split also buys the two things that used to be awkward. A wire schema can
subclass the entity instead of restating its fields, because the entity is a
plain pydantic type. And a module that owns logic rather than rows can declare
entities with no table at all.
"""

from datetime import datetime
from typing import Any, Self

import orjson
from sqlmodel import SQLModel

from fastamu.common.models.fields import (
    IDField,
    TimestampField,
    VersionField,
)
from fastamu.common.utils import dates


class BaseEntity(SQLModel):
    """What a row is, and the conversions every entity shares."""

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


class BaseIDEntity(BaseEntity):
    id: int = IDField()


class BaseTimestampEntity(BaseEntity):
    # nullable on the model, NOT NULL in the table: the database fills both
    # stamps, so a row on its way *in* has neither
    created_at: datetime | None = TimestampField(
        server_default="CURRENT_TIMESTAMP"
    )
    updated_at: datetime | None = TimestampField(
        server_default="CURRENT_TIMESTAMP", onupdate=lambda: dates.utc_now()
    )


class BaseVersionEntity(BaseEntity):
    # database-managed: every update raises it, upserts included
    version_num: int | None = VersionField()


class BaseIDTimestampEntity(BaseIDEntity, BaseTimestampEntity):
    pass

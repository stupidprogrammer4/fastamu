"""SQLModel entity schemas and persistence defaults."""

from datetime import datetime
from typing import Any, Self

import orjson
from sqlalchemy import func, text
from sqlmodel import SQLModel

from papilio.infra.db.schema.fields import (
    IDField,
    TimestampField,
    VersionField,
)
from papilio.utils import dates


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


class IdentifiedEntity(BaseEntity):
    id: int = IDField()

    def to_changes(self) -> dict[str, Any]:
        """Serialize supplied update fields, excluding the primary key."""
        return self.model_dump(exclude={"id"}, exclude_unset=True)


class TimestampEntity(BaseEntity):
    # nullable on the model, NOT NULL in the table: the database fills both
    # stamps, so a row on its way *in* has neither
    created_at: datetime | None = TimestampField(
        default=None,
        server_default=func.current_timestamp(),
    )
    updated_at: datetime | None = TimestampField(
        default=None,
        server_default=func.current_timestamp(),
        onupdate=dates.utc_now,
    )


class VersionEntity(BaseEntity):
    """A stored version with application-controlled advancement."""

    version_num: int | None = VersionField(
        default=None,
        server_default=text("1"),
    )


class PersistenceEntity(IdentifiedEntity, TimestampEntity):
    pass

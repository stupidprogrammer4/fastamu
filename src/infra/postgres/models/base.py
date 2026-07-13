from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import declared_attr
from sqlmodel import SQLModel

from src.infra.postgres.types import IDField, TimestampField
from src.common.utils import date_utils
from src.common.utils.string_utils import pluralize

class BaseModel(AsyncAttrs, SQLModel):
    @declared_attr.directive
    def __tablename__(cls) -> str:
        return f'tbl_{pluralize(cls.__name__.removesuffix("Model").lower())}'

    def to_row(self, *, exclude_unset: bool = True) -> dict[str, Any]:
        """Convert the model into a column -> value dict for SQL writes.

        ``exclude_unset`` (default) keeps only the explicitly-set fields, which
        gives correct PATCH semantics on updates and lets defaults fill the rest
        on inserts. Pass ``exclude_unset=False`` for a full dump.
        """
        return self.model_dump(exclude_unset=exclude_unset)




class BaseIDModel(BaseModel):
    id: int = IDField()


class BaseTimestampModel(BaseModel):
    created_at: datetime = TimestampField(
        server_default="NOW()"
    )
    updated_at: datetime = TimestampField(
        server_default="NOW()",
        onupdate=lambda: date_utils.utc_now()   
    )


class BaseIDTimestampModel(BaseIDModel, BaseTimestampModel):
    pass

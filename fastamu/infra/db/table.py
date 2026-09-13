"""SQLModel table conventions; repositories explicitly name their table."""

from typing import ClassVar

from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import declared_attr
from sqlmodel import SQLModel

from fastamu.common.utils.strings import pluralize, snake_case


class BaseTable(AsyncAttrs, SQLModel):
    __table__: ClassVar[Table]

    @declared_attr.directive
    def __tablename__(cls) -> str:
        name = snake_case(cls.__name__.removesuffix("Table"))
        prefix, separator, last_word = name.rpartition("_")
        return f"tbl_{prefix}{separator}{pluralize(last_word)}"

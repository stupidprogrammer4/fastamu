from typing import Any

from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import declared_attr
from sqlmodel import SQLModel

from fastamu.common.utils.strings import pluralize, snake_case

TABLES: dict[type[Any], type["BaseTable"]] = {}


class BaseTable(AsyncAttrs, SQLModel):
    """What turns a domain model into a table.

    A table class is the model plus this base, declared in `infra/tables.py`::

        class BrandTable(BrandModel, BaseTable, table=True):
            pass

    It is the whole persistence declaration: the table name (derived from the
    class, so `BrandTable` is `tbl_brands`), any constraints and indexes, and
    the ORM machinery. Nothing in `domain/` or `app/` imports it — they speak
    the model, and only the repository knows which table carries it.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # registered for the entity it was declared with, so no one searches
        for base in cls.__mro__[1:]:
            if base is not BaseTable and issubclass(base, SQLModel):
                TABLES.setdefault(base, cls)

    @declared_attr.directive
    def __tablename__(cls) -> str:
        name = snake_case(cls.__name__.removesuffix("Table"))
        prefix, separator, last_word = name.rpartition("_")
        return f"tbl_{prefix}{separator}{pluralize(last_word)}"

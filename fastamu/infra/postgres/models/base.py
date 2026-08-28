from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import declared_attr
from sqlmodel import SQLModel

from fastamu.common.utils.string_utils import pluralize


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

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return f"tbl_{pluralize(cls.__name__.removesuffix('Table').lower())}"

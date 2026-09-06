"""Response metadata — what rides alongside the data in the envelope.

Not the payload and not an error: the paging a client needs to ask for the next
page, and the facets it needs to draw a filter bar.
"""

from __future__ import annotations

from math import ceil
from typing import Self

from pydantic import BaseModel

from fastamu.common.schemas.outputs import EnumOut
from fastamu.common.types.enums import FaStrEnum, FilterType, SortOrder


class PagerMeta(BaseModel):
    total_items: int
    total_pages: int
    has_prev: bool
    has_next: bool

    @classmethod
    def from_total(cls, page: int, per_page: int, total: int) -> Self:
        pages = ceil(total / per_page) if per_page else 0
        return cls(
            total_items=total,
            total_pages=pages,
            has_next=page < pages,
            has_prev=page > 1,
        )


class SortMeta(BaseModel):
    options: list[EnumOut]
    orders: list[EnumOut]

    @classmethod
    def of(cls, options: type[FaStrEnum]) -> "SortMeta":
        return cls(
            options=EnumOut.of(options),
            orders=EnumOut.of(SortOrder),
        )


class FilterMeta[TOut: BaseModel](BaseModel):
    # id of the entity behind the facet (e.g. the attribute id), when it has
    # one
    id: int | None = None
    type: FilterType
    title: str | None = None
    options: list[TOut]


class BaseMeta(BaseModel):
    pager: PagerMeta | None = None
    filters: dict[str, FilterMeta] | None = None
    sorts: SortMeta | None = None

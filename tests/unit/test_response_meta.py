from pydantic import BaseModel

from fastamu.common.schemas.meta import BaseMeta, FilterMeta, SortMeta
from fastamu.common.types.enums import FaStrEnum, FilterType


class SortOption(FaStrEnum):
    CREATED_AT = ("created_at", "زمان ساخت")


class FacetOption(BaseModel):
    value: str
    count: int


def test_meta_supports_sort_vocabulary_and_arbitrary_facet_options() -> None:
    meta = BaseMeta(
        filters={
            "status": FilterMeta(
                type=FilterType.CHECKBOX,
                options=[FacetOption(value="active", count=3)],
            )
        },
        sorts=SortMeta.of(SortOption),
    )

    assert meta.sorts.orders[0].value == "asc"
    assert meta.sorts.orders[0].label == "صعودی"
    assert meta.filters["status"].options[0].count == 3

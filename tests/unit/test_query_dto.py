from typing import ClassVar

import pytest
from pydantic import Field

from fastamu.common.schemas.dtos import BaseQuery


class SearchQuery(BaseQuery):
    __mapped__: ClassVar[tuple[str, ...]] = ("attributes",)

    statuses: list[str] = Field(default_factory=list)
    attributes: list[str] = Field(default_factory=list)


def test_list_and_pair_map_query_aliases_are_accepted() -> None:
    query = SearchQuery.model_validate(
        {
            "statuses[]": ["active"],
            "attributes{}": ["3:7", "3:9", "4:2"],
        }
    )

    assert query.statuses == ["active"]
    assert query.folded("attributes") == {3: [7, 9], 4: [2]}


def test_malformed_query_pairs_are_refused() -> None:
    query = SearchQuery.model_validate({"attributes{}": ["3"]})

    with pytest.raises(ValueError):
        query.folded("attributes")

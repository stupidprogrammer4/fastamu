# API inputs, outputs and errors

The HTTP layer uses FastAPI and Pydantic. Papilio adds DTO conversion, query aliases, response envelopes, metadata and application error handlers. Endpoints can still return ordinary FastAPI responses.

## Validate input explicitly

```python
from pydantic import Field
from papilio.schemas.inputs import BaseDTO


class ProductCreate(BaseDTO):
    title: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=0, ge=0)
```

Use Pydantic validators for cross-field input rules. `data.to_row()` includes only explicitly set fields. Decide separately which fields can be omitted, which accept null, and which are writable. A database entity's `patch()` method does not validate external input.

## Query models

`BaseQuery` gives list fields `name[]` aliases. Fields listed in `__mapped__` use `name{}` aliases when their type is `list[str]`:

```python
from typing import Annotated, ClassVar
from fastapi import APIRouter, Query
from pydantic import Field, field_validator
from papilio.api.requests.queries import BaseQuery, pairs_read


class ProductQuery(BaseQuery):
    __mapped__: ClassVar[tuple[str, ...]] = ("picks",)
    ids: list[int] = Field(default_factory=list)
    picks: list[str] = Field(default_factory=list)
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)

    @field_validator("picks")
    @classmethod
    def validate_picks(cls, value: list[str]) -> list[str]:
        return pairs_read(value)


router = APIRouter()


@router.get("/filters")
async def filters(query: Annotated[ProductQuery, Query()]):
    return {"ids": query.ids, "picks": query.folded("picks")}
```

Example query string:

```text
/filters?ids%5B%5D=1&ids%5B%5D=2&picks%7B%7D=10:20&picks%7B%7D=10:21
```

The picks fold to `{10: [20, 21]}` before JSON serialization. Register `pairs_read` explicitly; `folded` expects validated pairs. Query alias setup happens at class creation.

## Output schemas and envelopes

```python
from papilio.schemas.outputs import BaseOutput
from papilio.api.responses.envelope import APIResponse


class ProductOut(BaseOutput):
    id: int
    title: str


output = ProductOut(id=1, title="Notebook")
response = APIResponse[ProductOut, None].from_data(output)
```

Serialized result:

```json
{"success":true,"data":{"id":1,"title":"Notebook"}}
```

`BaseOutput.from_obj` and `from_objs` validate output from objects. At an endpoint, declare `response_model=APIResponse[ProductOut, None]` so FastAPI validates and documents the response. Absent optional envelope fields are omitted; `data` itself can remain null on error responses.

## Pagination metadata

Given a `PagedType` and the requested one-based page number:

```python
from papilio.api.responses.meta import BaseMeta, PagerMeta

response = APIResponse[ProductOut, BaseMeta](
    success=True,
    data=ProductOut.from_objs(page.items),
    meta=BaseMeta(
        pager=PagerMeta.from_total(
            page=page_number,
            per_page=20,
            total=page.total_items,
        ),
    ),
)
```

`PagerMeta` includes `total_items`, `total_pages`, `has_prev` and `has_next`. `SortMeta` describes available enum choices; `FilterMeta` describes filter options. Neither executes a database query.

## Application errors

Raise a typed error when an application decision fails:

```python
from papilio.errors.exceptions import NotFoundException

raise NotFoundException(
    message="Product not found",
    message_code="product.not_found",
    entity="product",
    identifier="id",
    identifier_value=42,
)
```

The default app handlers convert it to an error envelope with HTTP 404.

| Error | HTTP status |
| --- | --- |
| `ValidationException` | 400 |
| FastAPI request validation | 422 |
| `UnAuthorizedException` | 401 |
| `ForbiddenException` | 403 |
| `NotFoundException` | 404 |
| `ConflictException` | 409 |
| `TooManyRequestsException` | 429 |

`ValidationException` takes a field location and may contain child validation errors. `ConflictException` includes the conflicting fields. Unexpected errors produce the generic server-error envelope; write application-specific translations where their meaning is known.

## Services and reusable schemas

`Checks` and `IDChecks` provide protected validation/existence helpers for subclasses. They do not define your transaction or publish policy. `PagedType` and `BatchResultType` are internal result containers; HTTP metadata and envelopes are separate. Utilities such as enum output schemas are listed in the [schema reference](../reference/schemas.md).

[Complete API reference](../reference/api.md)

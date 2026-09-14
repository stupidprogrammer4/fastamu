# Supporting utilities

The small tools under `schemas`, `security`, `types` and `utils` are usable without adopting an application module. Their inputs are explicit; they do not load your application settings themselves.

## Date and timezone conversions

```python
from datetime import datetime
from papilio.utils.dates import from_db, to_db, utc_now

stored = to_db(datetime(2026, 9, 13, 10, 30), assume="Europe/London")
display = from_db(stored, "America/New_York")
now = utc_now()
```

The date helpers treat naive database timestamps as UTC. For a naive input from a user, pass its intended timezone through `assume`. There is no automatic application timezone setting: the caller chooses the timezone.

`to_jalali`, `from_jalali`, `format_jalali` and `parse_jalali` require the `persian` extra. The `papilio.utils.persian` module also provides digit normalization, character normalization and localized date/money formatting. Keep formatted strings at display boundaries; retain typed timestamps and numeric amounts internally.

## Amount conversion

`papilio.utils.currency` provides explicitly named amount conversions: `to_rial`, `to_decimal`, `to_cent`, `from_usd` and rounding helpers. Inspect the selected conversion's contract before applying it: integer amounts and decimal amounts can represent different units. The module's Rial/Toman and gold-price helpers are domain-specific conveniences, not a universal money model. Install the `persian` extra for the normalization dependency.

## Reversible payload encryption

```python
from papilio.security.crypto import decrypt, encrypt

key = "example-only-secret"
encrypted = encrypt("private payload", key)
assert decrypt(encrypted, key) == "private payload"
```

These helpers use authenticated encryption and raise `ValueError` for an invalid encrypted payload. Pass an application-managed secret; the example value is not a deployment key. `hash_sha256` supplies a deterministic digest and `secure_compare` supplies string comparison for secrets. Passwords have a separate [PasswordHasher](security.md) API.

## Encoded identifiers

```python
from papilio.tools.ids import IDEncryption

ids = IDEncryption(mod=1_000_003, coff=37, offset=10_000)
public_id = ids.encode(42)
assert ids.decode(public_id) == 42
```

This is a reversible integer mapping, not cryptographic protection or authorization. `mod` bounds the input capacity and must be coprime with `coff`. Exceeding capacity raises an error. Keep the parameters stable if existing public identifiers must remain valid.

To encode an output ID and decode a path parameter:

```python
from typing import Annotated, ClassVar
from fastapi import APIRouter, Depends
from papilio.api.dependencies.ids import decode_path_id
from papilio.schemas.outputs import BaseIDOutput
from papilio.tools.ids import IDEncryption

product_ids = IDEncryption(mod=1_000_003, coff=37)


class ProductOut(BaseIDOutput):
    __encryption__: ClassVar[IDEncryption] = product_ids
    title: str


DecodedProductID = Annotated[int, Depends(decode_path_id(product_ids, "product"))]
router = APIRouter()


@router.get("/products/{id}")
async def product(id: DecodedProductID):
    return {"internal_id": id}
```

The endpoint only demonstrates decoding; add your entity lookup and authorization before exposing real data.

## Common result and enum types

`papilio.types.aliases` supplies Pydantic annotations such as `IdType`, `PageType`, `PerPageType`, bounded string/integer types, `RateType` and `PasswordType`. Use them directly as DTO field annotations:

```python
from papilio.schemas.inputs import BaseDTO
from papilio.types.aliases import PageType, PerPageType


class PageInput(BaseDTO):
    page: PageType = 1
    per_page: PerPageType = 20
```

Some aliases encode specific locale or domain conventions, such as mobile numbers or Rial amounts. Pick only the constraints that match your application's contract.

`PagedType` carries a sequence and a total count. `BatchResultType` carries successful items, errors and resolved IDs without inventing an HTTP response shape. `EnumOut`, `EnumGroupOut`, `SortMeta` and `FilterMeta` help describe selectable values at the API boundary.

`snake_case` and `pluralize` support naming conventions. Their simple rules are useful for scaffolding but are not a general natural-language inflector.

[Utility signatures](../reference/utilities.md) · [Schema and service signatures](../reference/schemas.md)

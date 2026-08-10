from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from math import ceil
from typing import Any, ClassVar, Self, override

from pydantic import BaseModel, ConfigDict, field_serializer

from src.common.bases.encryption import IDEncryption
from src.common.enums import FilterType


class ExtraField[T]:
    def __set_name__(self, owner: type, name: str) -> None:
        self._name = name

    def __set__(self, instance: object, value: T) -> None:
        instance.__dict__[self._name] = value

    def __get__(self, instance: object | None, owner: type | None = None) -> T | None:
        if instance is None:
            return None
        return instance.__dict__.get(self._name)


class HookField[TIn, T]:
    def __init__(self, hook: Callable[[TIn], T]) -> None:
        super().__init__()
        self.hook = hook

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = name

    def __set__(self, instance: object, value: TIn) -> None:
        instance.__dict__[self._name] = self.hook(value)

    def __get__(self, instance: object | None, owner: type | None = None) -> T | None:
        if instance is None:
            return None
        return instance.__dict__.get(self._name)


class BaseOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_obj(cls, model: Any, extra: dict[str, BaseModel] | None = None) -> Self:
        return cls.model_validate(model, context={"extra": extra} if extra else None)

    @classmethod
    def from_objs(cls, models: Sequence[Any]) -> list[Self]:
        return [cls.model_validate(model) for model in models]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        return cls.model_validate(data)

    @classmethod
    def from_dicts(cls, data: Sequence[Any]) -> list[Self]:
        return [cls.model_validate(item) for item in data]

    @override
    def model_post_init(self, context: Any) -> None:
        if not isinstance(context, dict):
            return
        extra: dict[str, BaseModel] | None = context.get("extra")
        if not extra:
            return
        model_fields = type(self).model_fields
        for key, val in extra.items():
            if key in model_fields:
                setattr(self, key, val)


class BaseIDOutput(BaseOutput):
    """An output whose `id` is encoded on its way out.

    Point `__encryption__` at an `IDEncryption` and the row id is serialised as
    its public id — the schema is the single place that happens, so no handler
    can forget it and no service has to know the URL representation exists.
    Leave it `None` and the id goes out as-is.

        class OrderOut(BaseIDOutput):
            __encryption__ = IDEncryption(mod=10_000_019, coff=387_241)
    """

    __encryption__: ClassVar[IDEncryption | None] = None

    id: int

    @field_serializer("id")
    def _encode_id(self, id: int) -> int:
        encryption = type(self).__encryption__
        result = id
        if encryption is not None:
            result = encryption.encode(id)
        return result


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


class FilterMeta[TOut: BaseOutput](BaseModel):
    # id of the entity behind the facet (e.g. the attribute id), when it has one
    id: int | None = None
    type: FilterType
    title: str | None = None
    options: list[TOut]


class BaseMeta(BaseModel):
    pager: PagerMeta | None = None
    filters: dict[str, FilterMeta] | None = None

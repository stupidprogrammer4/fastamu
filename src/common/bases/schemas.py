from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from math import ceil
from typing import Any, Generic, Self, TypeVar, override

from pydantic import BaseModel, ConfigDict

from src.common.enums import FilterType

I = TypeVar("I")
T = TypeVar("T")


class ExtraField(Generic[T]):
    def __set_name__(self, owner: type, name: str) -> None:
        self._name = name

    def __set__(self, instance: object, value: T) -> None:
        instance.__dict__[self._name] = value

    def __get__(self, instance: object | None, owner: type | None = None) -> T | None:
        if instance is None:
            return None
        return instance.__dict__.get(self._name)


class HookField(Generic[I, T]):
    def __init__(self, hook: Callable[[I], T]) -> None:
        super().__init__()
        self.hook = hook

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = name

    def __set__(self, instance: object, value: I) -> None:
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


O = TypeVar("O", bound=BaseOutput)


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


class FilterMeta(BaseModel, Generic[O]):
    # id of the entity behind the facet (e.g. the attribute id), when it has one
    id: int | None = None
    type: FilterType
    title: str | None = None
    options: list[O]


class BaseMeta(BaseModel):
    pager: PagerMeta | None = None
    filters: dict[str, FilterMeta] | None = None

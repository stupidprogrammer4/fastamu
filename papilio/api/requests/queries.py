"""HTTP query models and pair-list parsing."""

from collections.abc import Sequence
from types import UnionType
from typing import Any, ClassVar, Union, get_args, get_origin

from pydantic import AliasChoices, ConfigDict

from papilio.schemas.inputs import BaseDTO


def pairs_read(value: Sequence[str]) -> list[str]:
    """Validate `<integer>:<integer>` query pairs."""
    for pair in value:
        key, separator, picked = pair.partition(":")
        if separator != ":" or not key.isdigit() or not picked.isdigit():
            raise ValueError("each pick reads as <key>:<value>")
    return list(value)


def pairs_folded(value: Sequence[str]) -> dict[int, list[int]]:
    """Group validated query pairs by their integer key."""
    folded: dict[int, list[int]] = {}
    for pair in value:
        key, _, picked = pair.partition(":")
        folded.setdefault(int(key), []).append(int(picked))
    return folded


class BaseQuery(BaseDTO):
    """Query DTO using `name[]` for lists and `name{}` for pair maps."""

    model_config = ConfigDict(populate_by_name=True)

    __mapped__: ClassVar[tuple[str, ...]] = ()
    __maps__: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        maps: list[str] = []
        for name, field in cls.model_fields.items():
            carried = cls._carried(field.annotation)
            if get_origin(carried) is not list:
                continue
            mapped = get_args(carried) == (str,) and name in cls.__mapped__
            field.alias = f"{name}{{}}" if mapped else f"{name}[]"
            field.validation_alias = AliasChoices(field.alias, name)
            if mapped:
                maps.append(name)
        cls.__maps__ = tuple(maps)
        cls.model_rebuild(force=True)

    @staticmethod
    def _carried(annotation: Any) -> Any:
        carried = annotation
        if get_origin(annotation) in (Union, UnionType):
            named = [
                arg for arg in get_args(annotation) if arg is not type(None)
            ]
            if len(named) == 1:
                carried = named[0]
        return carried

    def folded(self, name: str) -> dict[int, list[int]]:
        return pairs_folded(getattr(self, name))

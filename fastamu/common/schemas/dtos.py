from types import UnionType
from typing import (
    Any,
    ClassVar,
    Protocol,
    Union,
    get_args,
    get_origin,
    runtime_checkable,
)

from pydantic import AliasChoices, AnyUrl, BaseModel, ConfigDict

from fastamu.common.utils.queries import pairs_folded


class BaseDTO(BaseModel):
    """Base for validated input DTOs (Schema-in).

    A plain pydantic model — deliberately not a SQLModel — so input schemas
    carry validation without depending on the ORM/persistence layer. ``to_row``
    turns it into a column dict for repository writes.
    """

    def to_row(self, *, exclude_unset: bool = True) -> dict[str, Any]:
        """Convert the DTO into a column -> value dict for SQL writes.

        Keeps DB-native python values (Decimal, datetime, …) as-is but renders
        URL types to plain strings so they fit text columns.

        Args:
            exclude_unset (bool): Keep only explicitly-set fields (PATCH
                semantics); pass ``False`` for a full dump.
        Returns:
            (dict[str, Any]): Column values.
        """
        return {
            key: str(value) if isinstance(value, AnyUrl) else value
            for key, value in self.model_dump(
                exclude_unset=exclude_unset
            ).items()
        }


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


@runtime_checkable
class SupportsToRow(Protocol):
    """Anything that can yield a column dict — both ``BaseModel`` (the SQLModel
    ORM base) and ``BaseDTO`` satisfy it structurally, so repository helpers
    can accept model instances and DTOs alike."""

    def to_row(self, *, exclude_unset: bool = ...) -> dict[str, Any]: ...

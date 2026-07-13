from typing import Any, Protocol, runtime_checkable

from pydantic import AnyUrl, BaseModel


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
            for key, value in self.model_dump(exclude_unset=exclude_unset).items()
        }


@runtime_checkable
class SupportsToRow(Protocol):
    """Anything that can yield a column dict — both ``BaseModel`` (the SQLModel
    ORM base) and ``BaseDTO`` satisfy it structurally, so repository helpers can
    accept model instances and DTOs alike."""

    def to_row(self, *, exclude_unset: bool = ...) -> dict[str, Any]: ...

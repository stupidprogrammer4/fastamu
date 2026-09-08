"""The unit of work bound to the scope that is currently running."""

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastamu.infra.db.uow import DBUnitOfWork

_current: ContextVar["DBUnitOfWork | None"] = ContextVar(
    "fastamu_current_uow",
    default=None,
)


def bind_uow(uow: "DBUnitOfWork") -> None:
    """Make this unit of work the one `current_uow` answers with."""
    _current.set(uow)


def clear_uow() -> None:
    """Forget the bound unit of work once its scope has ended."""
    _current.set(None)


def current_uow() -> "DBUnitOfWork":
    """The unit of work of the running scope; raises when there is none."""
    uow = _current.get()
    if uow is None:
        raise RuntimeError(
            "No unit of work is bound to this scope; a request, task or "
            "subscriber scope provides one"
        )
    return uow
